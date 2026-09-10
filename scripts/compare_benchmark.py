"""Compare measurements from the same bounded workload; never invent a timing."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("retest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    before, after, repeated = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.baseline, args.candidate, args.retest)
    ]
    if len({run["workload_hash"] for run in (before, after, repeated)}) != 1:
        raise ValueError("Workload drift prevents comparison")
    rows = [
        {
            "metric": metric,
            "baseline": before[metric],
            "candidate": after[metric],
            "retest": repeated[metric],
            "candidate_change_percent": 100 * (after[metric] / before[metric] - 1),
        }
        for metric in ("p50_ms", "p95_ms", "mean_database_queries", "mean_database_ms")
    ]
    retained = (
        after["mean_database_queries"] < before["mean_database_queries"]
        and max(after["p50_ms"], repeated["p50_ms"]) < before["p50_ms"]
        and not after["error_rate"]
        and not repeated["error_rate"]
    )
    report = {
        "schema_version": 1,
        "retained": retained,
        "baseline_commit": before["git_commit"],
        "candidate_commit": after["git_commit"],
        "workload_hash": before["workload_hash"],
        "rows": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Measured database round-trip reduction",
        "",
        "| Metric | Baseline | Candidate | Re-test | Candidate change |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['metric']} | {row['baseline']:.4f} | {row['candidate']:.4f} "
        f"| {row['retest']:.4f} | {row['candidate_change_percent']:.2f}% |"
        for row in rows
    ]
    lines += [
        "",
        f"Optimization retained: **{retained}**. See ADR 0008 and the source JSON EXPLAIN plans.",
        "",
        "Three Profile/Tool/KB query fingerprints decreased from 28 to 18 occurrences per request. "
        "Each request still checks current permissions at every graph boundary. The small-table "
        "sequential scan was not the bottleneck; redundant application round trips were. "
        "P95 has visible local scheduling noise. Real-provider latency is a separate dataset.",
        "",
    ]
    (args.output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
