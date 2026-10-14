import json
from collections import defaultdict
from src.grading import is_correct

DEV_M1B = "data/results_baseline_sql.jsonl"
DEV_M2 = "data/results_agent.jsonl"
DEV_QUOTES = "data/results_agent_normalizequotes.jsonl"
DEV_FFR = "data/results_agent_normalizequotes_finalfromresult.jsonl"
DEV_C2 = "data/results_agent_normalizequotes_finalfromresult_precisiononly.jsonl"

HELD_M1B = "data/results_baseline_sql_heldout.jsonl"
HELD_M2 = "data/results_agent_heldout.jsonl"
HELD_QUOTES = "data/results_agent_normalizequotes_heldout.jsonl"
HELD_FFR = "data/results_agent_normalizequotes_finalfromresult_heldout.jsonl"
HELD_C2 = "data/results_agent_normalizequotes_finalfromresult_precisiononly_heldout.jsonl"

CONFIG_FILES = [
    ("M1b", DEV_M1B, HELD_M1B),
    ("M2", DEV_M2, HELD_M2),
    ("normalize-quotes", DEV_QUOTES, HELD_QUOTES),
    ("normalize-quotes+final-from-result", DEV_FFR, HELD_FFR),
    ("normalize-quotes+final-from-result+precision-only", DEV_C2, HELD_C2),
]

STATUS_TWISTS = {
    "What is the average amount of delivered orders?",
    "What is the total amount of pending orders?",
    "What is the average amount of pending orders?",
    "How many pending orders are there in total?",
}


def load(path):
    return [json.loads(l) for l in open(path)]


def by_id(path):
    return {r["id"]: r for r in load(path)}


def classify_template(text):
    if text in STATUS_TWISTS:
        return "status_only_twists"
    if text.startswith("How many orders did Customer"):
        return "customer_id_count"
    if text.startswith("How many delivered") and "are there" in text:
        return "category_delivered_count"
    if text.startswith("How many pending") and "are there" in text:
        return "category_pending_count"
    if text.startswith("How many orders were placed in"):
        return "month_count"
    if text.startswith("What is the total amount of orders placed in"):
        return "month_sum"
    if text.startswith("How many pending orders were placed by customers in"):
        return "city_pending_join"
    if text.startswith("How many delivered") and "placed by customers in" in text:
        return "city_category_delivered_join"
    if text.startswith("How many pending") and "placed by customers in" in text:
        return "city_category_pending_join"
    if text.startswith("What is the average amount of pending"):
        return "avg_pending_category"
    return "UNCLASSIFIED"


def section_a():
    print("=== (a) smart-quote scan + cmp: held-out M2 vs +quotes ===")
    smart = set("‘’“”")
    for label, path in [("M2 heldout", HELD_M2), ("+quotes heldout", HELD_QUOTES)]:
        rows = load(path)
        ids = set()
        for r in rows:
            for t in r["trajectory"]:
                if t["tool"] == "run_sql" and any(c in smart for c in t["input"].get("sql", "")):
                    ids.add(r["id"])
        print(f"  {label}: ids with smart quotes = {sorted(ids)}")
    a, b = by_id(HELD_M2), by_id(HELD_QUOTES)
    diffs = [i for i in a if a[i]["got"] != b[i]["got"] or a[i]["correct"] != b[i]["correct"]]
    print(f"  full id-level diff: {diffs}")
    for i in diffs:
        print(f"    id={i} M2_got={a[i]['got']} quotes_got={b[i]['got']}")


def section_b():
    print("=== (b) re-score dev C2 file ===")
    rows = load(DEV_C2)
    total = sum(is_correct(r["got"], r["expected"]) for r in rows)
    print(f"  {total}/{len(rows)}")


