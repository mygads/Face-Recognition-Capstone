#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_PATH="${1:-}"

if [[ -z "$BUNDLE_PATH" ]]; then
  read -r -p 'Path to presensi-device-setup.json: ' BUNDLE_PATH
fi
if [[ ! -f "$BUNDLE_PATH" ]]; then
  echo "Setup bundle not found: $BUNDLE_PATH" >&2
  exit 2
fi
BUNDLE_PATH="$(cd "$(dirname "$BUNDLE_PATH")" && pwd)/$(basename "$BUNDLE_PATH")"

if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.11 or newer is required. Install Python 3 before continuing.' >&2
  exit 2
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")
PY

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["deployment_profile"])' "$BUNDLE_PATH")"
case "$PROFILE" in
  AI_EDGE)
    CONFIG_PATH="$ROOT/apps/edge-agent/config/edge-agent.yaml"
    VENV_PATH="$ROOT/.venv-edge-agent"
    INSTALL_ARGS=(-e "$ROOT/apps/edge-agent[camera]" -e "$ROOT/libs/recognition-core[opencv]")
    VENV_ARGS=()
    ;;
  STB_GATEWAY)
    CONFIG_PATH="$ROOT/apps/edge-agent/config/stb-gateway.yaml"
    VENV_PATH="$ROOT/.venv-edge-agent"
    if [[ "$(uname -m)" == "aarch64" || "$(uname -m)" == "arm64" ]]; then
      if ! command -v apt-get >/dev/null 2>&1; then
        echo 'ARM64 STB setup expects Debian/Armbian with apt-get.' >&2
        exit 2
      fi
      if [[ "$EUID" -eq 0 ]]; then
        apt-get update
        apt-get install -y python3-venv python3-pip python3-opencv python3-numpy python3-yaml v4l-utils
      elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3-venv python3-pip python3-opencv python3-numpy python3-yaml v4l-utils
      else
        echo 'Install python3-opencv, python3-numpy, python3-yaml, v4l-utils, and python3-venv first.' >&2
        exit 2
      fi
      VENV_ARGS=(--system-site-packages)
      INSTALL_ARGS=(-e "$ROOT/apps/edge-agent")
    else
      INSTALL_ARGS=(-e "$ROOT/apps/edge-agent[camera]")
      VENV_ARGS=()
    fi
    ;;
  *)
    echo 'Setup bundle has an unknown deployment profile.' >&2
    exit 2
    ;;
esac

if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  python3 -m venv "${VENV_ARGS[@]}" "$VENV_PATH"
fi
"$VENV_PATH/bin/python" -m pip install "${INSTALL_ARGS[@]}"

DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/presensi-edge-agent"
STATE_DIR="$DATA_ROOT/state"
mkdir -p "$DATA_ROOT" "$STATE_DIR"
chmod 700 "$DATA_ROOT" "$STATE_DIR"
TOKEN_PATH="$DATA_ROOT/device.token"
REPLACE_ARGS=()
if [[ -f "$TOKEN_PATH" ]]; then
  read -r -p 'A token file exists. Replace it with the token in this setup bundle? [y/N] ' ANSWER
  case "$ANSWER" in
    y|Y|yes|YES) REPLACE_ARGS=(--replace-token) ;;
    *) echo 'Setup cancelled. The existing token file was left unchanged.' >&2; exit 2 ;;
  esac
fi

"$VENV_PATH/bin/python" "$ROOT/scripts/apply_device_setup.py" \
  --bundle "$BUNDLE_PATH" \
  --config "$CONFIG_PATH" \
  --token-file "$TOKEN_PATH" \
  --state-dir "$STATE_DIR" \
  "${REPLACE_ARGS[@]}"
chmod 600 "$TOKEN_PATH"

if [[ "$PROFILE" == "AI_EDGE" ]]; then
  echo 'Provisioning checksum-verified YuNet/SFace models for AI_EDGE...'
  echo 'SFace is for evaluation; obtain school/institutional license clearance before operational use.'
  "$VENV_PATH/bin/python" "$ROOT/scripts/download_face_models.py"
fi

AGENT="$VENV_PATH/bin/presensi-edge-agent"
echo
read -r -p 'Run interactive camera setup now (camera, resolution, FPS)? [Y/n] ' CONFIGURE_CAMERA
case "$CONFIGURE_CAMERA" in
  n|N|no|NO) echo "Camera setup skipped. Run later: $AGENT --config $CONFIG_PATH configure-camera" ;;
  *)
    set +e
    "$AGENT" --config "$CONFIG_PATH" configure-camera
    CAMERA_SETUP_STATUS=$?
    set -e
    if [[ "$CAMERA_SETUP_STATUS" -ne 0 ]]; then
      echo 'Camera setup did not complete. Check UVC permission and close other camera apps.' >&2
      echo "Run later: $AGENT --config $CONFIG_PATH configure-camera"
    fi
    ;;
esac

echo
echo 'Checking camera indexes. Close enrollment and camera preview apps first.'
set +e
"$AGENT" --config "$CONFIG_PATH" cameras
CAMERA_STATUS=$?
"$AGENT" --config "$CONFIG_PATH" status
RUNTIME_STATUS=$?
set -e
if [[ "$CAMERA_STATUS" -ne 0 ]]; then
  echo 'Camera discovery did not complete. Check UVC permissions and close other camera apps.' >&2
fi
echo
echo "Profile: $PROFILE"
echo "Config: $CONFIG_PATH"
echo "Protected token file: $TOKEN_PATH"
echo 'The setup bundle contains a device secret. Remove it from Downloads after verifying this device.'
if [[ "$PROFILE" == AI_EDGE ]]; then
  echo 'AI_EDGE requires local YuNet/SFace files and calibrated Top-1/margin thresholds before attendance can run.'
fi
if [[ "$RUNTIME_STATUS" -eq 0 ]]; then
  read -r -p 'Start the agent now in this terminal? [Y/n] ' START_NOW
  case "$START_NOW" in
    n|N|no|NO) echo "When ready: $AGENT --config $CONFIG_PATH run" ;;
    *)
      echo 'Agent is running. Press Ctrl+C to stop this commissioning run.'
      "$AGENT" --config "$CONFIG_PATH" run
      ;;
  esac
else
  echo 'Resolve the status output above before starting the attendance agent.'
  echo "When readiness is green: $AGENT --config $CONFIG_PATH run"
fi
