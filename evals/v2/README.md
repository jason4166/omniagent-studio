# E2E v2 — answer facts and completeness

This version preserves all 66 v1 cases and adds six predeclared answer-quality
rubrics, two for each Profile. Dev and test each receive three new cases.
The expected facts come from the existing synthetic policy specifications, not from
observing a model's candidate answer. The scorer does not read retrieved chunks or reuse
the runtime grounding verdict. It checks presence of required relationships and explicit
counterclaims, so a cited but incomplete answer can fail.

This is a bounded regression oracle, not a general semantic judge. Regex rules can reject
unseen valid wording or miss an unlisted contradiction. The eight deliberately wrong/right
answers in `answer-quality-v1/counterexamples.json` test the scorer itself and are not counted
as eight additional end-to-end model cases.

Default: `uv run omniagent eval --output .pytest-tmp-eval-v2`.
Historical v1: add `--dataset evals/v1/cases.json` and use a different output directory.
Compare only matching dataset hashes and recorded controls. Do not edit frozen labels after
observing results; record failures and introduce a new version for a changed contract.

License: synthetic fixtures and labels, CC0-1.0.
