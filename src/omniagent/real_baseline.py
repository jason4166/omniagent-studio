"""Opt-in live evaluation; no substitution of Fake models or embeddings."""

from pathlib import Path

from omniagent.eval_platform import EvalRun, evaluate


def real_baseline(
    database_url: str,
    output: Path,
    *,
    variant: str = "real-candidate",
    dataset_path: Path = Path("evals/real-v3/cases.json"),
) -> EvalRun:
    return evaluate(
        database_url,
        output,
        variant=variant,
        provider_mode="real",
        dataset_path=dataset_path,
    )
