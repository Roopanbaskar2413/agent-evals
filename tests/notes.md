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

Trajectory-level prediction (added before running): Q20, Q22, Q24 -- the
step-2 query executes and returns a number (high confidence); whether the
final answer is graded correct is uncertain and separate.

RESULT (data/results_agent_normalizequotes.jsonl): 12/31, unchanged from the
flags-off baseline. Every changed id was in the predicted set {12,20,21,22,24}
-- no surprises outside the prediction this time.
  Q12: correct->correct, steps 3->2 (as predicted exactly).
  Q20, Q22, Q24: BAD->BAD. Trajectory prediction held exactly -- step 2 now
    runs and returns the precise right number (20232.22, 9772.15, 15603.82)
    -- but the top-level correctness prediction was wrong: they don't become
    correct, because fixing the quote bug just exposes the pre-existing
    submit_answer decimal-truncation bug underneath (got 20232.0, 9772.0,
    15603.0). One bug traded for another on the same 3 questions, net zero.
  Q21: BAD->BAD as predicted, but the mechanism changed more than expected --
    previously ended via "no tool call" (text reply after a correct query),
    now ends via a real submit_answer call that's truncated (got=21055.0).
    Same root bug (decimal truncation) as Q20/22/24, just reached through a
    different path than predicted.

Scan for near-tolerance-boundary misses (abs(got-expected) in [0.005,0.01]),
across all 10 result files on disk (data/results_*.jsonl and
data/scratch/results_*.jsonl), grader untouched: zero matches. The earlier
Q21 case (diff ~=0.01000000000022, just above this range) no longer exists
in any currently saved file -- it was overwritten when the plain-text
fallback was removed from agent.py.

Conclusion: --normalize-quotes fixes exactly what it targets (the quote
character), proving the ran_out_of_steps category's cause was correctly
diagnosed, but it does not raise the score by itself, because
wrong_after_recovery (decimal truncation at submit_answer) is a second,
independent bug sitting right behind it on the same questions. Fixing both
quote normalization AND the truncation bug together is the next logical
step, not a new M4 attempt on a fresh failure type.

2026-10-14  Read-only check across all 8 saved results_agent*.jsonl files
(158 total submit_answer calls): the model NEVER used the declared argument
name "number" -- only "a" (105x) or "x" (53x), 0 times "number". Of the 53
submits where the expected answer has a nonzero decimal part, 0 kept any
decimal digit in the submitted value (all 53 dropped it).
CAVEAT: this 0/53 is incomplete, not just surprising. data/results_agent_m2b
.jsonl (which had one confirmed exception -- Q3 via the old nudge path kept
full precision, 291.521724137931) was deleted when agent_m2b.py's behavior
was folded into --nudge. The scan is accurate for what's on disk now, but
the full history had at least one counterexample that's no longer in it.

2026-10-14  Added --structured-final to agent.py (off by default). When on,
AND the loop ended via a real submit_answer call (used_submit_tool), one
extra ollama.chat call is made after the loop: full transcript + a user
message asking for the final numeric answer, format=FinalAnswer
(pydantic, number: float), temperature 0. That value overwrites got.
Verified flags-all-off still reproduces strict M2 exactly: reran with no
flags, 0/31 diffs against the pre-refactor saved results.
FinalAnswer/pydantic were already a project dependency (used in baseline.py)
-- no new dependency added.

Ids that called submit_answer in the saved M2c results (data/results_agent_
normalizequotes.jsonl) -- only these 26 may change under --structured-final,
since the extra call is gated on used_submit_tool:
[1,2,3,4,5,6,7,8,9,10,12,13,14,15,17,18,19,20,21,22,23,24,28,29,30,31]
(11, 16, 25, 26, 27 never called submit_answer in M2c and cannot change.)

Per-id prediction, split into what's known (does the right number appear in
some query result already) vs what's uncertain (will the re-ask grade
correct) -- NOT RUN YET:

