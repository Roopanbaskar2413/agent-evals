# agent-evals

## What this is

An evaluation harness for a small agent that answers questions about a SQLite shop database (40 customers, 300 orders), using a local 3B model (llama3.2 through Ollama). The point is the measuring, not the agent. The correct answer to every question is computed by running SQL, so no model grades another model. All numbers below are generated from the saved result files by `make report`.

## How to run

Requires Python, `pip install ollama pydantic`, and Ollama running with `llama3.2` pulled.

- `make demo` rebuilds the database and the 31 dev questions and runs the one-shot baseline.
- `make report` regenerates the tables below from the saved results in `data/`.
- Agent configurations run with `python -m src.agent` plus flags (`--normalize-quotes`, `--final-from-result`, `--precision-only`, `--questions <file>`).

## Results

Two question sets. The 31 dev questions (15 easy, 9 medium, 7 hard) are the ones I looked at while building and fixing. The 60 held-out questions (26 easy, 16 medium, 18 hard) come from the same templates with different values. I ran them once, with the configurations and the rules written down in advance. They test robustness to new values, not new kinds of questions. "Tokens per correct" is total tokens spent divided by correct answers.

### Overall score

| Configuration | Dev overall | Held-out overall |
|---|---|---|
| M1b | 15/31 | 22/60 |
| M2 | 12/31 | 20/60 |
| normalize-quotes | 12/31 | 20/60 |
| normalize-quotes+final-from-result | 16/31 | 19/60 |
| normalize-quotes+final-from-result+precision-only | 19/31 | 24/60 |

### Score by difficulty

| Configuration | Difficulty | Dev | Held-out |
|---|---|---|---|
| M1b | easy | 15/15 | 21/26 |
| M1b | medium | 0/9 | 0/16 |
| M1b | hard | 0/7 | 1/18 |
| M2 | easy | 12/15 | 16/26 |
| M2 | medium | 0/9 | 0/16 |
| M2 | hard | 0/7 | 4/18 |
| normalize-quotes | easy | 12/15 | 16/26 |
| normalize-quotes | medium | 0/9 | 0/16 |
| normalize-quotes | hard | 0/7 | 4/18 |
| normalize-quotes+final-from-result | easy | 11/15 | 13/26 |
| normalize-quotes+final-from-result | medium | 5/9 | 0/16 |
| normalize-quotes+final-from-result | hard | 0/7 | 6/18 |
| normalize-quotes+final-from-result+precision-only | easy | 14/15 | 19/26 |
| normalize-quotes+final-from-result+precision-only | medium | 5/9 | 0/16 |
| normalize-quotes+final-from-result+precision-only | hard | 0/7 | 5/18 |

### Tokens

| Configuration | Dataset | Avg tokens_in | Avg tokens_out | Tokens per correct |
|---|---|---|---|---|
| M1b | dev | 136.6 | 21.8 | 327.5 |
| M1b | held-out | 136.7 | 24.2 | 439.0 |
| M2 | dev | 1153.4 | 85.7 | 3200.9 |
| M2 | held-out | 1220.1 | 99.3 | 3958.1 |
| normalize-quotes | dev | 863.0 | 62.3 | 2390.4 |
| normalize-quotes | held-out | 1220.1 | 99.3 | 3958.1 |
| normalize-quotes+final-from-result | dev | 899.4 | 71.8 | 1881.6 |
| normalize-quotes+final-from-result | held-out | 1260.5 | 107.4 | 4319.7 |
| normalize-quotes+final-from-result+precision-only | dev | 879.9 | 67.1 | 1545.2 |
| normalize-quotes+final-from-result+precision-only | held-out | 1225.5 | 101.0 | 3316.2 |

### Failure types (agent configurations only)

