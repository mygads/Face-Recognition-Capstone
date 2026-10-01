# Tests

Unit and API regression tests live beside their owning application/package. The synthetic school-day API regression runs with `python scripts/regression.py`; browser smoke tests live in `apps/web/e2e/` and run with `npm --prefix apps/web run test:e2e`.

Use synthetic or legally approved adult-volunteer fixtures only; never commit real student biometric data.
