import json
from src.grading import is_correct


def strict_got(row):
    for t in row["trajectory"]:
        if t["tool"] == "submit_answer":
            return t["output"]
    return None


def rescore(path):
    rows = [json.loads(l) for l in open(path)]
    out = []
    for r in rows:
        got = strict_got(r)
        out.append({**r, "strict_got": got, "strict_correct": is_correct(got, r["expected"])})
    return out


for label, path in [("M2", "data/results_agent.jsonl"), ("M2b", "data/results_agent_m2b.jsonl")]:
    rows = rescore(path)
    total = sum(r["strict_correct"] for r in rows)
    print(f"{label} strict score: {total}/{len(rows)}")
    for r in rows:
        if r["correct"] != r["strict_correct"]:
            print(f"  id={r['id']:>2} loose_correct={r['correct']} strict_correct={r['strict_correct']} "
                  f"loose_got={r['got']} strict_got={r['strict_got']} expected={r['expected']}")
    print()
