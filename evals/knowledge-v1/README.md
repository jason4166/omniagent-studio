# Expanded knowledge coverage v1

This independent set contains 24 original Chinese policy questions, eight per
Profile. Each Profile has four dev and four test cases. Source labels and answer
rubrics cover payroll, benefits, attendance, onboarding, learning support,
product selection and care, troubleshooting, shipping and returns, customer
follow-up, quotations and discount approval. All questions, labels and policy
documents are original synthetic data licensed under CC0-1.0.

Run natural-language quality checks with the configured real chat and embedding
providers on an isolated real-mode evaluation database:

```powershell
uv run omniagent eval-real --dataset evals/knowledge-v1/cases.json --output .pytest-tmp-knowledge-v1
```

This consumes provider requests. The existing evaluation runner records the
dataset hash, Profile/Prompt/KB/model/tool/Git versions, per-case results, answer
rubric checks and safety gates. The questions are passed unchanged to the Runtime;
the answer rubrics are never included in model prompts. A passing small fixed set
does not establish general conversational accuracy. This set expands policy
coverage; it does not replace the frozen v1–v3 workflows or adversarial datasets.
Publish measured results only after a run, including any failures.

`retrieval-contracts.json` serves a different purpose: it contains literal body
phrases for database contracts. `tests/test_knowledge_coverage.py` imports all
presets into PostgreSQL, checks the corresponding full-text Top5 source, verifies
that the citation's character range locates the stored content, checks KB scoping,
and compares source/chunk identities and creation times across repeated seeding.
These contracts use FakeEmbedding only to construct the repository; full-text
search does not depend on those hash vectors. They **do not measure Chinese
semantic retrieval** or substitute for the real-provider natural-language run.

```powershell
uv run pytest tests/test_knowledge_coverage.py
```

Set `OMNIAGENT_TEST_DATABASE_URL` to a migrated disposable PostgreSQL database for
the contracts. The tests do not send external requests or execute business writes.
Preserve this version and its labels after publication; corrections belong in a
new dataset version with the reason recorded.
