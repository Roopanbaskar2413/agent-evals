import argparse
import json
import ollama
from pydantic import BaseModel
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize

MODEL = "llama3.2"
QUESTIONS = "data/questions.jsonl"
RESULTS = "data/results_baseline_sql.jsonl"

SYSTEM = f"""You write one SQLite SELECT query that answers the question.
{SCHEMA}
The first column of the first row of the result must be the answer."""


class Query(BaseModel):
    sql: str


def answer(question: str) -> dict:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        format=Query.model_json_schema(),
        options={"temperature": 0},
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
    args = p.parse_args()

    tag = questions_tag(args.questions)
    results_path = f"data/results_baseline_sql_{tag}.jsonl" if tag else RESULTS

    results = []
    for q in load_questions(args.questions):
        out = answer(q["question"])
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        status = "OK " if row["correct"] else "BAD"
        note = row["error"] or f"got={out['got']} expected={q['expected']}"
        print(f"{q['id']:>2} {status} {note}")
    with open(results_path, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()