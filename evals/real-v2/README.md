# Optional live v2

Preserves the 24 frozen real-v1 cases and adds the six predeclared completeness and
counterclaim rubrics from e2e v2. There are 30 cases, 15 dev and 15 test. The old
corpus and its published results remain unchanged. Live evaluation now defaults to
v2; reproduce a historical run explicitly with `--dataset evals/real-v1/cases.json`.

On an isolated real-model deployment, run `omniagent eval-real --dataset
evals/real-v2/cases.json --output .pytest-tmp-real-v2`. This consumes real provider
requests. Results and missing coverage must be reported separately from Fake gates.

See [v2 methodology](../v2/README.md). Synthetic data and rules: CC0-1.0.
