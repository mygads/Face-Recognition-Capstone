from __future__ import annotations

import argparse
import base64
import os
import secrets
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def ensure_env_file() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        print("Created .env from .env.example (local development values).")
    env_text = ENV_FILE.read_text(encoding="utf-8")
    lines = env_text.splitlines()
    secret_factories: dict[str, Callable[[], str]] = {
        "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
        "JWT_SECRET": lambda: secrets.token_hex(32),
        "PRESENSI_FACE_TEMPLATE_KEYS": lambda: (
            '{"local-v1":"' + base64.b64encode(secrets.token_bytes(32)).decode() + '"}'
        ),
    }
    generated = False
    for key, create_secret in secret_factories.items():
        for index, line in enumerate(lines):
            if line.startswith(f"{key}="):
                if not line.partition("=")[2].strip():
                    lines[index] = f"{key}={create_secret()}"
                    generated = True
                break
        else:
            lines.append(f"{key}={create_secret()}")
            generated = True
    if generated:
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Generated local database/auth secrets in the ignored .env file.")


def run(command: list[str]) -> int:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def run_web_build() -> int:
    if os.name == "nt":
        return run(["cmd.exe", "/d", "/s", "/c", "npm --prefix apps/web run build"])
    return run(["npm", "--prefix", "apps/web", "run", "build"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Local development task runner")
    parser.add_argument("task", choices=("dev-up", "dev-down", "test"))
    parser.add_argument(
        "--central", action="store_true", help="also start the central AI service"
    )
    parser.add_argument(
        "--web-container",
        action="store_true",
        help="run the optional web HMR container",
    )
    args = parser.parse_args()

    ensure_env_file()
    if args.task == "dev-up":
        command = ["docker", "compose"]
        if args.central:
            command.extend(("--profile", "central"))
        if args.web_container:
            command.extend(("--profile", "web-container"))
        command.extend(("up", "--build", "--detach"))
        if run(command) != 0:
            return 1

        setup_commands = [
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "api",
                "alembic",
                "upgrade",
                "head",
            ],
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "api",
                "python",
                "-m",
                "presensi_api.db.seed_roles",
            ],
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "api",
                "python",
                "-m",
                "presensi_api.auth.bootstrap_admin",
            ],
        ]
        for setup_command in setup_commands:
            if run(setup_command) != 0:
                return 1
        return 0

    if args.task == "dev-down":
        return run(
            [
                "docker",
                "compose",
                "--profile",
                "central",
                "--profile",
                "web-container",
                "down",
            ]
        )

    commands = [
        ["docker", "compose", "config", "--quiet"],
    ]
    if run(commands[0]) != 0:
        return 1
    if run_web_build() != 0:
        return 1

    api_test = [
        "docker",
        "compose",
        "run",
        "--build",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "-m",
        "pytest",
        "-q",
        "/service/tests",
    ]
    if run(api_test) != 0:
        return 1

    ai_test = [
        "docker",
        "compose",
        "--profile",
        "central",
        "run",
        "--build",
        "--rm",
        "--no-deps",
        "ai-service",
        "python",
        "-m",
        "pytest",
        "-q",
        "/service/tests",
    ]
    return run(ai_test)


if __name__ == "__main__":
    sys.exit(main())