Group A -- already correct, integer expected, right number already in a
query result (known=yes): 1,4,5,6,7,8,9,10,12,13,14,15.
  Uncertain: re-asking should return the same integer -- predict no change,
  still correct. Low risk since there's no decimal to lose.

Group B -- currently BAD via decimal truncation, right number IS present in
a query result in the trajectory (known=yes): 2,3,20,21,22,23,24.
  Uncertain: whether a second, separate structured-output call (JSON
  schema forcing number:float, not a free-form tool-call argument) makes
  the model restate the number with full precision this time. This is a
  genuinely different generation path than submit_answer's tool-call
  argument, so unlike the earlier failed prompt-wording fixes, this has a
  real mechanical reason to behave differently -- but still uncertain.
  Predict: some or all of these flip to correct; cannot predict how many
  without running it.

Group C -- currently BAD, right number was NEVER in any query result in the
trajectory (known=no -- there is nothing correct to recover):
17,18,19,28,29,30,31.
  Uncertain in principle, but predict with high confidence: stay incorrect.
  Re-asking for "the final numeric answer" cannot produce a number the
  model never actually computed; at best it restates the same wrong number
  already in the transcript (0.0 for 17-19, 242.63... for 28-31).

Expected net effect if prediction holds: Group A unchanged (12 correct),
Group C unchanged (7 incorrect), Group B is the only open question --
net could range from 12/31 (no change) to 19/31 (all of Group B fixed).
Not run yet.

RESULT (data/results_agent_normalizequotes_structuredfinal.jsonl): 12/31
(39%), easy 12/15, medium 0/9, hard 0/7 -- identical to the 12/31 baseline.
Prediction held on scope: no Group A regressions, no id outside the 26
eligible changed at all.
Group B (the open question) resolved to the worst case: 0/7 recovered.
Every one of 2,3,20,21,22,23,24 restates the SAME truncated value through
the structured_final call as it already had from submit_answer:
  id  query_value         structured_final  correct
  2   39064.32            39064.0           False
  3   291.521724137931    291.0             False
  20  20232.22            20232.0           False
  21  21055.43            21055.0           False
  22  9772.15             9772.0            False
  23  9913.59             9913.0            False
  24  15603.82            15603.0           False
Cause (visible in the full transcript the structured_final call sees): the
model re-derives its answer from its own prior submit_answer statement
(already truncated) rather than looking back at the original run_sql
result earlier in the same transcript, even though the schema explicitly
allows a float and nothing prevents it from reading further back.

Token cost: average tokens per question went DOWN, not up --
tokens_in 1153.4->1111.2, tokens_out 85.7->68.3 vs the flags-off baseline.
The extra structured_final call does cost tokens on the 19 ids where it
fires, but --normalize-quotes lets Q20/22/24 finish in 3 steps instead of 8
(no more burning the full step cap on repeated quote failures), and that
savings outweighs the extra call's cost across the full 31.

Conclusion: --structured-final does not help at all once a wrong number is
already committed via submit_answer -- the model treats its own prior
tool-call argument as ground truth and restates it, rather than re-reading
the original query result still present in the same context. The real fix
has to happen before or during the submit_answer call itself, not after it.
M2d reverts to being an interesting negative result, not a step forward.
Not committed -- pending review.

2026-10-14  Isolated precision test (data/scratch/test_isolated_structured.py,
not committed): one ollama.chat call per id, ONLY "{question}\nQuery result:
{result}" as the user message, format=Answer(number:float), temperature 0 --
no transcript, no prior submit_answer call in context at all. All 7 of
2,3,20,21,22,23,24 returned the exact query value, decimals intact
(e.g. 291.521724137931 -> 291.521724137931). Confirms the model CAN carry
full precision through structured output; the full-pipeline failure
(--structured-final, 0/7) is specifically caused by the prior truncated
submit_answer statement still sitting in the transcript, not a general
inability to handle decimals via structured output.
Corrected token comparison (M2c alone vs M2c+structured-final, not vs the
flags-off baseline): --structured-final itself costs +248.1 tokens_in,
+6.0 tokens_out per question on average, isolated from --normalize-quotes'
own token savings.

