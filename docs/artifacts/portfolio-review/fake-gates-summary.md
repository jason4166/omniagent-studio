# Clean Fake acceptance

Source commit: `c7769fa1f31cfe324d01da4e79cad7de0cf99b68`.

Overall status: **pass**.

| Gate | Result |
| --- | --- |
| fresh_volume | pass |
| source_clean | pass |
| acceptance | pass |
| backend | pass |
| frontend | pass |
| evaluation | pass |
| evaluation_repeatability | pass |
| benchmark | pass |
| security | pass |
| image | pass |
| browser | pass |

Backend: 738 tests, zero skips, 88.01% line coverage. Frontend: 22 tests. Browser: 5 flows, zero skips.

Evaluation: two independent runs of 72 versioned cases; each retains the known hr-08 safe abstention (71/72 success). Benchmarks: three independent runs of the same source revision; comparison is repeatability.

Initial clean acceptance found 3 packaging/line-ending failures on 4541e57. Their original reports were preserved, then the fixed revision was tested again.

Commands and denominator details are in the adjacent JSON. Raw private artifacts are not included.

Fake model and embeddings; this summary contains no live-provider evidence.
Three runs share one source revision. Timing differences describe repeatability, not optimization.
Passing bounded synthetic security cases and pattern scans does not certify universal security.
Raw traces, credentials, logs and local host metadata remain excluded from publication.
