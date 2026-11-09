import argparse
import json
from src.agent import answer
from src.grading import load_questions, is_correct

QUESTIONS = "data/questions_heldout.jsonl"
RESULTS_TEMPLATE = "data/results_agent_normalizequotes_finalfromresult_precisiononly_heldout_run{n}.jsonl"


def run_once(n: int, questions: list) -> list:
    results_path = RESULTS_TEMPLATE.format(n=n)
    results = []
    with open(results_path, "w") as f:
        for q in questions:
            out = answer(q["question"], normalize=True, final_from_result=True, precision_only=True)
            row = {**q, **out, "correct": is_correct(out["got"], q["expected"])}
            results.append(row)
            f.write(json.dumps(row) + "\n")
            f.flush()
            status = "OK " if row["correct"] else "BAD"
            note = row["error"] or f"got={out['got']} expected={q['expected']} steps={out['steps_used']}"
            print(f"run{n} {q['id']:>2} {status} {note}")
    return results


def print_stability_table(all_runs: list):
    n_runs = len(all_runs)
    by_id = {}
    for run_idx, results in enumerate(all_runs):
        for row in results:
            by_id.setdefault(row["id"], {"difficulty": row["difficulty"], "runs": {}})
            by_id[row["id"]]["runs"][run_idx] = (row["correct"], row["got"])

    header = "id difficulty " + " ".join(f"verdict{i+1}" for i in range(n_runs)) + " " + \
             " ".join(f"got{i+1}" for i in range(n_runs)) + " stable_verdict stable_number"
    print(header)
    for qid in sorted(by_id):
        entry = by_id[qid]
        verdicts = [entry["runs"][i][0] for i in range(n_runs)]
        gots = [entry["runs"][i][1] for i in range(n_runs)]
        stable_verdict = len(set(verdicts)) == 1
        stable_number = len(set(gots)) == 1
        verdict_cols = " ".join("OK " if v else "BAD" for v in verdicts)
        got_cols = " ".join(str(g) for g in gots)
        print(f"{qid:>2} {entry['difficulty']:<8} {verdict_cols} {got_cols} "
              f"{stable_verdict!s:<13} {stable_number!s}")


def print_summary(all_runs: list):
    scores = [sum(row["correct"] for row in results) for results in all_runs]
    total = len(all_runs[0])
    print()
    for i, score in enumerate(scores, start=1):
        print(f"run{i}: {score}/{total}")
    print(f"min={min(scores)} max={max(scores)} range={max(scores) - min(scores)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3, help="number of times to repeat the held-out run")
    args = p.parse_args()

    questions = load_questions(QUESTIONS)
    all_runs = [run_once(n, questions) for n in range(1, args.runs + 1)]

    print()
    print_stability_table(all_runs)
    print_summary(all_runs)


if __name__ == "__main__":
    main()
