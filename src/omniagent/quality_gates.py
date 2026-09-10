"""Executable gates and comparisons; safety never participates in a weighted average."""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from omniagent.eval_platform import EvalRun
from omniagent.security_scan import scan


def number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0


def eval_passes(run: EvalRun) -> bool:
    return all(run.safety_gates.values()) and all(
        number(run.metrics.get(metric)) >= minimum
        for metric, minimum in {"e2e_success_rate": 0.95, "route_accuracy": 0.95}.items()
    )


def compare(baseline: Path, candidate: Path, output: Path) -> dict[str, object]:
    before = EvalRun.model_validate_json(baseline.read_text(encoding="utf-8"))
    after = EvalRun.model_validate_json(candidate.read_text(encoding="utf-8"))
    if before.dataset_hash != after.dataset_hash or before.provider_mode != after.provider_mode:
        raise ValueError("Comparison requires the same dataset and provider mode")
    names = (
        "route_accuracy",
        "recall_at_1",
        "mrr",
        "citation_validity",
        "claim_support",
        "e2e_success_rate",
        "p50_ms",
        "p95_ms",
        "model_calls",
        "retrieval_calls",
        "tool_calls",
        "total_tokens",
    )
    rows = []
    for name in names:
        left, right = before.metrics[name], after.metrics[name]
        rows.append(
            {
                "metric": name,
                "baseline": left,
                "candidate": right,
                "delta": float(right) - float(left)
                if isinstance(left, (float, int)) and isinstance(right, (float, int))
                else None,
            }
        )
    report = {
        "schema_version": 1,
        "baseline_run": before.run_id,
        "candidate_run": after.run_id,
        "dataset_hash": after.dataset_hash,
        "candidate_gate": eval_passes(after),
        "safety_gates": after.safety_gates,
        "metrics": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Frozen evaluation comparison",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['metric']} | {row['baseline']} | {row['candidate']} | {row['delta']} |"
        for row in rows
    ]
    lines += [
        "",
        f"Candidate gate: **{report['candidate_gate']}**. Safety gates: `{after.safety_gates}`.",
        "",
        "Latency is measured on local Fake runs; the benchmark report separately measures "
        "repeated workloads. No real-model comparison is implied.",
        "",
    ]
    (output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="350" viewBox="0 0 800 350">',
        '<rect width="800" height="350" fill="#f8fafc"/>',
        '<g font-family="sans-serif" fill="#0f172a"><text x="30" y="30" font-size="20">'
        "Frozen Fake evaluation · baseline / candidate</text>",
    ]
    for index, name in enumerate(("route_accuracy", "recall_at_1", "mrr", "e2e_success_rate")):
        y = 65 + index * 65
        svg.append(f'<text x="30" y="{y + 16}" font-size="14">{name}</text>')
        for offset, run, color in ((0, before, "#94a3b8"), (24, after, "#0f766e")):
            value = number(run.metrics[name])
            svg.append(
                f'<rect x="230" y="{y + offset}" width="{value * 450:.1f}" '
                f'height="18" rx="3" fill="{color}"/>'
                f'<text x="690" y="{y + offset + 14}" font-size="13">{value:.2%}</text>'
            )
    svg.append("</g></svg>")
    (output / "comparison.svg").write_text("\n".join(svg), encoding="utf-8")
    return report


def security_gate(root: Path, output: Path, database_url: str) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603 - fixed test targets, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_security_matrix.py",
            "tests/test_api_boundaries.py",
            "tests/test_semantic_cache.py",
            "tests/test_http_tools.py",
            "tests/test_mcp_tools.py",
            "tests/test_security_scan.py",
            "--basetemp",
            str(root / ".pytest-tmp-security-gate"),
            "--junitxml",
            str(output / "junit.xml"),
            "-p",
            "no:cacheprovider",
        ],
        cwd=root,
        env={
            **os.environ,
            "OMNIAGENT_DATABASE_URL": database_url,
            "OMNIAGENT_TEST_DATABASE_URL": database_url,
        },
        timeout=180,
        check=False,
    )
    suites = ET.parse(output / "junit.xml").getroot()  # noqa: S314 - our own bounded pytest output
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    secrets = scan(root, output)
    report = {
        "schema_version": 1,
        "versioned_attack_cases": len(
            json.loads((root / "security/v1/cases.json").read_text(encoding="utf-8"))["cases"]
        ),
        "tests": tests,
        "skipped": skipped,
        "test_exit_code": result.returncode,
        "secret_findings": secrets["finding_count"],
        "passed": result.returncode == 0 and skipped == 0 and secrets["status"] == "pass",
    }
    (output / "security.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "security.md").write_text(
        "# Security gate\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in report.items())
        + "\n\nThe separate evaluation reports observed unauthorized-write, KB-isolation and "
        "attack-success rates. Passing synthetic attacks does not prove universal "
        "prompt-injection resistance.\n",
        encoding="utf-8",
    )
    return report
