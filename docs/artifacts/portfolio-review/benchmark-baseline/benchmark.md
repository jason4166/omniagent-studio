# Fake benchmark — baseline

new HR thread -> one grounded leave query; serial in-process TestClient; two warmups; cache disabled

successful message POST only; excludes creation, cleanup, HTTP server transport, browser and human waits; not a concurrent load test

- Gate passed: True
- Measured attempts / successes / failures: 20 / 20 / 0
- Error rate: 0.0 (denominator 20)
- Warmup failures: 0
- Environment error: None
- Successful message POST P50 / P95: 267.6051895005003 / 366.8070680003894 ms (20 samples)
- Mean database queries / ms: 131 / 62.04399435 (20 samples)
- Observed model calls / Fake byte tokens: 40 / 123720
- Attempts with observed usage: 20

The JSON preserves failed attempts and cleanup failures without exception bodies. Warmups do not enter the measured error-rate denominator. No measured attempts means an unknown rate, not zero. Legacy p50_ms/p95_ms are compatibility aliases for the successful message POST distribution. Local observations do not establish an SLA.
