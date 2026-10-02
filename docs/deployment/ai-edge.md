# AI_EDGE deployment runbook

This runbook deploys FastAPI and PostgreSQL on one Linux server, serves the Vue
production build through Nginx, and runs one native edge-agent per lab PC. Each
edge-agent performs local inference and sends attendance events to the Core API
over HTTPS. The root `docker-compose.yml` is for development; production uses
`infra/deployment/compose.ai-edge.yml`.

PostgreSQL has no published port. The API binds only to server loopback for the
local reverse proxy. Public ingress should allow HTTPS only (and HTTP when
needed for certificate issuance/redirects); never open ports 5432, 8000, or
8001 to the Internet.

## 1. Deployment prerequisites

Use Ubuntu Linux on the server and deployed lab PCs. The server needs Docker
Engine and the Compose plugin, a school DNS name, and an institution-managed
TLS certificate. Lab PCs need outbound HTTPS to the API name. Restrict SSH to
the management network. Windows is covered for local development and supervised
demos; it is not the documented unattended deployment target.

Before real student data is used, the school must approve its purpose,
notice/consent or other lawful basis for minors, roles, retention, manual
fallback, and incident process. This runbook is an engineering guide, not a
claim of legal compliance. Review [security and privacy](../security-and-privacy.md).

Also confirm the SFace/YuNet model provenance and licenses in
[model documentation](../models.md), local recognition-threshold calibration,
and tested recovery access to the database encryption keyring. The sample has
liveness disabled; keep a supervised-entry or other school-approved physical
control in place unless a separately cleared liveness model is deployed.

## 2. Model files, versions, and checksums

Keep model binaries outside Git and outside the API image. The API mounts them
read-only from `/srv/presensi/models`; each lab PC provisions the same assets
locally. Expected baseline filenames are:

| Stage | Asset | Version record |
| --- | --- | --- |
| Detection | `face_detection_yunet_2023mar.onnx` | Exact approved asset filename/release |
| Embedding | `face_recognition_sface_2021dec.onnx` | `opencv-zoo-sface-2021dec` |

No model binary or trusted SHA-256 value is included here. Compare each received
file to a checksum from the separately reviewed artifact channel, then record
the filename, model version, SHA-256, source, device/lab, and verification date
in the deployment record. Calculating a checksum from an unreviewed file does
not establish its provenance. Once verified, these commands detect later file
changes:

```bash
sudo install -d -o root -g root -m 0755 /srv/presensi/models
cd /srv/presensi/models
sha256sum face_detection_yunet_2023mar.onnx face_recognition_sface_2021dec.onnx | tee SHA256SUMS
sha256sum --check SHA256SUMS
```

On a Windows edge PC:

```powershell
Get-FileHash C:\Presensi\models\face_detection_yunet_2023mar.onnx -Algorithm SHA256
Get-FileHash C:\Presensi\models\face_recognition_sface_2021dec.onnx -Algorithm SHA256
```

The SFace version in the edge YAML must match
`PRESENSI_ENROLLMENT_MODEL_VERSION` on the API. Keep the same SFace files and
version on all lab PCs. A model-version change requires planned template
re-enrollment and gallery rollout; a config-only change makes existing
templates unavailable to that version. The edge sample leaves recognition
thresholds empty intentionally; do not start attendance until Top-1 and margin
thresholds are calibrated locally.

## 3. Server secrets and environment

Check out the exact reviewed release under a stable path, for example
`/opt/presensi/server`. Do not put Git credentials in a remote URL. Copy and
protect the production environment template:

```bash
cd /opt/presensi/server
sudo cp infra/deployment/ai-edge.env.example .env.ai-edge
sudo chown root:root .env.ai-edge
sudo chmod 0600 .env.ai-edge
sudoedit .env.ai-edge
```

Replace every sample value. Set `PRESENSI_RELEASE_TAG` to this approved source
revision, set `PRESENSI_MODELS_DIR` to an absolute model directory, and pin
`POSTGRES_IMAGE` to the institution-approved PostgreSQL 16 image digest. The
example tag is only a starting point.

Use different random values for `POSTGRES_PASSWORD` and
`PRESENSI_APP_DB_PASSWORD`. `POSTGRES_USER` is the database owner used for
migrations/recovery; the API connects as the separate
`PRESENSI_APP_DB_USER` role, which has data access but cannot create schema
objects. Set `JWT_SECRET` to at least 32 random bytes.

