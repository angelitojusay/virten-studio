"""High-resolution face analysis for culling: expression, gaze, head angle and eye focus for every face.

The main photo analysis looks at a ~1000 px preview, where faces are small. For choosing between frames of a burst
of people, this decodes the camera's embedded JPEG at 2880 px (Sony and most cameras embed a full-size one), finds
faces (whole frame plus overlapping tiles for small faces) and keeps MediaPipe's 52 expression scores, head
yaw/pitch/roll, and sharpness of the eyes, face and mouth. Results are cached per file."""
import io
import math
import os
import sqlite3
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

import cv2
import numpy as np
import rawpy
from PIL import Image

from .paths import cache_dir

FACE_VERSION = 1
SIDE = 2880
N_BLEND = 52
L_EYE = [33, 133, 159, 145, 160, 144, 158, 153]  # MediaPipe face-mesh landmarks
R_EYE = [362, 263, 386, 374, 385, 380, 387, 373]
MOUTH = [61, 291, 13, 14, 0, 17]
_local = threading.local()


def names(blend_names):
    return (["n_faces"] + [f"main_{b}" for b in blend_names] + [f"group_{b}" for b in blend_names] +
            ["main_area", "main_cx", "main_cy", "main_eye_sharp", "main_face_sharp", "main_mouth_sharp", "yaw", "pitch",
             "roll", "n_big", "max_blink_big", "min_smile_big", "mean_smile_big", "min_eye_sharp_big"])


N_FEATURES = 1 + 2 * N_BLEND + 14


def _landmarker():
    if not hasattr(_local, "lm"):
        import mediapipe as mp
        from .vision import _model_bytes
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=_model_bytes("face_landmarker.task")),
            running_mode=mp.tasks.vision.RunningMode.IMAGE, num_faces=12, output_face_blendshapes=True,
            output_facial_transformation_matrixes=True, min_face_detection_confidence=0.4,
            min_face_presence_confidence=0.4)
        _local.lm = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
    return _local.lm


def _lapvar(gray, xs, ys, pad):
    x0, x1 = int(max(0, min(xs) - pad)), int(min(gray.shape[1], max(xs) + pad))
    y0, y1 = int(max(0, min(ys) - pad)), int(min(gray.shape[0], max(ys) + pad))
    crop = gray[y0:y1, x0:x1]
    if crop.size < 64:
        return np.nan
    return math.log1p(float(cv2.Laplacian(crop, cv2.CV_32F).var()))


def _angles(mat):
    R = np.asarray(mat)[:3, :3]
    yaw = math.degrees(math.atan2(-R[2, 0], math.hypot(R[0, 0], R[1, 0])))
    pitch = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    roll = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return yaw, pitch, roll


def _load(path):
    with rawpy.imread(path) as r:
        flip = r.sizes.flip
        try:
            th = r.extract_thumb()
            jpeg = th.format == rawpy.ThumbFormat.JPEG
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            th, jpeg = None, False
        if jpeg:
            im = Image.open(io.BytesIO(th.data))
            im.draft("RGB", (SIDE, SIDE))
            im = im.convert("RGB")
            im.thumbnail((SIDE, SIDE))
            rgb = np.asarray(im)
        else:
            rgb = r.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            s = SIDE / max(rgb.shape[:2])
            if s < 1:
                rgb = cv2.resize(rgb, (int(rgb.shape[1] * s), int(rgb.shape[0] * s)), interpolation=cv2.INTER_AREA)
            flip = 0  # LibRaw already rotated it
    if flip == 3:
        rgb = np.rot90(rgb, 2)
    elif flip == 5:
        rgb = np.rot90(rgb, 1)
    elif flip == 6:
        rgb = np.rot90(rgb, -1)
    return np.ascontiguousarray(rgb)


