# AI_EDGE vs AI_CENTRAL benchmark

This harness compares the real YuNet/SFace inference path on an AI_EDGE host
with requests to a running AI_CENTRAL service. It measures decision p50/p95,
per-stage recognition-core time, edge and server CPU/RAM, application-level bytes
per central event, sequential and two-lab throughput, and retry/error rates.

No model or image is downloaded or committed. The benchmark reads one
operator-supplied local face image in memory, omits its path from reports, and
does not save the image or embedding. Use a lawful, non-sensitive adult test
image or another fixture approved for local evaluation. It is not a substitute
for accuracy/FAR calibration or demographic evaluation.

## Generate the initial pending report

Install the repository development dependencies once:

```powershell
python -m pip install -r requirements-dev.txt
```

Then run from the repository root. This produces honest `PENDING HARDWARE`
results until model files, an input image, and an active AI Central test session
are configured:

```powershell
py -3 tests/deployment-benchmark/benchmark.py --output-dir tests/deployment-benchmark/reports/initial-pending
```

Linux:

```bash
python3 tests/deployment-benchmark/benchmark.py --output-dir tests/deployment-benchmark/reports/initial-pending
```

The output directory contains `summary.csv`, `samples.csv`, `summary.json`, and
`summary.md`. Later report directories under `reports/runs/` are ignored by Git.

## Run with lab hardware and provisioned models

AI_EDGE config must select `AI_EDGE`, point at locally provisioned YuNet/SFace
models, and contain the same calibrated thresholds and quality settings used by
that lab. The supplied image must pass that config's one-face and quality
checks. AI_EDGE builds a seeded synthetic gallery from that image's embedding
plus normalized random distractors; it does not use student templates. This
makes the profile useful for repeatable performance measurement without using
biometric enrollment data.

AI_CENTRAL must be running with the benchmark timing switch enabled, a reachable
`/metrics` endpoint, and a real active session gallery for each test device.
The supplied image must correspond to an enrolled consenting test identity in
each session. The harness sends the same image as a short JPEG burst. Tokens are
read from environment variables and are never included in the report.

PowerShell example (replace IDs and local paths with the authorized test setup):

```powershell
$env:PRESENSI_BENCH_DEVICE_TOKEN = "<lab-1-device-token>"
$env:PRESENSI_BENCH_LAB2_DEVICE_TOKEN = "<lab-2-device-token>"
$env:PRESENSI_BENCH_DEVICE_ID = "<lab-1-device-uuid>"
$env:PRESENSI_BENCH_SESSION_ID = "<lab-1-active-session-uuid>"
$env:PRESENSI_BENCH_LAB2_DEVICE_ID = "<lab-2-device-uuid>"
$env:PRESENSI_BENCH_LAB2_SESSION_ID = "<lab-2-active-session-uuid>"
py -3 tests/deployment-benchmark/benchmark.py `
  --image C:/local/approved-fixtures/volunteer.jpg `
  --edge-config apps/edge-agent/config/edge-agent.yaml `
  --central-url https://ai.lab.example `
  --device-id $env:PRESENSI_BENCH_DEVICE_ID `
  --session-id $env:PRESENSI_BENCH_SESSION_ID `
  --lab2-device-id $env:PRESENSI_BENCH_LAB2_DEVICE_ID `
  --lab2-session-id $env:PRESENSI_BENCH_LAB2_SESSION_ID `
  --iterations 30 --warmup 3 --frames-per-decision 3 --max-bursts 5 `
  --output-dir tests/deployment-benchmark/reports/runs/pilot-01
```

Linux uses the same arguments with `export` for the six `PRESENSI_BENCH_*`
environment variables and `python3` instead of `py -3`.

Enable stage timing on the AI Central host only for the benchmark window, then
restart that service:

```text
PRESENSI_AI_BENCHMARK_TIMING_ENABLED=true
```

The flag defaults to false. It allows trusted device requests that explicitly
send `X-Benchmark-Timing: true` to receive stage timing and gallery-template
count response headers. These contain aggregates only. Disable the setting and
restart AI Central after the run. Restrict
`/metrics` to the trusted operations network.

## Measurement definitions and limits

- AI_EDGE end-to-end time starts with the decoded in-memory frame and ends with
  a terminal track decision. AI_CENTRAL includes JPEG/base64/JSON request work,
  network round trips, service processing, and responses until a terminal
  decision. Each uses up to `--max-bursts` bursts for one track.
- Camera exposure/capture, device heartbeat, Core API attendance event delivery,
  and database finalization are excluded. The comparison is for recognition
  decision latency.
- Decision p50/p95 and throughput include terminal states only (`ACCEPTED`,
  `NEED_FRONTAL_RETRY`, or `REJECTED`). Tracks still `COLLECTING` at the burst
  limit count as incomplete, not successful decisions. Response latency is also
  reported for every measured logical run, including incomplete tracks and
  failed requests.
- Per-stage values are summed across all frames/bursts for a track. Stages not
  reached (for example embedding after a quality rejection) are omitted, never
  reported as zero.
- CPU reports process CPU percent normalized to one core (values can exceed
  100%) and sampled host CPU percent. RAM reports peak process RSS and average
  host memory in use. The table emphasizes host CPU/RAM. CSV also carries
  benchmark-process RSS/CPU; for AI_CENTRAL that process is the load generator,
  not the edge-agent service. AI Central server process/host values are sampled
  from its `/metrics` endpoint while requests are running.
- Central network bytes estimate serialized HTTP/1.1 request and response
  headers plus bodies. It excludes TLS, TCP/IP, and Ethernet framing; it is not
  a NIC counter.
- Two-lab AI_CENTRAL sends one serialized stream per device concurrently. AI_EDGE runs
  two independent model workers on the current host to create concurrent load;
  that is not equal to two separate lab PCs. For a deployment decision, also run
  one worker on each actual lab PC and retain both reports.
- Warmups are excluded. Decision latency percentiles use terminal track
  decisions; error, incomplete, and retry rates use all measured logical runs.
  P50/P95 use the nearest-rank method (`ceil(p × sample_count)`).
  HTTP retries are measured in AI_CENTRAL only; API event delivery retries are
  outside this benchmark.
- Keep the service, gallery size, model versions, thresholds, frame count,
  fixture, host power mode, and background load fixed when comparing runs.
  Reports include the code revision, hardware/runtime facts, AI_EDGE YuNet and
  SFace model SHA-256 hashes, and observed model versions. They omit image path,
  image bytes, embeddings, tokens, device IDs, and session IDs. Central model
  hashes are not exposed by the service; record the central image's deployment
  digest alongside the report when comparing a controlled build.

## Tests

The no-hardware tests verify report generation and that unavailable measurements
remain null rather than receiving invented values:

```bash
python -m pytest tests/deployment-benchmark apps/ai-service/tests libs/recognition-core/tests -q
```
