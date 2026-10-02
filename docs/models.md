# Model assets

## Practical recommendation

For the current codebase, YuNet 2023mar plus SFace 2021dec are the pair already
supported by the shared recognition-core adapter. YuNet's directory states MIT;
SFace's directory states Apache-2.0. However, a public OpenCV Zoo issue asks for
clarification about the exact SFace ONNX weight's training-data provenance and
whether the directory license fully covers it; the issue is still open. Treat
SFace as **local development/evaluation only** until the school has reviewed
that question and approved deployment. The model pair is not calibrated for
this school and is not an approval to process student biometrics.

The current adapter targets OpenCV 4. OpenCV Zoo now also lists a newer dynamic
input YuNet artifact intended for OpenCV 5. Do not replace the current file as a
drop-in upgrade: first update and test the detector adapter, pin the OpenCV
runtime, run legal/provenance review, and repeat threshold calibration. Keep the
model version and checksum fixed across enrollment and inference.

Model weights are never fetched automatically at application runtime and are
not committed to Git. Run `python scripts/download_face_models.py` to download
the checksum-pinned OpenCV Zoo files into the ignored `models/weights/` folder.
The recommended pair is a practical evaluation baseline, not a production
selection. Test on lawfully collected data representative of camera height,
distance, lighting, motion, glasses, and the people the school has permission
to evaluate.

### Candidate choices

| Option | Detection + recognition | Repository status | Licensing / decision |
| --- | --- | --- | --- |
| OpenCV Zoo baseline | YuNet 2023mar + SFace 2021dec | Implemented and covered by recognition-core adapters | Best starting point for local evaluation because it is integrated. YuNet directory says MIT; SFace directory says Apache-2.0, but exact weight provenance/licensing remains an open question. Do not deploy SFace until reviewed. |
| InsightFace family | SCRFD + ArcFace-derived recognition, for example a public model package | Not integrated; would need an adapter, dependency/runtime pinning, compatibility tests and new calibration | InsightFace library code is MIT, but its public pretrained weights are licensed for non-commercial research. Do not assume school attendance use is covered; require separate written licensing clearance before evaluation for operations. |
| Licensed vendor or institution-approved model | Vendor-selected detector/recognizer and optional PAD | Not integrated; can be added behind existing detector/embedder/liveness protocols | Consider if the vendor provides clear deployment rights, provenance, support, security updates and acceptable processing terms. Require a technical benchmark and procurement/privacy review; a vendor claim alone is not proof of fit. |

Recommendation: use the existing OpenCV Zoo pair for a controlled, local,
non-production fit and robustness evaluation first. Do not spend time swapping
to a model advertised as state of the art until its weight license is usable,
its runtime fits the target PC/server, and it wins a reproducible test on the
school camera conditions. A model family name or public benchmark does not
establish recognition performance for this deployment.

The listed OpenCV Zoo folder licenses are useful provenance, but do not alone
approve processing student biometrics, settle every upstream/data-rights
question, or replace the school's own privacy and procurement review. Preserve
all model notices and separately record the exact weight source and any terms
that apply to those weights.

