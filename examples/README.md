# Focused examples

The application starts through `omniagent serve` or `scripts/ops.py`; these small
programs isolate individual mechanisms and are not additional production runtimes.
Run them from the repository root with `uv run python examples/<name>.py --help`.

| Example | Purpose |
| --- | --- |
| `async_timeout.py` | Bounded asynchronous calls |
| `routing_eval.py` | Frozen routing evaluation |
| `configurable_runtime.py` | Configuration-driven execution |
| `ingestion.py` | PDF/Markdown/text import |
| `hybrid_retrieval_eval.py` | Hybrid retrieval evaluation |
| `grounding_eval.py` | Grounding contract evaluation; pass `--dataset-path evals/grounding-v2.jsonl` for the current contract |
| `real_provider_smoke.py` | Optional paid-provider smoke |
| `bounded_graph.py` | Budgeted state graph |

Older records refer to these files by their original `dayNN_*` names. Those records
remain unchanged so their historical commands and results can be traced to their commit.
