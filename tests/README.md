# Tests

Unit and API regression tests live beside their owning application/package. The synthetic school-day API regression runs with `python scripts/regression.py`; browser smoke tests live in `apps/web/e2e/` and run with `npm --prefix apps/web run test:e2e`.

Use synthetic or legally approved adult-volunteer fixtures only; never commit real student biometric data.

The AI_EDGE vs AI_CENTRAL hardware performance harness and its measurement
definitions are documented in `tests/deployment-benchmark/README.md`. Runs
without configured hardware/model/session inputs produce `PENDING HARDWARE` and
leave measured values empty.
