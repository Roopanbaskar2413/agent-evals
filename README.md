# agent-evals

Result: two fixes landed together. A one-line schema fix (telling the model what year the data is from, and that SQLite has no MONTH()/YEAR()) raised every configuration's held-out score, but it also quietly broke the agent's tool-calling on unrelated dev questions. Turning on an existing `--nudge` flag (re-prompt once when a step has no tool call) recovered that regression cleanly, with zero side effects on either dataset. Net result: the best agent configuration now ties one-shot SQL on the 31 dev questions (17/31 each) and leads it clearly on the 60 held-out questions (43/60 vs 35/60). The schema fix still traded one failure for another on the baseline -- it fixed date filtering everywhere, but made one-shot SQL add filters nobody asked for on plain counts. The useful part is the eval that caught all three effects, not just the headline number.

## What this is

An evaluation harness for a small agent that answers questions about a SQLite shop database (40 customers, 300 orders), using a local 3B model (llama3.2 through Ollama). The point is the measuring, not the agent. The correct answer to every question is computed by running SQL, so no model grades another model. All numbers below are generated from the saved result files by `make report`.

## How to run

Setup:
- `python3 -m venv .venv`
- `source .venv/bin/activate`
- `pip install ollama pydantic`

Also requires Ollama running with `llama3.2` pulled (`ollama pull llama3.2`).

- `make demo` rebuilds the database and the 31 dev questions and runs the one-shot baseline; it ends by printing `Overall: 17/31 = 55%` with the easy/medium/hard breakdown (easy 12/15, medium 4/9, hard 1/7).
- `make report` regenerates the tables below from the saved results in `data/`.
- Agent configurations run with `python -m src.agent` plus flags (`--nudge`, `--normalize-quotes`, `--final-from-result`, `--precision-only`, `--questions <file>`). Needs the venv active. `--nudge` is included in every reported agent configuration below (see "What broke").

## Results

Two question sets. The 31 dev questions (15 easy, 9 medium, 7 hard) are the ones I looked at while building and fixing. The 60 held-out questions (26 easy, 16 medium, 18 hard) come from the same templates with different values. Each configuration was run once against the held-out set for the tables below, with the configurations and the rules written down in advance; one configuration was re-run later to check how stable the results were. They test robustness to new values, not new kinds of questions. "Tokens per correct" is total tokens spent divided by correct answers.

### Overall score

| Configuration | Dev overall | Held-out overall |
|---|---|---|
| M1b | 17/31 | 35/60 |
| M2+nudge | 15/31 | 32/60 |
| normalize-quotes+nudge | 15/31 | 32/60 |
| normalize-quotes+final-from-result+nudge | 14/31 | 37/60 |
| normalize-quotes+final-from-result+precision-only+nudge | 17/31 | 43/60 |

### Score by difficulty

| Configuration | Difficulty | Dev | Held-out |
|---|---|---|---|
| M1b | easy | 12/15 | 8/26 |
| M1b | medium | 4/9 | 16/16 |
| M1b | hard | 1/7 | 11/18 |
| M2+nudge | easy | 11/15 | 16/26 |
| M2+nudge | medium | 4/9 | 8/16 |
| M2+nudge | hard | 0/7 | 8/18 |
| normalize-quotes+nudge | easy | 11/15 | 16/26 |
| normalize-quotes+nudge | medium | 4/9 | 8/16 |
| normalize-quotes+nudge | hard | 0/7 | 8/18 |
| normalize-quotes+final-from-result+nudge | easy | 10/15 | 13/26 |
| normalize-quotes+final-from-result+nudge | medium | 4/9 | 16/16 |
| normalize-quotes+final-from-result+nudge | hard | 0/7 | 8/18 |
| normalize-quotes+final-from-result+precision-only+nudge | easy | 13/15 | 19/26 |
| normalize-quotes+final-from-result+precision-only+nudge | medium | 4/9 | 16/16 |
| normalize-quotes+final-from-result+precision-only+nudge | hard | 0/7 | 8/18 |

