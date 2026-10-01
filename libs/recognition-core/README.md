# Recognition Core

Python package for the shared face-recognition pipeline used by AI_EDGE and
AI_CENTRAL. Domain contracts and pipeline orchestration remain framework-independent.
Optional OpenCV Zoo adapters provide a YuNet detector, SFace alignment/embedder, and
cosine matcher. Frames stay transient and are not retained by the package.

## Pipeline contract

RecognitionPipeline delegates these steps in order:

1. preprocess
2. detect
3. assess face quality
4. align
5. evaluate liveness
6. create embedding
7. match against the supplied session gallery
8. make a temporal track decision

The pipeline avoids embedding and matching when detection, quality, or liveness does
not permit those stages. TemporalDecisionEngine owns multi-frame policy, thresholds,
and retry/frontal behavior; this interface layer does not choose a production
threshold or accept an attendance record.

`MultiFrameDecisionEngine` is the configurable implementation. It gates sampling
before preprocessing/model inference, keeps evidence by upstream `track_id`, and
uses only the highest-quality configured N frames. A sampled Top-1 identity change
clears the old evidence. Acceptance requires the configured same-identity frame
count; each evidence frame and the selected-frame averages must pass the configured
Top-1 similarity threshold and Top-1 minus Top-2 margin. An ambiguous sampled frame
exposes status `NEED_FRONTAL_RETRY`; domain state remains `retry_frontal`. Top-1 and
margin thresholds must be supplied by configuration and calibrated on local
benchmark data.

```python
from recognition_core import MultiFrameDecisionEngine, TemporalDecisionConfig

temporal = MultiFrameDecisionEngine(
    TemporalDecisionConfig(
        min_top1_similarity=calibrated_top1_threshold,
        min_top1_top2_margin=calibrated_margin,
        sample_every_n_frames=2,
        minimum_agreeing_frames=3,
        best_frame_count=5,
    )
)
```

The input `FrameObservation.track_id` must come from a stable upstream tracker, and
one engine instance should be used per camera stream. A changed Top-1 identity or
poor quality clears accumulated evidence; track state also expires after the
configured idle timeout. Normalized decision confidence is a mapped cosine score,
not a calibrated probability. Temporal matching only returns recognition state;
the Core API remains responsible for attendance decisions.

## Replaceable stages

Preprocessor, FaceDetector, FaceQualityAssessor, FaceAligner, LivenessModel,
FaceEmbedder, Matcher, and TemporalDecisionEngine are structural Python protocols.
Implementations can wrap OpenCV, ONNX Runtime, or another compatible local runtime
without changing domain objects or caller APIs. The Core API remains the only
authority for attendance decisions. Adapter and model setup is documented in
[`docs/models.md`](../../docs/models.md).

## Domain objects

The package exports immutable values for face boxes/landmarks, quality signals,
versioned embeddings, candidate similarities, recognition outcomes, liveness, frame
observations, and track decisions. Similarity supports cosine values from -1 to 1.
Decision confidence and quality scores use the unit interval; temporal margin is a
normalized 0–1 value.

recognition_core.testing provides deterministic fakes for each stage. Tests generate
synthetic in-memory inputs; no face images, student data, or pretrained weights are
bundled. OpenCV and NumPy are optional package dependencies and are imported only by
the OpenCV adapters.

## YuNet + SFace baseline

Install the optional runtime and provision the model files separately:

```bash
python -m pip install -e "libs/recognition-core[opencv]"
recognition-core compare image-a.jpg image-b.jpg --yunet-model models/face_detection_yunet_2023mar.onnx --sface-model models/face_recognition_sface_2021dec.onnx
```

The CLI reports cosine similarity only unless `--threshold` is supplied. It does
not provide a production attendance decision or choose a calibrated threshold.
Folder benchmarks use one subfolder per identity and compare all pairs. Keep local
benchmark data lawfully collected and outside Git; the CLI reports aggregate scores
without printing folder labels or embeddings.

```bash
recognition-core benchmark ./local-benchmark --yunet-model ./models/yunet.onnx --sface-model ./models/sface.onnx
```

## Development

Run the unit suite from the repository root with:

- python -m pytest libs/recognition-core/tests
- python -m ruff check libs/recognition-core
- python -m mypy

OpenCV adapter tests use mocked OpenCV APIs and generated synthetic arrays, so the
unit suite does not download weights or require camera hardware. For an actual model
smoke check, supply locally provisioned model assets and lawfully collected images.
