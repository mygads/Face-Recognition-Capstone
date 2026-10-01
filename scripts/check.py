from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, label: str) -> int:
    print(f"\n== {label} ==", flush=True)
    print("+ " + " ".join(command), flush=True)
    if os.name == "nt" and command[0] == "npm":
        command = ["cmd.exe", "/d", "/s", "/c", " ".join(command)]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    checks = [
        ([sys.executable, "-m", "ruff", "check", "."], "Python lint (Ruff)"),
        (
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            "Python format (Ruff)",
        ),
        ([sys.executable, "-m", "mypy"], "Python type check (mypy)"),
        ([sys.executable, "-m", "pytest"], "Python unit tests (pytest)"),
        (["npm", "--prefix", "apps/web", "run", "lint"], "Frontend lint (ESLint)"),
        (
            ["npm", "--prefix", "apps/web", "run", "format:check"],
            "Frontend format (Prettier)",
        ),
        (
            ["npm", "--prefix", "apps/web", "run", "typecheck"],
            "Frontend type check (TypeScript)",
        ),
        (
            ["npm", "--prefix", "apps/web", "run", "typecheck:e2e"],
            "E2E type check (TypeScript)",
        ),
        (
            ["npm", "--prefix", "apps/web", "run", "test:unit"],
            "Frontend unit tests (Vitest)",
        ),
    ]
    for command, label in checks:
        if run(command, label=label) != 0:
            return 1
    print("\nAll lint, type-check, and unit-test checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
