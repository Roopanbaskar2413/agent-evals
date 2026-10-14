import json
import re
import ollama
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize

MODEL = "llama3.2"
RESULTS = "data/results_agent.jsonl"
MAX_STEPS = 8

SYSTEM = f"""You answer questions about a shop database by running SQL queries.
{SCHEMA}
Call run_sql to check the database. Look at the result. If it looks wrong
(an error, an empty result, or a number that seems off), try a different query.
When you are confident in the final number, call submit_answer with that number.
Never answer in a plain sentence. Every reply must be a call to run_sql or submit_answer."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Run one read-only SQLite SELECT query and see the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A single SQLite SELECT statement."},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "Submit your final numeric answer to the question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {"type": "number", "description": "The final numeric answer."},
                },
                "required": ["number"],
            },
        },
    },
]


def extract_number(text: str):
    match = re.search(r"-?\d[\d,]*\.?\d*", text or "")
    if not match:
        return None
    return float(match.group().replace(",", ""))


def get_arg(args: dict, key: str):
    """Small models sometimes rename the one declared argument (e.g. 'a'
    instead of 'number'). With only one parameter, any single value is it."""
    if key in args:
        return args[key]
    if len(args) == 1:
        return next(iter(args.values()))
    return None


def answer(question: str) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    trajectory = []
    got = None
    error = None
    tokens_in = 0
    tokens_out = 0
    steps_used = 0

    for step in range(1, MAX_STEPS + 1):
        steps_used = step
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            options={"temperature": 0},
        )
        tokens_in += response["prompt_eval_count"]
        tokens_out += response["eval_count"]

        msg = response["message"]
        messages.append(msg)
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            content = msg.get("content") or ""
            fallback = extract_number(content)
            if fallback is not None:
                got = fallback
                error = "no tool call: parsed from plain-text reply"
            else:
                error = "no tool call: could not parse a number"
            trajectory.append({"step": step, "tool": None, "input": None, "output": f"{error} | text={content!r}"})
            break

        call = tool_calls[0]
        name = call["function"]["name"]
        args = call["function"]["arguments"]

        if name == "submit_answer":
            value = get_arg(args, "number")
            if value is None:
                error = f"submit_answer called with unreadable arguments: {args}"
                trajectory.append({"step": step, "tool": name, "input": args, "output": error})
                break
            got = float(value)
            trajectory.append({"step": step, "tool": name, "input": args, "output": got})
            break

        if name == "run_sql":
            sql = get_arg(args, "sql") or ""
            try:
                output = run_query(sql)
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
        else:
            output = f"unknown tool: {name}"

        trajectory.append({"step": step, "tool": name, "input": args, "output": str(output)})
        messages.append({"role": "tool", "tool_name": name, "content": str(output)})

    if got is None and error is None:
        error = "max steps reached without submit_answer"

    return {
        "got": got,
        "error": error,
        "steps_used": steps_used,
        "trajectory": trajectory,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def main():
    results = []
    for q in load_questions():
        out = answer(q["question"])
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        status = "OK " if row["correct"] else "BAD"
        note = row["error"] or f"got={out['got']} expected={q['expected']} steps={out['steps_used']}"
        print(f"{q['id']:>2} {status} {note}")
    with open(RESULTS, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()
