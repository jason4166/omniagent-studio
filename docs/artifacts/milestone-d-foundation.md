# Milestone D foundation checkpoint

This local commit freezes the implementation before the measured optimization. Milestone D continues with a frozen baseline/candidate comparison; it is not the v1 release acceptance.

- Full backend with PostgreSQL, Fake and local mock: **559 passed**, **0 skipped**, **51.79 seconds**.
- Line coverage: **5,170 / 6,061 = 85.2994555353902%** from pytest-cov JSON.
- Ruff check and format: passed, **169 files**; mypy: passed, **78 source/entry files**; Git diff check: passed.
- Security command: **69 passed**, **0 skipped**, **10.71 seconds**; **16 versioned security cases**. Publishable worktree scan: **233 files**, reachable history: **300 blobs**, **0 findings**.
- Vue lint, format, TypeScript, build: passed; Vitest: **16 passed**; Chromium E2E: **4 passed**, **21.3 seconds**, no retries.
- The unified dataset contains **66 cases**, **33 dev / 33 test**, **22 per Profile**, including **23 attacks**. The 14-scenario fault manifest maps to executable backend/browser tests.

The source tree was verified after the changes in this commit. Exact test outputs are local ignored gate artifacts; the final D reports will lock this commit as the pre-optimization baseline. Secrets and the two protected untracked files are excluded from staging.

Real Provider probing is independent of Fake gates. The first three-query run exposed endpoint thinking-mode and extraction issues. Explicit compatible non-thinking mode improved it to **2/3 E2E**, with **3/3 route accuracy**, emitted citation/claim checks passing, and the HR answer rejected by grounding. This small sample is retained as a limitation and is not averaged into Fake quality. Real cost remains unknown. No production external business system was called.