def _find_faces(rgb):
    """[(landmark xs, ys, blendshapes, transform matrix)] for every face: the whole frame plus overlapping tiles, so
    small faces in group photos are found too."""
    import mediapipe as mp
    h, w = rgb.shape[:2]
    found = []
    th, tw = int(h * 0.6), int(w * 0.6)
    tiles = [(0, 0, w, h)] + [(ox, oy, tw, th) for oy in (0, h - th) for ox in (0, w - tw)] + \
            [((w - tw) // 2, (h - th) // 2, tw, th)]
    for ox, oy, cw, ch in tiles:
        r = _landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                          data=np.ascontiguousarray(rgb[oy:oy + ch, ox:ox + cw])))
        for k, lms in enumerate(r.face_landmarks):
            xs = np.array([p.x for p in lms]) * cw + ox
            ys = np.array([p.y for p in lms]) * ch + oy
            fw0 = xs.max() - xs.min()
            if any(abs(xs.mean() - f[0].mean()) < fw0 * 0.5 and abs(ys.mean() - f[1].mean()) < fw0 * 0.5 for f in found):
                continue
            mats = r.facial_transformation_matrixes
            found.append((xs, ys, r.face_blendshapes[k], mats[k] if mats else None))
    return found


def extract_face_crops(path, max_faces=4, crop_size=140):
    """Close-ups for checking eyes and focus while culling: up to max_faces faces (largest first), each a square
    crop_size RGB crop centred on the eyes of the 2880 px camera preview, at 100 % when the eyes fit (else scaled down
    just enough to show both). Returns [{"crop", "blink", "smile", "eye_sharp", "area", "zoom"}]."""
    rgb = _load(path)
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    out = []
    for xs, ys, shapes, _ in _find_faces(rgb):
        fw = xs.max() - xs.min()
        bs = {s.category_name: s.score for s in shapes}
        ex, ey = np.concatenate([xs[L_EYE], xs[R_EYE]]), np.concatenate([ys[L_EYE], ys[R_EYE]])
        side = int(min(max(crop_size, (ex.max() - ex.min()) * 1.5), w, h))
        cx, cy = float(ex.mean()), float(ey.mean())
        x0 = int(min(max(cx - side / 2, 0), w - side))
        y0 = int(min(max(cy - side / 2, 0), h - side))
        crop = rgb[y0:y0 + side, x0:x0 + side]
        if side != crop_size:
            crop = cv2.resize(crop, (crop_size, crop_size), interpolation=cv2.INTER_AREA if side > crop_size
                              else cv2.INTER_CUBIC)
        out.append({"crop": np.ascontiguousarray(crop), "zoom": crop_size / side,
                    "blink": max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)),
                    "smile": (bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0)) / 2,
                    "eye_sharp": float(np.nanmax([_lapvar(gray, xs[L_EYE], ys[L_EYE], fw * 0.06),
                                                  _lapvar(gray, xs[R_EYE], ys[R_EYE], fw * 0.06)])),
                    "area": float(fw * (ys.max() - ys.min()) / (w * h))})
    out.sort(key=lambda f: -f["area"])
    return out[:max_faces]


def analyse(path):
    """Feature vector (N_FEATURES floats) for one photo; n_faces = 0 and NaNs when there's nobody in it."""
    rgb = _load(path)
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    found = _find_faces(rgb)
    faces = []
    for xs, ys, shapes, mat in found:
        fw = xs.max() - xs.min()
        bs = {s.category_name: s.score for s in shapes}
        faces.append({
            "area": fw * (ys.max() - ys.min()) / (w * h), "cx": xs.mean() / w, "cy": ys.mean() / h,
            "bs": np.array([s.score for s in shapes], np.float32)[:N_BLEND],
            "blink": max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)),
            "smile": (bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0)) / 2,
            "eye_sharp": np.nanmax([_lapvar(gray, xs[L_EYE], ys[L_EYE], fw * 0.06),
                                    _lapvar(gray, xs[R_EYE], ys[R_EYE], fw * 0.06)]),
            "face_sharp": _lapvar(gray, xs, ys, 0), "mouth_sharp": _lapvar(gray, xs[MOUTH], ys[MOUTH], fw * 0.05),
            "angles": _angles(mat) if mat is not None else (np.nan, np.nan, np.nan)})
    if not faces or any(len(f["bs"]) < N_BLEND for f in faces):
        return np.array([0.0] + [np.nan] * (N_FEATURES - 1), np.float32)
    faces.sort(key=lambda f: -f["area"])
    m = faces[0]
    big = [f for f in faces if f["area"] >= 0.25 * m["area"]]  # the people who matter in the frame
    return np.array([len(faces)] + list(m["bs"]) + list(np.mean([f["bs"] for f in big], 0)) + [
        m["area"], m["cx"], m["cy"], m["eye_sharp"], m["face_sharp"], m["mouth_sharp"], *m["angles"],
        len(big), max(f["blink"] for f in big), min(f["smile"] for f in big), float(np.mean([f["smile"] for f in big])),
        float(np.nanmin([f["eye_sharp"] for f in big]))], np.float32)


