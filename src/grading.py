import json
import math
from collections import defaultdict


def load_questions(path="data/questions.jsonl"):
    with open(path) as f:
        return [json.loads(line) for line in f]


def is_correct(got, expected):
    return got is not None and math.isclose(got, expected, abs_tol=0.01)


def summarize(results):
    by_level = defaultdict(list)
    for r in results:
        by_level[r["difficulty"]].append(r["correct"])
    total = [r["correct"] for r in results]
    print(f"Overall: {sum(total)}/{len(total)} = {sum(total) / len(total):.0%}")
    for level in ("easy", "medium", "hard"):
        scores = by_level.get(level, [])
        if scores:
            print(f"  {level}: {sum(scores)}/{len(scores)} = {sum(scores) / len(scores):.0%}")