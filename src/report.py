import json
from collections import defaultdict
from src.inspect_trajectories import classify

CONFIGS = [
    ("M1b", "data/results_baseline_sql.jsonl", "data/results_baseline_sql_heldout.jsonl"),
    ("M2", "data/results_agent.jsonl", "data/results_agent_heldout.jsonl"),
    ("normalize-quotes", "data/results_agent_normalizequotes.jsonl",
     "data/results_agent_normalizequotes_heldout.jsonl"),
    ("normalize-quotes+final-from-result", "data/results_agent_normalizequotes_finalfromresult.jsonl",
     "data/results_agent_normalizequotes_finalfromresult_heldout.jsonl"),
    ("normalize-quotes+final-from-result+precision-only",
     "data/results_agent_normalizequotes_finalfromresult_precisiononly.jsonl",
     "data/results_agent_normalizequotes_finalfromresult_precisiononly_heldout.jsonl"),
]
DIFFICULTIES = ("easy", "medium", "hard")
FAILURE_TYPES = ("no_submit_text", "ran_out_of_steps", "gave_up_after_errors",
                 "silent_wrong", "wrong_after_recovery")


def load(path):
    return [json.loads(l) for l in open(path)]


def by_difficulty(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["difficulty"]].append(r["correct"])
    return by


def fmt(v):
    return f"{sum(v)}/{len(v)}" if v else "-"


def overall_table():
    lines = ["| Configuration | Dev overall | Held-out overall |", "|---|---|---|"]
    for name, dev_path, held_path in CONFIGS:
        dev, held = load(dev_path), load(held_path)
        lines.append(f"| {name} | {sum(r['correct'] for r in dev)}/{len(dev)} "
                      f"| {sum(r['correct'] for r in held)}/{len(held)} |")
    return "\n".join(lines)


def difficulty_table():
    lines = ["| Configuration | Difficulty | Dev | Held-out |", "|---|---|---|---|"]
    for name, dev_path, held_path in CONFIGS:
        dev_by = by_difficulty(load(dev_path))
        held_by = by_difficulty(load(held_path))
        for d in DIFFICULTIES:
            lines.append(f"| {name} | {d} | {fmt(dev_by.get(d, []))} | {fmt(held_by.get(d, []))} |")
    return "\n".join(lines)


def tokens_table():
    lines = ["| Configuration | Dataset | Avg tokens_in | Avg tokens_out | Tokens per correct |",
              "|---|---|---|---|---|"]
    for name, dev_path, held_path in CONFIGS:
        for label, path in (("dev", dev_path), ("held-out", held_path)):
            rows = load(path)
            tin = sum(r["tokens_in"] for r in rows) / len(rows)
            tout = sum(r["tokens_out"] for r in rows) / len(rows)
            correct = sum(r["correct"] for r in rows)
            total_tok = sum(r["tokens_in"] + r["tokens_out"] for r in rows)
            tpc = f"{total_tok / correct:.1f}" if correct else "-"
            lines.append(f"| {name} | {label} | {tin:.1f} | {tout:.1f} | {tpc} |")
    return "\n".join(lines)


def failure_table():
    header = "| Configuration | Dataset | " + " | ".join(FAILURE_TYPES) + " |"
    sep = "|---|---|" + "---|" * len(FAILURE_TYPES)
    lines = [header, sep]
    for name, dev_path, held_path in CONFIGS:
        if name == "M1b":
            continue
        for label, path in (("dev", dev_path), ("held-out", held_path)):
            rows = load(path)
            counts = {}
            for r in rows:
                if not r["correct"]:
                    c = classify(r)
                    counts[c] = counts.get(c, 0) + 1
            vals = [str(counts.get(cat, 0)) for cat in FAILURE_TYPES]
            lines.append(f"| {name} | {label} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    print("### Overall score\n")
    print(overall_table())
    print("\n### Score by difficulty\n")
    print(difficulty_table())
    print("\n### Tokens\n")
    print(tokens_table())
    print("\n### Failure types (agent configurations only)\n")
    print(failure_table())


if __name__ == "__main__":
    main()
