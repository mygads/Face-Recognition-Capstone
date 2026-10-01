# End-to-end tests

Web browser smoke tests live in `apps/web/e2e/` and run with `npm --prefix apps/web run test:e2e`.

The synthetic school-day API regression flow lives in
`apps/api/tests/test_school_day_regression.py`. It drives the FastAPI app through
student import, enrollment, session open, mocked recognition decisions,
correction audit, session close, and report export. It uses an in-memory SQLite
database and a deterministic fake enrollment processor; it does not start a
camera, load a face model, or use real student data.

Run the full API regression suite from the repository root with:

```sh
python scripts/regression.py
```

This runs the dedicated API regression test. Install the Python development
requirements first (`python -m pip install -r requirements-dev.txt`). The
repository-wide `python scripts/check.py` command also runs it with the full
API pytest suite in CI.

Keep E2E fixtures synthetic. Do not load or commit real student biometric data.