`PRESENSI_FACE_TEMPLATE_KEYS` must be a JSON object mapping key IDs to
base64-encoded 32-byte AES keys. Set the active key ID to one of those IDs. Store
the keyring, JWT secret, DB credentials, and backup passphrase in the institution
secret manager as well as the protected host file. A database backup without
the matching template keyring cannot restore usable templates. Limit Docker
daemon access because Docker administrators can inspect container environments.

Changing a password in `.env.ai-edge` does not change an initialized PostgreSQL
role. For an API-password rotation, open `psql` interactively as
`POSTGRES_USER`, run `\password presensi_api`, update
`PRESENSI_APP_DB_PASSWORD` in the protected environment file, then recreate the
API container with `dc up -d --force-recreate api`. For an owner-password
rotation, run `\password presensi_db_owner` and update `POSTGRES_PASSWORD`;
recreate the API container and use the new owner password for future migrations
and recovery. Do not put a new password in a SQL command or shell argument.

Keep `PRESENSI_CORS_ALLOWED_ORIGINS` empty when the UI and API share this
HTTPS origin. If the school intentionally hosts the UI on another origin, set
that exact HTTPS origin only; never use `*`.

The Compose Postgres init script creates the restricted API role and default
table/sequence grants on the first initialization of its own named volume. Do
not reuse the development Postgres volume or point production Compose at an
existing data directory.

## 4. Start database and API

Run these commands from the repository root on the server. Define this helper
once per shell so commands consistently use the production Compose file and
environment:

```bash
cd /opt/presensi/server
dc() {
  sudo docker compose --env-file .env.ai-edge \
    --project-directory "$PWD" \
    -f infra/deployment/compose.ai-edge.yml "$@"
}
```

Validate, build the API image, and start PostgreSQL:

```bash
dc config --quiet
dc build api
dc up -d db
dc ps
```

Wait until the database reports `healthy`. Apply migrations with the one-shot
migration service, which uses the database-owner credentials. Then seed roles,
create the first ADMIN account, and start the API. The password is requested at
a hidden prompt instead of being placed in shell history:

```bash
dc --profile ops run --rm migrate
dc run --rm api python -m presensi_api.db.seed_roles
dc run --rm -it api python -m presensi_api.auth.create_user \
  --email admin@example.edu --full-name "School Administrator" --role ADMIN
dc up -d api
```

`/health` checks that the API process responds; it does not prove database
read/write access. Check both services:

```bash
dc ps
dc exec -T db sh -ec 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
curl --fail --show-error http://127.0.0.1:8000/health
```

The checks should report the database as `healthy` and return HTTP 200 from the
API health endpoint. `/health` confirms that the API process responds; it is not
a database read/write check.

The production Compose file contains no database `ports` mapping. Confirm
Postgres has no host mapping and the API listens only on loopback:

```bash
sudo ss -lntp | grep -E ':(5432|8000|443)\b'
```

There must be no 5432 listener/mapping; API should be `127.0.0.1:8000`. The
`db` service in the production Compose file deliberately has no `ports` section.
Keep 5432, 8000, and 8001 blocked at the host firewall.

## 5. Build Vue and configure Nginx

Build the production SPA from the same reviewed source revision. The client uses
relative `/api/...` URLs, so same-origin hosting needs no browser CORS exception.
Deploy each build to a versioned static directory, then switch the `current`
symlink:

```bash
cd /opt/presensi/server/apps/web
npm ci
npm run build
cd /opt/presensi/server
WEB_RELEASE=$(git rev-parse --short HEAD)
sudo install -d -o root -g root -m 0755 "/var/www/presensi/releases/$WEB_RELEASE"
sudo cp -a apps/web/dist/. "/var/www/presensi/releases/$WEB_RELEASE/"
sudo chown -R root:root "/var/www/presensi/releases/$WEB_RELEASE"
sudo ln -sfn "/var/www/presensi/releases/$WEB_RELEASE" /var/www/presensi/current.next
sudo mv -Tf /var/www/presensi/current.next /var/www/presensi/current
```

Install Nginx and provision the school's TLS certificate before enabling its
HTTPS server block. Put the following `map` in the Nginx `http` context (for
example, a file in `/etc/nginx/conf.d/`) so WebSocket upgrades work:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

