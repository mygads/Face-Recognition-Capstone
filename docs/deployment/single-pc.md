# Single-computer development and deployment

This guide covers a laptop/PC that runs the web app, Core API, PostgreSQL,
camera, and edge-agent. It is useful for development, local demonstrations,
and controlled commissioning. It is not high availability and does not replace
the school hardware/field acceptance process.

## Recommended layout

For the first full local camera path, use AI_EDGE:

| Part | Runs where | Why |
| --- | --- | --- |
| PostgreSQL | Docker | Repeatable local database; default Compose publishes it only on loopback. |
| Core API | Docker | Reuses the same API/domain code as both server deployments. |
| Vue web | Native Vite for development; static files behind Nginx for deployment | HMR is easier natively; deployment serves the built SPA. |
| Edge-agent and webcam | Native host process/service | Direct UVC access avoids Docker Desktop device passthrough differences. |
| AI service | Optional Docker central profile | Needed only to experiment with STB_GATEWAY + AI_CENTRAL on the same computer. |

The project does not configure the host webcam as a Compose device. Linux can
pass a device node to a container, but that mode is not the project's tested
default. On Windows, keep the camera process native. Do not run enrollment and
edge capture at the same time if the webcam driver only allows one application.

## Development: Windows and Ubuntu

### Host prerequisites

| Windows | Ubuntu |
| --- | --- |
| Docker Desktop using Linux containers and WSL2; Python 3.11+; Git; Node 22.22.2 or 24.15.0+; npm 10+ | Docker Engine with the Compose plugin; Python 3.11+; Git; Node 22.22.2 or 24.15.0+; npm 10+ |
| Allow desktop applications to access the camera in Windows Privacy settings. | Give the interactive user/service access to the camera device; check V4L2 permissions. |
| Use a terminal with access to the cloned repository. | Use a desktop session for the calibration preview; a headless session cannot open its GUI window. |

The repository declares its Node range in apps/web/package.json. Node 23 is
outside that range even if Vite happens to start. If changing the host Node
installation is inconvenient, the optional web container uses Node 24:

~~~powershell
py -3 scripts/dev.py dev-up --web-container
~~~

Use either native Vite or the web container on port 5173 at a time; stop the
existing Vite terminal before starting the container profile.

### Start database and Core API

From the repository root:

~~~powershell
# Windows PowerShell
py -3 scripts/dev.py dev-up
~~~

~~~bash
# Ubuntu
python3 scripts/dev.py dev-up
~~~

The task runner copies .env.example to .env if needed and fills blank local
database/JWT/encrypted-template secrets, applies migrations, seeds roles, and
creates a local administrator only when the user table is empty. Sign in as
`admin@local.test` with `123456789abcd` and change it at first sign-in. This
fixed password is for local development only; do not expose the development
stack before changing it. The .env file is ignored by Git. Keep
the local generated keyring with the database volume; losing it makes encrypted
templates in that volume unusable. These development secrets are not production
secrets.

The database persists in the named postgres-data volume. The API and database
host ports bind to loopback. Migration is explicit; API process health does not
mean that a migration has been run.

### Start web, create a local account, and check health

~~~sh
npm ci --prefix apps/web
npm --prefix apps/web run dev
~~~

Open http://127.0.0.1:5173. Check API health at
http://127.0.0.1:8000/health and the versioned endpoint at
http://127.0.0.1:8000/api/v1/health.

After first login, open **Kelola akun staf** in the left menu to create a
TEACHER or LABORANT account. The page shows the generated temporary password
once; share it directly with the account owner. They must set their own
password at first sign-in. Use only fictional master-data records and an adult
volunteer who agrees to a local camera test.

### Test the webcam and prepare recognition

The camera calibration utility shows camera FPS, YuNet face boxes, face pixel
size, blur/brightness proxies, and simple warnings. It never writes image
frames. Install it in a separate virtual environment because it uses desktop
OpenCV; the edge-agent uses headless OpenCV.

~~~powershell
# Windows PowerShell, from repository root
py -3 -m venv .venv-camera-calibration
./.venv-camera-calibration/Scripts/Activate.ps1
python -m pip install -e "apps/edge-agent[camera-preview]" -e "libs/recognition-core"
presensi-camera-calibration --list-cameras --scan-max-index 1
~~~

~~~bash
# Ubuntu, from repository root and a local graphical session
python3 -m venv .venv-camera-calibration
source .venv-camera-calibration/bin/activate
python -m pip install -e 'apps/edge-agent[camera-preview]' -e 'libs/recognition-core'
presensi-camera-calibration --list-cameras
~~~

Face boxes require a local YuNet model. From the repository root,
`python scripts/download_face_models.py` fetches the OpenCV Zoo pair and checks
their pinned SHA-256 values into the ignored `models/weights/` folder. SFace is
for local evaluation only until its weight provenance/license is reviewed. See
[model provenance](../models.md) and the [camera usage guide](../camera-usage.md).
The model weights are not committed or downloaded at application runtime:

- face_detection_yunet_2023mar.onnx
- face_recognition_sface_2021dec.onnx

Run the calibration preview with YuNet only. Close it with Q/Esc. Store the
optional aggregate JSON report outside the repository:

