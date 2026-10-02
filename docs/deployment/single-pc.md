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

The repository declares its Node range in `apps/web/package.json`. Node 23 is
outside that range even if Vite happens to start. The default one-command
development startup uses native Vite and installs the locked web dependencies
when needed. If changing the host Node installation is inconvenient, the
optional web container uses Node 24:

~~~powershell
py -3 scripts/dev.py dev-up --web-container
~~~

Use either native Vite or the web container on port 5173 at a time; stop the
existing Vite terminal before starting the container profile.

### One-command development startup

After cloning and installing the host prerequisites, run this from the
repository root. It creates local `.env` secrets if needed, starts PostgreSQL
and FastAPI through Compose, runs migrations/role seed/local admin bootstrap,
installs web dependencies when needed, then keeps the native Vue dev server in
the foreground:

~~~powershell
# Windows PowerShell
py -3 scripts/start-local.py
~~~

~~~bash
# Ubuntu
python3 scripts/start-local.py
~~~

Open `http://127.0.0.1:5173`. Press Ctrl+C to stop Vite. The API/database
continue in Docker so that they can be reused; stop them when finished:

~~~powershell
py -3 scripts/dev.py dev-down
~~~

~~~bash
python3 scripts/dev.py dev-down
~~~

If Python is missing on Windows and the `py` launcher suggests that no runtime
is installed, install Python 3.12 with `py install 3.12`, reopen PowerShell, and
use `py -3`. Do not use `py -3.12` until that specific runtime has been
installed.

For server-only startup without Vite, use `py -3 scripts/dev.py dev-up` on
Windows or `python3 scripts/dev.py dev-up` on Ubuntu.

The task runner copies `.env.example` to `.env` if needed and fills blank local
database/JWT/encrypted-template secrets, applies migrations, seeds roles, and
creates a local administrator only when the user table is empty. Sign in as
`admin@local.test` with `123456789abcd` and change it at first sign-in. This
fixed password is for local development only; do not expose the development
stack before changing it. The .env file is ignored by Git. Keep
the local generated keyring with the database volume; losing it makes encrypted
templates in that volume unusable. These development secrets are not production
secrets.

The database persists in the named `postgres-data` volume. The API and database
host ports bind to loopback. The `scripts/dev.py dev-up` task called by
`start-local.py` runs migrations; if you start containers directly with Docker
Compose, run the documented migration/seed commands yourself. API process
health alone does not mean that the schema is current.

### Sign in and prepare local records

The web app is already available after `start-local.py`. Check API health at
http://127.0.0.1:8000/health and the versioned endpoint at
http://127.0.0.1:8000/api/v1/health.

After first login, open **Kelola akun staf** in the left menu to create a
TEACHER or LABORANT account. The page shows the generated temporary password
once; share it directly with the account owner. They must set their own
password at first sign-in. Use only fictional master-data records and an adult
volunteer who agrees to a local camera test.

Recommended setup order: create laboratories, classes and school years, import
or add students, create teacher/laborant accounts, configure enrollment models,
then register a camera device. A teacher creates a schedule and opens a session
only after its class roster is ready; opening a session snapshots that roster.

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

For backend enrollment, the Core API container sees weights at `/models` because
Compose mounts the model directory read-only. A fresh `.env` already contains
these non-secret local evaluation paths and model version; confirm them if this
checkout has an older `.env`:

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

The host AI_EDGE config uses host-visible model paths instead of `/models`.
Register an `AI_EDGE` device at **Perangkat**, assign its laboratory, create its
one-time credential, enter `http://127.0.0.1:8000` as the Core API URL, then
download the setup bundle. On the same computer, run the installer from the
repository root:

~~~powershell
.\scripts\install-camera-device.ps1 -BundlePath "$HOME\Downloads\presensi-device-setup.json"
~~~

~~~bash
bash scripts/install-camera-device.sh "$HOME/Downloads/presensi-device-setup.json"
~~~

It creates the local agent environment, selects `AI_EDGE` from the bundle,
writes `apps/edge-agent/config/edge-agent.yaml` and a protected token file, and
checks camera/config readiness. If the camera PC is a different computer, also
download the checksum-pinned model files into that checkout before `run`:

~~~powershell
py -3 scripts/download_face_models.py
~~~

~~~bash
python3 scripts/download_face_models.py
~~~

Remove the setup bundle after confirming the device. For a camera on a different
computer, use that computer's LAN/DNS API address; `127.0.0.1` only works when
the API is on the same machine. The local development API is bound to loopback,
so it cannot serve a second computer; for remote cameras use an intentionally
configured private LAN server/reverse proxy from the deployment runbook. Never
expose the raw development API port directly to the Internet.

Recognition thresholds `min_top1_similarity` and `min_top1_top2_margin`
intentionally have no final defaults. The installer reports this as a
readiness blocker and does not invent values. Calibrate locally under approved
conditions before running attendance. For the first webcam test, use the
camera calibration preview, then close it before running the edge-agent because
many webcams allow only one process at a time. See [edge-agent setup](../../apps/edge-agent/README.md).

### Optional central-profile development on the same host

Run the development AI service only when explicitly testing AI_CENTRAL:

~~~powershell
# Windows
py -3 scripts/start-local.py --central
~~~

~~~bash
# Ubuntu
python3 scripts/start-local.py --central
~~~

Before starting it, place the model files and set the central YuNet/SFace paths
and model version in `.env` (fresh `.env.example` already contains local paths
and the baseline version).
Both Top-1 and Top-1/Top-2 margin values must come from approved local
calibration; there are no production defaults. The camera-side process must use
STB_GATEWAY mode and send bursts to the service. A webcam on the same laptop is
only a developer simulation of the networked STB arrangement; it does not test
ARM64 performance, Armbian drivers, LAN latency, or STB thermals.

The AI service does not replace Core API attendance rules. STB_GATEWAY itself
does not run a face identity model.

### Stop development services

Stop the native Vite and edge-agent processes with Ctrl+C in their terminals,
then stop Compose while preserving the PostgreSQL volume:

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