log_format presensi_safe '$remote_addr [$time_local] "$request_method $uri $server_protocol" '
                         '$status $body_bytes_sent';
```

Use a site config like this after replacing the hostname and certificate paths:

```nginx
server {
    listen 80;
    server_name presensi.example.edu;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name presensi.example.edu;
    root /var/www/presensi/current;
    client_max_body_size 17m;
    access_log /var/log/nginx/presensi.access.log presensi_safe;

    ssl_certificate     /etc/letsencrypt/live/presensi.example.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/presensi.example.edu/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 60s;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Configure access logs to record `$uri`, not `$request` or `$request_uri`, so
query values are not copied into logs. Do not log request bodies or the
`Authorization` header. Check and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail --show-error https://presensi.example.edu/health
curl --fail --show-error --head https://presensi.example.edu/
```

Only proxy `/api/` and `/health` to the API; serve other paths from the Vue
build. Do not publish `/docs` or `/openapi.json` publicly. Nginx handles API
WebSocket upgrades. Keep CORS empty for same-origin use and do not trust
forwarded headers from any source other than this proxy.

## 6. Register one device for each lab

In the administrator UI at `/app/devices`, create a separate device per lab:
type `edge_pc`, profile `AI_EDGE`, and the assigned laboratory. Record its UUID;
do not share an ID across PCs.

In the device row, choose **Kredensial** and then **Buat token pertama**. The UI
returns the raw token once with copy and download actions. Save it directly to
that PC's protected token file; do not place it in a shell command, ticket,
chat, screenshot, or log. Closing the panel clears the token from the page, and
it cannot be retrieved again. If the token file is lost, choose the rotation
flow, enter an audit reason, and install the new token promptly; the previous
verifier overlaps for a limited period.

Device credentials renew automatically when the agent loads them from a token
file. The file must be writable by the service account because renewal replaces
it atomically. Put it in the protected service state directory, not in a
root-owned read-only `/etc` directory.

## 7. Install an AI_EDGE service on each Linux lab PC

Do one PC at a time. Keep software root-owned/read-only, model files readable but
not writable by the service account, and only its token/outbox state writable.
Install tools, create the service account, and grant UVC access:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip v4l-utils
sudo useradd --system --no-create-home --home-dir /var/lib/presensi-edge-agent \
  --shell /usr/sbin/nologin presensi-edge
sudo usermod -aG video presensi-edge
sudo install -d -o root -g root -m 0755 /opt/presensi-edge-agent/releases
sudo install -d -o root -g presensi-edge -m 0750 /etc/presensi-edge-agent
sudo install -d -o presensi-edge -g presensi-edge -m 0750 /var/lib/presensi-edge-agent
sudo install -d -o root -g root -m 0755 /opt/presensi-edge-agent/models
```

Place the approved source release at
`/opt/presensi-edge-agent/releases/<release-id>`. Install the edge and shared
recognition packages in a release-local virtual environment, then switch the
`current` symlink:

```bash
RELEASE=/opt/presensi-edge-agent/releases/<release-id>
sudo python3 -m venv "$RELEASE/.venv"
sudo "$RELEASE/.venv/bin/pip" install \
  -e "$RELEASE/apps/edge-agent[camera]" \
  -e "$RELEASE/libs/recognition-core[opencv]"
sudo ln -sfn "$RELEASE" /opt/presensi-edge-agent/current
```

Copy the approved model files to `/opt/presensi-edge-agent/models`; verify
checksums and make them read-only to the service account. Copy
`apps/edge-agent/config/edge-agent-ai-edge.example.yaml` to
`/etc/presensi-edge-agent/edge-agent.yaml`. Set the HTTPS API name, camera
index/backend/mode, absolute model paths, exact SFace version, and calibrated
thresholds. Keep the config root-owned and readable by the agent:

```bash
sudo install -o root -g presensi-edge -m 0640 \
  "$RELEASE/apps/edge-agent/config/edge-agent-ai-edge.example.yaml" \
  /etc/presensi-edge-agent/edge-agent.yaml
sudoedit /etc/presensi-edge-agent/edge-agent.yaml
```

Create `/etc/presensi-edge-agent/edge-agent.env` with the registered UUID:

```ini
PRESENSI_EDGE_DEVICE_ID=<registered-device-uuid>
```

Protect that file and create the service-owned token file. Paste the one-time
device credential at the hidden prompt, avoiding shell history and process
arguments:

```bash
sudo install -o root -g presensi-edge -m 0640 /dev/null \
  /etc/presensi-edge-agent/edge-agent.env
sudoedit /etc/presensi-edge-agent/edge-agent.env
sudo -u presensi-edge sh -c ': > /var/lib/presensi-edge-agent/device.token && chmod 0600 /var/lib/presensi-edge-agent/device.token'
read -r -s -p 'Paste the one-time device credential: ' DEVICE_TOKEN
printf '\n'
printf '%s\n' "$DEVICE_TOKEN" | sudo -u presensi-edge tee \
  /var/lib/presensi-edge-agent/device.token >/dev/null
unset DEVICE_TOKEN
```

Install and enable the AI_EDGE systemd unit. The checked-in STB gateway unit is
for a different profile and should not be used here:

```bash
sudo install -o root -g root -m 0644 \
  "$RELEASE/apps/edge-agent/deploy/presensi-edge-agent-ai-edge.service" \
  /etc/systemd/system/presensi-edge-agent.service
sudo systemd-analyze verify /etc/systemd/system/presensi-edge-agent.service
sudo -u presensi-edge "$RELEASE/.venv/bin/presensi-edge-agent" \
  --config /etc/presensi-edge-agent/edge-agent.yaml cameras
sudo systemctl daemon-reload
sudo systemctl enable --now presensi-edge-agent.service
sudo systemctl status --no-pager presensi-edge-agent.service
sudo journalctl -u presensi-edge-agent.service -n 100 --no-pager
```

The unit should show `active (running)`. The camera enumeration command should
list the selected UVC device. After the first heartbeat, `/app/devices` should
show this device as online with a healthy camera status.

The agent heartbeats every 15 seconds; the default server timeout marks it
offline after 60 seconds. Confirm the device is online and its camera status is
healthy at `/app/devices`. Logs omit frames, embeddings, and credentials. For an
offline device, check lab assignment, UUID, outbound DNS/TLS, `video` group
access, token-file permissions, and model paths/checksums.

### Optional Windows development/demo client

The edge-agent can run natively on Windows for a supervised demo; do not pass the webcam into the
server Compose stack. Install the approved source/model versions in a dedicated
Python virtual environment, choose a camera backend (`msmf`, `dshow`, or
`auto`), and keep the SQLite outbox and token under `C:\ProgramData\Presensi`.
For unattended startup, use the school's approved service wrapper (such as
NSSM or WinSW) under a dedicated non-administrator service account. Grant that
account camera access, read-only model/config access, and read/write access only
to its token/outbox directory. Configure restart-on-failure and protect service
files with Windows ACLs; do not run it as a personal administrator account.