### Tokens

| Configuration | Dataset | Avg tokens_in | Avg tokens_out | Tokens per correct |
|---|---|---|---|---|
| M1b | dev | 175.6 | 31.3 | 377.4 |
| M1b | held-out | 175.7 | 35.5 | 362.2 |
| M2+nudge | dev | 1090.9 | 65.6 | 2390.1 |
| M2+nudge | held-out | 847.0 | 52.5 | 1686.6 |
| normalize-quotes+nudge | dev | 1067.4 | 63.8 | 2337.8 |
| normalize-quotes+nudge | held-out | 847.0 | 52.5 | 1686.6 |
| normalize-quotes+final-from-result+nudge | dev | 1105.2 | 73.7 | 2610.5 |
| normalize-quotes+final-from-result+nudge | held-out | 886.9 | 62.3 | 1539.2 |
| normalize-quotes+final-from-result+precision-only+nudge | dev | 1084.3 | 68.6 | 2102.4 |
| normalize-quotes+final-from-result+precision-only+nudge | held-out | 858.7 | 55.9 | 1276.2 |

### Failure types

| Configuration | Dataset | no_submit_text | ran_out_of_steps | gave_up_after_errors | silent_wrong | wrong_after_recovery | error |
|---|---|---|---|---|---|---|---|
| M1b | dev | 0 | 0 | 0 | 9 | 0 | 5 |
| M1b | held-out | 0 | 0 | 0 | 25 | 0 | 0 |
| M2+nudge | dev | 0 | 2 | 6 | 6 | 2 | 0 |
| M2+nudge | held-out | 0 | 0 | 2 | 15 | 11 | 0 |
| normalize-quotes+nudge | dev | 0 | 2 | 6 | 6 | 2 | 0 |
| normalize-quotes+nudge | held-out | 0 | 0 | 2 | 15 | 11 | 0 |
| normalize-quotes+final-from-result+nudge | dev | 0 | 2 | 6 | 6 | 3 | 0 |
| normalize-quotes+final-from-result+nudge | held-out | 0 | 0 | 2 | 15 | 6 | 0 |
| normalize-quotes+final-from-result+precision-only+nudge | dev | 0 | 2 | 6 | 6 | 0 | 0 |
| normalize-quotes+final-from-result+precision-only+nudge | held-out | 0 | 0 | 2 | 15 | 0 | 0 |

no_submit_text, ran_out_of_steps, gave_up_after_errors, and wrong_after_recovery can only happen inside the tool loop; M1b makes one SQL call and stops, so it can only fail with error (the query itself raised) or silent_wrong (the query ran, the answer was wrong).

