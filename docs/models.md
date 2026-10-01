# Model assets

## OpenCV Zoo YuNet + SFace baseline

`libs/recognition-core` contains optional adapters for OpenCV Zoo's YuNet face
detector and SFace face recognizer. The adapter code does not fetch model files.
Each process must receive explicit local model paths through configuration or CLI
arguments, and deployments must control which versioned files are provisioned.

| Component | OpenCV Zoo model directory | Example asset name | Directory license |
| --- | --- | --- | --- |
| Face detection | [face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | `face_detection_yunet_2023mar.onnx` | MIT |
| Face recognition | [face_recognition_sface](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | `face_recognition_sface_2021dec.onnx` | Apache-2.0 |

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
- [OpenCV DNN face detection and recognition tutorial](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html)
