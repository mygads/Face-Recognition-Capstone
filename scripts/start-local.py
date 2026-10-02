from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"


def run(command: list[str], *, cwd: Path = ROOT) -> int:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def npm_command(*arguments: str) -> list[str]:
    command = "npm " + " ".join(arguments)
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["npm", *arguments]


def ensure_web_dependencies() -> bool:
    node_modules = WEB_ROOT / "node_modules"
    installed_lock = node_modules / ".package-lock.json"
    lock_file = WEB_ROOT / "package-lock.json"
    dependencies_are_current = (
        node_modules.is_dir()
        and installed_lock.is_file()
        and installed_lock.stat().st_mtime >= lock_file.stat().st_mtime
    )
    if dependencies_are_current:
        print("Web dependencies are already installed.")
        return True
    return run(npm_command("--prefix", "apps/web", "ci")) == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the local Presensi development stack and Vue web app."
    )
    parser.add_argument(
        "--central",
        action="store_true",
        help="also start the optional AI_CENTRAL service",
    )
    args = parser.parse_args()

    missing = [tool for tool in ("docker", "node", "npm") if shutil.which(tool) is None]
    if missing:
        print(
            "Missing host tools: "
            + ", ".join(missing)
            + ". Install Docker Desktop/Engine with Compose, Node.js 22 or 24, "
            "and npm first.",
            file=sys.stderr,
        )
        return 2

    print(
        "Starting local PostgreSQL and FastAPI, applying migrations, then "
        "starting Vue Vite."
    )
    dev_command = [sys.executable, "scripts/dev.py", "dev-up"]
    if args.central:
        dev_command.append("--central")
        print("AI_CENTRAL is enabled for the STB_GATEWAY development profile.")
    if run(dev_command) != 0:
        return 1
    if not ensure_web_dependencies():
        print(
            "Web dependency installation failed. PostgreSQL and API may still "
            "be running."
        )
        return 1

    print("Open http://127.0.0.1:5173. Press Ctrl+C to stop Vite.")
    stop_command = (
        "py -3 scripts/dev.py dev-down"
        if os.name == "nt"
        else "python3 scripts/dev.py dev-down"
    )
    print(f"Stop the API and database later with: {stop_command}")
    try:
        return run(npm_command("--prefix", "apps/web", "run", "dev"))
    except KeyboardInterrupt:
        print("Vite stopped. PostgreSQL and API remain running.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
