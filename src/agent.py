import argparse
import json
import ollama
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize

MODEL = "llama3.2"
RESULTS = "data/results_agent.jsonl"
MAX_STEPS = 8
NUDGE = "Call submit_answer with your final numeric answer now."

SMART_QUOTES = {"“": "'", "”": "'", "‘": "'", "’": "'"}

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


def get_arg(args: dict, key: str):
    """Small models sometimes rename the one declared argument (e.g. 'a'
    instead of 'number'). With only one parameter, any single value is it."""
    if key in args:
        return args[key]
    if len(args) == 1:
        return next(iter(args.values()))
    return None


def normalize_quotes(sql: str) -> str:
    """Replace typographic/smart quotes with a plain ASCII quote, since
    SQLite only recognizes the plain one as a string delimiter."""
    for smart, straight in SMART_QUOTES.items():
        sql = sql.replace(smart, straight)
    return sql


def answer(question: str, nudge: bool = False, normalize: bool = False) -> dict:
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
    nudges = 0

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
            if nudge and nudges == 0:
                nudges += 1
                messages.append({"role": "user", "content": NUDGE})
                trajectory.append({"step": step, "tool": None, "input": None,
                                    "output": f"no tool call, nudged | text={content!r}"})
                continue
            error = "no tool call" + (" (after nudge)" if nudges else "")
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
            if normalize:
                sql = normalize_quotes(sql)
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
        "nudges": nudges,
        "trajectory": trajectory,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nudge", action="store_true",
                   help="one-time nudge to call submit_answer if a step has no tool call")
    p.add_argument("--normalize-quotes", action="store_true",
                   help="replace smart/curly quotes with a plain quote before running SQL")
    args = p.parse_args()

    results = []
    for q in load_questions():
        out = answer(q["question"], nudge=args.nudge, normalize=args.normalize_quotes)
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        status = "OK " if row["correct"] else "BAD"
        note = row["error"] or f"got={out['got']} expected={q['expected']} steps={out['steps_used']}"
        print(f"{q['id']:>2} {status} {note} nudges={out['nudges']}")
    with open(RESULTS, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()
