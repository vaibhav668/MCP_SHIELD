import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # so 'shield.xxx' imports work when run as a script
from shield.detectors import scan_arguments, scan_description, scan_result
from shield.graph import HIGH, inspect

HERE = Path(__file__).parent
# "--dataset holdout" runs evals/holdout.json instead of the main dataset
NAME = sys.argv[sys.argv.index("--dataset") + 1] if "--dataset" in sys.argv else "dataset"
DATASET = HERE / f"{NAME}.json"
RESULTS = HERE / ("results.json" if NAME == "dataset" else f"results_{NAME}.json")
SCANNERS = {"description": scan_description, "arguments": scan_arguments, "result": scan_result}


def ms_since(start):
    return round((time.perf_counter() - start) * 1000, 3)


def predict_none(case):
    """Baseline: no protection, nothing is ever flagged."""
    return {"flagged": False, "ms": 0.0}


def predict_fast(case):
    """Fast path only: the regex score alone decides (middle band counts as not flagged)."""
    start = time.perf_counter()
    score, reasons = SCANNERS[case["kind"]](case["content"])
    return {"flagged": score >= HIGH, "ms": ms_since(start), "score": score}


def predict_full(case):
    """The whole graph: fast path, then the LLM judge for the middle band.
    A judge that failed (UNSURE) counts as flagged, because the real system would ask a human."""
    start = time.perf_counter()
    out = inspect(case["kind"], case["content"])
    ms = ms_since(start)
    if out["path"] == "judge":
        time.sleep(2)  # stay under the API rate limit (not counted in ms)
    return {"flagged": out["verdict"] in ("BLOCK", "UNSURE"), "ms": ms, "score": out["score"],
            "path": out["path"], "verdict": out["verdict"], "judge_reason": out.get("judge_reason")}


def rate(flags):
    return round(100 * sum(flags) / len(flags), 1) if flags else None


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p / 100))] if ordered else None


def summarise(rows):
    """rows is a list of (case, prediction). Returns detection rate, false-positive rate and latency."""
    attacks = [pred["flagged"] for case, pred in rows if case["label"] == "attack"]
    benign = [pred["flagged"] for case, pred in rows if case["label"] == "benign"]
    times = [pred["ms"] for case, pred in rows]
    return {
        "detection_rate": rate(attacks),
        "false_positive_rate": rate(benign),
        "median_ms": round(statistics.median(times), 3) if times else None,
        "p95_ms": percentile(times, 95),
        "judge_calls": sum(1 for case, pred in rows if pred.get("path") == "judge"),
        "judge_failed": sum(1 for case, pred in rows if pred.get("verdict") == "UNSURE"),
    }


def breakdown(rows, key):
    """The same numbers split by kind, category or difficulty."""
    groups = {}
    for case, pred in rows:
        groups.setdefault(case[key], []).append((case, pred))
    return {name: summarise(group) for name, group in sorted(groups.items())}


def print_table(title, table):
    print(f"\n{title}")
    print(f"  {'':<18}{'detect %':>10}{'false pos %':>13}{'median ms':>12}{'p95 ms':>12}")
    for name, s in table.items():
        print(f"  {name:<18}{str(s['detection_rate']):>10}{str(s['false_positive_rate']):>13}{s['median_ms']:>12.2f}{s['p95_ms']:>12.2f}")


def run_mode(name, predict, cases):
    print(f"\nRunning '{name}' on {len(cases)} cases...")
    rows = [(case, predict(case)) for case in cases]
    overall = summarise(rows)
    print_table(f"=== {name}: overall ===", {"all": overall})
    print(f"  judge calls: {overall['judge_calls']}")
    if overall["judge_failed"]:
        print(f"  WARNING: {overall['judge_failed']} judge calls FAILED (rate limit or API error). They are counted as flagged,")
        print("  so detection and false-positive numbers are NOT trustworthy. Wait, then re-run.")
    print_table(f"=== {name}: by threat ===", breakdown(rows, "category"))
    print_table(f"=== {name}: by difficulty ===", breakdown(rows, "difficulty"))
    return rows


def main():
    cases = json.loads(DATASET.read_text())
    modes = {"none": predict_none, "fast": predict_fast}
    if "--fast" not in sys.argv:
        modes["full"] = predict_full  # needs GROQ_API_KEY
    # keep modes from an earlier run (so a quick --fast run does not throw away a slow full run)
    saved = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    for name, predict in modes.items():
        rows = run_mode(name, predict, cases)
        saved[name] = {"summary": summarise(rows),
                       "cases": [{"id": c["id"], "label": c["label"], "difficulty": c["difficulty"], **p} for c, p in rows]}
    RESULTS.write_text(json.dumps(saved, indent=1))
    print(f"\nPer-case results saved to {RESULTS}")


if __name__ == "__main__":
    main()
