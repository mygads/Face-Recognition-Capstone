# AI_EDGE vs AI_CENTRAL deployment benchmark

- Run: `20261001T203623Z`
- Started: `2026-10-01T20:36:23.250071+00:00`
- Overall status: **PENDING HARDWARE**
- Workload source: locally supplied image; path and image data are not written to the report.
- No performance values are synthesized. Missing measurements remain blank/null.

## Results

| Profile | Scenario | Status | Gallery size(s) | Decisions/s | Decision p50 ms | Decision p95 ms | Retries | Errors | Incomplete | Edge host CPU % | Edge host RAM MB | Server host CPU % | Server host RAM MB | App bytes/event |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AI_EDGE | sequential | PENDING HARDWARE | — | — | — | — | — | — | — | — | — | — | — | — |
| AI_EDGE | two_labs_concurrent | PENDING HARDWARE | — | — | — | — | — | — | — | — | — | — | — | — |
| AI_CENTRAL | sequential | PENDING HARDWARE | — | — | — | — | — | — | — | — | — | — | — | — |
| AI_CENTRAL | two_labs_concurrent | PENDING HARDWARE | — | — | — | — | — | — | — | — | — | — | — | — |

## Decision states

Terminal decision latency excludes tracks that remained COLLECTING.

| Profile | Scenario | Final track states |
|---|---|---|
| AI_EDGE | sequential | `—` |
| AI_EDGE | two_labs_concurrent | `—` |
| AI_CENTRAL | sequential | `—` |
| AI_CENTRAL | two_labs_concurrent | `—` |

## Inference stages

Per-decision stage time is summed across frames and bursts.

| Profile | Scenario | Stage | Samples | p50 ms | p95 ms |
|---|---|---|---:|---:|---:|

## Method and limits

- Latency starts at a decoded image and ends at a terminal AI_EDGE track decision or AI_CENTRAL response. It excludes camera capture and Core API attendance writes. COLLECTING tracks are reported as incomplete.
- Stage timings come from recognition-core and are summed across frames and bursts until a terminal decision. They measure pipeline work, not camera time.
- AI_EDGE uses the real local YuNet/SFace pipeline and a seeded synthetic gallery. One target template is derived from the supplied test image; remaining distractors are seeded normalized vectors. This workload is for performance only, not threshold calibration or demographic evaluation.
- AI_CENTRAL requests go to the configured service with active-session galleries. The two-lab scenario runs one serialized stream per device concurrently. HTTP byte estimates include HTTP/1.1 headers and bodies, and exclude TLS, TCP/IP, and link-layer framing.
- CPU reports process percent normalized to one core (may exceed 100%) and sampled host CPU percent. RAM reports peak process RSS and average host memory use. Central server values come from its /metrics endpoint.
- Sequential runs one lab at a time. Two-lab runs two workers concurrently. AI_EDGE workers share this benchmark host; repeat one worker on each real lab PC before making a deployment decision.
- Warmup is excluded. Decision latency percentiles use terminal track decisions; response latency covers all measured logical requests. Retry/error rates use all logical requests. Percentiles use nearest rank. This runner saves no camera or raw image, and omits image paths and credentials from reports.

## Blockers

- **AI_EDGE / sequential:** Provide --image with a local approved fixture, --edge-config, and locally provisioned YuNet/SFace model files.
- **AI_EDGE / two_labs_concurrent:** Provide --image with a local approved fixture, --edge-config, and locally provisioned YuNet/SFace model files.
- **AI_CENTRAL / sequential:** Provide --image, a running AI Central URL, active lab session/device IDs, and their device tokens.
- **AI_CENTRAL / two_labs_concurrent:** Provide --image, a running AI Central URL, active lab session/device IDs, and their device tokens.
