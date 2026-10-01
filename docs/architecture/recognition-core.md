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
`MultiFrameDecisionEngine` is the configurable local implementation: it samples
before preprocessing and model inference, aggregates the best-quality frames per
stable upstream track ID, and resets evidence when the winning identity changes or
quality is unacceptable. It requires a configured count of agreeing frames, and
both each evidence frame and the selected-frame averages must pass configured Top-1
cosine and Top-1 minus Top-2 margin thresholds. Thresholds have no bundled
production defaults and must be calibrated from local benchmark data.

Liveness policy is also explicit configuration on `RecognitionPipeline`. Disabled
mode skips anti-spoof inference; enabled mode requires a model and an explicitly
calibrated live-score cutoff. When required, missing, inconclusive, and failing
scores block acceptance before embedding/matching, and the pipeline has a second
fail-closed guard against custom temporal engines that return an acceptance anyway.
When optional, liveness scores remain observational and are not a security gate.
`RecognitionDecision.liveness_score` carries the current failed score or the mean
score from selected track evidence.

`anti-spoof-mn3` is the ONNX Runtime evaluation candidate, not a cleared
production default: the source reports MIT licensing and Open Model Zoo metadata
lists Apache-2.0 for its converted artifact, but its training dataset agreement
limits dataset use to non-commercial research. The repository intentionally
includes no weights and performs no download. See [model provenance and deployment
constraints](../models.md#liveness-presentation-attack-detection).

Students generally do not bring phones on a normal school day, which reduces one
screen-replay route. It does not address printed images, other displays, or masks.
Production operation must have a legally cleared liveness detector or documented
physical/session controls, including for outages and uncertain scores.

An ambiguous margin yields domain state `retry_frontal` and machine status
`NEED_FRONTAL_RETRY`; it never auto-accepts that observation. The engine returns
recognition state only. Attendance remains a Core API/domain decision.

Stage contracts are Python protocols. OpenCV, ONNX Runtime, or other local inference
implementations can be swapped while keeping FaceDetection, FaceQuality,
FaceEmbedding, CandidateMatch, RecognitionDecision, and TrackDecision stable. The
default install has no external runtime dependencies; the optional `opencv` extra
provides OpenCV/NumPy. YuNet and SFace model paths must be supplied by the deployment
configuration. No model is downloaded at runtime; see [model provenance and usage](../models.md).

FaceEmbedding stores a model name/version and numeric vector, but this foundation
does not persist the vector. Similarity uses cosine-compatible [-1, 1] values.
Recognition confidence and face quality use [0, 1]; temporal match margin is
normalized to [0, 1] for the existing recognition-event contract.

Deterministic fake stages live in recognition_core.testing and are used by
framework-free unit tests. Production adapters must not import those fakes. The
OpenCV Zoo baseline adapts YuNet's five landmarks to SFace landmark alignment,
normalizes extracted SFace features, and ranks candidates by cosine similarity.
The matcher has no default identity threshold; temporal/business policy must use a
threshold calibrated from local evaluation data.
