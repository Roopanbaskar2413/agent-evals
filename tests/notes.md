2026-10-14  M1b baseline: llama3.2, schema in prompt, one SQL query, no loop
overall 15/31 (48%), easy 15/15, medium 0/9, hard 0/7
failures: 8 missing join (city), 2 MONTH() unsupported, 2 date filter returns 0, 4 category filter dropped

2026-10-14  M2 agent: llama3.2, run_sql + submit_answer tools, MAX_STEPS 8, no retry prompt beyond "if it looks wrong, try again"
sanity check (3 easy Qs) found: tool-calling works, but model renames the single
declared argument (e.g. 'a' instead of 'number'/'sql') -- handled by taking the
only value when there's one argument. Model also sometimes answers in a plain
sentence instead of calling submit_answer -- handled by regex-parsing a number
out of the text as a fallback, flagged as such in the row's error field.
Found and could not fix via prompting: model truncates decimals when restating
a number into submit_answer (39064.32 -> 39064, 291.52 -> 291) even on whole-number
amounts it just saw correctly from run_sql. Tried adding "use the exact number,
do not round" to SYSTEM -- no effect, reverted.
Prediction before full run: should fix most/all of M1b's 10 visible SQL errors
(bad column, MONTH()) since the agent can now see the error and retry. Expect
little or no improvement on M1b's 6 silent wrong-answers (wrong filter, no error
to react to). New risk introduced by this milestone itself: even a correct SQL
answer can now fail at the final step if it has decimals, because of the
truncation bug above -- so medium/hard decimal questions (averages, sums) may
undercount true capability.

RESULT: overall 13/31 (42%), easy 13/15, medium 0/9, hard 0/7.
Lower than M1b (15/31) at the score level, but medium/hard score (0/9, 0/7) is
UNCHANGED from M1b -- the prediction about silent failures (dropped category
filter, Q28-31) was correct: identical bug, completely untouched by the retry
loop, since nothing ever flags "missing filter" as wrong.
Verified by trajectory (not guessed), 18 failures broken down:
- 3 (Q2,Q3,Q23): SQL came back exactly right, agent truncated the decimal when
  calling submit_answer (39064.32->39064, 9913.59->9913). Q23 is a case where
  the agent CORRECTLY self-corrected a missing join after a real error, then
  lost the right answer on the last step anyway.
- 4 (Q28-31): same dropped-category-filter bug as M1b, now also truncated.
- 3 (Q20,Q22,Q24): after "no such column: city", correctly tries a join, but
  writes it with typographic/smart quotes; SQLite rejects those too; agent
  retries with different curly-quote variants, never tries a plain quote,
  burns all 8 steps.
- 1 (Q16): MONTH() error correctly triggers a retry to SUBSTR, but the SQL is
  malformed (trailing "="); repeats the identical broken query for 7 steps.
- 3 (Q17,Q18,Q19): MONTH() error retried with syntactically valid SUBSTR, but
  compares a TEXT column to an unquoted number -> silent 0, a new silent-
  failure mode not seen in M1b.
- 1 (Q21): gets the join and the number right, but answers in a plain sentence
  instead of calling submit_answer, and introduces a 1-cent typo restating it
  (21055.42 vs 21055.43) -- caught by the text-fallback parser, still wrong.
- 3 (Q25,Q26,Q27): on the hardest (join + 2 filters) questions, the model
  abandons real tool-calling and writes a JSON-shaped string as plain content.

Headline finding: giving the agent a retry loop DID improve its SQL reasoning
(two verified cases of successful self-correction, Q21 and Q23) but that gain
is currently invisible in the score because of an unrelated bug at the very
last step: llama3.2 3B cannot reliably restate a decimal number when calling
submit_answer. Fixing that one issue (likely M4 territory) could plausibly
move several easy/medium questions from BAD to OK without touching the SQL
logic at all.

2026-10-14  M3 trajectory inspector (src/inspect_trajectories.py): classifies
every incorrect row straight from trajectory (not from agent.py's own error/
steps_used fields), in this check order:
  1. no_submit_text   -- trajectory's last step has tool=None (model answered
                          in plain text or unparseable text instead of ever
                          calling a tool as its final move)
  2. ran_out_of_steps  -- hit MAX_STEPS (8) while last step is still run_sql,
                          never reached submit_answer
  3/4/5 (checked together): scan every run_sql step; "recovered" = at least
   one step's result matches expected (abs_tol 0.01); "had_error" = at least
   one step raised a real SQLite exception.
     - wrong_after_recovery: recovered is True (checked first) -- the right
       number appeared in some query result, but the final submitted answer
       does not match it. True regardless of whether an error ever occurred;
       covers both "error then fixed then lost it" (Q23) and "never erred,
       lost it on the very first try" (Q2, Q3).
     - gave_up_after_errors: not recovered, but had_error is True -- hit a
       real SQL error, retried, but never actually got the right number
       anywhere, and submitted something anyway (Q17-19: fixed the MONTH()
       syntax error but the retry query itself was still logically wrong).
     - silent_wrong: not recovered, no error ever -- a clean logic mistake
       with nothing to react to (Q28-31: dropped category filter).
