import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from omniagent.llm import (
    LLMInvalidOutputError,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    RouteDecision,
    parse_route_decision,
)
from omniagent.profiles import PromptVersion

ROUTE_LABELS = ("direct", "retrieve", "tool", "clarify")
PREDICTED_ROUTE_LABELS = (*ROUTE_LABELS, "invalid")
FailureType = Literal["invalid_schema", "wrong_route", "forbidden_tool"]


class EvalCase(BaseModel):
    case_id: str = Field(min_length=1)
    user_input: str = Field(min_length=1)
    expected_route: Literal["direct", "retrieve", "tool", "clarify"]
    allowed_tools: tuple[str, ...] = ()


class EvalResult(BaseModel):
    case_id: str
    expected_route: Literal[
        "direct",
        "retrieve",
        "tool",
        "clarify",
    ]
    raw_output: str | None
    decision: RouteDecision | None
    schema_valid: bool
    allowed_tools: tuple[str, ...] = ()
    error_type: str | None = None


class EvalReport(BaseModel):
    prompt_version_id: str = Field(min_length=1)
    prompt_content_hash: str = Field(min_length=1)
    prompt_variables: dict[str, str]
    rendered_prompt_hash: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    dataset_hash: str = Field(min_length=1)
    model: str = Field(min_length=1)
    case_count: int = Field(gt=0)
    schema_validity: float = Field(ge=0.0, le=1.0)
    route_accuracy: float = Field(ge=0.0, le=1.0)
    forbidden_tool_rate: float = Field(ge=0.0, le=1.0)
    confusion_matrix: dict[str, dict[str, int]]
    failure_counts: dict[str, int]
    failed_case_ids: list[str]


class EvalDatasetError(ValueError):
    pass


def build_routing_request(
    case: EvalCase,
    *,
    model: str,
    system_prompt: str,
) -> LLMRequest:
    return LLMRequest(
        model=model,
        messages=[
            LLMMessage(
                role="system",
                content=system_prompt,
            ),
            LLMMessage(
                role="user",
                content=case.user_input,
            ),
        ],
        response_schema=RouteDecision.model_json_schema(),
    )


def run_routing_eval(
    cases: list[EvalCase],
    provider: LLMProvider,
    *,
    model: str,
    system_prompt: str,
) -> list[EvalResult]:
    results: list[EvalResult] = []

    for case in cases:
        request = build_routing_request(
            case,
            model=model,
            system_prompt=system_prompt,
        )
        response = provider.generate(request)

        try:
            decision = parse_route_decision(response)
        except LLMInvalidOutputError:
            results.append(
                EvalResult(
                    case_id=case.case_id,
                    expected_route=case.expected_route,
                    allowed_tools=case.allowed_tools,
                    raw_output=response.content,
                    decision=None,
                    schema_valid=False,
                    error_type="invalid_schema",
                )
            )
            continue

        results.append(
            EvalResult(
                case_id=case.case_id,
                expected_route=case.expected_route,
                allowed_tools=case.allowed_tools,
                raw_output=response.content,
                decision=decision,
                schema_valid=True,
            )
        )

    return results


def load_eval_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_case_ids: set[str] = set()

    lines = path.read_text(encoding="utf-8").splitlines()

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise EvalDatasetError(f"Blank line at line {line_number}")

        try:
            raw_case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalDatasetError(f"Invalid JSON at line {line_number}") from exc

        try:
            case = EvalCase.model_validate(raw_case)
        except ValidationError as exc:
            raise EvalDatasetError(f"Invalid EvalCase at line {line_number}") from exc

        if case.case_id in seen_case_ids:
            raise EvalDatasetError(f"Duplicate case_id at line {line_number}: {case.case_id}")

        seen_case_ids.add(case.case_id)

        cases.append(case)

    if not cases:
        raise EvalDatasetError("Evaluation dataset must not be empty")

    return cases


