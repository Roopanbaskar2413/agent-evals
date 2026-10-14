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

2026-10-14  Diagnostics before M2b (read-only, no code or commits changed):
- repr() + unicodedata scan of all 4 ran_out_of_steps trajectories (Q16, 20,
  22, 24): Q16 has no quote characters at all -- the SQL is simply
  incomplete ("...= " with nothing after). Q20, Q22, Q24 all use smart/curly
  quote characters (U+201C/201D or U+2018/2019) instead of straight ASCII
  quotes, every single attempt, across 32 total attempts -- never once
  tries a plain quote.
- Raw ollama.chat replay of Q16 (data/scratch/diagnose_q16_raw.py, not
  committed): reproduced deterministically. The RAW tool_calls returned by
  Ollama already contain the truncated SQL string, with content=''. Confirms
  the truncation is the model's own generation, not a bug in agent.py's
  parsing -- get_arg() just reads the string Ollama already handed back.

2026-10-14  M2b prediction (written before running): adding a one-time nudge
-- when a step has no tool call, append one user message asking for
submit_answer, continue the loop, but only once per question -- can only
possibly change behavior for rows that actually hit the no-tool-call branch
in the current run: Q21, Q25, Q26, Q27 (the 4 current no_submit_text rows).
No other row's message history changes at all before that branch fires, and
the system prompt, tool list, and MAX_STEPS are unchanged, so by the same
determinism already confirmed (0/31 variance across 3 reruns of unchanged
code), all other 27 ids should produce byte-identical got/trajectory to the
current data/results_agent.jsonl.
Whether the 4 nudged rows become correct is uncertain and predicted separately:
- Q21: already stated the right number (21055.42, off by 1 cent) in plain
  text before. Nudging may just make it restate the same slightly-wrong
  number through a real submit_answer call -- predict still BAD.
- Q25, Q26, Q27: never ran a real query at all (step 1 was already a fake
  JSON-shaped text blob, no run_sql call happened). Nudging asks for
  submit_answer, not for it to go back and query -- predict these likely
  stay BAD too, since there's no real number behind them yet.
If any id outside {21, 25, 26, 27} changes, that would mean the determinism
assumption above is wrong and needs investigating, not explaining away.

RESULT: M2b overall 14/31 (45%), easy 13/15, medium 0/9, hard 1/7 -- up from
M2's 13/31. 5 rows changed, not the predicted 4: Q11, Q21, Q25, Q26, Q27.

Prediction MISS, root cause found (checked, not guessed): Q11 changed too.
Its original M2 trajectory also ended with a no-tool-call plain-text reply
at the last step, structurally identical to Q21/25/26/27 -- it just happened
to grade correct already (regex fallback parsed "5" correctly), so it never
showed up in inspect_trajectories.py's failure list, which only scans
INCORRECT rows. The prediction was built from that list, so it missed a row
that could be touched by the new branch. Determinism itself was not wrong;
the scoping of "which rows can the nudge possibly affect" was too narrow.

Per-row result:
- Q11: correct in both. M2 reached 5.0 via the regex fallback; M2b reached
  the same 5.0 via a real submit_answer call after one nudge (steps 6->7).
  Same grade, cleaner mechanism -- no concern.
- Q21: still BAD, and got WORSE: 21055.42 (1 cent off) -> 21055.0 (43 cents
  off). The nudge made the model restate the number less precisely than its
  own original sentence had.
- Q25: still BAD, got=3.0 (expected 13). Never ran a real query before or
  after the nudge -- step 1 was always a fake JSON-text blob, not a real
  tool call.
- Q26: BAD -> OK, got=3.0 (expected 3). NOT a real fix -- same fake-blob
  pattern as Q25/27, model guesses "3" with no query ever run. Matches
  expected by coincidence only (true count for this question happens to be
  3); the identical guess is wrong for Q25 (13) and Q27 (5).
- Q27: still BAD, got=3.0 (expected 5). Same fake-blob pattern, guess wrong.

Conclusion: net +1 (13->14) is mostly not real. One genuine neutral change
(Q11), one regression in precision (Q21), one lucky guess (Q26), two
unchanged (Q25, Q27). The nudge does not make the model go back and run a
query it skipped -- it only prompts for a final number, so rows that never
queried the database still don't query it after nudging, they just guess.
src/agent_m2b.py kept as a separate module (not merged into agent.py), per
the M4 lesson that prompt/tool changes must be evaluated in full before
being adopted. Not yet decided whether to keep, extend, or discard M2b.

2026-10-14  Code check (read-only): confirmed agent.py's no-tool-call branch
calls extract_number() on plain-text content and can set got from that alone
-- a text-only reply can grade correct without ever calling submit_answer.
Confirmed diff src/agent.py src/agent_m2b.py: the nudge logic (nudges
counter, the "if nudges == 0" branch, the nudges field) exists ONLY in
agent_m2b.py. agent.py's committed code is untouched.
Confirmed Q11 in the M2 (committed) trajectory ends on a text reply at step
6 ('The number of customers living in Pune is 5.'), tool=None, no
submit_answer call anywhere in its trajectory -- it graded correct purely
via the regex fallback.

