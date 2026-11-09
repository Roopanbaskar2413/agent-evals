import argparse
import json
from pydantic import BaseModel
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize
from src.providers import get_provider

DEFAULT_MODEL = "llama3.2"
QUESTIONS = "data/questions.jsonl"
RESULTS = "data/results_baseline_sql.jsonl"

SYSTEM = f"""You write one SQLite SELECT query that answers the question.
{SCHEMA}
The first column of the first row of the result must be the answer."""


class Query(BaseModel):
    sql: str


def answer(question: str, provider) -> dict:
    response = provider.chat(
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        response_schema=Query,
        temperature=0,
    )
    sql = Query.model_validate_json(response["message"]["content"]).sql
    try:
        rows = run_query(sql)
        got = float(rows[0][0]) if rows and rows[0][0] is not None else None
        error = None
    except Exception as e:
        got, error = None, f"{type(e).__name__}: {e}"
    return {
        "sql": sql,
        "got": got,
        "error": error,
        "tokens_in": response["prompt_eval_count"],
        "tokens_out": response["eval_count"],
        "cost_usd": response["cost_usd"],
    }


def questions_tag(path: str) -> str:
    """'' for the default dev set (unchanged filename), else a short tag
    e.g. 'data/questions_heldout.jsonl' -> 'heldout'."""
    if path == QUESTIONS:
        return ""
    base = path.rsplit("/", 1)[-1]
    if base.endswith(".jsonl"):
        base = base[:-len(".jsonl")]
    if base.startswith("questions_"):
        base = base[len("questions_"):]
    elif base == "questions":
        base = ""
    return base


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=QUESTIONS, help="path to the questions .jsonl file")
    p.add_argument("--model", choices=sorted(["llama3.2", "gemini", "gpt"]), default=DEFAULT_MODEL,
                   help="which model/provider to answer with")
    args = p.parse_args()
    provider = get_provider(args.model)

    tag = questions_tag(args.questions)
    model_tag = "" if args.model == DEFAULT_MODEL else f"_{args.model}"
    results_path = (
        f"data/results_baseline_sql{model_tag}_{tag}.jsonl" if tag
        else f"data/results_baseline_sql{model_tag}.jsonl" if model_tag
        else RESULTS
    )

    results = []
    with open(results_path, "w") as f:
        for q in load_questions(args.questions):
            out = answer(q["question"], provider)
            row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
            results.append(row)
            f.write(json.dumps(row) + "\n")
            f.flush()  # saved the instant it's computed -- a later crash
            # (e.g. hitting the retry ceiling on a paid API) only costs the
            # questions not yet reached, not everything already answered.
            status = "OK " if row["correct"] else "BAD"
            note = row["error"] or f"got={out['got']} expected={q['expected']}"
            print(f"{q['id']:>2} {status} {note}")
    print()
    summarize(results)


if __name__ == "__main__":
    main()