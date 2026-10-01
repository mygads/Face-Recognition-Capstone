# AI verification benchmark

This local harness evaluates YuNet/SFace as a one-to-one face verification
baseline. It reads a CSV manifest with `path`, `person_id`, and `condition`,
computes every unordered image pair, and reports genuine (same `person_id`) and
impostor (different `person_id`) cosine similarities.

## Data and privacy

Images and model weights are not included. Store evaluation images only in a
locally authorized dataset directory such as `tests/ai-benchmark/datasets/`;
that directory, model assets, and reports are ignored by Git. Use lawfully
collected data and follow the repository's face-data rules. Never use student or
minor photographs in cloud CI. Reports omit image paths and person IDs. They do
include condition labels and aggregate counts; treat reports and pair-score CSVs
as sensitive evaluation artifacts and keep them local.

`example-manifest.csv` is synthetic metadata only. Its image paths are
placeholders and must be replaced with local images before running the harness.
Paths in the manifest are resolved relative to the manifest file. Each image must
contain exactly one detectable face; a bad row fails the run rather than silently
changing the pair denominators.

## Install and run

The repository development requirements already install the recognition core
with its optional OpenCV dependencies. Model paths are explicit; the harness never
downloads model files.

PowerShell:

```powershell
python tests/ai-benchmark/ai_benchmark.py `
  --manifest tests/ai-benchmark/example-manifest.csv `
  --yunet-model C:/local/models/face_detection_yunet_2023mar.onnx `
  --sface-model C:/local/models/face_recognition_sface_2021dec.onnx `
  --threshold-min -1 --threshold-max 1 --threshold-steps 201 `
  --max-fmr 0.001 `
  --json-out tests/ai-benchmark/reports/baseline.json `
  --csv-out tests/ai-benchmark/reports/thresholds.csv `
  --pair-csv-out tests/ai-benchmark/reports/pairs.csv `
  --plot-out tests/ai-benchmark/reports/distributions.png
```

Linux:

```bash
python3 tests/ai-benchmark/ai_benchmark.py \
  --manifest tests/ai-benchmark/example-manifest.csv \
  --yunet-model /local/models/face_detection_yunet_2023mar.onnx \
  --sface-model /local/models/face_recognition_sface_2021dec.onnx \
  --threshold-min -1 --threshold-max 1 --threshold-steps 201 \
  --max-fmr 0.001 \
  --json-out tests/ai-benchmark/reports/baseline.json \
  --csv-out tests/ai-benchmark/reports/thresholds.csv \
  --pair-csv-out tests/ai-benchmark/reports/pairs.csv \
  --plot-out tests/ai-benchmark/reports/distributions.png
```

The example command is reproducible when the manifest, image bytes, model files,
OpenCV version, and arguments are held fixed. Score metrics are deterministic;
latency measurements vary with hardware and system load. To skip plotting, omit
`--plot-out`. Plotting requires `python -m pip install matplotlib`.

## Metrics and threshold review

For this pairwise verification protocol, a pair is accepted when
`cosine_similarity >= threshold`:

- FAR and FMR are aliases here: impostor pairs accepted divided by all impostor
  pairs.
- FRR and FNMR are aliases here: genuine pairs rejected divided by all genuine
  pairs.
- The report contains rates and support counts at each threshold, genuine and
  impostor score distributions, histogram bins, and condition-pair strata.
- `--max-fmr` marks thresholds that meet the supplied low-FMR constraint. It does
  not select a threshold or optimize total accuracy. Review false-accept counts,
  pair denominators, FRR, and the cost of errors before considering a candidate.

The benchmark's measured baseline stages are image read, YuNet detection, SFace
alignment, SFace embedding, cosine comparison, and total per-image inference.
Quality, liveness, temporal tracking, and attendance policy are not exercised, so
these timings are not end-to-end attendance latency.

Threshold candidates must be validated on a separate, representative holdout set.
A zero observed FMR is not proof of zero operational false acceptance, especially
when the impostor-pair count is small. This report does not establish a production
threshold or demographic performance claim.

## Tests

The harness tests use deterministic in-memory embeddings and generated metadata;
they contain no face images or pretrained weights:

```bash
python -m pytest tests/ai-benchmark -q
python -m ruff check tests/ai-benchmark
python -m mypy tests/ai-benchmark
```