Strict re-score (data/scratch/rescore_strict.py, read-only, no model calls):
recomputed got/correct from saved trajectories using ONLY a submit_answer
step's recorded value; any row that never called submit_answer gets
strict_got=None regardless of what the original row's got/correct said.
RESULT:
  M2  strict: 12/31 (vs the already-reported loose score 13/31)
    id 11 is the only row that changes: loose correct=True (got=5.0 via
    text fallback) -> strict correct=False (got=None, no submit_answer call
    in its trajectory at all).
  M2b strict: 14/31 (identical to the already-reported loose score -- no
    ids differ). By the time M2b ran, Q11 got nudged into actually calling
    submit_answer, so the fallback was never needed for it there.

Conclusion: under strict, submit_answer-only scoring the real M2->M2b gap is
12->14 (+2), not the loose +1. But one of those two points (Q26) is
confirmed to be a lucky guess -- the model never ran a real query for Q25,
Q26, or Q27 either before or after the nudge, it just states "3" for all
three, which happens to equal Q26's true answer and is wrong for the other
two. The other point (Q11) is a real mechanism improvement: same correct
data, now reached through an actual submit_answer call instead of an
accidental text-parse. M2b's "+1" headline score was overstating a lucky
guess as a fix; the honest read is "one real win, one coincidence."
M2c is next.

2026-10-14  Removed the plain-text number fallback from agent.py. The
no-tool-call branch no longer calls extract_number() on the reply content --
got stays None, error is just "no tool call". extract_number() itself and
the now-unused `import re` were deleted from agent.py (agent_m2b.py's import
of it is about to be removed too, once it's deleted in the next step).
inspect_trajectories.py updated to match: added strict_got(row), which scans
the trajectory for a submit_answer step and returns its value, or None --
used everywhere the script previously trusted the row's own got/correct
fields (show(), --bad, the summary counts), so the inspector can never
silently disagree with how agent.py itself grades.
Reran agent.py on all 31 (model unchanged, deterministic) to keep
data/results_agent.jsonl consistent with the new code.
RESULT: 12/31 (39%), easy 12/15, medium 0/9, hard 0/7 -- matches the strict
re-score exactly. Only Q11 differs from the previous committed file: now
"BAD, no tool call" instead of the old fallback-sourced "OK, got=5.0".
no_submit_text count goes from 4 to 5 (picks up Q11), all other 4 categories
unchanged.
OFFICIAL BASELINES from here on: M2 = 12/31, M2b = 14/31 (both strict,
submit_answer-only scoring).

2026-10-14  Refactored agent.py to take --nudge and --normalize-quotes flags
(both off by default, action="store_true"). --nudge reimplements exactly
what agent_m2b.py did (one-time nudge on no-tool-call, continue instead of
break). --normalize-quotes replaces curly/smart quotes (U+201C/201D/2018/
2019) with a plain ASCII quote in the SQL string before it's run.
Verified both flags off reproduces the strict M2 baseline exactly: 12/31,
0/31 fields differ (got and correct compared row by row against the saved
strict M2 results, not just the aggregate score).
Verified --nudge alone reproduces agent_m2b.py's 14/31 exactly: 0/31 fields
differ against the old results_agent_m2b.jsonl.
Deleted src/agent_m2b.py and data/results_agent_m2b.jsonl -- the --nudge
flag is now the only place that behavior lives.

2026-10-14  M2c prediction (written before running, --normalize-quotes only,
--nudge off): computed the ids whose saved run_sql arguments actually
contain a curly/smart quote character: [12, 20, 21, 22, 24].
Only these 5 ids may change. All other 26 should produce byte-identical
got/correct to the current flags-off baseline (12/31), same reasoning as the
M2b prediction: normalize_quotes() only runs inside the run_sql branch, so
a question whose trajectory never contains a smart quote is byte-for-byte
unaffected.
Per-id prediction:
- Q12: already correct (got=7.0) via self-correction on step 2 after a
  curly-quote error on step 1. Normalizing should let step 1 succeed
  directly -- predict stays correct, fewer steps (3 -> 2), no score change.
- Q20, Q22, Q24 (ran_out_of_steps, pure curly-quote loops, never once tried
  a straight quote in 8 attempts): predict these become correct, since the
  only known blocker was the quote character itself and the underlying join
  logic was already right.
- Q21: already contains both a curly-quote failure (step 1) AND a
  straight-quote success (step 4, got the exact right number 21055.43) in
  its saved trajectory. Normalizing quotes shouldn't change this path at all
  since step 1's failure already gets bypassed by the model's own retry --
  predict no change (still BAD, no tool call, same as the current flags-off
  baseline), since this row's problem was never the quote character, it was
  the model not calling submit_answer after step 4's correct result.
Expected net effect if prediction holds: 12/31 -> 15/31 (Q20, Q22, Q24 fixed,
Q12 unchanged just faster, Q21 unchanged). Not run yet.