~~~powershell
presensi-camera-calibration --yunet-model C:/Presensi/models/face_detection_yunet_2023mar.onnx --duration-seconds 60 --report C:/Presensi/camera-calibration.json
~~~

Do not use a student/minor image as a calibration fixture. The displayed
brightness and FPS are diagnostic proxies, not lux or guaranteed capture FPS.

For backend enrollment, the Core API container sees weights at /models because
Compose mounts the model directory read-only. Set these non-secret .env values
after placing the files:

~~~dotenv
PRESENSI_AI_MODELS_DIR=./models/weights
PRESENSI_ENROLLMENT_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
PRESENSI_ENROLLMENT_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
PRESENSI_ENROLLMENT_MODEL_VERSION=opencv-zoo-sface-2021dec
~~~

Recreate the API container after changing Compose environment:

~~~sh
docker compose up -d --no-deps --force-recreate api
~~~

The host AI_EDGE config uses host-visible model paths instead of /models.
Use apps/edge-agent/config/edge-agent.example.yaml as a template; keep a
machine-specific config and device token out of Git. Recognition thresholds
min_top1_similarity and min_top1_top2_margin intentionally have no final
defaults. Calibrate and record them using the harness and approved local
conditions; do not copy a threshold from an article or another camera.

Follow [edge-agent setup](../../apps/edge-agent/README.md) to install the
headless runtime, register an AI_EDGE device, assign its laboratory, provision
its one-time credential from `/app/devices` into a protected token file, enroll
the adult demo identity, create a schedule, open an active session, and start the
agent. The backend will not create final attendance unless device, laboratory,
session, roster, model, liveness policy, grace period, and idempotency checks pass.

### Optional central-profile development on the same host

Run the development AI service only when explicitly testing AI_CENTRAL:

~~~powershell
# Windows
py -3 scripts/dev.py dev-up --central
~~~

~~~bash
# Ubuntu
python3 scripts/dev.py dev-up --central
~~~

Before starting it, set the central YuNet/SFace paths and model version in .env.
Both Top-1 and Top-1/Top-2 margin values must come from approved local
calibration; there are no production defaults. The camera-side process must use
STB_GATEWAY mode and send bursts to the service. A webcam on the same laptop is
only a developer simulation of the networked STB arrangement; it does not test
ARM64 performance, Armbian drivers, LAN latency, or STB thermals.

The AI service does not replace Core API attendance rules. STB_GATEWAY itself
does not run a face identity model.

### Stop development services

Stop the native Vite and edge-agent processes with Ctrl+C in their terminals.
Then stop Compose while preserving the PostgreSQL volume:

~~~powershell
py -3 scripts/dev.py dev-down
~~~

~~~bash
python3 scripts/dev.py dev-down
~~~

Do not use docker compose down -v unless you intentionally want to delete the
local database and all local template data.

## Deployment terbatas: satu host Ubuntu

For a lab demo that should survive reboot, Ubuntu is the recommended
single-host OS. Run PostgreSQL/Core API with the production AI_EDGE Compose
file, serve the Vue production build through Nginx, and install AI_EDGE as a
native systemd service on the same machine as the webcam:

~~~text
Web browser -> Nginx HTTPS -> Vue static files and /api routes
Nginx -> Core API on loopback -> PostgreSQL in private Docker network
UVC camera -> native systemd edge-agent -> Core API
~~~

The checked-in production AI_EDGE Compose file contains database, Core API, and
migration service; Nginx and edge-agent are installed/configured separately.
Use [the AI_EDGE production runbook](ai-edge.md) for model checksum, protected
environment, DB role, TLS, migration, backup/restore, upgrade, and rollback.
For one physical host, set the camera agent API base URL to the local trusted
HTTPS origin and keep the API listener private behind Nginx.

This is a controlled single-host installation, not a fault-tolerant
production cluster. A disk/host failure stops both inference and central data
services. Schedule off-host encrypted backups, protect the template keyring,
and verify restore before enrolling real data.

## Windows single-computer deployment boundary

Windows is covered for development and supervised demos. This repository does
not supply a hardened Windows production installer/service package for the
Core API, reverse proxy, backup/restore, and native camera worker. A service
wrapper such as NSSM/WinSW would still require an institution-managed service
account, ACLs, restart policy, TLS proxy, backup process, and field validation.
For routine school operation on one host, use the Ubuntu runbook. For
Windows lab PCs connecting to a VPS, see the Windows edge-agent notes in the
AI_EDGE runbook.

## Readiness gate before real attendance

- Provision the same reviewed YuNet/SFace versions used for enrollment and
  inference; check provenance and checksums.
- Calibrate Top-1, margin, quality, and duplicate warning behavior locally with
  consented, representative data. Review false accepts/rejects and field
  conditions; do not optimize only for aggregate accuracy.
- Register each camera endpoint as a separate device and provision a unique
  credential. Never copy one device identity to another.
- Run supervised/manual fallback and test session close, network loss, retry,
  reboot, and retentions.
- Complete school approval for purpose, privacy notices/basis, access,
  retention, correction/appeal and incident response.
- Mark unavailable physical checks as MANUAL HARDWARE TEST REQUIRED.