class FaceCache:
    def __init__(self):
        self.db = sqlite3.connect(os.path.join(cache_dir(), "faces.sqlite"))
        # WAL: readers don't block the writer and commits are much cheaper (a cache can afford synchronous=NORMAL).
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("pragma synchronous=NORMAL")
        self.db.execute("create table if not exists faces (path text primary key, mtime real, size integer, "
                        "version integer, data blob)")
        self.db.execute("create index if not exists faces_mtime_size on faces (mtime, size)")

    def get(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        r = self.db.execute("select mtime, size, version, data from faces where path=?", (path,)).fetchone()
        if r and r[0] == st.st_mtime and r[1] == st.st_size and r[2] == FACE_VERSION:
            return np.frombuffer(r[3], dtype=np.float32).copy()
        # Drive-portable: the same file analysed at another path (moved shoot); re-key it to the new path.
        name = os.path.basename(path).lower()
        for old, data in self.db.execute("select path, data from faces where mtime=? and size=? and version=?",
                                         (st.st_mtime, st.st_size, FACE_VERSION)):
            if old != path and os.path.basename(old).lower() == name:
                self.db.execute("insert or replace into faces values (?,?,?,?,?)",
                                (path, st.st_mtime, st.st_size, FACE_VERSION, data))
                return np.frombuffer(data, dtype=np.float32).copy()
        return None

    def put(self, path, vec):
        st = os.stat(path)
        self.db.execute("insert or replace into faces values (?,?,?,?,?)",
                        (path, st.st_mtime, st.st_size, FACE_VERSION, vec.astype(np.float32).tobytes()))

    def close(self):
        self.db.commit()
        self.db.close()


def _init_worker():
    cv2.setNumThreads(1)


def _job(path):
    try:
        return analyse(path)
    except Exception as e:  # unreadable file: left out
        return e


def analyse_many(paths, progress=None, cancelled=lambda: False):
    """{path: vector} for every readable path, cached; analysed in parallel processes."""
    from .features import worker_count
    cache = FaceCache()
    out, todo = {}, []
    for p in paths:
        v = cache.get(p)
        if v is not None and len(v) == N_FEATURES:
            out[p] = v
        else:
            todo.append(p)
    done = [len(paths) - len(todo)]
    if progress:
        progress(done[0], len(paths), "Reading faces")

    def run(executor_cls, jobs, **kw):
        with executor_cls(worker_count(), **kw) as ex:
            futs = {ex.submit(_job, p): p for p in jobs}
            for fut in as_completed(futs):
                if cancelled():
                    ex.shutdown(wait=False, cancel_futures=True)
                    return
                res = fut.result()
                p = futs[fut]
                if not isinstance(res, Exception):
                    out[p] = res
                    cache.put(p, res)
                done[0] += 1
                if progress:
                    progress(done[0], len(paths), "Reading faces")

    try:
        if todo:
            try:
                if len(todo) < 12:
                    raise BrokenProcessPool
                run(ProcessPoolExecutor, todo, initializer=_init_worker)
            except (BrokenProcessPool, OSError, RuntimeError):
                run(ThreadPoolExecutor, [p for p in todo if p not in out])
    finally:
        cache.close()
    return out
