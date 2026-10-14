import argparse
import json
import re
from src.agent import MAX_STEPS
from src.grading import is_correct

RESULTS = "data/results_agent.jsonl"
ORDER = ["no_submit_text", "ran_out_of_steps", "gave_up_after_errors",
         "silent_wrong", "wrong_after_recovery"]


def load(path=RESULTS):
    with open(path) as f:
        return [json.loads(line) for line in f]


def strict_got(row):
    """Correctness counts only a real submit_answer call -- never a
    plain-text reply, so this must match agent.py's own grading exactly."""
    for t in row["trajectory"]:
        if t["tool"] == "submit_answer":
            return t["output"]
    return None


def is_sql_error(output):
    return bool(re.match(r"^[A-Za-z]+Error:", output))


def parse_number(output):
    m = re.search(r"-?\d+\.?\d*", output)
    return float(m.group()) if m else None


def classify(row):
    traj = row["trajectory"]
    last = traj[-1]
    if last["tool"] is None:
        return "no_submit_text"
    if len(traj) >= MAX_STEPS and last["tool"] != "submit_answer":
        return "ran_out_of_steps"

    recovered = had_error = False
    for t in traj:
        if t["tool"] == "run_sql":
            if is_sql_error(t["output"]):
                had_error = True
            else:
                val = parse_number(t["output"])
                if val is not None and is_correct(val, row["expected"]):
                    recovered = True

    if recovered:
        return "wrong_after_recovery"
    if had_error:
        return "gave_up_after_errors"
    return "silent_wrong"


def show(row):
    print(f"Q{row['id']} ({row['difficulty']}): {row['question']}")
    print(f"  expected={row['expected']} got={strict_got(row)} steps={len(row['trajectory'])}")
    for t in row["trajectory"]:
        print(f"    {t['step']} {t['tool']} {t['input']} -> {str(t['output'])[:120]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, help="show the full trajectory for one question id")
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    p.add_argument("--bad", action="store_true", help="list each incorrect row with its classification")
    args = p.parse_args()

    rows = load()
    if args.difficulty:
        rows = [r for r in rows if r["difficulty"] == args.difficulty]

    if args.id is not None:
        for r in rows:
            if r["id"] == args.id:
                show(r)
        return

    if args.bad:
        for r in rows:
            if not is_correct(strict_got(r), r["expected"]):
                print(f"Q{r['id']:>2} {classify(r):<22} got={strict_got(r)} expected={r['expected']}")
        return

    counts = {}
    for r in rows:
        if not is_correct(strict_got(r), r["expected"]):
            c = classify(r)
            counts[c] = counts.get(c, 0) + 1
    total_bad = sum(counts.values())
    print(f"Failures: {total_bad}/{len(rows)}")
    for cat in ORDER:
        if cat in counts:
            print(f"  {cat}: {counts[cat]}")


if __name__ == "__main__":
    main()