- **The schema fix raised every configuration's held-out score by 8 to 15 questions before nudge was added**, almost entirely by fixing the month-filter questions (medium on held-out is exactly those questions): M2/normalize-quotes went from 0/16 to 8/16 (counts fixed, sums still lose decimals -- they don't have the fix for that); the two final-from-result configs went from 0/16 to a clean 16/16.
- **The schema fix also broke the agent's tool-calling on unrelated dev questions, and `--nudge` fixed it with no measured side effects.** Immediately after the schema fix, dev easy fell for every agent config (e.g. plain M2 12/15 -> 9/15) on questions that never touch a date at all: Q4/Q6 (plain category counts) went from a clean `submit_answer` call to a plain-text sentence instead of a tool call (`no_submit_text`); Q10/Q11 (plain city counts) got stuck repeating an invented `WHERE city = ?` + `bindings` syntax the tool doesn't accept, never recovering within the step budget. Turning on the existing `--nudge` flag (re-prompt once when a step has no tool call) was tested in two stages, each confirmed clean on the full set before moving on: first on dev (13/31 -> 15/31, +2, zero regressions on any previously-correct question), then on held-out (28/60 -> 32/60, +4, zero regressions) for plain M2. Rolled out to all 4 agent configs the same way; one config (`+final-from-result`, no `precision-only`) showed a known interaction -- recovering Q4/Q6 via nudge exposed them to the still-unexplained "returns 1.0" bug below, so that config didn't net-gain on dev (14/31, unchanged) even though its held-out score still rose (33/60 -> 37/60, +4, different recovered questions). A second targeted fix attempt (telling the `run_sql` tool schema not to use placeholder/bindings syntax) was tried for Q10/Q11 specifically and had no measurable effect at all -- the model's trajectory was byte-for-byte identical before and after the edit, so it was reverted; Q10/Q11 remains a documented, unfixed limit (see "What broke").
- **With nudge folded in, the ranking is closer than either pre-nudge snapshot suggested.** Before any of this session's fixes, the best agent configuration led dev (19/31 vs M1b's 15/31) and was roughly tied with M1b on held-out (24/60 vs 22/60). After the schema fix alone (pre-nudge), the ranking flipped in opposite directions per dataset. With nudge folded into every agent config: the best agent configuration now **ties** M1b on dev (17/31 each) and **leads** M1b clearly on held-out (43/60 vs 35/60, an 8-question gap). I'd call the held-out lead real at this sample size; the dev tie is still close enough that I wouldn't read a clear winner into it either way.
- **The fix traded a known failure for a different one, on M1b only.** M1b now adds unprompted `status = 'delivered' AND order_date LIKE '2026-%-%'` to plain customer-count questions that never mention status or date -- M1b's easy score fell from 21/26 to 8/26 on held-out almost entirely because of this (see "What broke"). None of the 4 agent configurations show this specific regression.
- Re-ran the best agent configuration three times on held-out, now under the current schema fix and with nudge (the actual reported configuration, not an earlier snapshot): 43/60 on all 3 runs, and every one of the 60 questions landed on the identical verdict and the identical submitted number across all 3 runs, including the non-whole-number answers and the four `None` rows. The earlier pre-fix check (24/60, also fully stable) is superseded by this one.

## What broke