## 8. Database backup and restore

Take an encrypted logical backup at least daily and before each schema upgrade.
Store an encrypted copy in the institution's protected backup location and a
separate recovery copy. Tables contain student records and encrypted biometric
vectors; back up the matching face-template keyring separately in the secret
manager. Do not rely on a copy of the live Docker volume as the only backup.

As an authorized operator with Docker and GPG access, use the `dc` helper from
section 4:

```bash
set -o pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=/srv/backups/presensi
install -d -m 0700 "$BACKUP_DIR"
dc exec -T db sh -ec \
  'pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  | gpg --symmetric --cipher-algo AES256 \
      --output "$BACKUP_DIR/presensi-$STAMP.dump.gpg"
sha256sum "$BACKUP_DIR/presensi-$STAMP.dump.gpg"
gpg --decrypt "$BACKUP_DIR/presensi-$STAMP.dump.gpg" | pg_restore --list >/dev/null
```

GPG prompts for a backup passphrase; store it in the secret manager, not beside
the backup. Copy only the encrypted file and checksum off-host. Schedule the
command with the school's backup system, alert on failed/missed runs, apply the
approved retention policy, and perform an isolated restore drill at least
quarterly.

To restore a dump to this Compose database, stop API writes and select a backup
plus the exact code/config/keyring release that matches it. This replaces the
current database contents: confirm the target and backup with a second operator
before continuing.