Do not select an acceptance threshold from internet examples or total accuracy.
Create genuine and impostor comparisons, inspect false match and false
non-match rates across candidate thresholds, and prioritize a low false
acceptance rate together with a documented manual fallback. Report relevant
conditions separately; image quality, lighting, height, angle, and demographic
groups can affect measured face-recognition errors. See the [NIST demographic
effects evaluation](https://pages.nist.gov/frvt/html/frvt_demographics.html)
and the [NIST report](https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.8280.pdf).

## OpenCV Zoo YuNet + SFace baseline

`libs/recognition-core` contains optional adapters for OpenCV Zoo's YuNet face
detector and SFace face recognizer. The adapter code does not fetch model files.
Each process must receive explicit local model paths through configuration or CLI
arguments, and deployments must control which versioned files are provisioned.

| Component | OpenCV Zoo model directory | Example asset name | Directory license |
| --- | --- | --- | --- |
| Face detection | [face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | `face_detection_yunet_2023mar.onnx` | MIT |
| Face recognition | [face_recognition_sface](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | `face_recognition_sface_2021dec.onnx` | Directory says Apache-2.0; exact pretrained-weight provenance is under clarification. |

Pinned artifact checksums used by the downloader:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `face_detection_yunet_2023mar.onnx` | 232,589 bytes | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `face_recognition_sface_2021dec.onnx` | 38,696,353 bytes | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

The downloader reads the official OpenCV Zoo Git LFS artifacts and rejects
size/checksum mismatches. The SFace directory's Apache-2.0 notice is included
upstream, but it does not answer every question raised about training data and
the exact pretrained weights. See [OpenCV Zoo issue #313](https://github.com/opencv/opencv_zoo/issues/313).

The model directory README/license is the provenance source for the corresponding
asset. Keep those notices with any distributed model files. Do not commit model
weights to this repository unless distribution, provenance, and license obligations
have been reviewed. The SFace ONNX conversion is attributed by OpenCV Zoo to its
upstream project; the model README contains the additional references.

## Runtime and configuration

Install the optional runtime dependency with:

```bash
python -m pip install -e "libs/recognition-core[opencv]"
```

The adapters use OpenCV's `FaceDetectorYN` and `FaceRecognizerSF` APIs. YuNet returns
a box, five facial landmarks, and a detector score. SFace alignment uses the five
landmarks; the resulting feature vector is L2-normalized before it becomes a
`FaceEmbedding`. Embeddings from different model names/versions or dimensions are
not compared.

Pass model paths explicitly. For example:

```bash
recognition-core compare enrollment.jpg probe.jpg --yunet-model ./models/face_detection_yunet_2023mar.onnx --sface-model ./models/face_recognition_sface_2021dec.onnx
```

The SFace model version in CLI output is the configured model filename without its
extension. Service deployments should persist an explicit model version alongside
each face template, instead of relying on a mutable path or latest download.

The cosine matcher orders candidates but has no default acceptance threshold. The
CLI's optional `--threshold` only reports the result for a value supplied by the
operator; it does not assert that value is suitable for attendance. Calibrate any
future threshold on representative, lawfully collected local evaluation data and
review false-match/false-nonmatch results before selecting an operational policy.

## Liveness / presentation-attack detection

### Evaluation-only candidate: Open Model Zoo anti-spoof-mn3

No liveness model has been selected or approved for operational use. The
integration has an evaluation-only MobileNetV3 anti-spoof-mn3 adapter. It is a
single-frame face anti-spoof classifier trained on
CelebA-Spoof. The model card reports 3.02 million parameters, 0.15 GFLOPs and
3.81% ACER on its reported evaluation; those figures are not a result for our
cameras, lighting, student population, or deployment hardware. The Open Model Zoo
artifact is ONNX, with a 128×128 RGB NCHW input normalized by published per-channel
mean and scale values and probabilities ordered `[live, spoof]`.

**License/deployment warning:** The original model/source repository identifies
MIT licensing; the Open Model Zoo model metadata identifies Apache-2.0 for its
downloaded ONNX artifact, and the Open Model Zoo repository is Apache-2.0.
Separately, the official CelebA-Spoof agreement restricts dataset use to
non-commercial research and prohibits commercial use of the images and derived
data. Those terms do not clearly resolve whether model weights trained on that
dataset may be deployed in routine school attendance or redistributed. Treat this
candidate and weights as **not cleared for operational attendance or
redistribution** until the institution has reviewed weight provenance and obtained
any needed written permission or legal clearance. No pretrained weights are
included in this repository, fetched at runtime, or approved as a production
default. Keep liveness disabled in example configuration until that review,
hardware evaluation, and local score calibration are complete. Until then,
follow an approved supervised session/physical control and manual attendance
fallback.

The package provides an optional `ONNXRuntimeAntiSpoofMN3` adapter for locally
provisioned `.onnx` files. It does no downloads; the local weights and model
version must be supplied by deployment configuration. Install its optional runtime
with:

```bash
python -m pip install -e "libs/recognition-core[antispoof]"
```

The adapter performs the RGB resize and normalization specified by the model
metadata and emits the live-class probability as `LivenessDecision.live_score`.
CPU is the default execution provider. Other providers must be installed and
explicitly configured for the target hardware; no performance is assumed.

The score cutoff is an explicit `LivenessConfig.min_live_score`; there is no
bundled production value. Calibrate it with authorized, representative
presentation-attack samples and measure false acceptance and false rejection
separately. `required=True` makes missing, inconclusive, or below-cutoff scores
block identity acceptance. `required=False` is an advisory/shadow mode and does
not provide a security gate. Production must enable a cleared detector or use
documented physical/session controls whenever camera liveness is unavailable.

The integration can be configured as follows (use a locally calibrated value and
a legally cleared asset before production):

```python
from recognition_core import LivenessConfig, ONNXRuntimeAntiSpoofMN3

liveness_config = LivenessConfig(
    enabled=True,
    required=True,
    min_live_score=calibrated_live_score,
)
liveness_model = ONNXRuntimeAntiSpoofMN3(
    model_path=local_onnx_model_path,
    model_version="provisioned-version",
)
```

In `AI_EDGE`, inference runs on the lab PC and must be benchmarked there. In
`AI_CENTRAL`, inference runs on the central AI server; the STB remains a camera
gateway and does not need ONNX Runtime. Student phones being unavailable on ordinary
school days lowers one replay opportunity, but it does not prevent printed-photo,
other-display, or mask attacks. Keep an operational control such as supervised
session entry or another physical/session check even when liveness is enabled.

## Data and test policy

No face photographs, student records, pretrained weights, or external face dataset
are included. Adapter tests use in-memory generated arrays and mocked OpenCV model
outputs. A hardware/model integration check requires locally provisioned weights
and lawfully collected test images; run it only in an environment authorized to
process those images. Never use real student/minor images in cloud CI.

## References

- [YuNet model README and license](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/README.md)
- [YuNet directory MIT license](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE)
- [SFace model README](https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/README.md)
- [SFace directory license](https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/LICENSE)
- [Open question about SFace weight provenance and use](https://github.com/opencv/opencv_zoo/issues/313)
- [InsightFace model zoo and pretrained-model license terms](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md)
- [NIST face-recognition demographic evaluation](https://pages.nist.gov/frvt/html/frvt_demographics.html)
- [OpenCV DNN face detection and recognition tutorial](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html)
- [Open Model Zoo `anti-spoof-mn3` model card and model license](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/public/anti-spoof-mn3/README.md)
- [Open Model Zoo `anti-spoof-mn3` artifact metadata and license](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/public/anti-spoof-mn3/model.yml)
- [Original lightweight anti-spoof source and MIT license](https://github.com/kprokofi/light-weight-face-anti-spoofing)
- [Official CelebA-Spoof agreement](https://mmlab.ie.cuhk.edu.hk/projects/CelebA/CelebA_Spoof.html)
- [ONNX Runtime execution providers](https://onnxruntime.ai/docs/execution-providers/)
