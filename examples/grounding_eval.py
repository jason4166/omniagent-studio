from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from omniagent.grounding_evaluation import (  # noqa: E402
    build_grounding_eval_report,
    save_grounding_eval_report,
)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "evals" / "grounding-v1.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evals" / "artifacts" / "grounding" / "day13"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Day 13 grounding evaluation."
    )
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_grounding_eval_report(args.dataset_path)
    json_path, markdown_path = save_grounding_eval_report(report, args.output_dir)
    summary = report.summary
    print(
        f"decision_accuracy={summary.decision_accuracy:.4f}",
        f"citation_validity={summary.citation_validity_rate:.4f}",
        f"claim_support={summary.claim_support_rate:.4f}",
        f"unsupported_claim={summary.unsupported_claim_rate:.4f}",
        f"abstention_accuracy={summary.abstention_accuracy:.4f}",
    )
    print("json_report =", json_path)
    print("markdown_report =", markdown_path)


if __name__ == "__main__":
    main()
