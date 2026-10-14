import json
import unicodedata

rows = {r["id"]: r for r in (json.loads(l) for l in open("data/results_agent.jsonl"))}

for qid in (16, 20, 22, 24):
    row = rows[qid]
    print("=" * 70)
    print(f"Q{qid}: {row['question']}")
    for t in row["trajectory"]:
        if t["tool"] != "run_sql":
            continue
        sql = t["input"].get("sql", "")
        print(f"  step {t['step']}: {repr(sql)}")
        for ch in sql:
            if ord(ch) > 127:
                print(f"    non-ASCII: {repr(ch)} U+{ord(ch):04X} {unicodedata.name(ch)}")
