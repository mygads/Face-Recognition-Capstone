# Deployment guide index

## Choose a topology

The app has two recognition profiles. A single-computer setup is a local
development/demo topology that runs one of those same profiles.

| Deployment | Camera side | Server side | Starting point |
| --- | --- | --- | --- |
| AI_EDGE + VPS | One native AI_EDGE agent and YuNet/SFace per lab PC; Ubuntu is the documented deployment target. | Ubuntu VPS/server with PostgreSQL and Core API in production Compose; Vue static build behind Nginx/TLS. | [AI_EDGE runbook](ai-edge.md) |
| AI_CENTRAL + STB | One native STB_GATEWAY on each supported ARM64 STB; UVC frames go as bounded bursts over a trusted LAN. | Ubuntu server with PostgreSQL, Core API and central AI service; Nginx routes HTTPS. | [AI_CENTRAL + STB runbook](ai-central-stb.md) |
| Single-computer development | Native Vite and native edge-agent access local webcam. | Local PostgreSQL/Core API in development Compose; optional AI service profile. Windows and Ubuntu instructions. | [Single-PC guide](single-pc.md#development-windows-dan-ubuntu) |
| Single-host Ubuntu demo/deployment | Native systemd AI_EDGE agent opens a camera on the same host. | Production PostgreSQL/Core API Compose plus host Nginx and static Vue build. | [Single-PC deployment section](single-pc.md#deployment-terbatas-satu-host-ubuntu), then [AI_EDGE runbook](ai-edge.md) |

The documented target for deployed AI_EDGE PCs and all central servers is
Ubuntu Linux. Windows is for local development and supervised laptop demos; the
agent can run natively there, but this repository does not provide a hardened
Windows service installer. For a deployed STB, use a supported ARM64 Linux image
and native systemd service. CasaOS is optional and is not required or tested as
the agent runtime. For a one-host deployment that restarts after reboot, use
Ubuntu with systemd.

For a new x86-64 server/lab PC, Ubuntu 24.04 LTS is the conservative documented
starting point; verify the exact camera driver, package/runtime versions, and
deployment image before rollout. Ubuntu lists standard security maintenance for
24.04 LTS through May 2029. This repository has not completed physical hardware
acceptance on that OS. See the [Ubuntu release lifecycle](https://ubuntu.com/about/release-cycle?product=ubuntu&release=ubuntu&version=24.04+LTS).

## Development and production are different

| Development | Deployment |
| --- | --- |
| Root docker-compose.yml, local .env and random development secrets. | Production Compose templates in infra/deployment and separately protected environment. |
| API hot reload, Vite dev server, localhost ports, test fixtures. | Pinned reviewed release, migration-only DB owner, restricted network listeners, HTTPS reverse proxy, managed secrets and backups. |
| Native edge-agent/webcam; optional AI service Compose profile. | Edge/STB native service, model checksums, device-specific credential, systemd/restart policy, acceptance checks. |
| No real student/minor face dataset. | School-approved biometric purpose, notice/legal basis, access, retention, manual fallback and incident policy required. |

For development, `py -3 scripts/start-local.py` (Windows) or
`python3 scripts/start-local.py` (Ubuntu) creates local secrets, starts the
database/API, applies migrations and seeds, bootstraps the development admin,
installs web dependencies when needed, and starts Vite. Host prerequisites
still need to be installed first. The Devices page issues a one-time
`UUID:token` for the camera bootstrap. Windows can run
`irm https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.ps1 | iex`;
Ubuntu/Armbian can run
`curl -fsSL https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.sh | bash`.
The bootstrap reads profile from the device registry and downloads the agent
source; it is a commissioning helper, not a persistent service. Use the
deployment-specific systemd runbook for reboot survival. The profile in the
registry selects local AI_EDGE versus STB_GATEWAY forwarding.

On the first local launch, choose whether this computer also runs AI_CENTRAL.
The choice is stored in ignored `.env`; change it later with
`scripts/start-local.py --profile edge` or `--profile central`. Starting this
service does not download model weights or calibrate decision thresholds.

Production server provisioning remains in the runbooks. Domain, TLS, firewall,
secret-store, backup, model approval, calibration, and school policy are
installation-specific. The camera installer is for commissioning and does not
replace the hardened systemd service setup in the AI_EDGE/STB runbooks.

## Required environment and artifacts

| Item | Development | Deployment |
| --- | --- | --- |
| Database/API settings | Root .env is created/populated by scripts/dev.py. | Copy the profile-specific example to a protected .env.ai-edge or .env.ai-central file; use distinct DB-owner and API-role passwords. |
| JWT and encryption keys | Random local keys are generated for development. | Generate/recover keys through the institution's approved secret manager; store backups securely. |
| YuNet/SFace | Optional until webcam recognition/enrollment; place approved files in ignored models/weights. | Provision outside Git/images, verify provenance and trusted SHA-256, and keep the same model version for enrollment and inference. |
| Attendance thresholds | Empty intentionally. Do not start recognition with uncalibrated settings. | Record approved local calibration report and configure Top-1 plus Top-1/Top-2 margin. |
| Web/domain | localhost Vite is enough; no public hostname required. | Vue build behind Nginx or another reviewed proxy with exact public/internal DNS and valid TLS. |
| Edge credentials | Register one development device and store its token in a local protected file. | Unique credential per physical device, OS ACL, renewal/revocation and audit. |
| Hardware | Camera may be mocked or local UVC. | Verify exact PC/STB camera, OS/kernel driver, resolution, sustained CPU/RAM/temp and reconnect. |

## Network entry points

The public/remote path should end at a reverse proxy. Do not publish PostgreSQL
5432 or raw API/AI development ports 8000/8001 directly. Nginx production
examples and firewall restrictions are in both server runbooks. Keep AI
inference and device routes on the lab/private network when possible. Metrics,
OpenAPI, and interactive API docs are operator-only.

If Cloudflare is used, publish the human web entry point intentionally and
protect it with an Access policy. Keep device/AI paths private unless the exact
device authentication and routing arrangement has been tested. A Cloudflare
Tunnel does not replace FastAPI authentication or RBAC.

See [domain and Cloudflare Tunnel](cloudflare-tunnel.md).

## Production guides

- [AI_EDGE server and lab PCs](ai-edge.md)
- [AI_CENTRAL server and STB Armbian](ai-central-stb.md)
- [Single-computer development and Ubuntu deployment](single-pc.md)
- [Domain, public hostname, Access, and tunnel](cloudflare-tunnel.md)

Do not declare operational readiness until the relevant runbook acceptance
checklist is complete. An unavailable hardware test must be marked
**MANUAL HARDWARE TEST REQUIRED**.
