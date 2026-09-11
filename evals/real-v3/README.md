# Optional live v3 — 30 business workflows and 7 conversation workflows

The first 30 cases are copied unchanged from real-v2, including every query,
expected route/outcome, approval action and independent answer rubric. Seven
conversation cases are appended: three Chinese greetings, three capability
questions, and sales viewer help. The complete set has 37 cases: 19 dev and
18 test. The original business subset remains 15 dev and 15 test.

The new conversation cases use the real routing model to recognize intent.
Their public responses are then rendered by the server from authorized
capabilities; they do not ask the model to answer business-policy facts.
Report the 30-case business workflow result separately from the seven-case
conversation result, alongside measured model calls/tokens. Even if all cases
pass, **37/37 is a combined workflow result, not model accuracy**. Neither the
small business subset nor the conversation subset estimates general production
quality, dialogue coverage or an SLA.

On an isolated real-model deployment, run
`uv run omniagent eval-real --output .pytest-tmp-real-v3` (the new default), or
pass `--dataset evals/real-v3/cases.json` explicitly. This consumes real provider
requests. Preserve historical runs with explicit `--dataset
evals/real-v2/cases.json` and a different output directory. No frozen v1/v2 data
or published result is rewritten by this version.

The [v3 scoring and rubric boundaries](../v3/README.md) apply to both modes.
These files declare expectations; they do not assert that a new live run has
already passed. Compare runs only with the same dataset hash and recorded
measurement conditions. Synthetic data and labels: CC0-1.0.
