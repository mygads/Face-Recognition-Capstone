from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
LOCAL_AI_PROFILE_KEY = "PRESENSI_LOCAL_AI_PROFILE"


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


def read_local_ai_profile() -> str | None:
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == LOCAL_AI_PROFILE_KEY:
            profile = value.strip().lower()
            return profile if profile in {"edge", "central"} else None
    return None


def save_local_ai_profile(profile: str) -> None:
    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example.")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    replacement = f"{LOCAL_AI_PROFILE_KEY}={profile}"
    for index, line in enumerate(lines):
        key, separator, _value = line.partition("=")
        if separator and key.strip() == LOCAL_AI_PROFILE_KEY:
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def choose_local_ai_profile(requested: str | None) -> str:
    profile: str | None = requested
    if profile is None:
        profile = read_local_ai_profile()
        if profile is None and sys.stdin.isatty():
            print("Pilih service inference yang dijalankan di komputer ini:")
            print("  1. AI_EDGE  — Core API + web; inference berjalan di PC kamera")
            print("  2. AI_CENTRAL — Core API + web + AI service untuk gateway STB")
            choice = input("Pilih 1 atau 2 [1]: ").strip()
            if choice not in {"", "1", "2"}:
                raise ValueError("Pilihan harus 1 (AI_EDGE) atau 2 (AI_CENTRAL).")
            profile = "central" if choice == "2" else "edge"
        elif profile is None:
            profile = "edge"
            print("No terminal selection available; using AI_EDGE profile.")
    save_local_ai_profile(profile)
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the local Presensi development stack and Vue web app."
    )
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument(
        "--central",
        dest="profile",
        action="store_const",
        const="central",
        help="start the optional AI_CENTRAL service (same as --profile central)",
    )
    profile_group.add_argument(
        "--edge",
        dest="profile",
        action="store_const",
        const="edge",
        help="start Core API/web only; inference stays on AI_EDGE devices",
    )
    profile_group.add_argument(
        "--profile",
        choices=("edge", "central"),
        help="select which inference service to start locally",
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

    try:
        local_profile = choose_local_ai_profile(args.profile)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    print(
        "Starting local PostgreSQL and FastAPI, applying migrations, then "
        "starting Vue Vite."
    )
    dev_command = [sys.executable, "scripts/dev.py", "dev-up"]
    if local_profile == "central":
        dev_command.append("--central")
        print(
            "AI_CENTRAL is enabled for the STB_GATEWAY development profile. "
            "Inference stays unavailable until approved local models and calibrated "
            "thresholds are configured."
        )
    else:
        print("AI_CENTRAL is disabled; local AI_EDGE devices run inference themselves.")
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
