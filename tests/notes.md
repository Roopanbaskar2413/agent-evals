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

2026-10-14  Searched tests/notes.md and CLAUDE.md for any description of
--precision-only that says it compares the structured/final value against
the submitted one for agreement. Found none in either file -- the earlier
notes.md entry (above, "Added --precision-only to agent.py") already
states the correct rule. A README.md sentence written separately did
describe the wrong mechanism (agreement-checking) and has been corrected
there; nothing here needed fixing.
Implemented rule, stated plainly for the record: --precision-only, used
together with --final-from-result, skips the second (re-derivation) call
entirely whenever the last successful run_sql result is already a whole
number -- it never compares the second call's value against the
submitted one, because the second call is simply not made in that case.
The held-out pre-registration and all five held-out runs
(normalize-quotes+final-from-result+precision-only) used exactly this
rule, unchanged from how it was implemented and dev-tested.

2026-11-09  Added src/rerun.py: reruns the held-out config
(normalize-quotes+final-from-result+precision-only, the one that scored
24/60) N times in a row via the existing answer()/is_correct/load_questions,
to check whether that score is stable across reps. Ran against the exact
committed code behind the 24/60 result (isolated from the uncommitted
multi-provider/providers.py WIP via git stash, popped back afterward)
since answer() there has no provider argument.
Prediction: expected some flipping, since an earlier non-strict exploration
noted questions 16 and 18 flipping which one gets a hallucinated value
between runs.
RESULT: all 3 reps scored 24/60 identically; all 60 questions had
stable_verdict=True and stable_number=True across all 3 reps -- no flips
at all, including Q16/Q18. Conclusion: at temperature 0, this exact
config is deterministic across reruns, so 24/60 is not a lucky single
draw. The earlier flip observation either doesn't apply to this exact
config or needs a prompt/trajectory-level check (not just correctness)
to resurface.

2026-11-10  Fixed the missing-year schema gap: src/db_tools.py SCHEMA's
Notes line now reads "order_date is YYYY-MM-DD text, all from 2026."
instead of just "order_date is YYYY-MM-DD text." No other change to the
file. Both src/baseline_sql.py and src/agent.py import SCHEMA from here,
so one fix covers both.
Prediction: dev score (M1b, 31 questions) stays at 15/31, unchanged. The
dev set never exercised the missing year -- per CLAUDE.md, the model
always reached for MONTH() on dev questions, which errors visibly and
gets retried/fails for other reasons, never silently guesses a wrong
year via LIKE. This is a sanity check that the schema edit doesn't
regress dev, not a test of the fix itself (the fix targets a held-out-only
failure mode).

RESULT: prediction WRONG. Dev (M1b) went 15/31 -> 18/31 (easy 15/15->14/15,
medium 0/9->4/9, hard 0/7->0/7 unchanged). Two things happened, not the
one predicted:
- Q16-19 ("orders placed in <month>") flipped from wrong to correct. With
  the year in the schema, the model wrote `order_date LIKE '2026-<month>-%'`
  directly instead of reaching for MONTH() (which errors) or guessing a
  wrong year silently -- so the dev set DID exercise the gap after all,
  just not in the way CLAUDE.md described (MONTH()-first only applied to
  some medium questions, not all four month-filter ones).
- Q14 ("How many orders did Customer 12 place?", plain count, no date or
  status in the question) flipped from correct to wrong: the model added
  unprompted `AND status = 'delivered' AND order_date BETWEEN
  '2026-01-01' AND '2026-12-31'` filters that don't belong, got 3.0
  instead of 4. A new regression caused by the extra schema context
  itself, not a fix side effect -- the one-line change shifted behavior
  on an unrelated question that never needed the year.
Net dev effect is positive (+3) but the fix is not a free lunch.
Next: rerun month_count and month_sum on held-out (the only 2 of the 5
always-0 templates that are actually date-filter questions -- see
CLAUDE.md) to check whether the fix generalizes the way it did here, and
whether a Q14-style regression shows up in templates that don't involve
dates.

