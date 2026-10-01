# Recognition Core

Framework-independent Python package for the shared face-recognition pipeline used
by AI_EDGE and AI_CENTRAL. It does not import FastAPI, OpenCV, or a model runtime.
Frames stay as opaque inputs at this layer boundary, and no image is retained.

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

## Replaceable stages

Preprocessor, FaceDetector, FaceQualityAssessor, FaceAligner, LivenessModel,
FaceEmbedder, Matcher, and TemporalDecisionEngine are structural Python protocols.
Implementations can wrap OpenCV, ONNX Runtime, or another compatible local runtime
without changing domain objects or caller APIs. The Core API remains the only
authority for attendance decisions.

## Domain objects

The package exports immutable values for face boxes/landmarks, quality signals,
versioned embeddings, candidate similarities, recognition outcomes, liveness, frame
observations, and track decisions. Similarity supports cosine values from -1 to 1.
Decision confidence and quality scores use the unit interval; temporal margin is a
normalized 0–1 value.

recognition_core.testing provides deterministic fakes for each stage. Use synthetic
values only; no face images, student data, or pretrained weights are bundled.

## Development

Run the unit suite from the repository root with:

- python -m pytest libs/recognition-core/tests
- python -m ruff check libs/recognition-core
- python -m mypy