2026-10-14  Added --final-from-result to agent.py (off by default, mutually
exclusive with --structured-final -- enforced in main(), p.error() if both
given). When on, and the loop ended via a real submit_answer call, one
ollama.chat call is made with ONLY {"role":"user","content": f"{question}\n
Query result: {last_sql_output}"} -- no system prompt, no transcript, none
of the model's own submit_answer call -- format=FinalAnswer, temperature 0.
That value becomes got. last_sql_output tracks the string of the most
recent run_sql call that did NOT error (updated unconditionally in the
loop, used only when this flag is on). If no run_sql ever succeeded, got is
set to None directly (no model call made) per spec.
Verified flags-all-off still reproduces strict M2 exactly: reran with no
flags, 0/31 diffs against the pre-refactor saved results.

Prediction (written before running --normalize-quotes --final-from-result),
same A/B/C groups as the --structured-final prediction, with confidence:

Group A (1,4,5,6,7,8,9,10,12,13,14,15) -- already correct, integer expected.
  Prediction: HIGH confidence these stay correct, following directly from
  the isolated precision test (the model reliably returns the right number
  when given only the question + a clean query result, no prior-answer
  bias in context). BUT stated plainly because it was asked for: Group A
  COULD regress here in a way it structurally could not under
  --structured-final. --structured-final only ever fires after submit_answer
  and uses the full transcript (including the model's own already-correct
  integer answer), so it had little room to go wrong on these. 
  --final-from-result discards that transcript entirely and re-derives the
  answer from a bare, out-of-context {question, query_result} pair -- a
  genuinely different (and harder, since it has zero conversational
  support) task for the model each time, run separately per question, so a
  regression on one or more of these 12 is possible, just not predicted.
Group B (2,3,20,21,22,23,24) -- currently BAD via decimal truncation, right
  number present in the trajectory's run_sql result.
  Prediction: HIGH confidence these become correct. This is exactly the
  isolated precision test's setup, id for id (same questions, same query
  results) -- that test already showed 7/7 exact matches under this
  precise input shape.
Group C (17,18,19,28,29,30,31) -- right number never appeared in any
  run_sql result at all.
  Prediction: HIGH confidence these stay incorrect. last_sql_output for
  these ids holds the WRONG number (0 for 17-19, 242.63... for 28-31,
  the same silently-wrong result the agent already computed) -- there is
  nothing for --final-from-result to recover, since it only ever re-derives
  from whatever run_sql last returned, right or wrong.

Expected net effect if prediction holds: 12/31 -> 19/31 (Group B fully
fixed, A and C unchanged). Not run yet.

RESULT (data/results_agent_normalizequotes_finalfromresult.jsonl): 16/31
(52%), easy 11/15, medium 5/9, hard 0/7 -- up from the 12/31 baseline, but
not the predicted 19/31.

Group B: prediction CONFIRMED exactly -- all 7/7 recovered, exact matches:
  id  query_value          final_from_result    correct
  2   39064.32             39064.32             True
  3   291.521724137931     291.521724137931     True
  20  20232.22             20232.22             True
  21  21055.43             21055.43             True
  22  9772.15              9772.15              True
  23  9913.59              9913.59              True
  24  15603.82             15603.82             True

Group A: prediction's stated risk CONFIRMED -- 3 of 12 regressed:
  id=4  got=1.0  expected=77
  id=6  got=1.0  expected=67
  id=13 got=1.0  expected=9
All three return the identical hallucinated value 1.0, regardless of the
actual question -- the same pattern as the earlier Q25/26/27 "guess 3 for
everything" failure mode, now showing up here because stripping the
transcript removes the conversational grounding that made these simple
count questions trivial in context. Re-deriving from a bare
{question, query_result} pair is a harder task than it looks for a 3B
model when the question has no surrounding context.