| Configuration | Dataset | no_submit_text | ran_out_of_steps | gave_up_after_errors | silent_wrong | wrong_after_recovery |
|---|---|---|---|---|---|---|
| M2 | dev | 5 | 4 | 3 | 4 | 3 |
| M2 | held-out | 7 | 11 | 8 | 9 | 5 |
| normalize-quotes | dev | 4 | 1 | 3 | 4 | 7 |
| normalize-quotes | held-out | 7 | 11 | 8 | 9 | 5 |
| normalize-quotes+final-from-result | dev | 4 | 1 | 3 | 4 | 3 |
| normalize-quotes+final-from-result | held-out | 6 | 11 | 9 | 9 | 6 |
| normalize-quotes+final-from-result+precision-only | dev | 4 | 1 | 3 | 4 | 0 |
| normalize-quotes+final-from-result+precision-only | held-out | 7 | 11 | 8 | 9 | 1 |

- The best agent configuration scored 24/60 on held-out against 22/60 for the one-shot SQL baseline. A two-question gap on 60 is within noise, so I don't claim the agent beats the baseline. It used about 9x the input tokens (1,226 against 137 per question) and about 7.6x the tokens per correct answer (3,316 against 439).
- The fixes worked at the level they were aimed at: decimal-truncation failures fell from 5 to 1 on held-out, and easy questions rose from 16/26 to 19/26.
- The dev-set gain on medium questions (0/9 to 5/9) did not replicate: medium is 0/16 on held-out in every configuration.
- Re-running one configuration three times gave 20/60 each time, although two questions changed trajectory between runs without changing correctness.

## What broke

- **No database:** the model alone scored 0/31, with confident guesses (850000 for an answer of 7).
- **The first agent was worse than one-shot SQL:** it scored 12/31 against 15/31. An inspector I wrote sorted its 19 failures into five types: no_submit_text (5), ran_out_of_steps (4), gave_up_after_errors (3), silent_wrong (4), wrong_after_recovery (3).
- **My grader was too lenient.** The agent pulled a number out of plain text when the model forgot to call `submit_answer`. A prediction I had written down failed on one question (Q11), which exposed it. Removing the fallback and re-scoring from the saved trajectories moved the agent from 13/31 to 12/31. From then on only the submitted number counted.
- **Two bugs stacked on the same questions.** The model wrote curly quotes in SQL (“Chennai”), which SQLite rejected, and then repeated the same query up to eight times. Converting them to straight quotes fixed the query but not the score, because behind it the model passed its final number with the decimals cut off (20232.22 became 20232.0, 15603.82 became 15603.0; truncated, not rounded). In all 53 saved cases the decimals were dropped.
- **Fixing the truncation took three tries.** Asking again for the number, showing the whole conversation, recovered 0 of 7: the model copied its own truncated answer. A small isolated test showed the model copies decimals fine when it sees only the question and the query result (7 of 7). So I asked for the final number in a separate structured-output call from only those two things. That fixed all 7 but broke three easy counts (Q4, Q6, Q13), where the model returned 1.0 for results like `[(77,)]`; I don't know why. Accepting the second call's number only if it agrees with the submitted one up to truncation repaired all three. Two earlier attempts (a tool that submits the last query result, and a shorter prompt) lowered the score and were reverted, because changing the prompt or tool list changes the input to every question.
- **The held-out set showed what is still unsolved.** Five templates (month filters, two-filter counts, filtered joins) score 0 in every configuration, including the one-shot baseline. The schema text never says the data is from 2026, so the model wrote `LIKE '2023-%'` and got 0.0. It also used `MONTH()`, which SQLite doesn't have, and it dropped one of two filters (four different delivered-category questions all returned 161.0).

## Limits and next steps

Limits: one small model; one database and one set of templates; samples of 31 and 60; difficulty labels are mine; the quote fix was not exercised on the held-out set because no curly quotes appeared there.

Next: put the year range and a SQLite date hint into the schema and test on a fresh second held-out set; run the same harness with a larger local model; find out why the second call returns 1.0 for some counts.