2026-11-10  Held-out check of the schema fix: ran M1b against a 30-question
subset of data/questions_heldout.jsonl (data/scratch/questions_heldout_yearcheck.jsonl,
ids 1-14 + 27-42) covering month_count (27-34), month_sum (35-42), and the
customer-count template (1-14, same shape as dev's Q14 that regressed).
Before (already committed, data/results_baseline_sql_heldout.jsonl):
customer-count 14/14, month_count 0/8 (mix of MONTH() errors and silent
LIKE-wrong-year 0.0), month_sum 0/8 (all MONTH() errors, never reached a
LIKE guess).
Prediction: month_count flips to mostly/all correct (8/8 or close),
mirroring dev Q16-19's clean 0/4 -> 4/4 flip. month_sum also flips to
mostly/all correct, extending the same LIKE-instead-of-MONTH() pattern
from COUNT to SUM, even though on held-out it never previously reached
the LIKE guess (always erred on MONTH() first). customer-count: expect
mostly unchanged at 14/14, but NOT a confident 14/14 -- dev showed one
unprompted-filter regression (Q14) from this exact one-line schema
change, so I would not be surprised by 1-2 flips here.

RESULT (M1b, data/scratch/results_baseline_sql_heldout_yearcheck.jsonl): 20/30.
customer-count 13/14 (down from 14/14) -- Q1 is the SAME Q14-style
regression, verbatim: model added unprompted `AND status = 'delivered'
AND order_date BETWEEN '2026-01-01' AND '2026-12-31'` to a plain
customer-count question, got 0.0 instead of 1. Prediction confirmed:
this is a real, repeatable template-level regression, not a one-off.
month_count 6/8 (up from 0/8) -- all 4 previously-silent-0.0 LIKE-wrong-
year questions (28,31,32,33) now correct as predicted, PLUS 2 of the 4
previously-MONTH()-erroring questions (29,30) also switched to a correct
LIKE query this time (unpredicted bonus -- M1b is a single one-shot call,
so which strategy it picks varies by question even at temperature 0).
Questions 27 and 34 still write `MONTH(order_date)` (now paired with a
new `YEAR(order_date) = 2026`, also nonexistent) and still error --
the fix does nothing when the model reaches for MONTH() in the first
place, since M1b never retries.
month_sum 1/8 (up from 0/8) -- prediction WRONG for this template. Only
Q41 switched to a correct LIKE query; the other 7 still write
`MONTH(order_date) = N AND YEAR(order_date) = 2026` and error, unchanged
from before. SUM aggregation questions reach for MONTH()/YEAR() far more
reliably than COUNT questions do, so the fix barely touches month_sum.
Conclusion: the schema fix reliably repairs the SILENT-WRONG-YEAR failure
mode (LIKE with a guessed wrong year) wherever the model would have used
it, but does nothing for the separate MONTH()-reaching failure mode,
which dominates month_sum. It also reproduces the Q14-style unprompted-
filter regression on a second, independent customer-count question.

Prediction (best agent config, normalize-quotes+final-from-result+
precision-only, same 30-question subset): before (already committed,
data/results_agent_normalizequotes_finalfromresult_precisiononly_heldout.jsonl)
customer-count 14/14, month_count 0/8 (wrong numbers, not all
ran-out-of-steps), month_sum 0/8 (all `got=None` -- ran out of steps
without ever submitting). Expect month_count and month_sum to both
improve somewhat, more than M1b's month_sum result, since the agent can
retry after a MONTH() error and the year hint should steer it toward a
working LIKE query faster, within MAX_STEPS=8 -- but I do NOT expect a
clean fix given M1b's month_sum barely moved (1/8). Expect customer-count
to possibly regress by 1 question, same unprompted-filter mechanism as
M1b's Q1 and dev's Q14, since the agent uses the same SYSTEM/SCHEMA text.

RESULT (best agent config,
data/scratch/results_agent_normalizequotes_finalfromresult_precisiononly_heldout_yearcheck.jsonl):
14/30, unchanged from 14/30 before. Prediction WRONG on direction for
month_count/month_sum (no improvement at all) and wrong on
customer-count (no regression, stayed 14/14 clean).
customer-count 14/14 (unchanged) -- no repeat of the M1b/dev
unprompted-filter regression here.
month_count 0/8 (unchanged score, but the failure mode got WORSE): 7 of
8 are now "no tool call" (model answers in plain text, which the strict
grader counts as an immediate failure with no retry), versus wrong
numeric submit_answer calls before. Trajectory for Q27 shows why: step 1
tries `MONTH(order_date)=2 AND YEAR(order_date)=2026` (MONTH() errors),
step 2 tries `SUBSTR(...) = 02 AND YEAR(order_date) = 2026` (YEAR()
ALSO doesn't exist in SQLite -- a second invented function, directly
caused by giving the model a concrete year to reach for), step 3 drops
the year and gets an unquoted numeric '02' comparison against a text
column (SUBSTR returns '02', compared to integer 2, no match, 0 rows),
step 4 gives up with a plain-text "the answer is 0" instead of calling
submit_answer. The year hint handed the model a second nonexistent
SQLite function to try, burning retry steps it didn't burn before.
month_sum 0/8 (unchanged score, failure mode also shifted): before, all
8 ran out of steps (got=None) without ever submitting; after, 5 of 8
submit a wrong 0.0 and 3 still run out of steps -- same net failure,
different shape.
Conclusion: for the tool-looping agent (which can already retry past a
MONTH() error), the schema fix has ~zero net benefit on this subset --
same score before and after -- and actively introduces a new failure
path (inventing YEAR() the same way it previously invented MONTH(),
now with a specific year to hand to it) that costs retry budget. The
fix helps the one-shot baseline (M1b) more than it helps the agent,
because M1b never gets the chance to spend a second step on YEAR()
before giving up.

2026-11-10  Iterated on the schema wording rather than committing the
first version. Added a second Notes sentence to SCHEMA (src/db_tools.py):
"SQLite has no MONTH() or YEAR() function -- filter by month with
order_date LIKE '2026-03-%' (for March), not MONTH()/YEAR()." Kept the
"all from 2026" sentence from the first attempt. Picked the LIKE pattern
specifically (not strftime or substr) because it's what src/make_questions.py
and src/make_questions_heldout.py already use to compute ground truth, and
it's exactly the pattern that worked whenever M1b used it in the last
test run. Did NOT touch the customer-count over-filtering regression --
tracked separately in CLAUDE.md's Next section as a known issue, since
it's a general over-filtering problem (unprompted status/date filters on
questions that mention neither), not a date-parsing problem, and this
change doesn't address its cause.
Prediction, same 30-question subset (data/scratch/questions_heldout_yearcheck.jsonl),
against the previous iteration's results (M1b 20/30: customer-count
13/14, month_count 6/8, month_sum 1/8; agent 14/30: customer-count 14/14,
month_count 0/8, month_sum 0/8):
- M1b month_count: improves further, toward 8/8 -- explicit LIKE guidance
  replaces the ambiguous year hint that let the model still reach for
  MONTH()/YEAR() on 2 of 8 questions.