Group C: unchanged as predicted, 0/7 (17,18,19,28,29,30,31) -- nothing to
recover since last_sql_output held the wrong number for all of these.

No id outside the 26 eligible changed. Net: 12->16 (+4), not the predicted
+7, because the 3 Group A regressions partially offset the 7 Group B gains.

Token cost vs --normalize-quotes-only (the correct baseline for isolating
this flag's cost): tokens_in +36.4, tokens_out +9.5 per question on average
-- far cheaper than --structured-final's +248.1/+6.0, because this call
sends a short two-line prompt instead of resending the whole transcript.

Conclusion: --final-from-result is the first change in this whole M2
series that raises the strict score, and cheaply. But it has a real,
measured cost (3 new regressions on previously-easy questions) that a
narrower before/after on just the targeted ids would have hidden -- this is
exactly why the "report ids outside the eligible set" and "state Group A
could regress" instructions mattered. Not committed -- pending review.
Open question for next step: can Group A's regression be avoided (e.g. by
only applying --final-from-result when the submitted answer actually has
a decimal, since Group A's correct integer answers never needed re-deriving
in the first place)?

2026-10-14  Added --precision-only to agent.py (off by default). With
--final-from-result, skips the re-derivation call when the last successful
run_sql result is already a whole number (is_whole_number(), a regex +
int-equality check on the raw result string) -- keeps the original
submit_answer value in that case instead of risking it on a bare
{question, query_result} re-ask. Verified flags-all-off still reproduces
strict M2 exactly: 0/31 diffs. Sanity-checked on the DEV set (not the
held-out set) that this actually fixes the earlier regression:
--normalize-quotes --final-from-result --precision-only -> 19/31 (easy
14/15, medium 5/9, hard 0/7) -- Q4, Q6, Q13 all correct again, Group B
(2,3,20,21,22,23,24) still 7/7 fixed. Best dev-set score of the whole M2
series. Not committed yet.

Added --questions to all three runners (baseline.py, baseline_sql.py,
agent.py), default data/questions.jsonl, so any question file can be
selected without editing code.

