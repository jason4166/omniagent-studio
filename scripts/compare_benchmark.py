"""Compare recorded benchmark conditions without inventing improvement or retention."""

import argparse
import json
from pathlib import Path


def compare_reports(before: dict, after: dict, repeated: dict) -> dict:
    runs = (before, after, repeated)
    if len({run["workload_hash"] for run in runs}) != 1:
        raise ValueError("Workload drift prevents comparison")
    controls = []
    for run in runs:
        versions = run.get("versions") or {}
        controls.append(
            {
                "versions": {
                    key: value for key, value in versions.items() if key != "git_and_code"
                },
                "environment": run.get("environment"),
                "timing_scope": run.get("timing_scope"),
                "provider": run.get("provider"),
            }
        )
    complete = all(
        all(value is not None and value != {} for value in row.values()) for row in controls
    )
    comparable = complete and controls[0] == controls[1] == controls[2]
    clean = all(run.get("passed") is True and run.get("error_rate") == 0 for run in runs)
    rows = []
    for metric in ("p50_ms", "p95_ms", "mean_database_queries", "mean_database_ms"):
        left, right = before.get(metric), after.get(metric)
        change = (
            100 * (right / left - 1)
            if comparable
            and clean
            and isinstance(left, (int, float))
            and left > 0
            and isinstance(right, (int, float))
            else None
        )
        rows.append(
            {
                "metric": metric,
                "baseline": left,
                "candidate": right,
                "retest": repeated.get(metric),
                "candidate_change_percent": change,
            }
        )
    source = [run.get("code_version") for run in runs]
    return {
        "schema_version": 2,
        "recorded_controls_match": comparable,
        "all_runs_passed": clean,
        "comparison_kind": "unverified_or_different_conditions"
        if not comparable
        else "repeatability"
        if all(source) and len(set(source)) == 1
        else "source_change",
        "retained": None,
        "baseline_commit": before.get("git_commit"),
        "candidate_commit": after.get("git_commit"),
        "workload_hash": before["workload_hash"],
        "rows": rows,
        "limitation": "Recorded controls do not freeze host load. The report makes no automatic "
        "optimization-retention decision; inspect traces, EXPLAIN and repeated results.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("baseline", "candidate", "retest", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    runs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.baseline, args.candidate, args.retest)
    ]
    report = compare_reports(*runs)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Benchmark observations",
        "",
        "Comparison: " + report["comparison_kind"],
        "",
        "| Metric | Baseline | Candidate | Retest | Change % |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["rows"]:
        values = [
            str(row[key]) if row[key] is not None else "unknown"
            for key in ("metric", "baseline", "candidate", "retest", "candidate_change_percent")
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines += ["", report["limitation"], ""]
    (args.output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
