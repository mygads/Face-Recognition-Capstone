#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly REPOSITORY="https://github.com/mygads/Face-Recognition-Capstone.git"
readonly INSTALL_REF="${PRESENSI_INSTALL_REF:-main}"
readonly INSTALL_ROOT="${PRESENSI_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/presensi-camera-agent}"
USE_WORKING_COPY=0
INPUT_BUNDLE_PATH="${PRESENSI_DEVICE_SETUP_BUNDLE:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --use-working-copy) USE_WORKING_COPY=1; shift ;;
    --bundle)
      [[ $# -ge 2 ]] || { echo '--bundle requires a setup JSON path.' >&2; exit 2; }
      INPUT_BUNDLE_PATH="$2"
      shift 2
      ;;
    *) echo 'Usage: bootstrap-camera-device.sh [--use-working-copy] [--bundle setup.json]' >&2; exit 2 ;;
  esac
done
if [[ "$USE_WORKING_COPY" -eq 1 ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  [[ -f "$ROOT/scripts/install-camera-device.sh" ]] \
    || { echo 'Jalankan local bootstrap dari checkout repository.' >&2; exit 2; }
  SOURCE_DIR="$ROOT"
else
  SOURCE_DIR="$INSTALL_ROOT/source"
fi
AUTH_CONFIG=""
SETUP_BUNDLE=""
TOKEN=""

cleanup() {
  [[ -z "$AUTH_CONFIG" ]] || rm -f -- "$AUTH_CONFIG"
  [[ -z "$SETUP_BUNDLE" ]] || rm -f -- "$SETUP_BUNDLE"
  TOKEN=""
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
  echo "Setup gagal: $1" >&2
  exit 2
}

if [[ "$EUID" -eq 0 ]]; then
  fail "jalankan sebagai user biasa yang memiliki sudo, bukan sebagai root."
fi
if ! command -v curl >/dev/null 2>&1; then
  command -v sudo >/dev/null 2>&1 || fail "curl belum terpasang dan sudo tidak tersedia."
  sudo apt-get update
  sudo apt-get install -y curl
fi
command -v curl >/dev/null 2>&1 || fail "curl belum tersedia setelah instalasi apt."
if ! command -v python3 >/dev/null 2>&1; then
  command -v sudo >/dev/null 2>&1 || fail "python3 belum terpasang dan sudo tidak tersedia."
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip
fi
command -v python3 >/dev/null 2>&1 || fail "python3 belum tersedia setelah instalasi."

PROFILE=""
CENTRAL_AI_URL=""
MODEL_VERSION=""
if [[ -n "$INPUT_BUNDLE_PATH" ]]; then
  [[ -f "$INPUT_BUNDLE_PATH" ]] || fail "file setup bundle tidak ditemukan: $INPUT_BUNDLE_PATH"
  BUNDLE_VALUES="$(python3 - "$INPUT_BUNDLE_PATH" <<'PY'
import json
import re
import sys
import uuid
from urllib.parse import urlsplit

def origin(value, name, required):
    if value in (None, ""):
        if required:
            raise SystemExit(f"{name} tidak ada pada setup bundle.")
        return ""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if not loopback:
        try:
            import ipaddress
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    if (parsed.scheme not in {"http", "https"} or
        (parsed.scheme == "http" and not loopback) or not host or
        parsed.username or parsed.password or parsed.path not in {"", "/"} or
        parsed.query or parsed.fragment):
        raise SystemExit(f"{name} harus berupa origin HTTPS (HTTP hanya localhost).")
    return f"{parsed.scheme}://{parsed.netloc}"

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        data = json.load(source)
    if data.get("schema_version") != 1:
        raise ValueError("versi setup bundle tidak didukung")
    device_id = str(uuid.UUID(str(data.get("device_id"))))
    profile = data.get("deployment_profile")
    if profile not in {"AI_EDGE", "STB_GATEWAY"}:
        raise ValueError("profile device tidak valid")
    token = data.get("token")
    if not isinstance(token, str) or len(token) < 40 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("credential device tidak valid")
    api_url = origin(data.get("core_api_url"), "Core API", True)
    ai_url = origin(data.get("central_ai_url"), "AI Central", profile == "STB_GATEWAY")
    model_version = data.get("model_version") or ""
    if profile == "AI_EDGE" and (not isinstance(model_version, str) or not model_version or len(model_version) > 128):
        raise ValueError("versi model AI_EDGE tidak valid")
except (OSError, json.JSONDecodeError, ValueError) as error:
    raise SystemExit(f"Setup bundle tidak valid: {error}")

for field in (api_url, device_id, profile, ai_url, model_version, token):
    print(field)
PY
  )" || fail "setup bundle tidak valid."
  mapfile -t BUNDLE_FIELDS <<< "$BUNDLE_VALUES"
  CORE_API_URL="${BUNDLE_FIELDS[0]:-}"
  DEVICE_ID="${BUNDLE_FIELDS[1]:-}"
  PROFILE="${BUNDLE_FIELDS[2]:-}"
  CENTRAL_AI_URL="${BUNDLE_FIELDS[3]:-}"
  MODEL_VERSION="${BUNDLE_FIELDS[4]:-}"
  TOKEN="${BUNDLE_FIELDS[5]:-}"
  unset BUNDLE_VALUES BUNDLE_FIELDS
  if [[ -n "${PRESENSI_CORE_API_URL:-}" && "$PRESENSI_CORE_API_URL" != "$CORE_API_URL" ]]; then
    fail "URL Core API pada command tidak cocok dengan setup bundle."
  fi
  if [[ -n "${PRESENSI_CENTRAL_AI_URL:-}" && "$PRESENSI_CENTRAL_AI_URL" != "$CENTRAL_AI_URL" ]]; then
    fail "URL AI Central pada command tidak cocok dengan setup bundle."
  fi
  if [[ -n "${PRESENSI_MODEL_VERSION:-}" && "$PRESENSI_MODEL_VERSION" != "$MODEL_VERSION" ]]; then
    fail "Versi model pada command tidak cocok dengan setup bundle."
  fi
else
  CORE_API_INPUT="${PRESENSI_CORE_API_URL:-}"
  if [[ -z "$CORE_API_INPUT" ]]; then
    read -r -p 'URL origin Core API (contoh https://presensi.sekolah.id): ' CORE_API_INPUT </dev/tty
  fi
  CORE_API_URL="$(python3 -c '
import sys
from urllib.parse import urlsplit
value = sys.argv[1].strip()
parsed = urlsplit(value)
local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
if (not (parsed.scheme == "https" or local_http) or not parsed.hostname or parsed.username or
        parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
    raise SystemExit("Gunakan origin HTTPS; HTTP hanya diizinkan untuk loopback lokal.")
print(f"{parsed.scheme}://{parsed.netloc}")
' "$CORE_API_INPUT")" || fail "URL Core API tidak valid."

  read -r -s -p 'Kredensial bootstrap (UUID:token) dari halaman Perangkat: ' SETUP_CREDENTIAL </dev/tty
  printf '\n'
  if [[ "$SETUP_CREDENTIAL" != *:* ]]; then
    fail "format harus UUID:token; salin dari tombol kredensial installer."
  fi
  DEVICE_ID="${SETUP_CREDENTIAL%%:*}"
  TOKEN="${SETUP_CREDENTIAL#*:}"
  SETUP_CREDENTIAL=""
  DEVICE_ID="$(python3 -c 'import sys,uuid; print(uuid.UUID(sys.argv[1]))' "$DEVICE_ID")" \
    || fail "UUID perangkat tidak valid."
fi
if [[ -n "${PRESENSI_DEVICE_ID:-}" && "$(python3 -c 'import sys,uuid; print(uuid.UUID(sys.argv[1]))' "$PRESENSI_DEVICE_ID")" != "$DEVICE_ID" ]]; then
  fail "Token tidak cocok dengan UUID perangkat pada command."
fi
[[ ${#TOKEN} -ge 40 && "$TOKEN" =~ ^[A-Za-z0-9_-]+$ ]] \
  || fail "token perangkat tidak valid."

# curl reads Authorization from a mode-0600 file, not its command line or URL.
AUTH_CONFIG="$(mktemp "${TMPDIR:-/tmp}/presensi-auth.XXXXXX")"
chmod 600 "$AUTH_CONFIG"
printf 'header = "Authorization: Bearer %s"\nheader = "X-Device-ID: %s"\n' \
  "$TOKEN" "$DEVICE_ID" > "$AUTH_CONFIG"
echo 'Memvalidasi kredensial dan membaca profile perangkat dari Core API...'
STATUS_JSON="$(curl --fail --silent --show-error --config "$AUTH_CONFIG" \
  "$CORE_API_URL/api/v1/devices/$DEVICE_ID/device-status")" \
  || fail "API menolak kredensial atau tidak dapat dijangkau. Periksa URL/token atau rotasi token di UI."
rm -f -- "$AUTH_CONFIG"
AUTH_CONFIG=""
STATUS_PROFILE="$(printf '%s' "$STATUS_JSON" | python3 -c '
import json,sys
data = json.load(sys.stdin)
expected = sys.argv[1]
if data.get("device_id", "").lower() != expected.lower():
    raise SystemExit("API mengembalikan identitas perangkat yang berbeda.")
profile = data.get("deployment_profile")
if profile not in ("AI_EDGE", "STB_GATEWAY"):
    raise SystemExit("Profile perangkat tidak dikenal.")
print(profile)
' "$DEVICE_ID")" || fail "respons profile perangkat dari API tidak valid."

if [[ -z "$PROFILE" ]]; then
  if [[ "$STATUS_PROFILE" == "STB_GATEWAY" ]]; then
    CENTRAL_AI_INPUT="${PRESENSI_CENTRAL_AI_URL:-}"
    if [[ -z "$CENTRAL_AI_INPUT" ]]; then
      read -r -p 'URL origin AI Central yang dapat dijangkau STB: ' CENTRAL_AI_INPUT </dev/tty
    fi
    CENTRAL_AI_URL="$(python3 -c '
import sys
from urllib.parse import urlsplit
value = sys.argv[1].strip()
parsed = urlsplit(value)
local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
if (not (parsed.scheme == "https" or local_http) or not parsed.hostname or parsed.username or
        parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
    raise SystemExit("Gunakan origin HTTPS; HTTP hanya untuk AI Central loopback lokal.")
print(f"{parsed.scheme}://{parsed.netloc}")
' "$CENTRAL_AI_INPUT")" || fail "URL AI Central tidak valid."
  else
    MODEL_VERSION="${PRESENSI_MODEL_VERSION:-}"
    if [[ -z "$MODEL_VERSION" ]]; then
      read -r -p 'Versi model template (default opencv-zoo-sface-2021dec): ' MODEL_VERSION </dev/tty
    fi
    MODEL_VERSION="${MODEL_VERSION:-opencv-zoo-sface-2021dec}"
  fi
elif [[ "$PROFILE" != "$STATUS_PROFILE" ]]; then
  fail "profile pada bundle tidak cocok dengan profile registry."
fi
PROFILE="$STATUS_PROFILE"

if [[ "$USE_WORKING_COPY" -eq 0 ]] && ! command -v git >/dev/null 2>&1; then
  command -v sudo >/dev/null 2>&1 || fail "git belum terpasang dan sudo tidak tersedia."
  sudo apt-get update
  sudo apt-get install -y git
fi

if [[ "$USE_WORKING_COPY" -eq 0 ]]; then
  mkdir -p "$(dirname "$SOURCE_DIR")"
  if [[ -e "$SOURCE_DIR" ]]; then
    [[ -d "$SOURCE_DIR/.git" ]] || fail "$SOURCE_DIR sudah ada dan bukan checkout repository."
    [[ -z "$(git -C "$SOURCE_DIR" status --porcelain)" ]] \
      || fail "checkout di $SOURCE_DIR memiliki perubahan lokal; simpan/pindahkan dulu."
    git -C "$SOURCE_DIR" fetch --depth 1 origin "$INSTALL_REF"
    git -C "$SOURCE_DIR" checkout --detach FETCH_HEAD
  else
    git clone --depth 1 --branch "$INSTALL_REF" "$REPOSITORY" "$SOURCE_DIR"
  fi
fi

SETUP_BUNDLE="$(mktemp "${TMPDIR:-/tmp}/presensi-setup.XXXXXX.json")"
printf '%s\0' "$DEVICE_ID" "$PROFILE" "$CORE_API_URL" \
  "$CENTRAL_AI_URL" "$MODEL_VERSION" "$TOKEN" | \
  python3 -c '
import json,sys
device_id,profile,api_url,ai_url,model_version,token = [
    item.decode("utf-8") for item in sys.stdin.buffer.read().split(b"\0")[:-1]
]
bundle = {
    "schema_version": 1,
    "device_id": device_id,
    "deployment_profile": profile,
    "core_api_url": api_url,
    "central_ai_url": ai_url or None,
    "model_version": model_version or None,
    "token": token,
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(bundle, stream)
' "$SETUP_BUNDLE"
unset TOKEN

echo "Profile dari registry: $PROFILE"
echo 'Menginstal dependency, menulis token/config terlindungi, memeriksa kamera, lalu menawarkan menjalankan agent.'
bash "$SOURCE_DIR/scripts/install-camera-device.sh" "$SETUP_BUNDLE" </dev/tty
