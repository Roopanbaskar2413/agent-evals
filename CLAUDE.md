# agent-evals

A learning and portfolio project: build an agent that answers questions about a SQLite shop database, and build the test system that measures how well it does. The measuring is the point; the agent is the thing being measured.

Inspired by the three briefs in github.com/rasswanth-lyzr/ship-ai-projects (CC BY 4.0): Agent Evals, LLM Ops, Auto Routing. The BRIEF.md files could not be read, so milestones below are our own. The code and analysis must be ours.

## Who I am and how to work with me
- I am Roopan, a backend engineer (Python, FastAPI, AWS serverless, Elasticsearch) moving into AI engineering. I am learning from this project, so I must be able to explain every line in an interview.
- Plan first and wait for my OK before writing code. One small step at a time, then run it.
- Give complete code, never blanks to fill in. After each step, explain what each part does and why, in plain language.
- If something fails, show the error and your diagnosis before fixing.
- Do not add frameworks (LangChain, LangGraph, CrewAI) or new dependencies without asking.
- Make no claim without a number: every result needs a baseline, a sample size and how it was measured.
- Log every run in tests/notes.md: date, what changed, scores before and after.

## Environment
- Mac, Python 3.14 in .venv, VS Code. Run everything from the repo root with `python -m src.<module>`.
- Models run locally with Ollama (llama3.2, 3B). Installed packages: ollama, pydantic.
- Git identity is already set to my GitHub noreply email. Do not change git config.
- Before every commit run `git status`. Never commit .env, .venv, or anything under data/private/.
- Never add Co-Authored-By trailers or "Generated with Claude Code" lines to commits or PRs.
- Set no paid API without telling me first; hard spending limits must be set before any paid key is used.

## Task and ground truth
- data/shop.db is built by src/make_db.py: 40 customers, 300 orders, random.seed(42) so it is identical every run.
  - customers(id, name, city). Names look like "Customer 12".
  - orders(id, customer_id, category, amount, status, order_date). customer_id joins to customers.id. Dates are TEXT like 2026-03-14. SQLite has no MONTH() function.
  - Statuses: delivered (about 60%), cancelled, pending. Categories: books, toys, gadgets, clothing. Cities: Chennai, Mumbai, Delhi, Pune, Kochi.
- src/make_questions.py writes data/questions.jsonl: 31 dev questions (15 easy, 9 medium, 7 hard). Each has id, question, expected, difficulty. Expected answers are computed by running real SQL, never written by hand or by a model.
  - easy: single-table counts and sums. medium: month filters and joins by city. hard: joins with two filters, and averages by category.
- src/make_questions_heldout.py writes data/questions_heldout.jsonl: 60 held-out questions (26 easy, 16 medium, 18 hard), same templates, parameter values never used in the dev set. One dev template (customers-by-city) has no held-out variant (no second column on customers to vary) and is deliberately not replicated.
- Changing the seed changes the data and invalidates every expected answer. Keep seed 42.
- Confirmed cause of a held-out-only failure mode: SCHEMA (src/db_tools.py) never states what year the data is from. On the dev set this never mattered because the model always reached for `MONTH()` first, which errors visibly. On the held-out set, for several months the model instead guessed a `LIKE '2023-%'` or `LIKE '2022-%'` date filter -- syntactically valid, runs cleanly, returns 0 silently, because every real date is `2026-`. This is a schema-completeness gap, not a model reasoning failure: nothing in the prompt ever told it the year, so "guess a plausible recent year" is a reasonable move that happens to be wrong. Not fixed yet; see Next below.

