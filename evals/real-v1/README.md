# Live natural-language evaluation v1

24 original synthetic Chinese requests: 8 per Profile, 12 dev and 12 held-out test.
The dataset was frozen before the first full live run. The 66-case offline suite remains
the mandatory CI engineering gate. These datasets measure different things and are
never averaged together.

Run `python scripts/ops.py eval-real --mode real` on an isolated real deployment.
This invokes paid chat and embedding APIs. Each case uses the public API and the same
Runtime as the UI; HTTP/MCP business records are local synthetic fixtures. Only the
explicitly labeled approve/edit cases execute sandbox writes. Approval decisions are
replayed and their tool usage must remain unchanged. Owned test sessions are deleted.

Every run records dataset, Profile, Prompt, tool, embedding, retriever, lockfile and Git
identities. Requested model names and vendor-reported aliases are both visible; cloud
weights and network latency cannot be frozen locally. All samples, including failures,
remain in the report. Dev results can inform fixes; do not relabel held-out cases to
make a candidate pass. A rerun of the same corpus is repeatability evidence, not another
independent dataset.

E2E success requires the expected route, outcome, tool transport, exact business
arguments, valid citations and supported claims where applicable. Edits must appear
in the executed arguments. Missing business values require clarification. Security
gates independently require zero unauthorized writes, foreign-KB exposure and recognized
attack success. Additional transport, injection and fault cases run in the offline
security suite. Passing this finite corpus does not establish universal attack resistance.

Chat tokens and embedding tokens are actual usage returned by each API and are shown
separately. Missing usage is unknown; prices are unknown until an operator supplies a
versioned price table. No paid API credential is stored in this dataset or report.

License: CC0-1.0 for the original synthetic questions and seeded knowledge text.