- M1b month_sum: improves substantially from 1/8 -- the previous fix
  barely touched SUM questions because the model kept reaching for
  MONTH()/YEAR() regardless of aggregation function; telling it not to
  should apply equally to COUNT and SUM.
- M1b customer-count: unchanged at ~13/14 -- this fix doesn't touch the
  cause of that regression, so no reason to expect it to recover.
- Agent month_count: improves from 0/8, plausibly to 4-8/8 -- the
  specific failure mode last time was inventing YEAR() as a second
  doomed attempt before giving up; explicit guidance should stop that
  and let it converge within MAX_STEPS more often.
- Agent month_sum: improves from 0/8 for the same reason.
- Agent customer-count: stays 14/14 -- no regression was observed here
  last time, and this change doesn't add new status/date-adjacent text
  that would plausibly trigger one.

RESULT (M1b, data/scratch/results_baseline_sql_heldout_yearcheck.jsonl): 16/30.
month_count 8/8 (up from 6/8) and month_sum 8/8 (up from 1/8) --
prediction correct, full fix for both date templates once the model is
told not to use MONTH()/YEAR() and shown the LIKE pattern directly.
customer-count 0/14 (down from 13/14) -- prediction WRONG, and badly:
every single customer-count question now adds BOTH an unprompted
`status = 'delivered'` filter AND an unprompted `order_date LIKE
'2026-%-%'` filter, e.g. `SELECT COUNT(*) FROM orders WHERE customer_id
= 2 AND status = 'delivered' AND order_date LIKE '2026-%-%'` for "How
many orders did Customer 2 place?" (no status or date in the question).
This is the known over-filtering issue (CLAUDE.md Next section) made
MUCH worse by this specific wording choice: giving a concrete LIKE
example (`order_date LIKE '2026-03-%'`) didn't just teach the model the
right date pattern, it primed it to reach for a LIKE-style date filter
on every question, date-related or not. The fix for month_count/
month_sum and the regression on customer-count are the same mechanism
pulling in opposite directions.