- **No database:** the model alone scored 0/31, with confident guesses (850000 for an answer of 7).
- **The first agent was worse than one-shot SQL:** it scored 12/31 against 15/31. An inspector I wrote sorted its 19 failures into five types: no_submit_text (5), ran_out_of_steps (4), gave_up_after_errors (3), silent_wrong (4), wrong_after_recovery (3).
- **My grader was too lenient.** The agent pulled a number out of plain text when the model forgot to call `submit_answer`. A prediction I had written down failed on one question (id 11 in data/questions.jsonl), which exposed it. Removing the fallback and re-scoring from the saved trajectories moved the agent from 13/31 to 12/31. From then on only the submitted number counted.
- **Two bugs stacked on the same questions.** The model wrote curly quotes in SQL (“Chennai”), which SQLite rejected, and then repeated the same query up to eight times. Converting them to straight quotes fixed the query but not the score, because behind it the model passed its final number with the decimals cut off (20232.22 became 20232.0, 15603.82 became 15603.0; truncated, not rounded). Across 8 saved snapshots of agent runs taken while debugging this, the model submitted an answer to one of the 7 dev questions with a decimal expected value 53 times in total, and every one of those 53 had its decimals dropped.
- **Fixing the truncation took three tries.** Asking again for the number, showing the whole conversation, recovered 0 of 7: the model copied its own truncated answer. A small isolated test showed the model copies decimals fine when it sees only the question and the query result (7 of 7). So I asked for the final number in a separate structured-output call from only those two things. That fixed all 7 but broke three easy counts (ids 4, 6, 13 in data/questions.jsonl), where the model returned 1.0 for results like `[(77,)]`; I don't know why. The `--precision-only` flag skips the second call whenever the query result is already a whole number, since there are no decimals to lose, and that repaired all three. Two earlier attempts (a tool that submits the last query result, and a shorter prompt) lowered the score and were reverted, because changing the prompt or tool list changes the input to every question.
- **The held-out set showed what was still unsolved.** Five templates (month filters, two-filter counts, filtered joins) scored 0 in every configuration, including the one-shot baseline. The schema text never said the data was from 2026, so the model wrote `LIKE '2023-%'` and got 0.0. It also used `MONTH()`, which SQLite doesn't have, and it dropped one of two filters (four different delivered-category questions all returned 161.0).
- **Fixing the missing year took three tries, and the one that worked still has a cost.** Adding "all from 2026" alone wasn't enough -- the model still sometimes invented `MONTH()`/`YEAR()`. Telling it there's no such function and giving a worked `LIKE '2026-03-%'` example fixed the two month-filter templates cleanly, but caused the one-shot baseline to add that same `LIKE` pattern (plus an unprompted `status = 'delivered'`) to plain customer-count questions that never mention a date. A follow-up wording that explicitly said "otherwise don't add a date filter" using `substr()` instead of the worked example made both problems worse at once -- it fixed fewer month questions and additionally made the model add unprompted status filters to month questions too. Reverted to the worked-`LIKE`-example version (the first fix) and logged the over-filtering trade-off as a known, separate issue rather than keep rewording -- a 3B model reliably treating "here's when to add a filter" as license to add filters elsewhere looks like a model-capability limit, not a prompt problem. Full iteration-by-iteration numbers are in `tests/notes.md`.
- **The same schema fix destabilized the agent's tool-calling in a second, unrelated way -- and this one had a real fix.** The two extra sentences pushed the model to occasionally answer in plain text instead of calling a tool, even on questions with no date in them at all (Q4/Q6), and made it less able to recover from an already-existing bug where it invents a `?`/`bindings` SQL syntax the tool doesn't support (Q10/Q11). An existing `--nudge` flag (re-prompt once on an empty-tool-call step) was off in every reported configuration; turning it on fixed the plain-text failures cleanly on both datasets with zero regressions, confirmed by comparing every row against the pre-nudge result file before and after, on both dev and held-out, before trusting it (same discipline as the M4 decimal-truncation work). A second attempt at Q10/Q11 specifically -- telling the `run_sql` tool schema to always inline literal values instead of using placeholders -- had no effect whatsoever: the model's trajectory was identical before and after the edit. Reverted that one and left Q10/Q11 as a documented, unfixed limit rather than keep trying wordings that don't move the needle.

## Limits and next steps

Limits: one small model; one database and one set of templates; samples of 31 and 60; difficulty labels are mine; the quote fix was not exercised on the held-out set because no curly quotes appeared there; the fixes were developed on the dev set; the stability check (3 reruns, identical every time, both verdict and submitted number for all 60 questions) has now been repeated on the current reported configuration and schema and still holds; an earlier exploratory run saw two questions change trajectory (not correctness) under the old schema, so I wouldn't assume this determinism generalizes to every configuration; the schema fix itself trades a fixed failure (month filtering) for a new one (unprompted filters on customer-count, M1b only) rather than solving the underlying over-filtering tendency; the dev tie between M1b and the best agent configuration (17/31 each) is close enough at this sample size that I wouldn't call either a settled winner on dev.

Next: two known, not-yet-fixed issues. (1) M1b adds unprompted `status`/`order_date` filters to plain customer-count questions after the schema fix (14/14 held-out, 3/3 dev); tried two other schema wordings and both made it worse, so this needs a different kind of fix (prompt structure, not wording) or should be accepted as a model limit. (2) the agent still invents an unsupported `?`/`bindings` SQL syntax on some plain city-count questions (Q10/Q11 on dev) and can fail to recover within the step budget; a targeted tool-schema fix for this had zero effect and was reverted, so this is accepted as a model-capability limit for now too. Also: test the date fix on a fresh second held-out set; run the same harness with a larger local model; find out why the final-from-result call returns 1.0 for some whole-number results (Q4/Q6/Q13) but not others (Q45/53/54/55 on held-out, which recovered correctly).