## Files so far
- src/make_db.py: builds the database.
- src/make_questions.py: builds the 31 dev questions with SQL-computed answers.
- src/make_questions_heldout.py: builds the 60 held-out questions (same templates, unused parameter values).
- src/grading.py: load_questions, is_correct (math.isclose, abs_tol=0.01), summarize (overall and per difficulty). Every runner must use this same grader.
- src/db_tools.py: SCHEMA (table layout as text) and run_query (read-only connection via file:data/shop.db?mode=ro, SELECT only, returns up to 20 rows).
- src/baseline.py: M1, model answers with no tools and no database. Output {"number": float} via structured output. Takes --questions.
- src/baseline_sql.py: M1b, schema in the prompt, model writes one SQL query, no loop, no retry. Takes --questions.
- src/agent.py: M2, tool loop (run_sql, submit_answer), MAX_STEPS 8, records full trajectory. Flags, all off by default, flags-off always reproduces strict M2 exactly:
  - `--nudge`: one-time nudge to call submit_answer if a step has no tool call. Included in every reported agent configuration as of 2026-11-11 -- confirmed a real fix for no_submit_text (not just a targeted patch) by checking the full 31-question dev set and the full 60-question held-out set both separately before folding it into the other 3 configs: dev 13/31->15/31 (+2, zero regressions), held-out 28/60->32/60 (+4, zero regressions), every previously-correct row unchanged in both. One interaction worth knowing: for the final-from-result config without precision-only, recovering a no_submit_text case via nudge can expose it to the separate, still-unexplained "returns 1.0" bug (see M4 below) -- this cancelled the gain on Q4/Q6 for that one config on dev, though not on held-out's equivalent recovered questions.
  - `--normalize-quotes`: replaces typographic/smart quotes (U+2018/2019/201C/201D) with a plain ASCII quote before running SQL, since SQLite only recognizes the plain one.
  - `--structured-final`: after a real submit_answer call, makes one extra structured-output call with the full transcript asking for the number again. Abandoned -- see M4 below.
  - `--final-from-result`: after a real submit_answer call, makes one extra structured-output call with ONLY {question, last successful run_sql result} (no transcript) and uses that as the answer.
  - `--precision-only`: with --final-from-result, skips that extra call entirely when the last successful run_sql result is already a whole number (no decimals to lose) -- it never compares the extra call's value against the submitted one, because the call is simply not made in that case.
  - `--questions PATH`: which question file to run. Output filename is tagged from the questions file's name when it isn't the dev default (e.g. questions_heldout.jsonl -> _heldout appended to the results filename) so held-out runs never overwrite dev-set result files.
  - The plain-text-answer fallback (pulling a number out of a non-tool-call reply via regex) was removed entirely -- got only ever comes from a real submit_answer call (or the two extra-call flags above). This changed the "official" M2 dev score from 13/31 to 12/31 (see M4).
