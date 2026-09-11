# Independent answer quality counterexamples v1

This is an eight-answer, separately labeled scorer test set. It is **not** a new model
evaluation, additional live requests, or an enlargement of the frozen 24-case corpus.
The original synthetic question, policy, relationships and contradiction labels are CC0.

The scorer receives only a candidate answer and trusted query-specific labels. It
checks two relationships (annual leave allowance and application notice), plus
explicit contradictions. It never receives retrieval chunks, citation objects or
the runtime grounding decision. Valid source extracts can fail for missing a fact
or answering a different question. A separately worded answer can pass. Negation
and the wrong allowance period are negative controls even when expected numbers
are present.

These labels are deliberately bounded rules, not general natural-language inference.
An unseen paraphrase or contradiction can remain unrecognized. Extending coverage
requires independently authored labels and a new version; do not tune held-out
labels after observing failures. Keep the existing frozen datasets/reports immutable.

`EvalCase.answer_quality` optionally attaches such a rubric to a newly versioned
dataset. Unlabeled cases have a null quality result and do not enter its denominator.
Rubric failures also fail E2E on labeled cases. Adding a rubric changes the dataset
hash; absent rubrics preserve legacy hashes exactly. Run the deterministic controls
with `uv --cache-dir .uv-cache run pytest tests/test_eval_platform.py -p no:cacheprovider`.
