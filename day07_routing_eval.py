from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from omniagent.evaluation import (  # noqa: E402
    build_eval_report,
    compute_file_hash,
    load_eval_cases,
    run_routing_eval,
    save_eval_artifacts,
)
from omniagent.llm import FakeLLM, LLMResponse  # noqa: E402
from omniagent.prompts import (  # noqa: E402
    InMemoryPromptVersionRepository,
    PromptVersionService,
    render_prompt,
)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "evals" / "routing-v1.jsonl"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "evals" / "prompts" / "routing-v0.txt"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "evals" / "artifacts"
DEFAULT_AGENT_GOAL = (
    "Choose the appropriate route for each employee IT request."
)
DEFAULT_SUCCESS_CRITERIA = (
    "Choose the correct route, avoid unauthorized actions, and return valid "
    "structured output."
)
FAKE_MODEL = "fake-router-fixed-direct"
FAKE_RAW_OUTPUT = (
    '{"route":"direct","reason":"Offline fixed FakeLLM output.",'
    '"confidence":0.5}'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic offline Day 7 routing evaluation."
    )
    parser.add_argument(
        "--run-name",
        choices=("baseline", "candidate"),
        default="baseline",
    )
    parser.add_argument(
        "--prompt-version-id",
        default="routing-v0",
    )
    parser.add_argument(
        "--prompt-path",
        type=Path,
        default=DEFAULT_PROMPT_PATH,
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=DEFAULT_DATASET_PATH,
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=DEFAULT_ARTIFACTS_ROOT,
    )
    parser.add_argument(
        "--success-criteria",
        default=DEFAULT_SUCCESS_CRITERIA,
        help="The only Prompt variable changed for the Day 7 candidate run.",
    )
    return parser.parse_args()


def save_comparison_if_ready(artifacts_root: Path) -> Path | None:
    baseline_path = artifacts_root / "baseline" / "report.json"
    candidate_path = artifacts_root / "candidate" / "report.json"
    if not baseline_path.exists() or not candidate_path.exists():
        return None

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    changed_prompt_variables = [
        variable_name
        for variable_name in baseline["prompt_variables"]
        if baseline["prompt_variables"][variable_name]
        != candidate["prompt_variables"][variable_name]
    ]
    metric_names = (
        "schema_validity",
        "route_accuracy",
        "forbidden_tool_rate",
    )
    comparison = {
        "baseline_prompt_version_id": baseline["prompt_version_id"],
        "candidate_prompt_version_id": candidate["prompt_version_id"],
        "same_dataset_hash": (
            baseline["dataset_hash"] == candidate["dataset_hash"]
        ),
        "same_model": baseline["model"] == candidate["model"],
        "changed_prompt_variables": changed_prompt_variables,
        "metric_deltas": {
            metric_name: candidate[metric_name] - baseline[metric_name]
            for metric_name in metric_names
        },
        "interpretation": (
            "The fixed FakeLLM ignores Prompt text, so unchanged scores do not "
            "measure Prompt quality."
        ),
    }
    comparison_path = artifacts_root / "comparison.json"
    comparison_path.write_text(
        f"{json.dumps(comparison, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    return comparison_path


def main() -> None:
    args = parse_args()
    prompt_content = args.prompt_path.read_text(encoding="utf-8")
    prompt_variables = {
        "agent_goal": DEFAULT_AGENT_GOAL,
        "success_criteria": args.success_criteria,
    }

    prompt_service = PromptVersionService(
        InMemoryPromptVersionRepository()
    )
    prompt_service.create(
        prompt_version_id=args.prompt_version_id,
        content=prompt_content,
        created_at=datetime.now(UTC),
        variables=tuple(prompt_variables),
    )
    prompt = prompt_service.get(args.prompt_version_id)
    rendered_prompt = render_prompt(prompt, prompt_variables)

    cases = load_eval_cases(args.dataset_path)
    provider = FakeLLM(
        LLMResponse(
            model=FAKE_MODEL,
            content=FAKE_RAW_OUTPUT,
        )
    )
    results = run_routing_eval(
        cases,
        provider,
        model=FAKE_MODEL,
        system_prompt=rendered_prompt,
    )
    report = build_eval_report(
        results,
        prompt=prompt,
        prompt_variables=prompt_variables,
        rendered_prompt=rendered_prompt,
        dataset_name=args.dataset_path.name,
        dataset_hash=compute_file_hash(args.dataset_path),
        model=FAKE_MODEL,
    )

    output_dir = args.artifacts_root / args.run_name
    raw_outputs_path = output_dir / "raw-outputs.jsonl"
    report_path = output_dir / "report.json"
    save_eval_artifacts(
        results,
        report,
        raw_outputs_path=raw_outputs_path,
        report_path=report_path,
    )
    comparison_path = save_comparison_if_ready(args.artifacts_root)

    print("evaluation_mode = offline_fake_fixed")
    print("run_name =", args.run_name)
    print("prompt_version_id =", report.prompt_version_id)
    print("case_count =", report.case_count)
    print("schema_validity =", report.schema_validity)
    print("route_accuracy =", report.route_accuracy)
    print("forbidden_tool_rate =", report.forbidden_tool_rate)
    print("raw_outputs =", raw_outputs_path)
    print("report =", report_path)
    if comparison_path is not None:
        print("comparison =", comparison_path)


if __name__ == "__main__":
    main()