- src/inspect_trajectories.py: M3, classifies every incorrect row straight from its trajectory (not from the row's own error/got fields) into one of 5 failure types -- see Results below. CLI: no args for a summary table, --bad for one line per failure with its category, --id N for one question's full trajectory, --difficulty to filter.
- src/report.py: generates every markdown table in README.md directly from the saved result files -- no hand-copied numbers. Run via `make report`.
- Makefile: `make demo` rebuilds the db + dev questions and runs M1b, printing its summary. `make report` runs src/report.py.
- README.md: what-this-is / how-to-run / results (generated tables) / what-broke / limits-and-next-steps. Results tables are machine-generated; prose is hand-written.
- tests/notes.md: run log (date, what changed, prediction, result) -- the full history. CLAUDE.md states only the current, final understanding.
- Result files in data/: results_baseline.jsonl, results_baseline_sql.jsonl, results_agent.jsonl and its flag-suffixed variants (e.g. results_agent_normalizequotes_finalfromresult_precisiononly.jsonl), each with a matching _heldout.jsonl. Agent rows additionally carry steps_used, nudges, and trajectory (a list of {step, tool, input, output} covering every tool/extra-call the agent made).
- data/scratch/: intermediate/diagnostic files (variance checks, raw-model-output replays, the held-out analysis script), gitignored except for a handful of scripts force-added because they produced findings logged in tests/notes.md.

## Results so far (dev / held-out, both strict: got only from a real submit_answer or final-from-result call)
Current numbers, under the fixed SCHEMA (src/db_tools.py now states the year and that SQLite has no MONTH()/YEAR()) and with --nudge folded into every agent configuration:
| Configuration | Dev | Held-out |
|---|---|---|
| M1 (no tools) | 0/31 | not run |
| M1b (one-shot SQL) | 17/31 | 35/60 |
| M2 + nudge | 15/31 | 32/60 |
| normalize-quotes + nudge | 15/31 | 32/60 |
| normalize-quotes + final-from-result + nudge | 14/31 | 37/60 |
| normalize-quotes + final-from-result + precision-only + nudge | 17/31 | 43/60 |

(Earlier numbers, for reference: pre-schema-fix -- M1b 15/31 / 22/60; M2 12/31 / 20/60; normalize-quotes 12/31 / 20/60; +final-from-result 16/31 / 19/60; +precision-only 19/31 / 24/60. Post-schema-fix, pre-nudge -- M1b 17/31 / 35/60 (unchanged by nudge, no tool loop); M2 13/31 / 28/60; normalize-quotes 13/31 / 28/60; +final-from-result 14/31 / 33/60; +precision-only 15/31 / 39/60.)

M1 failure mode: confident guessed numbers (e.g. 850000 for an answer of 7), many 0.0.

With nudge folded in, the best agent configuration now ties M1b on dev (17/31 each) and leads it clearly on held-out (43/60 vs 35/60, an 8-question gap). I'd treat the held-out lead as real at this sample size; the dev tie is too close to call a winner either way. See README.md "What broke" for the full chain of fixes and tests/notes.md for every run's prediction and result.

Held-out findings (pre-registered: 5 configs, run once, no tuning afterward):
- The dev-set medium gain (0/9 -> 5/9 from final-from-result on) did not replicate: medium is 0/16 on held-out in every single configuration, including M1b.
- Exactly 5 templates score 0 across all 5 configurations on held-out: category_delivered_count, month_count, month_sum, city_category_delivered_join, city_category_pending_join. Two causes confirmed: the missing-year schema gap (above), and M1b/agent both still sometimes dropping the category filter (same question, same wrong number, e.g. 161.0 for all 4 category_delivered_count questions under M1b).
- Q20/Q21 in the held-out set ("pending toys/gadgets orders", template category_pending_count) are not part of that always-0 cluster: M1b answers both correctly. Only the best agent config (normalize-quotes+final-from-result+precision-only) gets them wrong, both as 81.0 -- the same dropped-category-filter bug as the category_delivered_count cluster, but on a template that otherwise works, so it's a per-configuration regression, not a shared failure.
- Re-running strict M2 on held-out is NOT fully deterministic: two questions (16, 18) flip which one gets a hallucinated value between runs, though neither ever grades correct either way. This is a held-out-only observation; the dev set showed 0/31 variance across 3 reruns of unchanged code.

Answer key validity check: 15 easy dev questions matched the model's own SQL, so the questions, database and grader agree.

## M4: chasing wrong_after_recovery (decimal truncation) -- eventually fixed
The model reliably gets the right number into a run_sql result, then loses precision retyping it into submit_answer's argument (e.g. 39064.32 -> 39064). Four attempts, in order:
- Attempt 1 (submit_last_result tool, reads the last query value directly): fixed Q3 but broke 2 unrelated easy questions (Q4, Q7). Net 12/31, reverted.
- Attempt 2 (shortened prompt on top of attempt 1): fixed different questions, broke 3 others (Q4, Q8, Q11). Net 11/31, reverted.
- Variance check after both: reran unchanged v1 agent.py 3x on the dev set, 13/31 every time, 0/31 unstable -- proved the regressions were real, deterministic consequences of the prompt/tool-list edits, not noise. Any future prompt/tool change must be judged against the full set, not just the targeted questions.
- Attempt 3 (--structured-final, re-ask with the full transcript): fixed 0/7 of the wrong_after_recovery questions -- the model just re-states its own already-truncated prior answer. An isolated test (question + query result only, no transcript) showed the model preserves decimals perfectly (7/7) when the prior truncated answer isn't in context.
- Attempt 4 (--final-from-result, re-ask with ONLY {question, query result}, no transcript): fixed 7/7, but broke 3 previously-correct easy integer questions (Q4, Q6, Q13 all returned 1.0 -- cause not understood).
- Fix (--precision-only): skip the extra call when the query result is already a whole number. Fixed all 3 regressions while keeping the 7/7 gain. Dev-set result: 19/31. This is the final, kept configuration.
- wrong_after_recovery count on held-out dropped from 5 (M2) to 1 (final config) -- the fix generalizes, though "why Q4/Q6/Q13 returned 1.0" is still unexplained.

## Milestones
- M0 done: database and 31 dev ground-truth questions.
- M1 done: no-tools baseline, 0/31.
- M1b done: schema-aware one-shot SQL baseline, 15/31.
- M2 done: tool-using agent, 12/31 (strict). Did not beat M1b on dev.
- M3 done: src/inspect_trajectories.py classifies failures from trajectories.
- M4 done: wrong_after_recovery fixed via normalize-quotes + final-from-result + precision-only (19/31 dev). See M4 section above.
- M5 done: held-out set (60 questions) built and pre-registered (5 configs, run once); src/report.py; Makefile (demo, report); README.md with generated tables and hand-written prose.
- Next: the full official re-run of all 5 configurations under the fixed SCHEMA plus --nudge is done (table above, README's generated tables regenerated via `make report`); results committed but not yet pushed as of 2026-11-11. Remaining: re-run the 3x stability check under the new schema and with nudge (it was only done pre-fix/pre-nudge); try a larger local model; understand the Q4/Q6/Q13 "1.0" failure (new evidence as of 2026-11-11: held-out's Q45/53/54/55 also have whole-number results and recovered correctly via final-from-result, so "whole number result" alone isn't the trigger -- something more specific to the Q4/Q6/Q13 template or phrasing is).
- Known issue (not yet fixed): under M1b only, the model adds unprompted `status = 'delivered' AND order_date LIKE '2026-%-%'` to plain customer-count questions that never mention status or date -- all 3 dev customer-count questions (Q13-15) and all 14 held-out customer-count questions (Q1-14) get this, after SCHEMA gained a concrete worked example (`order_date LIKE '2026-03-%'`) for the month-filter fix below. The best agent configuration does not show this regression on the same questions (clean, no extra filters). Tried two other SCHEMA wordings (a bare year note with no example; a conditional "only add a date filter when the question asks for one" note using substr instead of LIKE) -- both made this worse, not better, and the second one also made M1b add unprompted status filters to month questions too. Treating this as a model-capability limit rather than a wording problem worth continuing to chase; see tests/notes.md (2026-11-10 entries) for the full iteration history.
- Fixed (2026-11-11): the SCHEMA getting two sentences longer also destabilized the agent's tool-calling on dev questions that never touch dates at all, in two separate ways (tests/notes.md, 2026-11-11). Q4/Q6 (plain category counts): pre-fix, run_sql returns the right count and submit_answer is called with it cleanly; post-fix, the identical correct run_sql result was followed by a plain-text sentence restating the number instead of a tool call (no_submit_text). Turning on the existing `--nudge` flag (re-prompt once on an empty-tool-call step, was off in every reported config) fixed this cleanly -- confirmed on the full dev set (13/31->15/31, +2, zero regressions on previously-correct rows) and the full held-out set (28/60->32/60, +4, zero regressions) separately, before rolling it into all 4 agent configs. No overlap with the Q4/Q6/Q13 "1.0" mystery above despite the shared IDs -- that's a separate code path (the --final-from-result extra call), not the main tool loop; one config (+final-from-result, no +precision-only) does show the two interacting (nudge recovers Q4/Q6 into the tool loop, then the extra call turns them into 1.0), see the flags section above.
- Known issue (not yet fixed): Q10/Q11 (plain city counts, no join) show the second half of the same destabilization -- the model invents a parameterized-query syntax (`WHERE city = ?` plus a `bindings` argument run_sql's schema doesn't accept) that already existed pre-fix (old Q11 shows the same failed attempts), but pre-fix it self-corrected to a literal string within the step budget and post-fix it does not (Q10 repeats the broken query for all 8 steps, ran_out_of_steps). A targeted fix (telling the run_sql tool schema to always inline literal values, never use placeholders) had zero measurable effect -- the model's trajectory was byte-for-byte identical before and after the edit -- so it was reverted. Honest conclusion: this looks like a prompt-length/shape sensitivity in an already-marginal 3B model's tool-calling reliability, not a bug traceable to the SCHEMA content itself (neither question touches the new MONTH()/YEAR()/LIKE text) and not one a tool-schema wording fix resolves. Treating it as a model-capability limit, same reasoning as the customer-count over-filtering issue above, rather than continuing to chase wording; see tests/notes.md (2026-11-11 entries) for the trajectory comparison and the failed fix attempt.
- Stretch: LLM-judge only if needed, checked against 20 hand-graded answers; a second model for comparison.

## Rules for the eval itself
- Same questions, same grader, one change at a time. Never edit expected answers to make a score look better.
- Write a prediction in tests/notes.md before each run.
- Grade from structured output, not by parsing prose.
- Report failures by type, not just the score.

## Next projects (same repo, built in this order)
1. Agent Evals (this).
2. LLM Ops: wrap every model call in one client that logs tokens, latency and cost per prompt version to SQLite, adds caching, retries and a fallback model, with a small dashboard.
3. Auto Routing: send each question to the cheapest model that answers it correctly, using per-model eval results from project 1 as labels, and compare against always-small and always-large baselines.