def calculate_schema_validity(
    results: list[EvalResult],
) -> float:
    if not results:
        raise ValueError("results must not be empty")

    valid_count = 0

    for result in results:
        if result.schema_valid:
            valid_count += 1

    return valid_count / len(results)


def calculate_route_accuracy(
    results: list[EvalResult],
) -> float:
    if not results:
        raise ValueError("results must not be empty")

    correct_count = 0

    for result in results:
        if result.decision is not None and result.decision.route == result.expected_route:
            correct_count += 1

    return correct_count / len(results)


def calculate_forbidden_tool_rate(
    results: list[EvalResult],
) -> float:
    tool_call_count = 0
    forbidden_tool_count = 0

    for result in results:
        decision = result.decision
        if decision is None or decision.route != "tool":
            continue

        tool_call_count += 1
        if decision.tool_name is None or decision.tool_name not in result.allowed_tools:
            forbidden_tool_count += 1

    if tool_call_count == 0:
        return 0.0

    return forbidden_tool_count / tool_call_count


def build_confusion_matrix(
    results: list[EvalResult],
) -> dict[str, dict[str, int]]:
    matrix = {
        expected_route: {predicted_route: 0 for predicted_route in PREDICTED_ROUTE_LABELS}
        for expected_route in ROUTE_LABELS
    }

    for result in results:
        predicted_route = result.decision.route if result.decision is not None else "invalid"
        matrix[result.expected_route][predicted_route] += 1

    return matrix


def classify_eval_result(result: EvalResult) -> tuple[FailureType, ...]:
    if not result.schema_valid or result.decision is None:
        return ("invalid_schema",)

    failures: list[FailureType] = []
    if result.decision.route != result.expected_route:
        failures.append("wrong_route")
    if result.decision.route == "tool" and (
        result.decision.tool_name is None or result.decision.tool_name not in result.allowed_tools
    ):
        failures.append("forbidden_tool")

    return tuple(failures)


def build_eval_report(
    results: list[EvalResult],
    *,
    prompt: PromptVersion,
    prompt_variables: dict[str, str],
    rendered_prompt: str,
    dataset_name: str,
    dataset_hash: str,
    model: str,
) -> EvalReport:
    failure_counts = {
        "invalid_schema": 0,
        "wrong_route": 0,
        "forbidden_tool": 0,
    }
    failed_case_ids: list[str] = []

    for result in results:
        failure_types = classify_eval_result(result)
        if failure_types:
            failed_case_ids.append(result.case_id)
        for failure_type in failure_types:
            failure_counts[failure_type] += 1

    return EvalReport(
        prompt_version_id=prompt.prompt_version_id,
        prompt_content_hash=prompt.content_hash,
        prompt_variables=prompt_variables,
        rendered_prompt_hash=hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest(),
        dataset_name=dataset_name,
        dataset_hash=dataset_hash,
        model=model,
        case_count=len(results),
        schema_validity=calculate_schema_validity(results),
        route_accuracy=calculate_route_accuracy(results),
        forbidden_tool_rate=calculate_forbidden_tool_rate(results),
        confusion_matrix=build_confusion_matrix(results),
        failure_counts=failure_counts,
        failed_case_ids=failed_case_ids,
    )


def compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_eval_artifacts(
    results: list[EvalResult],
    report: EvalReport,
    *,
    raw_outputs_path: Path,
    report_path: Path,
) -> None:
    if len(results) != report.case_count:
        raise ValueError("result count must match report case_count")
    if raw_outputs_path == report_path:
        raise ValueError("raw outputs and report paths must be different")

    raw_outputs_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    raw_output_rows: list[str] = []
    for result in results:
        raw_output_row = result.model_dump(mode="json")
        raw_output_row["failure_types"] = classify_eval_result(result)
        raw_output_rows.append(json.dumps(raw_output_row, ensure_ascii=False))

    raw_outputs = "\n".join(raw_output_rows)
    raw_outputs_path.write_text(f"{raw_outputs}\n", encoding="utf-8")
    report_path.write_text(
        f"{report.model_dump_json(indent=2)}\n",
        encoding="utf-8",
    )
