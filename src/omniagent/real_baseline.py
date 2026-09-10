"""Opt-in live evaluation; no substitution of Fake models or embeddings."""

from pathlib import Path

from omniagent.eval_platform import EvalRun, evaluate


def real_baseline(database_url: str, output: Path, *, variant: str = "real-candidate") -> EvalRun:
    return evaluate(
        database_url,
        output,
        variant=variant,
        provider_mode="real",
        dataset_path=Path("evals/real-v1/cases.json"),
    )
