import json
import ollama
from pydantic import BaseModel
from src.grading import load_questions, is_correct, summarize

MODEL = "llama3.2"
RESULTS = "data/results_baseline.jsonl"

SYSTEM = "Answer the question with a single number. If you do not know, give your best guess."


class Answer(BaseModel):
    number: float


def ask(question: str) -> dict:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        format=Answer.model_json_schema(),
        options={"temperature": 0},
    )
    answer = Answer.model_validate_json(response["message"]["content"])
    return {
        "got": answer.number,
        "tokens_in": response["prompt_eval_count"],
        "tokens_out": response["eval_count"],
    }


def main():
    results = []
    for q in load_questions():
        out = ask(q["question"])
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        print(f"{q['id']:>2} {'OK ' if row['correct'] else 'BAD'} got={out['got']} expected={q['expected']}")
    with open(RESULTS, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()