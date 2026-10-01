# End-to-end tests

Web browser smoke tests live in `apps/web/e2e/` and run with `npm --prefix apps/web run test:e2e`.
Cross-service browser workflows can be added here when those features exist.

Keep E2E fixtures synthetic. Do not load or commit real student biometric data.