Verified against the real run (31 rows): counts and per-row category checked
by hand against --id output for one example per category (16, 17, 21, 23, 28)
-- all five matched what a manual read of the trajectory would conclude.

RESULT:
Failures: 18/31
  no_submit_text: 4        (Q21, Q25, Q26, Q27)
  ran_out_of_steps: 4      (Q16, Q20, Q22, Q24)
  gave_up_after_errors: 3  (Q17, Q18, Q19)
  silent_wrong: 4          (Q28, Q29, Q30, Q31)
  wrong_after_recovery: 3  (Q2, Q3, Q23)

Prediction check: "fixes most of M1b's visible errors, little/no improvement
on silent ones" -- partially right, partially wrong. silent_wrong (dropped
filter) is exactly as predicted: 4/4 completely unfixed by the retry loop.
But the visible-error questions (MONTH(), missing join) did NOT mostly get
fixed -- they got reshuffled into three new failure shapes instead
(ran_out_of_steps, gave_up_after_errors, no_submit_text), and only
wrong_after_recovery (3 cases) shows the retry mechanism actually working
end-to-end on the SQL side, undone at the last step by decimal truncation.
Net effect: same medium/hard score as M1b (0/9, 0/7), two fewer easy correct
(13/15 vs 15/15) because of the same truncation bug hitting simple questions
too (Q2, Q3).

2026-10-14  M4 fix attempt #1: added a third tool, submit_last_result() (no
arguments -- code reads the last successful run_sql value directly, bypassing
the model retyping it), targeting wrong_after_recovery (3 cases: Q2, Q3, Q23).
Prediction: should fix all 3 wrong_after_recovery cases cleanly, no effect on
anything else.
Backed up pre-fix results to data/results_agent_v1.jsonl before rerunning.

RESULT: overall 12/31 (39%), DOWN from 13/31. Only 3 rows actually flipped:
  Q3  BAD->OK   (291.0 -> 291.521724137931, exact precision via submit_last_result -- works as designed)
  Q4  OK->BAD   (77.0 -> None, "no tool call: could not parse a number")
  Q7  OK->BAD   (83.0 -> None, "max steps reached", stuck repeating identical malformed SQL)
Q2 and Q23 (the other 2 wrong_after_recovery cases) were already BAD before
and stayed BAD after, just via a different failure mode -- the longer prompt
made their very first SQL attempt malformed instead of correct-then-truncated.

Diagnosis (checked by trajectory, not guessed): Q4 and Q7 both fail at STEP 1,
before submit_last_result is ever relevant -- the model's first SQL generation
itself broke on two previously one-shot-correct easy questions. Cause is the
longer SYSTEM prompt (new tool description + extra instruction paragraph), not
a bug in the submit_last_result code path itself -- that path is confirmed
correct by Q3.

Prediction check: WRONG on net effect. The targeted mechanism works exactly as
designed (Q3 proves it), but adding a third tool + more instructions to an
already-small model's prompt destabilized unrelated easy-question SQL
generation, costing more than the fix gained. Net: -1 question overall.
This is a real result, not reverted without discussion -- decision on whether
to keep, shorten the prompt and retry, or revert is pending.

2026-10-14  M4 fix attempt #2: shortened SYSTEM from 8 sentences to 5, kept
submit_last_result, hypothesis was that prompt length itself destabilized
Q4/Q7. RESULT: worse again, 11/31 (down from 12/31). Flips vs v1: Q3 fixed
(same clean win as attempt #1), but now Q4, Q8, Q11 broke (Q7 recovered this
time) -- net -3 vs v1, worse than attempt #1's net -1. Confirms prompt length
alone isn't the mechanism; shortening just moved the instability to different
questions rather than removing it.

Variance check (prompted by the above): reverted agent.py to the exact v1
code (plain run_sql + submit_answer, no submit_last_result, original SYSTEM),
ran all 31 questions 3 times with zero code changes between runs.
RESULT: 13/31 all three times, and every single question produced the
identical got value and correct/incorrect verdict across all 3 runs --
0/31 unstable. This model + this code is fully deterministic at temperature=0.

Conclusion: the three different scores (13, 12, 11) across the fix attempts
were NOT noise -- they are fully reproducible consequences of the specific
wording/tool-list changes. Adding a third tool and/or changing instruction
wording genuinely shifts the model's greedy-decoded output on OTHER,
unrelated questions elsewhere in the same run, not just the targeted ones.
This is a real property of this setup (shared context affects every
completion downstream), not run-to-run randomness, and it means any future
prompt/tool change to agent.py must be evaluated on the full 31, not assumed
to be isolated to the questions it was intended to affect.

DECISION: reverted agent.py to v1 (13/31, confirmed reproducible). The
wrong_after_recovery decimal-truncation bug (Q2, Q3, Q23) remains open,
documented, and deliberately NOT fixed -- two targeted attempts both produced
a net regression once the full 31-question effect was measured, not just the
3 targeted questions. Moving to a different, more isolated fix for the next
M4 attempt, or on to M5.