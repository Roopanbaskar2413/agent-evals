import json
import ollama
from pydantic import BaseModel
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize

MODEL = "llama3.2"
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


def main():
    results = []
    for q in load_questions():
        out = answer(q["question"])
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        status = "OK " if row["correct"] else "BAD"
        note = row["error"] or f"got={out['got']} expected={q['expected']}"
        print(f"{q['id']:>2} {status} {note}")
    with open(RESULTS, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()