def paired(a, b):
    both = sum(1 for i in a if a[i] and b[i])
    only_a = sum(1 for i in a if a[i] and not b[i])
    only_b = sum(1 for i in a if not a[i] and b[i])
    neither = sum(1 for i in a if not a[i] and not b[i])
    return both, only_a, only_b, neither


def section_c():
    print("=== (c) paired counts: C2 vs M1b, C2 vs M2 ===")
    for label, m1b_path, m2_path, c2_path in [
        ("dev", DEV_M1B, DEV_M2, DEV_C2),
        ("held-out", HELD_M1B, HELD_M2, HELD_C2),
    ]:
        c2 = {i: r["correct"] for i, r in by_id(c2_path).items()}
        m1b = {i: r["correct"] for i, r in by_id(m1b_path).items()}
        m2 = {i: r["correct"] for i, r in by_id(m2_path).items()}
        print(f"  {label}:")
        print(f"    C2 vs M1b: {paired(c2, m1b)}")
        print(f"    C2 vs M2:  {paired(c2, m2)}")


def section_d():
    print("=== (d) oracle router: best of M1b and C2 ===")
    for label, m1b_path, c2_path in [("dev", DEV_M1B, DEV_C2), ("held-out", HELD_M1B, HELD_C2)]:
        m1b = by_id(m1b_path)
        c2 = by_id(c2_path)
        oracle = {i: (m1b[i]["correct"] or c2[i]["correct"]) for i in m1b}
        by_diff = defaultdict(list)
        for i, r in m1b.items():
            by_diff[r["difficulty"]].append(oracle[i])
        print(f"  {label}: overall {sum(oracle.values())}/{len(oracle)}")
        for d in ("easy", "medium", "hard"):
            v = by_diff.get(d, [])
            print(f"    {d}: {sum(v)}/{len(v)}")


def section_e():
    print("=== (e) per-template scores, held-out, all 5 configs ===")
    order = ["customer_id_count", "category_delivered_count", "category_pending_count",
             "status_only_twists", "month_count", "month_sum", "city_pending_join",
             "city_category_delivered_join", "city_category_pending_join", "avg_pending_category"]
    for name, _, held_path in CONFIG_FILES:
        rows = load(held_path)
        by_t = defaultdict(list)
        for r in rows:
            by_t[classify_template(r["question"])].append(r["correct"])
        print(f"  {name}:")
        for t in order:
            v = by_t.get(t, [])
            print(f"    {t}: {sum(v)}/{len(v)}")


def section_f():
    print("=== (f) tokens per correct answer ===")
    for label, which in [("dev", 1), ("held-out", 2)]:
        print(f"  {label}:")
        for name, dev_path, held_path in CONFIG_FILES:
            path = dev_path if which == 1 else held_path
            rows = load(path)
            total_tokens = sum(r["tokens_in"] + r["tokens_out"] for r in rows)
            correct = sum(r["correct"] for r in rows)
            tpc = total_tokens / correct if correct else float("inf")
            print(f"    {name}: total={total_tokens} correct={correct} tokens/correct={tpc:.1f}")


def section_g():
    print("=== (g) held-out run_sql args ending in a dangling operator ===")
    operators = ["=", "LIKE", "IN", "("]
    for name, _, held_path in CONFIG_FILES:
        if name == "M1b":
            continue
        rows = load(held_path)
        hits = []
        for r in rows:
            for t in r["trajectory"]:
                if t["tool"] == "run_sql":
                    sql = t["input"].get("sql", "").rstrip()
                    upper = sql.upper()
                    for op in operators:
                        if upper.endswith(op.upper()):
                            hits.append((r["id"], r["difficulty"], op))
                            break
        unique_ids = sorted(set(i for i, d, op in hits))
        by_diff = defaultdict(set)
        for i, d, op in hits:
            by_diff[d].add(i)
        print(f"  {name}: {len(hits)} occurrences, unique ids {unique_ids}")
        for d, ids in by_diff.items():
            print(f"    {d}: {sorted(ids)}")


if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