```bash
set -o pipefail
BACKUP=/srv/backups/presensi/<selected-backup>.dump.gpg
dc stop api
dc exec -T db sh -ec \
  'dropdb --if-exists --username="$POSTGRES_USER" --maintenance-db=postgres "$POSTGRES_DB" && createdb --username="$POSTGRES_USER" --owner="$POSTGRES_USER" "$POSTGRES_DB"'
dc exec -T db sh /docker-entrypoint-initdb.d/10-create-api-role.sh
gpg --decrypt "$BACKUP" | dc exec -T db sh -ec \
  'pg_restore --no-owner --no-privileges --exit-on-error --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"'
```

The role/grant script is rerun because Postgres default grants belong to one
database. It skips an existing app login and reapplies grants for future
migrations. Check that restore exited successfully; inspect the restored schema
with `dc --profile ops run --rm migrate current`, then start the API and verify
`/health`, admin login, device heartbeats, and reports before resuming
attendance. If the recovery target is an older schema, apply a migration only
after confirming that this is the intended target.

Keep `JWT_SECRET`, the template keyring, DB credentials, and backup passphrase
recoverable. Losing every copy of the active/old template keys makes encrypted
embeddings unusable. Do not remove an old key until all rows are re-encrypted
and the new keyring backup has been verified.

## 9. Upgrade and rollback

First upgrade a non-production environment with the same PostgreSQL major,
model versions, and migration path. For production:

1. Announce a maintenance window and pause session starts and enrollment.
2. Record the current source revision, API image, Vue static release, edge-agent
   release/config, model versions/checksums, and Compose status.
3. Take and verify an encrypted database backup using section 8.
4. Check out the reviewed new source. Set `PRESENSI_RELEASE_TAG` in
   `.env.ai-edge` to its immutable commit/release ID; retain the old source and
   API image so rollback does not need to rebuild old dependencies.
5. Build the new API image, apply migrations with the migration-only DB owner,
   seed roles, and start API:

   ```bash
   dc build api
   dc --profile ops run --rm migrate
   dc run --rm api python -m presensi_api.db.seed_roles
   dc up -d api
   dc ps
   curl --fail --show-error https://presensi.example.edu/health
   ```

6. Build Vue from the same revision, publish a versioned static directory,
   atomically switch `current`, run `nginx -t`, and reload Nginx.
7. Upgrade lab PCs one at a time. Install a release-local venv, verify model
   checksums/thresholds, switch `/opt/presensi-edge-agent/current`, and restart
   the service. Keep the local SQLite queue and token state in place.
8. Check API health, admin login, one lab heartbeat/camera status, active
   session gallery, and attendance/report behavior using the school's approved
   non-student commissioning procedure before normal sessions resume.

Prefer a forward fix when a migration has changed the schema. Roll code back
only if the previous release is compatible with the migrated schema. Restore
the previous Vue symlink and edge-agent release/config, and start an already
built prior API image without rebuilding it (`dc up -d --no-build api`). Do not
use `alembic downgrade` as a routine rollback. If schema compatibility or data
integrity is uncertain, stop writes, restore the pre-upgrade database backup and
matching old code/config/keyring, then verify recovery. Restore loses changes
after that backup; communicate the recovery point and reconcile attendance under
the school's correction/audit policy.

Do not change the SFace version as an incidental software upgrade. Templates,
enrollment model version, and edge model version must remain aligned; plan
re-enrollment and rollback of model/config/assets as a separate controlled
release.

## 10. Routine health checks

Schedule the event-retention command daily with the institution's Linux
scheduler. Set `PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS` to the school-approved
period. The command deletes expired unlinked recognition events and redacts
expired events referenced by attendance records; attendance and audit retention
are separate policies:

```bash
dc run --rm api python -m presensi_api.retention
```

On the server:

```bash
dc ps
dc logs --since 15m api db
curl --fail --show-error https://presensi.example.edu/health
```

On a lab PC:

```bash
sudo systemctl status --no-pager presensi-edge-agent.service
sudo journalctl -u presensi-edge-agent.service --since '15 minutes ago' --no-pager
```

If Postgres is unhealthy, check disk space, volume availability, and
`pg_isready`; do not publish port 5432 to troubleshoot. If API process health
passes but requests fail, check API logs, database grants, secret keyring, and
model configuration. If a device is offline, check heartbeat, lab assignment,
outbound TLS, camera access, token renewal permissions, and model version. Do
not weaken recognition thresholds to mask lighting/framing problems; use the
approved field calibration plan.

For an incident involving student data, preserve only necessary operational
logs, restrict access, follow school incident policy, and do not attach face
images, embeddings, credentials, or unredacted request logs to a ticket.
