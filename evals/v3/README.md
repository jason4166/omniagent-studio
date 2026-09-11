# E2E v3 — public conversation and business evidence

This version contains 78 synthetic workflow cases: 39 dev and 39 test.
It copies all 72 v2 cases, changes only `hr-13` (`你好`) from
`retrieve`/`abstain` to `direct`/`conversation`, and adds six public-help cases.
The other 71 cases are unchanged, including the `hr-08` answer expectation;
an observed business-answer failure is not relabeled as success.

The seven conversation cases comprise a Chinese greeting for each Profile
(dev), a capability question for each Profile (test), and sales viewer help
(dev). In the real runtime, the routing model identifies the semantic intent;
the server renders the public response using the authorized Profile and tools.
Fake uses deterministic fixtures for this routing contract. These examples are
regression inputs, not a production utterance allowlist or a general dialogue benchmark.

`conversation` requires a successful result with both `route=direct` and the
server-provided `response_kind=conversation`. Unmarked direct responses do not
receive this classification. Business `answer` cases still require valid
citations and supported claims. Conversation cases are excluded from the
business E2E, business answer-rubric and abstention denominators; the report
includes separate conversation E2E and rubric rates. Actual model calls and
tokens remain recorded. The combined 78-case E2E rate is a workflow measure,
not model answer accuracy.

The predeclared rubrics require a Chinese greeting, the relevant public
capabilities and human approval for sales writes. Sales viewers may see sales
and discount policy help, but must not be offered customer lookup, follow-up
creation or discount submission. Forbidden claims also reject selected policy
fact dumps. The labels are authored in this dataset; the scorer neither imports
the runtime capability helper nor derives its oracle from generated answers.
These bounded regex checks are not a semantic judge: they can reject an unseen
valid phrasing, including some explicit descriptions of unavailable operations,
or miss an unlisted overclaim. Independent positive/negative examples exercise
the labels in `tests/test_eval_platform.py` and are not extra E2E cases.

Default command: `uv run omniagent eval --output .pytest-tmp-eval-v3`.
Historical datasets remain runnable with an explicit `--dataset`, for example
`--dataset evals/v2/cases.json`, and a separate output directory. Old labels and
published results remain frozen; running old labels against the new conversation
contract can correctly produce a changed result for `hr-13`.

This dataset contains expectations, not newly observed results. Freeze it before
the candidate evaluation and compare only matching dataset hashes and recorded
measurement conditions. The scorer protocol is `workflow-metrics-v4-conversation`.

License: synthetic fixtures and labels, CC0-1.0.