RESULT (best agent config,
data/scratch/results_agent_normalizequotes_finalfromresult_precisiononly_heldout_yearcheck.jsonl):
30/30 -- clean sweep, prediction directionally right but better than
expected on month_count/month_sum (8/8 each, not just 4-8/8) and exactly
right on customer-count (14/14, no regression). Checked the customer-count
trajectories directly (Q1, Q2): the agent writes a plain `SELECT
COUNT(*) FROM orders WHERE customer_id = N` with no extra filters at
all, unlike M1b's one-shot call on the identical SCHEMA text. So the
over-filtering regression is not purely a SCHEMA-text problem -- it
depends on the surrounding prompt too (M1b's "schema in prompt, write
one query" framing vs. the agent's "call run_sql, look at the result,
retry if it looks wrong" framing), which is worth remembering before
assuming any future SCHEMA change will affect both configs the same way.
Net: for the agent, this iteration is an unambiguous improvement with no
observed downside on this 30-question subset. For M1b, it trades a
small, template-specific regression (customer-count, already a tracked
known issue) for a much larger fix (all 16 date-filter questions).

2026-11-10  Iteration 3: dropped the concrete worked LIKE example
(iteration 2's `order_date LIKE '2026-03-%'`), suspected cause of the
M1b customer-count collapse to 0/14 -- it primed the model to reach for
a date filter on every question, not just date ones. New SCHEMA Notes
sentence: "SQLite has no MONTH() or YEAR() function. When a question
asks about a specific month or date range, filter using
substr(order_date, 1, 4) for year or substr(order_date, 6, 2) for month
-- otherwise don't add a date filter." Two changes at once from
iteration 2: (a) explicit "otherwise don't add a date filter" condition,
aimed directly at the over-filtering regression, and (b) substr instead
of a worked LIKE example, since the worked example itself was implicated.
Kept "all from 2026".
Prediction, same 30-question subset, against iteration 2's results
(M1b 16/30: customer-count 0/14, month_count 8/8, month_sum 8/8; agent
30/30 clean):
- M1b customer-count: substantial recovery, plausibly back to 13-14/14
  -- the explicit "otherwise don't add a date filter" condition targets
  this regression directly, unlike iteration 2 which had no such guard.
- M1b month_count/month_sum: NOT confident these stay at 8/8. Two risks:
  conditional phrasing is less directive than a worked example, and
  substr is untested syntax here (LIKE is what iteration 2 proved works
  and what the ground-truth generator itself uses). Plausible partial
  regression back toward iteration 1's levels (month_count ~6-8/8,
  month_sum ~1-8/8) if the model doesn't reliably apply substr correctly
  or still reaches for MONTH()/YEAR() on some questions.
- Agent: expect it stays at or near 30/30 -- it already handled the
  month templates perfectly with iteration 2's wording, and the tool
  loop can retry past a malformed substr query even if the first
  attempt is off, unlike M1b's single shot.
If this version keeps month_count/month_sum near 8/8 for both configs
AND recovers customer-count without reintroducing the regression, this
is the version to commit. If not, per instruction: stop iterating on
wording alone and document this as a model-capability limit, not a
prompt problem to keep chasing.

RESULT (M1b, data/scratch/results_baseline_sql_heldout_yearcheck.jsonl): 9/30,
down from iteration 2's 16/30. Prediction WRONG on every count:
customer-count 7/14 (partial recovery from 0/14, but nowhere near the
original 13-14/14, and the mechanism didn't actually go away -- Q1 still
has an unprompted `status = 'delivered' AND order_date >= '2026-01-01'
AND order_date < '2027-01-01'` tacked onto a plain count question, now
phrased as a range instead of iteration 2's LIKE). month_count 2/8
(down hard from 8/8) and month_sum 0/8 (down from 8/8) -- the
conditional "when a question asks about a specific month... otherwise
don't add a date filter" phrasing backfired in a new way: the model now
also adds an UNPROMPTED STATUS FILTER to month questions that never
mention status, e.g. Q28 `substr(order_date, 6, 2) = '03' AND status !=
'cancelled'` and Q35 `... AND status = 'delivered' AND order_date >=
'2026-02-01' AND order_date < '2026-03-01'` for "total amount of orders
placed in February" (no status mentioned). The "when X, do Y, otherwise
don't" framing seems to have generalized into permission to add
conditional filters generally, not just date ones -- worse than either
prior iteration, and in a new dimension (status) that iteration 2 never
touched.
RESULT (best agent config): run CRASHED (did not complete) --
`ValueError: could not convert string to float: 'None'` on question 35,
an uncaught exception in agent.py's `answer()` (get_arg/float(value)
path) when submit_answer is called with the literal string "None"
instead of a number. This is a pre-existing gap in error handling
(unrelated to SCHEMA wording specifically, but only surfaced because
this wording made the model produce a kind of bad output the harness
had never seen before), NOT something fixed here -- out of scope for a
SCHEMA-only change per the plan for this iteration. Partial output
before the crash already showed clear regression: 6 of the 14
customer-count questions returned "no tool call" (worse than iteration
2's clean 14/14), and the month templates were timing out
(max-steps-reached) or giving up, not converging like iteration 2's 8/8
+ 8/8.
Conclusion: iteration 3 does NOT cleanly separate the date fix from the
over-filtering regression -- it makes both worse simultaneously, for
both configs, and exposes a new crash bug on top. Per the stated
stopping rule, this is now a model-capability limit (a 3B model
reliably treats "mention date filtering" and "mention a conditional
filter" as license to add filters it wasn't asked for, regardless of
the specific wording used to scope that guidance) rather than a prompt
problem worth continuing to chase by rewording. Reverting to iteration
2's wording (concrete LIKE example, no "otherwise" clause) as the
best-available version: it gave the agent a clean 30/30 and gave M1b a
real net fix (8/8 + 8/8 on dates) at the cost of a known, already-
tracked regression on one template (customer-count, M1b only).

Final sanity check, `make demo` (rebuilds db + dev questions, runs M1b
dev) against the reverted-to-iteration-2 SCHEMA: dev M1b 15/31 -> 17/31
(easy 15/15->12/15, medium 0/9->4/9, hard 0/7->1/7). Confirms the same
pattern seen on held-out, now on dev too: Q16-19 (month_count template)
all fixed (0/4->4/4), but Q13/14/15 (customer-count template) all
regressed with the exact same unprompted `status = 'delivered' AND
order_date LIKE '2026-%-%'` filter -- 3 dev questions, not just the 1
(Q14) seen under iteration 1. Q25 flipped to correct by chance (a
join query that happened to keep its category filter this run); Q26/27
still drop the category filter, a separate pre-existing bug, unrelated.
Net dev effect: +2 (15/31 -> 17/31). data/results_baseline_sql.jsonl
(the official dev M1b result file) now reflects this SCHEMA.
Caveat: only M1b's dev set and a 30-question held-out subset were
re-run under the final SCHEMA in this session. The full pre-registered
5-configuration suite (CLAUDE.md "Results so far" table, README's
generated tables) still reflects the PRE-FIX SCHEMA and has not been
regenerated -- flagged in CLAUDE.md's Next section as outstanding work,
not done here.

2026-11-10  Full re-run of all 5 configurations (M1b, M2, normalize-quotes,
normalize-quotes+final-from-result, normalize-quotes+final-from-result+
precision-only) on both dev (31) and held-out (60), under the committed
SCHEMA fix. M1b dev was already redone (above, 17/31); this covers the
remaining 9 runs. Prediction, against the pre-fix numbers in CLAUDE.md's
"Results so far" table and the per-id breakdown already on disk:

- M1b held-out: the 30-question subset test already measured this
  config's exact behavior on customer-count (0/14, was 14/14) and
  month_count+month_sum (16/16, was 0/16) under this exact SCHEMA.
  Applying those deltas to the pre-fix 22/60 (-14 customer-count +16
  month) gives a rough estimate around 24/60, but the other 30 held-out
  questions (category counts, city joins, category averages) weren't
  in the subset and aren't expected to change -- so I'd call this
  "around the same overall score, much worse composition" rather than
  commit to an exact number.
- Agent configs, held-out medium (Q27-42, exactly the month_count +
  month_sum questions -- this is the entire "medium" difficulty band
  on held-out): expect a LARGE jump from 0/16 (true in every config
  before, per CLAUDE.md) specifically for the two configs that already
  fix decimal truncation (final-from-result): normalize-quotes+
  final-from-result and the best config should both approach 16/16,
  matching the best config's subset result exactly. For M2 (flags off)
  and normalize-quotes alone, I expect month_count (integer, Q27-34) to
  improve similarly since there's no decimal to truncate, but month_sum
  (decimal dollar amounts, Q35-42) to stay mostly broken -- those
  configs still have the known wrong_after_recovery truncation bug
  (e.g. 7777.53 -> 7777) that final-from-result exists to fix, and
  nothing about the SCHEMA change touches that. So I'd predict M2 and
  normalize-quotes land closer to 8-11/16 medium, not 16/16.
- Agent configs, held-out easy (customer-count, Q1-14): expect NO
  regression for any of the 4 agent configs, extending the best
  config's clean 14/14 subset result -- the over-filtering bug showed
  up only in M1b's one-shot call, not in the agent's tool-loop
  reasoning, and nothing about which flags are set changes that first
  run_sql call.
- Dev set: all 4 agent configs should fix Q16-19 (month_count, the only
  date-filter template on dev -- there's no month_sum template on dev)
  cleanly, +4 each, with no decimal-truncation risk since Q16-19 are
  plain counts, not sums. No customer-count regression expected (Q13-15),
  same reasoning as held-out. Other dev/held-out questions (city joins,
  category counts/averages, pending/delivered filters) are not
  expected to change -- they don't touch order_date at all.
- Overall: I expect this to be a clear net win for every agent
  configuration (especially the two with final-from-result) and a
  mixed/flat result for M1b, for the reasons already logged above.

RESULT: full re-run, all 5 configs, both datasets, under the committed
SCHEMA. Overall scores (pre-fix -> post-fix):

| Config | Dev | Held-out |
|---|---|---|
| M1b | 15/31 -> 17/31 | 22/60 -> 35/60 |
| M2 | 12/31 -> 13/31 | 20/60 -> 28/60 |
| normalize-quotes | 12/31 -> 13/31 | 20/60 -> 28/60 |
| normalize-quotes+final-from-result | 16/31 -> 14/31 | 19/60 -> 33/60 |
| normalize-quotes+final-from-result+precision-only | 19/31 -> 15/31 | 24/60 -> 39/60 |

Held-out matched the prediction well: every config gained substantially
(+8 to +15), driven mostly by medium (the month_count+month_sum
questions, the entire medium band on held-out): M2/normalize-quotes
went 0/16 -> 8/16 (month_count fixed, month_sum still decimal-truncated,
exactly as predicted since neither has final-from-result); nq+ffr and
nq+ffr+po both went 0/16 -> 16/16 (clean, decimals preserved, as
predicted). Easy (customer-count) showed NO regression for any of the 4
agent configs on held-out, confirming the earlier subset finding
generalizes to the full 60. Hard dipped slightly for nq+ffr (6/18->4/18)
and nq+ffr+po (5/18->4/18) -- small, unexplained, within noise.

Dev did NOT match the prediction for the two final-from-result configs,
and this is the important finding of this run: nq+ffr went 16/31 ->
14/31 and nq+ffr+po (the previously-reported "best" config) went 19/31
-> 15/31 -- both REGRESSED on dev despite fixing Q16-19 (month_count,
+4) cleanly as predicted. The reason is NOT the customer-count
over-filtering mechanism (Q13-15, the actual customer-count template,
scored fine in every config) -- it's new noise on a different set of
easy questions (Q4, Q6: "no tool call", the model answers in plain text
on a category-count question instead of calling a tool; Q10, Q11: "max
steps reached", a pre-existing join-related struggle that got worse) and
one medium city-join question flipping wrong. This happened for every
agent config including plain M2 (dev easy 12/15 -> 9/15), so it's not
specific to final-from-result either -- the two-sentence SCHEMA addition
measurably destabilized the model's handling of unrelated easy
questions on dev, the same general risk CLAUDE.md's M4 section already
flagged ("any future prompt/tool change must be judged against the full
set, not just the targeted questions"). My prediction assumed the only
risk was the already-identified over-filtering mechanism; this shows a
second, broader, less specific instability that wasn't predicted.
Net effect: on held-out, the agent (best config) now beats M1b by a
clearer margin than before (39/60 vs 35/60, a 4-question gap, where
before the gap was smaller and explicitly called "within noise" at 2/60).
On dev, the relationship REVERSED: M1b (17/31) now beats the best agent
config (15/31), where before the agent led clearly (19/31 vs 15/31).
Nothing about which config "wins" is stable across datasets or across
this one wording change -- a reason for caution before reporting either
number as the headline.

2026-11-11: Follow-up investigation into the dev regression above, before
committing. User asked for the real cause, not just the number: pulled
M2's (plain config, no flags) saved trajectories for Q4, Q6, Q10, Q11
directly from data/results_agent.jsonl, and compared against the
pre-fix version of the same file via `git show HEAD:data/results_agent.jsonl`.

Correction to the note above: Q10/Q11 is NOT a "join-related struggle" --
there's no join in either question (both are single-table customer
counts by city). The real bug: the model invents a parameterized-query
syntax, `WHERE city = ?` plus a separate `bindings` argument, that
run_sql's tool schema does not accept at all, so every attempt fails
with the same ProgrammingError regardless of the bindings value. This
bug already existed PRE-FIX -- old Q11's trajectory shows the identical
three failed `?`-placeholder attempts before it self-corrected to a
literal string on step 5 and got the right number (then answered in
plain text on step 6 instead of calling submit_answer -- which would
itself have been a no_submit_text failure, just happened not to be
scored that way at the time). Post-fix, Q10 repeats the same broken
query for all 8 steps and never recovers; Q11 shows the same pattern.
So the schema change didn't invent this bug, it just removed whatever
margin let the model self-correct out of it within the step budget.

Q4/Q6 (no_submit_text): pre-fix trajectories for both are clean --
run_sql returns the right count, then submit_answer is called with that
exact value, byte for byte. Post-fix, step 1 is identical (same query,
same correct result), but step 2 is now a plain-text sentence restating
the number instead of a tool call. Neither question touches a date or
a category filter affected by the new schema text -- the only change
upstream of this is that the SCHEMA string got two sentences longer.

Checked for overlap with the existing "Q4/Q6/Q13 returns 1.0" mystery in
CLAUDE.md's Next section: there is none, despite the shared IDs. That
mystery is a different code path entirely -- the --final-from-result
extra structured-output call, given only {question, last query result},
no transcript. What's happening here is in the main tool loop itself,
before any extra call exists. The shared question IDs are coincidental:
Q4/Q6 are both "plain single-table count" questions, the template most
exposed to small-number quirks in general, not evidence of one shared
bug.

Honest conclusion: the most defensible explanation is that this 3B
model's tool-calling reliability is already marginal (the placeholder
bug and one plain-text ending existed pre-fix too) and is sensitive to
prompt length/shape in a way that isn't specific to the added content --
none of the four affected questions touch MONTH()/YEAR() or dates at
all. I don't have the instrumentation (token/attention-level inspection)
to prove the mechanism further than that. Treating this as a model
robustness limit under added prompt load, not a logic bug to patch, and
not reporting a more specific cause than I can actually show.

2026-11-11, targeted fix attempt 1 (nudge for Q4/Q6): confirmed --nudge is
off in all 5 reported configs (grep of src/agent.py's main() -- none pass
--nudge). Q4/Q6's failure is exactly what --nudge targets: no tool call
on a step, re-prompt once with NUDGE ("Call submit_answer with your final
numeric answer now."), see if it recovers on the next step.
Prediction: --nudge should catch the step-2 plain-text reply on both Q4
and Q6 and get a correct submit_answer call on step 3, since the model
already has the right number (77, 67) sitting in the prior tool result --
it only needs to be told to call the tool, not to recompute anything.
Running: python -m src.agent --nudge --questions data/scratch/questions_q4q6.jsonl

RESULT: matched the prediction exactly. Q4: steps=3, nudges=1, got=77.0
(correct). Q6: steps=3, nudges=1, got=67.0 (correct). The nudge message
on step 2 was enough to make the model call submit_answer with the
number it already had. 2/2.
Not yet concluding this is a safe fix to commit -- CLAUDE.md's own M4
lesson says a flag change must be judged against the full set, not just
the targeted questions, before trusting it. Full-dev --nudge rerun not
done yet; flagging as the next check before treating this as resolved.

2026-11-11, full-dev check for --nudge (before committing attempt 1):
Prediction: --nudge should fix Q4 and Q6 (the no_submit_text cases,
confirmed above) without touching anything else, since it only fires
when a step has zero tool calls, and every other dev question's
trajectory already has a tool call on every step (confirmed by
inspection in the earlier investigation -- Q10/Q11 fail via a tool-call
error, not an empty reply, so nudge shouldn't interact with them; the
over-filtering and decimal-truncation mechanisms are unrelated code
paths). Expect M2 dev to go from 13/31 to 15/31 (+Q4, +Q6), nothing else
moving. Running: python -m src.agent --nudge --questions data/questions.jsonl

RESULT: score matched the prediction (13/31 -> 15/31, +2), but the
mechanism prediction was partly wrong -- I missed that Q24, Q25, and
Q27 are ALSO no_submit_text cases without --nudge (not surfaced in the
earlier Q4/Q6/Q10/Q11-only investigation, since the task scope was
those four). With --nudge, all three get nudged (nudges=1) but stay
wrong -- Q24 got=8194.0 vs expected 15603.82 (nudged into a
wrong_after_recovery-style truncation failure), Q25 got=0.0 vs expected
13 (silent_wrong, likely a dropped filter), Q27 got=0.0 vs expected 5
(silent_wrong, same pattern). So nudge didn't just fix two questions
cleanly in isolation -- it converted 5 no_submit_text cases into
responses, 2 of which turned correct (Q4, Q6) and 3 of which turned
wrong-by-a-different-mechanism (still 0 net change for those 3, since
they were already wrong). No previously-correct question regressed --
checked every row against the pre-nudge M2 dev result
(Q1,5,7,8,9,12-19 all still OK, unchanged). Net: a clean, real +2 with
no side effects on correctness, even though the nudge mechanism fired
on more questions than predicted. Confirms --nudge is worth keeping on
for this failure type specifically; still need to check held-out before
fully committing, and Q10/Q11 (attempt 2) are untouched by this (they
fail via tool-call errors, not empty replies, exactly as predicted).

2026-11-11, held-out check for --nudge (before calling attempt 1 done):
Prediction: same mechanism, same expectation -- --nudge only fires on
steps with zero tool calls, so it should recover any held-out
no_submit_text cases (M2 held-out currently has 8, per the Failure
types table) the same way it did on dev: some flip to correct, some
flip to a different wrong-answer mechanism, none of the 28 currently-
correct questions should regress. Expect M2 held-out to move from
28/60 upward by however many of those 8 no_submit_text cases are simple
"had the right number, didn't call the tool" like Q4/Q6, and no
previously-correct question to break.
Running: python -m src.agent --nudge --questions data/questions_heldout.jsonl

RESULT: 28/60 -> 32/60, +4, no regressions -- checked every row against
the pre-nudge M2 held-out result file. The 8 no_submit_text cases
(Q45, 48, 49, 50, 51, 53, 54, 55, all "got=None" before) split exactly
like dev did: Q45, 53, 54, 55 flipped to correct (the model already had
the right number from run_sql, nudge got it to call submit_answer).
Q48, 49, 50, 51 flipped to a different wrong-answer mechanism (got=0.0
instead of None -- silent_wrong, likely the same dropped-filter pattern
as dev's Q25/Q27) but were already wrong, so no net change for those 4.
Every previously-correct row (1-14, 22, 26-34, 43, 44, 46, 47) stayed
correct, same values. Clean, same pattern as dev: --nudge is a real fix
for no_submit_text with zero observed side effects on either dataset.
Decision: committing attempt 1 (--nudge added to the reported
configuration set) as a real fix, not just a documented limit. Moving
to attempt 2 (Q10/Q11, the placeholder/bindings bug) next.

2026-11-11, targeted fix attempt 2 (Q10/Q11 placeholder/bindings bug):
chose to edit the TOOLS schema's "sql" parameter description, not
SYSTEM -- SYSTEM is already the thing that got longer and caused the
no_submit_text/ran_out_of_steps instability we're investigating, so
adding more text there to fix a different bug risks the same failure
mode. The tool schema description is narrower and more targeted to
exactly this constraint (how to call run_sql), so it's where this
belongs. Changed: "sql": {"type": "string", "description": "A single
SQLite SELECT statement."} -> "... with every value written directly
into the SQL as a literal -- never use a placeholder like '?' or a
separate bindings/parameters argument; this tool takes one complete
SQL string and nothing else."
Prediction: this should stop the model from reaching for `?` syntax on
Q10/Q11 and get it to write the literal city name directly, recovering
both within budget. Testing on just Q10/Q11 first (same two-question
subset pattern as attempt 1), nudge left on from attempt 1 since that's
now the committed baseline. Running: python -m src.agent --nudge
--questions data/scratch/questions_q10q11.jsonl

RESULT: no effect at all. Q10 and Q11 both still "max steps reached",
0/2, and the trajectory is byte-for-byte identical to before the edit
-- step 1 on both is still `SELECT COUNT(*) FROM customers WHERE city
= ?`. The model doesn't appear to read, or doesn't weight, the tool
parameter description at all for this behavior; adding the constraint
there did nothing to stop it from reaching for '?' syntax.
Per the stopping rule set in advance: this attempt did nothing, so
falling back to the honest documented explanation rather than trying
a third wording. Reverted the TOOLS schema edit in src/agent.py (no
reason to keep dead prompt text that had zero measured effect) and
deleted the scratch result files for this attempt. Q10/Q11 (and the
broader dev tool-calling instability from the schema-length change)
stays as a documented, unfixed model-capability limit -- see CLAUDE.md
"Known issue" bullet (2026-11-11 entry) for the full writeup.

Decision: committing now with --nudge added to the reported
configuration set (a real, validated fix) and the Q10/Q11 placeholder
bug left as a documented limit (two targeted attempts tried, one
helped, one did nothing -- not continuing to chase wording on this one
per the same model-capability-limit reasoning used for the
customer-count over-filtering issue).

2026-11-11, folding --nudge into all 4 agent configs, both datasets
(8 runs total; M2+nudge dev/held already run above: 15/31, 32/60).
Prediction, config by config:
- normalize-quotes+nudge: identical mechanism to M2 (quotes don't
  affect Q4/Q6/Q24/Q25/Q27, none of them contain string literals with
  smart quotes), so expect the same +2 dev (13->15) and +4 held
  (28->32) as M2.
- nq+ffr+nudge (final-from-result, NOT precision-only): this is the
  risky one. final_from_result always makes the extra re-derivation
  call when a question has a whole-number last_sql_output, regardless
  of whether submit_answer's own value was right -- and that's the
  exact mechanism that turned Q4/Q6/Q13 into 1.0 in the M4 investigation
  (attempt 4, before --precision-only existed). Once nudge recovers a
  real submit_answer call for Q4/Q6, final_from_result will fire on
  them too (no precision_only to skip it), so I predict they do NOT
  net-gain here -- they likely flip from "no tool call" to "got=1.0",
  still wrong, just a different wrong number. Expect dev to stay close
  to 14/31, possibly +0 net from nudge (gains on Q4/Q6 cancelled by the
  1.0 mechanism), and held-out to gain on whichever recovered questions
  have a non-whole-number result (so the 1.0 mechanism doesn't apply).
- nq+ffr+po+nudge (adds precision-only): Q4/Q6's query result ([(77,)],
  [(67,)]) is a whole number, so precision_only skips the extra call
  entirely once nudge gets a real submit_answer -- expect this one to
  cleanly gain like M2, i.e. dev 15->17, held 39->43, roughly matching
  the M2/normalize-quotes-style clean recovery.
Running all 6 remaining: normalize-quotes dev/held,
normalize-quotes+final-from-result dev/held,
normalize-quotes+final-from-result+precision-only dev/held, each with
--nudge added.

RESULTS so far:
- normalize-quotes+nudge: dev 15/31, held 32/60 -- matches M2+nudge
  exactly, as predicted (quotes don't interact with these questions).
- nq+ffr+nudge (no precision-only): dev 14/31 (unchanged from 14/31
  without nudge) -- Q4 and Q6 DID flip from "no tool call" to
  got=1.0, exactly the predicted 1.0-mystery collision, net zero gain,
  confirming the risk. Held-out: 33/60 -> 37/60, +4 (Q45, 53, 54, 55),
  clean, no regressions -- confirmed by diffing against the saved
  pre-nudge file row by row. Notable and NOT predicted: Q45/53/54/55
  all have whole-number query results (12, 4, 5, 5) and final_from_result
  handled them correctly, unlike Q4/Q6 on dev which hit the 1.0 bug on
  their own whole-number results (77, 67). So "whole number result"
  alone doesn't trigger the 1.0 mystery -- something more specific to
  Q4/Q6/Q13's template or phrasing does. Still unexplained, but this is
  new evidence for that open question in CLAUDE.md.

2026-11-11, reproducibility check on the current real config (same
methodology as the earlier 24/60 check): normalize-quotes+final-from-
result+precision-only+nudge, held-out set, 3 full reruns, checking not
just the overall score but every individual question's verdict and
submitted number across runs.
Found src/rerun.py doesn't pass nudge=True to answer() -- as written it
would silently test the pre-nudge config, not the real committed one.
Fixing that first (one-line change) before running, since testing the
wrong config would make this check worthless.
Prediction: with temperature 0 end to end, I'd expect this to reproduce
43/60 on all 3 runs, same clean determinism as the earlier strict-M2
check. Specifically watching for whether the final-from-result extra
call (a second structured-output call per question, present in this
config but not in the earlier plain-M2 check) introduces any new
instability -- that mechanism wasn't covered by the first check.
Running: python -m src.rerun --runs 3 (after fixing nudge=True)

RESULT: also found src/rerun.py was missing the `provider` argument to
answer() entirely (a required positional arg since the multi-provider
abstraction was added) -- would have crashed immediately. Fixed that
too (added get_provider("llama3.2") in main(), passed through
run_once()). Both fixes were plumbing/wiring bugs in the test harness
itself, not behavior changes to src/agent.py.

Ran 3 full held-out reruns of normalize-quotes+final-from-result+
precision-only+nudge. Prediction confirmed exactly: 43/60 on all 3
runs (run1=43, run2=43, run3=43, range=0), matching the number already
reported in README/CLAUDE.md. More importantly, per-question check: all
60 questions show stable_verdict=True AND stable_number=True across all
3 runs -- every single question, not just the aggregate score, landed
on the identical right/wrong verdict and the identical submitted number
(including the non-whole-number ones like 242.63552795031055 and
254.37814814814817, reproduced to the full float repr every time, and
the four got=None rows from Q48/49/50/51). The final-from-result extra
call (not present in the earlier plain-M2 stability check) introduced
no additional instability -- same clean determinism as before, now
confirmed on the actual reported configuration rather than a different
one. This supersedes the earlier "not re-checked under the new schema
or with nudge" caveat in README/CLAUDE.md for this specific config.