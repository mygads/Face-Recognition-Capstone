#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly REPOSITORY="https://github.com/mygads/Face-Recognition-Capstone.git"
readonly INSTALL_REF="${PRESENSI_INSTALL_REF:-main}"
readonly INSTALL_ROOT="${PRESENSI_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/presensi-camera-agent}"
USE_WORKING_COPY=0
if [[ "${1:-}" == "--use-working-copy" ]]; then
  USE_WORKING_COPY=1
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  [[ -f "$ROOT/scripts/install-camera-device.sh" ]] \
    || { echo 'Jalankan local bootstrap dari checkout repository.' >&2; exit 2; }
  SOURCE_DIR="$ROOT"
elif [[ $# -eq 0 ]]; then
  SOURCE_DIR="$INSTALL_ROOT/source"
else
  echo 'Usage: bootstrap-camera-device.sh [--use-working-copy]' >&2
  exit 2
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
command -v curl >/dev/null 2>&1 || fail "curl belum terpasang; jalankan dari Ubuntu/Armbian yang memiliki curl."
if ! command -v python3 >/dev/null 2>&1; then
  command -v sudo >/dev/null 2>&1 || fail "python3 belum terpasang dan sudo tidak tersedia."
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip
fi
command -v python3 >/dev/null 2>&1 || fail "python3 belum tersedia setelah instalasi."

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
PROFILE="$(printf '%s' "$STATUS_JSON" | python3 -c '
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

CENTRAL_AI_URL=""
MODEL_VERSION=""
if [[ "$PROFILE" == "STB_GATEWAY" ]]; then
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
