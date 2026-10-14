import argparse
import json
import re
import ollama
from pydantic import BaseModel
from src.db_tools import SCHEMA, run_query
from src.grading import load_questions, is_correct, summarize

FINAL_ANSWER_PROMPT = "What is your final numeric answer? Reply with just the number."


class FinalAnswer(BaseModel):
    number: float

MODEL = "llama3.2"
QUESTIONS = "data/questions.jsonl"
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


def is_whole_number(result_str: str) -> bool:
    """True if the first number in a run_sql result string has no
    fractional part (e.g. '[(77,)]' -> True, '[(291.52,)]' -> False)."""
    match = re.search(r"-?\d+\.?\d*", result_str or "")
    if not match:
        return False
    value = float(match.group())
    return value == int(value)


def answer(question: str, nudge: bool = False, normalize: bool = False,
           structured_final: bool = False, final_from_result: bool = False,
           precision_only: bool = False) -> dict:
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
    used_submit_tool = False
    last_sql_output = None

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
            used_submit_tool = True
            trajectory.append({"step": step, "tool": name, "input": args, "output": got})
            break

        if name == "run_sql":
            sql = get_arg(args, "sql") or ""
            if normalize:
                sql = normalize_quotes(sql)
            try:
                output = run_query(sql)
                last_sql_output = str(output)
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
        else:
            output = f"unknown tool: {name}"

        trajectory.append({"step": step, "tool": name, "input": args, "output": str(output)})
        messages.append({"role": "tool", "tool_name": name, "content": str(output)})

    if got is None and error is None:
        error = "max steps reached without submit_answer"

    if structured_final and used_submit_tool:
        messages.append({"role": "user", "content": FINAL_ANSWER_PROMPT})
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            format=FinalAnswer.model_json_schema(),
            options={"temperature": 0},
        )
        tokens_in += response["prompt_eval_count"]
        tokens_out += response["eval_count"]
        parsed = FinalAnswer.model_validate_json(response["message"]["content"])
        got = parsed.number
        trajectory.append({"step": steps_used + 1, "tool": "structured_final", "input": None, "output": got})

    if final_from_result and used_submit_tool:
        if last_sql_output is None:
            got = None
            trajectory.append({"step": steps_used + 1, "tool": "final_from_result",
                                "input": {"query_result": None}, "output": None})
        elif precision_only and is_whole_number(last_sql_output):
            trajectory.append({"step": steps_used + 1, "tool": "final_from_result",
                                "input": {"query_result": last_sql_output, "skipped": "whole number"},
                                "output": got})
        else:
            content = f"{question}\nQuery result: {last_sql_output}"
            response = ollama.chat(
                model=MODEL,
                messages=[{"role": "user", "content": content}],
                format=FinalAnswer.model_json_schema(),
                options={"temperature": 0},
            )
            tokens_in += response["prompt_eval_count"]
            tokens_out += response["eval_count"]
            parsed = FinalAnswer.model_validate_json(response["message"]["content"])
            got = parsed.number
            trajectory.append({"step": steps_used + 1, "tool": "final_from_result",
                                "input": {"query_result": last_sql_output}, "output": got})

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
    p.add_argument("--structured-final", action="store_true",
                   help="after a submit_answer call, re-ask for the number via structured output")
    p.add_argument("--final-from-result", action="store_true",
                   help="after a submit_answer call, re-derive the number from only the "
                        "question and the last successful run_sql result (no transcript)")
    p.add_argument("--precision-only", action="store_true",
                   help="with --final-from-result, skip the re-derivation when the query "
                        "result is already a whole number")
    p.add_argument("--questions", default=QUESTIONS, help="path to the questions .jsonl file")
    args = p.parse_args()

    if args.structured_final and args.final_from_result:
        p.error("--structured-final and --final-from-result are mutually exclusive")

    suffix = ""
    if args.nudge:
        suffix += "_nudge"
    if args.normalize_quotes:
        suffix += "_normalizequotes"
    if args.structured_final:
        suffix += "_structuredfinal"
    if args.final_from_result:
        suffix += "_finalfromresult"
    if args.precision_only:
        suffix += "_precisiononly"
    results_path = f"data/results_agent{suffix}.jsonl"

    results = []
    for q in load_questions(args.questions):
        out = answer(q["question"], nudge=args.nudge, normalize=args.normalize_quotes,
                     structured_final=args.structured_final,
                     final_from_result=args.final_from_result,
                     precision_only=args.precision_only)
        row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
        results.append(row)
        status = "OK " if row["correct"] else "BAD"
        note = row["error"] or f"got={out['got']} expected={q['expected']} steps={out['steps_used']}"
        print(f"{q['id']:>2} {status} {note} nudges={out['nudges']}")
    with open(results_path, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    print()
    summarize(results)


if __name__ == "__main__":
    main()