Built data/questions_heldout.jsonl (src/make_questions_heldout.py): 60
questions from the same templates as make_questions.py, using parameter
values never used in the dev set (customer ids outside {3,12,27}; months
outside {1,4,8,11}; fresh (city,category) pairs for the hard join+2-filter
template; status='pending' introduced as the varied second dimension
wherever a dimension was already exhausted in the dev set, e.g. "average
pending {category} orders" in place of "average delivered {category}
orders"). One dev template (customers-by-city, easy) has no held-out
variant: the customers table only has id/name/city, every city is already
used in the dev set, and there is no second column to vary -- deliberately
not replicated, documented in the script's own comment. 26 easy / 16
medium / 18 hard, same database (shop.db, seed 42), expected answers
computed by real SQL exactly as in make_questions.py.

PRE-REGISTRATION -- held-out evaluation, written before running it.
(Corrected to 5 configurations -- the original 4-config version above
collapsed two distinct configs, --final-from-result alone and
--final-from-result --precision-only, into one; both are run and reported
separately below so precision-only's own effect is visible on held-out
data too, not just assumed from the dev-set result.)

Five configurations to run on data/questions_heldout.jsonl, via --questions:
  1. M1b   : python -m src.baseline_sql --questions data/questions_heldout.jsonl
  2. M2    : python -m src.agent --questions data/questions_heldout.jsonl
             (strict M2, all flags off -- the already-established 12/31 dev
             baseline's exact configuration, no change)
  3. normalize-quotes only:
             python -m src.agent --normalize-quotes
             --questions data/questions_heldout.jsonl
  4. normalize-quotes + final-from-result:
             python -m src.agent --normalize-quotes --final-from-result
             --questions data/questions_heldout.jsonl
  5. normalize-quotes + final-from-result + precision-only:
             python -m src.agent --normalize-quotes --final-from-result
             --precision-only --questions data/questions_heldout.jsonl

What will be reported for each of the 5 configs, on the held-out set:
  - overall score and the easy/medium/hard breakdown
  - for the 4 agent.py configs (M2 and the 3 flag combinations): the
    failure-type breakdown from inspect_trajectories.py
  - average tokens_in/tokens_out per question, for the 4 agent.py configs
  - the full comparison table: dev-set score vs held-out-set score, for
    all 5 configs side by side, since the real question this run answers
    is whether the dev-set ranking holds up on data none of the fixes were
    built against.

Commitment, stated before seeing any held-out result: nothing gets tuned,
re-prompted, or re-fixed based on what the held-out run shows. No new flag,
no prompt edit, no threshold change in response to a held-out failure.
Whatever breaks on the held-out set is written up in the README as a
finding -- e.g. "normalize-quotes + final-from-result generalizes to new
cities but not to new months" is a result to report, not a bug to patch. This is the whole point of holding
the set out: M4's repeated pattern in this project (fix one thing, measure
full effect, sometimes revert) was legitimate because every fix was judged
against the same dev set it was built on, with full before/after visibility.
Held-out evaluation is a different kind of claim -- it's evidence the
dev-set gains are real improvements, not dev-set-specific overfitting --
and that claim is only honest if nothing is adjusted afterward. Not run yet.

RESULT -- held-out evaluation (data/questions_heldout.jsonl, 60 questions).
Numbers only, no interpretation, no changes made as a result of this run.
Output files: data/results_baseline_sql_heldout.jsonl,
data/results_agent_heldout.jsonl,
data/results_agent_normalizequotes_heldout.jsonl,
data/results_agent_normalizequotes_finalfromresult_heldout.jsonl,
data/results_agent_normalizequotes_finalfromresult_precisiononly_heldout.jsonl.
(Note: baseline_sql.py and agent.py write to a fixed filename per flag
combo regardless of --questions, so each held-out run first overwrote the
same-named dev-set file; every one was copied out under a _heldout name
and the original dev-set file restored via git checkout immediately after,
before the next config ran. All 5 dev-set tracked files confirmed clean via
git status after. The one untracked dev file,
results_agent_normalizequotes_finalfromresult_precisiononly.jsonl, was
manually backed up to data/scratch/ first and restored from that copy.)

TABLE 1 -- held-out score, breakdown, and average tokens per configuration:
  M1b                                                 22/60  easy 21/26  medium 0/16  hard 1/18   tokens_in=136.7   tokens_out=24.2
  M2 (strict)                                         20/60  easy 16/26  medium 0/16  hard 4/18   tokens_in=1220.1  tokens_out=99.3
  normalize-quotes                                    20/60  easy 16/26  medium 0/16  hard 4/18   tokens_in=1220.1  tokens_out=99.3
  normalize-quotes+final-from-result                  19/60  easy 13/26  medium 0/16  hard 6/18   tokens_in=1260.5  tokens_out=107.4
  normalize-quotes+final-from-result+precision-only   24/60  easy 19/26  medium 0/16  hard 5/18   tokens_in=1225.5  tokens_out=101.0

TABLE 2 -- per-difficulty, dev vs held-out, each configuration:
  M1b
    easy    dev 15/15   held-out 21/26
    medium  dev 0/9     held-out 0/16
    hard    dev 0/7     held-out 1/18
  M2 (strict)
    easy    dev 12/15   held-out 16/26
    medium  dev 0/9     held-out 0/16
    hard    dev 0/7     held-out 4/18
  normalize-quotes
    easy    dev 12/15   held-out 16/26
    medium  dev 0/9     held-out 0/16
    hard    dev 0/7     held-out 4/18
  normalize-quotes+final-from-result
    easy    dev 11/15   held-out 13/26
    medium  dev 5/9     held-out 0/16
    hard    dev 0/7     held-out 6/18
  normalize-quotes+final-from-result+precision-only
    easy    dev 14/15   held-out 19/26
    medium  dev 5/9     held-out 0/16
    hard    dev 0/7     held-out 5/18

TABLE 3 -- failure-type breakdown (inspect_trajectories.classify(), applied
read-only to each held-out results file), for the 4 agent.py configurations:
  M2 (strict): failures 40/60
    no_submit_text: 7, ran_out_of_steps: 11, gave_up_after_errors: 8,
    silent_wrong: 9, wrong_after_recovery: 5
  normalize-quotes: failures 40/60
    no_submit_text: 7, ran_out_of_steps: 11, gave_up_after_errors: 8,
    silent_wrong: 9, wrong_after_recovery: 5
  normalize-quotes+final-from-result: failures 41/60
    no_submit_text: 6, ran_out_of_steps: 11, gave_up_after_errors: 9,
    silent_wrong: 9, wrong_after_recovery: 6
  normalize-quotes+final-from-result+precision-only: failures 36/60
    no_submit_text: 7, ran_out_of_steps: 11, gave_up_after_errors: 8,
    silent_wrong: 9, wrong_after_recovery: 1

Results not committed -- pending review, per instruction to stop before
committing results.

2026-10-14  Filename fix (item 1): added questions_tag() to agent.py,
baseline.py, baseline_sql.py -- the results filename now includes a tag
derived from --questions when it differs from the default dev set (e.g.
data/questions_heldout.jsonl -> _heldout appended), and stays exactly the
same filename as before when --questions is not passed (tag == ""). This
is why the held-out run above needed a manual rescue/restore step; it
won't be needed for future runs.
Verified: flags-off on the dev set still writes to data/results_agent.jsonl
(unchanged path) and gives 12/31, 0/31 fields different from the pre-fix
saved copy.

2026-10-14  Read-only follow-up analysis (item 2), numbers only, no code
changes, no tuning:

(a) Smart-quote scan + cmp, held-out M2 vs +quotes:
  M2 heldout: ids with a smart quote (U+2018/2019/201C/201D) in any
    run_sql argument: [] (0)
  +quotes heldout: same scan: [] (0)
  cmp data/results_agent_heldout.jsonl data/results_agent_normalizequotes_
    heldout.jsonl: differ at char 7507, line 16.
  Full id-level diff (not just first byte): exactly 2 ids differ, 16 and
    18 -- both still incorrect in both files (M2 id16 got=None/id18
    got=161.0; +quotes id16 got=161.0/id18 got=None). No smart quotes
    involved in either differing row.

(b) Re-score data/results_agent_normalizequotes_finalfromresult_
    precisiononly.jsonl (dev) using is_correct(got, expected) directly:
    19/31. Confirmed.

(c) Paired counts (question-id matched), C2 = normalize-quotes+final-
    from-result+precision-only:
  dev:
    C2 vs M1b: both_correct=14  only_C2=5  only_M1b=1  neither=11
    C2 vs M2:  both_correct=12  only_C2=7  only_M2=0   neither=12
  held-out:
    C2 vs M1b: both_correct=20  only_C2=4  only_M1b=2  neither=34
    C2 vs M2:  both_correct=20  only_C2=4  only_M2=0   neither=36

(d) Oracle router (correct if M1b OR C2 is correct, per question):
  dev:      overall 20/31   easy 15/15  medium 5/9   hard 0/7
  held-out: overall 26/60   easy 21/26  medium 0/16  hard 5/18

(e) Per-template scores, held-out, all 5 configs (10 templates: 14
    customer_id_count, 4 category_delivered_count, 4 category_pending_count,
    4 status_only_twists, 8 month_count, 8 month_sum, 5 city_pending_join,
    5 city_category_delivered_join, 4 city_category_pending_join,
    4 avg_pending_category):
  M1b:
    customer_id_count 14/14, category_delivered_count 0/4,
    category_pending_count 3/4, status_only_twists 4/4, month_count 0/8,
    month_sum 0/8, city_pending_join 0/5, city_category_delivered_join 0/5,
    city_category_pending_join 0/4, avg_pending_category 1/4
  M2 (strict):
    customer_id_count 14/14, category_delivered_count 0/4,
    category_pending_count 1/4, status_only_twists 1/4, month_count 0/8,
    month_sum 0/8, city_pending_join 4/5, city_category_delivered_join 0/5,
    city_category_pending_join 0/4, avg_pending_category 0/4
  normalize-quotes:
    customer_id_count 14/14, category_delivered_count 0/4,
    category_pending_count 1/4, status_only_twists 1/4, month_count 0/8,
    month_sum 0/8, city_pending_join 4/5, city_category_delivered_join 0/5,
    city_category_pending_join 0/4, avg_pending_category 0/4
  normalize-quotes+final-from-result:
    customer_id_count 8/14, category_delivered_count 0/4,
    category_pending_count 1/4, status_only_twists 4/4, month_count 0/8,
    month_sum 0/8, city_pending_join 5/5, city_category_delivered_join 0/5,
    city_category_pending_join 0/4, avg_pending_category 1/4
  normalize-quotes+final-from-result+precision-only:
    customer_id_count 14/14, category_delivered_count 0/4,
    category_pending_count 1/4, status_only_twists 4/4, month_count 0/8,
    month_sum 0/8, city_pending_join 4/5, city_category_delivered_join 0/5,
    city_category_pending_join 0/4, avg_pending_category 1/4

(f) Tokens per correct answer ((tokens_in+tokens_out summed over all rows)
    / count correct), dev and held-out:
  dev:
    M1b: total=4913 correct=15 tokens/correct=327.5
    M2: total=38411 correct=12 tokens/correct=3200.9
    normalize-quotes: total=28685 correct=12 tokens/correct=2390.4
    normalize-quotes+final-from-result: total=30106 correct=16 tokens/correct=1881.6
    normalize-quotes+final-from-result+precision-only: total=29358 correct=19 tokens/correct=1545.2
  held-out:
    M1b: total=9658 correct=22 tokens/correct=439.0
    M2: total=79161 correct=20 tokens/correct=3958.1
    normalize-quotes: total=79161 correct=20 tokens/correct=3958.1
    normalize-quotes+final-from-result: total=82074 correct=19 tokens/correct=4319.7
    normalize-quotes+final-from-result+precision-only: total=79590 correct=24 tokens/correct=3316.2

(g) Held-out run_sql arguments ending in a dangling operator (=, LIKE, IN,
    "(", case-insensitive, trailing whitespace stripped), all 4 agent
    configs, with the difficulty tier of the affected question ids:
  M2 (strict): 26 occurrences, unique ids {15,16,17,32}
    easy ids {15,16,17} (category_delivered_count template, "...WHERE
      category = ? AND status =" truncated before the literal)
    medium id {32} (month_count template, "...SUBSTR(order_date,5,2) ="
      truncated -- same shape as dev-set Q16)
    all occurrences end in "=" specifically; none end in LIKE, IN, or "("
  normalize-quotes: 26 occurrences, unique ids {15,17,18,32} (same two
    templates/tiers as M2, slightly different id set)
  normalize-quotes+final-from-result: 26 occurrences, unique ids
    {15,16,17,32} (same pattern)
  normalize-quotes+final-from-result+precision-only: 26 occurrences,
    unique ids {15,16,17,32} (same pattern)
  Across all 4 configs: the dangling-operator bug only ever appears in
  these same two templates (category_delivered_count/easy and
  month_count/medium), and always ends in "=", never LIKE/IN/"(".

No code changes beyond item 1 (the filename fix). No tuning performed in
response to any of the above.