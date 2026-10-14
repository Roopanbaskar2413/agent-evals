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
- Set no paid API without telling me first; hard spending limits must be set before any paid key is used.

## Task and ground truth
- data/shop.db is built by src/make_db.py: 40 customers, 300 orders, random.seed(42) so it is identical every run.
  - customers(id, name, city). Names look like "Customer 12".
  - orders(id, customer_id, category, amount, status, order_date). customer_id joins to customers.id. Dates are TEXT like 2026-03-14. SQLite has no MONTH() function.
  - Statuses: delivered (about 60%), cancelled, pending. Categories: books, toys, gadgets, clothing. Cities: Chennai, Mumbai, Delhi, Pune, Kochi.
- src/make_questions.py writes data/questions.jsonl: 31 questions (15 easy, 9 medium, 7 hard). Each has id, question, expected, difficulty. Expected answers are computed by running real SQL, never written by hand or by a model.
  - easy: single-table counts and sums. medium: month filters and joins by city. hard: joins with two filters, and averages by category.
- Changing the seed changes the data and invalidates every expected answer. Keep seed 42.

## Files so far
- src/make_db.py: builds the database.
- src/make_questions.py: builds the question set with SQL-computed answers.
- src/grading.py: load_questions, is_correct (math.isclose, abs_tol=0.01), summarize (overall and per difficulty). Every runner must use this same grader.
- src/db_tools.py: SCHEMA (table layout as text) and run_query (read-only connection via file:data/shop.db?mode=ro, SELECT only, returns up to 20 rows).
- src/baseline.py: M1, model answers with no tools and no database. Output {"number": float} via structured output.
- src/baseline_sql.py: M1b, schema in the prompt, model writes one SQL query, no loop, no retry.
- src/agent.py: M2, tool loop with run_sql and submit_answer, MAX_STEPS 8, records full trajectory. Written but NOT yet run or verified.
- tests/notes.md: run log.
- Result files: data/results_baseline.jsonl, data/results_baseline_sql.jsonl, data/results_agent.jsonl (each row = question fields + got + correct + tokens).

## Results so far
| Run | Setup | Score |
|---|---|---|
| M1 baseline | llama3.2, no tools, no database | 0/31 (0%) |
| M1b baseline | schema in prompt, one SQL query, no loop | 15/31 (48%): easy 15/15, medium 0/9, hard 0/7 |

M1 failure mode: confident guessed numbers (for example 850000 for an answer of 7), many 0.0.

M1b failures, 16 total:
- 8 x `no such column: city` (rows 20 to 27): city is on customers, the model never joined. Visible error.
- 2 x `no such function: MONTH` (rows 16, 18). Visible error.
- 2 x returned 0.0 (rows 17, 19): likely a wrong date filter. Silent wrong answer. Cause inferred, not yet confirmed.
- 4 x identical answer 242.6355 for four different categories (rows 28 to 31): category filter dropped. Silent wrong answer. Cause inferred, not yet confirmed.

Key insight: visible errors can be fixed by an agent that reads the error and retries; silent wrong answers give it nothing to react to. Prediction for M2: it fixes some of the 10 visible failures and few of the 6 silent ones. If it does better than that, find out why.

Answer key validity check: 15 easy questions matched the model's own SQL, so the questions, database and grader agree.

## Milestones
- M0 done: database and 31 ground-truth questions.
- M1 done: no-tools baseline, 0/31.
- M1b done: schema-aware one-shot SQL baseline, 15/31.
- M2 next: run the tool-using agent; compare with M1 and M1b question by question; report avg steps, tokens, SQL error count.
- M3: trajectory recording is built into agent.py; add a script to inspect trajectories.
- M4: read failures, sort into types, fix the biggest type, re-run, show before/after. Run each question 3 times to measure variance.
- M5: README with results table, a "what broke" section, and one-command run (make demo or a shell script).
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