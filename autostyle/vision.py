"""Neural-network vision models.

- MediaPipe Face Landmarker: every face, with per-eye blink and smile scores (CPU, ~10 ms per face).
- MediaPipe multiclass selfie segmentation: people / skin / hair / clothes mask, so exposure and focus can be
  measured on the subject rather than the whole frame (CPU).
- CLIP ViT-B/32 image encoder (ONNX): a 512-number "what is this scene" description used by the editing and
  quality measurements. Runs on the best accelerator ONNX Runtime finds: DirectML (any DX12 GPU on Windows), CUDA,
  or CoreML (Apple Silicon), falling back to the CPU.

MediaPipe models are loaded once per worker process; CLIP runs batched in the main process on the GPU."""
import os
import threading

# Keep MediaPipe/TensorFlow Lite's C++ logging quiet (it writes straight to stderr from every worker process).
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import cv2  # noqa: E402
import numpy as np

from .paths import resource_dir

MODELS = os.path.join(resource_dir(), "models")
CLIP_SIZE = 224
CLIP_DIM = 512
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_ACCEL_ORDER = ("CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider")
_local = threading.local()
_clip = {"session": None, "lock": threading.Lock()}


def _model_bytes(name):
    # Read into memory: MediaPipe can't open paths with some non-ASCII characters on Windows.
    with open(os.path.join(MODELS, name), "rb") as f:
        return f.read()


# ---------------------------------------------------------------- faces

def _landmarker():
    if not hasattr(_local, "faces"):
        import mediapipe as mp
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=_model_bytes("face_landmarker.task")),
            running_mode=mp.tasks.vision.RunningMode.IMAGE, num_faces=16, output_face_blendshapes=True,
            min_face_detection_confidence=0.45, min_face_presence_confidence=0.45)
        _local.faces = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
    return _local.faces


def _detect(rgb, ox=0, oy=0, full=None):
    import mediapipe as mp
    h, w = rgb.shape[:2]
    fw, fh = full if full else (w, h)
    res = _landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    faces = []
    for lms, shapes in zip(res.face_landmarks, res.face_blendshapes or [[]] * len(res.face_landmarks)):
        xs = np.array([p.x for p in lms]) * w + ox
        ys = np.array([p.y for p in lms]) * h + oy
        score = {s.category_name: s.score for s in shapes}
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        faces.append({
            "box": (max(0, int(x0)), max(0, int(y0)), int(x1 - x0), int(y1 - y0)),
            "area": (x1 - x0) * (y1 - y0) / (fw * fh),
            "blink": max(score.get("eyeBlinkLeft", 0), score.get("eyeBlinkRight", 0)),
            "blink_both": min(score.get("eyeBlinkLeft", 0), score.get("eyeBlinkRight", 0)),
            "smile": (score.get("mouthSmileLeft", 0) + score.get("mouthSmileRight", 0)) / 2,
        })
    return faces


def find_faces(rgb, people_frac=0.0):
    """All faces with blink/smile scores. For likely group photos, small faces are found by also scanning
    overlapping quarters of the frame at higher effective resolution."""
    faces = _detect(rgb)
    h, w = rgb.shape[:2]
    if people_frac > 0.08 and (len(faces) == 0 or len(faces) >= 3 or max(f["area"] for f in faces) < 0.01):
        th, tw = int(h * 0.6), int(w * 0.6)
        for oy in (0, h - th):
            for ox in (0, w - tw):
                for f in _detect(rgb[oy:oy + th, ox:ox + tw], ox, oy, (w, h)):
                    cx, cy = f["box"][0] + f["box"][2] / 2, f["box"][1] + f["box"][3] / 2
                    if not any(abs(cx - (g["box"][0] + g["box"][2] / 2)) < g["box"][2] / 2 and
                               abs(cy - (g["box"][1] + g["box"][3] / 2)) < g["box"][3] / 2 for g in faces):
                        faces.append(f)
    return faces


# ---------------------------------------------------------------- people segmentation

def _segmenter():
    if not hasattr(_local, "seg"):
        import mediapipe as mp
        opts = mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=_model_bytes("selfie_multiclass_256x256.tflite")),
            running_mode=mp.tasks.vision.RunningMode.IMAGE, output_category_mask=True, output_confidence_masks=False)
        _local.seg = mp.tasks.vision.ImageSegmenter.create_from_options(opts)
    return _local.seg


def segment_people(rgb):
    """Category mask the size of rgb: 0 background, 1 hair, 2 body skin, 3 face skin, 4 clothes, 5 other."""
    import mediapipe as mp
    res = _segmenter().segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    mask = res.category_mask.numpy_view()
    if mask.shape[:2] != rgb.shape[:2]:
        mask = cv2.resize(mask, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_NEAREST)
    return mask.reshape(rgb.shape[:2])


# ---------------------------------------------------------------- CLIP scene embeddings

def clip_input(rgb):
    """224x224 centre crop as uint8 (small enough to send between processes)."""
    h, w = rgb.shape[:2]
    s = CLIP_SIZE / min(h, w)
    im = cv2.resize(rgb, (max(CLIP_SIZE, round(w * s)), max(CLIP_SIZE, round(h * s))), interpolation=cv2.INTER_AREA)
    y0, x0 = (im.shape[0] - CLIP_SIZE) // 2, (im.shape[1] - CLIP_SIZE) // 2
    return np.ascontiguousarray(im[y0:y0 + CLIP_SIZE, x0:x0 + CLIP_SIZE])


def accelerator():
    """(provider list, human-readable device) for ONNX Runtime on this machine."""
    import onnxruntime as ort
    avail = ort.get_available_providers()
    for p in _ACCEL_ORDER:
        if p in avail:
            name = {"CUDAExecutionProvider": "NVIDIA GPU (CUDA)", "DmlExecutionProvider": "GPU (DirectML)",
                    "CoreMLExecutionProvider": "Apple Neural Engine / GPU (CoreML)"}[p]
            return [p, "CPUExecutionProvider"], name
    return ["CPUExecutionProvider"], "CPU"


def _clip_session():
    with _clip["lock"]:
        if _clip["session"] is None:
            import onnxruntime as ort
            providers, _ = accelerator()
            path = os.path.join(MODELS, "clip_vision.onnx")
            try:
                _clip["session"] = ort.InferenceSession(path, providers=providers)
            except Exception:  # GPU driver problem: run on the CPU instead
                _clip["session"] = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return _clip["session"]


def clip_embed(batch):
    """batch: list of 224x224x3 uint8 → (n, 512) unit-length float32 embeddings."""
    if not batch:
        return np.zeros((0, CLIP_DIM), np.float32)
    x = (np.stack(batch).astype(np.float32) / 255.0 - _CLIP_MEAN) / _CLIP_STD
    x = x.transpose(0, 3, 1, 2)
    sess = _clip_session()
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    return (out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-8)).astype(np.float32)
