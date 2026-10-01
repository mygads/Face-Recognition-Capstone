# Recognition Core

The shared Python package at libs/recognition-core owns framework-neutral domain
values and the ordered image-to-track pipeline boundary. It is imported by both
AI_EDGE edge inference and AI_CENTRAL inference. It must not depend on FastAPI or
own API, attendance, camera transport, or persistence rules.

The RecognitionPipeline calls preprocess, detect, quality assessment, alignment,
liveness, embedding, gallery matching, and temporal decision in that order. Unsafe
or insufficient frames stop before expensive or sensitive later stages. The temporal
decision engine owns tracking windows, match thresholds, ambiguity policy, and
frontal retry behavior; the pipeline foundation leaves those policies replaceable.

Stage contracts are Python protocols. OpenCV, ONNX Runtime, or other local inference
implementations can be swapped while keeping FaceDetection, FaceQuality,
FaceEmbedding, CandidateMatch, RecognitionDecision, and TrackDecision stable. The
package currently has no external runtime dependencies and downloads no model.

FaceEmbedding stores a model name/version and numeric vector, but this foundation
does not persist the vector. Similarity uses cosine-compatible [-1, 1] values.
Recognition confidence and face quality use [0, 1]; temporal match margin is
normalized to [0, 1] for the existing recognition-event contract.

Deterministic fake stages live in recognition_core.testing and are used by
framework-free unit tests. Production adapters must not import those fakes.
