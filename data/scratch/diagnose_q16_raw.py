import ollama
from src.agent import SYSTEM, TOOLS, MODEL, MAX_STEPS
from src.db_tools import run_query

question = "How many orders were placed in January?"
messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": question},
]

for step in range(1, MAX_STEPS + 1):
    response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, options={"temperature": 0})
    msg = response["message"]
    print("=" * 70)
    print(f"STEP {step}")
    print("raw content:", repr(msg.get("content")))
    print("raw tool_calls:", msg.get("tool_calls"))
    messages.append(msg)

    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        break
    call = tool_calls[0]
    name = call["function"]["name"]
    args = call["function"]["arguments"]
    print("tool name:", name, "| raw args:", repr(args))

    if name == "submit_answer":
        break
    if name == "run_sql":
        sql = args.get("sql", "")
        try:
            output = run_query(sql)
        except Exception as e:
            output = f"{type(e).__name__}: {e}"
        messages.append({"role": "tool", "tool_name": name, "content": str(output)})
    else:
        break
