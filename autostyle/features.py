"""Image features computed from a RAW file's embedded camera preview plus catalog EXIF.

The embedded JPEG is what the camera rendered at its as-shot settings, which is
exactly the "before" state an editor reacts to. Features are cached on disk."""
import hashlib
import io
import math
import os
import shutil
import sqlite3
import threading
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

import cv2
import numpy as np
import rawpy
from PIL import Image

from . import vision
from .paths import cache_dir

FEATURE_VERSION = 5
cv2.setNumThreads(1)  # we parallelise across photos instead; avoids oversubscribing the CPU
THUMB_SIZE = 360
LINE_SIDE = 1024
_local = threading.local()


def load_preview(path, max_side=512):
    """Return (rgb uint8 HxWx3, camera wb (r/g, b/g), libraw flip code) for a RAW file."""
    with rawpy.imread(path) as raw:
        wb = list(raw.camera_whitebalance or [1, 1, 1, 1])
        flip = raw.sizes.flip
        try:
            th = raw.extract_thumb()
            if th.format == rawpy.ThumbFormat.JPEG:
                im = Image.open(io.BytesIO(th.data))
                im.draft("RGB", (max_side, max_side))
                im = im.convert("RGB")
                im.thumbnail((max_side, max_side))
                rgb = np.asarray(im)
            else:
                rgb = np.asarray(Image.fromarray(th.data).convert("RGB"))
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, no_auto_bright=True, output_bps=8)
    if max(rgb.shape[:2]) > max_side:
        s = max_side / max(rgb.shape[:2])
        rgb = cv2.resize(rgb, (int(rgb.shape[1] * s), int(rgb.shape[0] * s)), interpolation=cv2.INTER_AREA)
    # Embedded previews are stored unrotated; apply the camera orientation.
    if flip == 3:
        rgb = np.rot90(rgb, 2)
    elif flip == 5:
        rgb = np.rot90(rgb, 1)
    elif flip == 6:
        rgb = np.rot90(rgb, -1)
    g = wb[1] or 1.0
    return np.ascontiguousarray(rgb), (wb[0] / g, wb[2] / g), flip


def _names():
    n = [f"lum_hist_{i}" for i in range(32)]
    n += [f"lum_p{p}" for p in (1, 5, 10, 25, 50, 75, 90, 95, 99)]
    n += ["lum_mean", "lum_std", "clip_hi", "clip_lo", "r_mean", "g_mean", "b_mean", "r_std", "g_std", "b_std",
          "L_mean", "a_mean", "b_lab_mean", "a_std", "b_lab_std", "sat_mean", "sat_std", "sat_p90"]
    n += [f"hue_hist_{i}" for i in range(12)]
    n += [f"grid_{i}" for i in range(16)]
    n += ["center_minus_mean", "top_minus_bottom", "skin_frac", "skin_lum", "skin_a", "skin_b",
          "face_count", "face_area", "face_lum", "face_a", "face_b", "sharpness", "edge_density",
          "wb_r", "wb_b", "log_iso", "aperture", "shutter", "focal", "flash", "camera_id", "aspect"]
    n += ["subj_frac", "subj_lum", "subj_minus_bg", "subj_sharp", "smile_mean"]
    n += ["tilt_h", "tilt_h_len", "tilt_v", "tilt_v_len", "tilt_all", "tilt_all_mean", "tilt_spread", "flip"]
    n += ["c_sharp", "c_sharp_max_tile", "c_sharp_p75_tile", "c_sharp_min_tile", "c_motion", "c_faces",
          "c_faces_closed", "c_closed_frac", "c_blink_max", "c_eyes", "c_smile", "c_face_sharp", "c_face_rel",
          "c_min_face_sharp"]
    return n


BASE_NAMES = _names()
CLIP_NAMES = [f"clip_{i}" for i in range(512)]
FEATURE_NAMES = BASE_NAMES + CLIP_NAMES


def _weighted_median(values, weights):
    order = np.argsort(values)
    v, w = values[order], weights[order]
    c = np.cumsum(w)
    return float(v[np.searchsorted(c, c[-1] / 2)])


def tilt_features(gray):
    """How far near-horizontal and near-vertical lines lean from level, in degrees (length-weighted)."""
    h, w = gray.shape
    lines = _lsd().detect(gray)[0]
    if lines is None:
        return [np.nan, 0, np.nan, 0, np.nan, np.nan, np.nan]
    x1, y1, x2, y2 = lines.reshape(-1, 4).T
    length = np.hypot(x2 - x1, y2 - y1)
    keep = length > 0.04 * max(h, w)
    ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))[keep]
    length = length[keep]
    ang = (ang + 90) % 180 - 90  # (-90, 90]
    horiz = np.abs(ang) < 12
    vert = np.abs(ang) > 78
    dev_v = ang - np.sign(ang) * 90
    out = []
    for mask, dev in ((horiz, ang), (vert, dev_v)):
        if mask.sum() >= 2:
            out += [_weighted_median(dev[mask], length[mask]), length[mask].sum() / max(h, w)]
        else:
            out += [np.nan, 0]
    both = horiz | vert
    if both.sum() >= 2:
        dev_all = np.where(horiz, ang, dev_v)[both]
        wts = length[both]
        out += [_weighted_median(dev_all, wts), float(np.average(dev_all, weights=wts)),
                float(np.sqrt(np.average((dev_all - np.average(dev_all, weights=wts)) ** 2, weights=wts)))]
    else:
        out += [np.nan, np.nan, np.nan]
    return out


def quality_features(gray, faces):
    """Keeper signals: overall and best-region sharpness (subject in focus over bokeh), motion blur, and per
    face: sharpness, blink and smile. Counting faces and blinks lets the model learn that one blink ruins a group
    photo while closed eyes can be fine in a couple's portrait."""
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    h, w = gray.shape
    tiles = np.array([lap[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4].var()
                      for i in range(4) for j in range(4)])
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    ex, ey = float((gx ** 2).mean()), float((gy ** 2).mean())
    overall = float(lap.var())
    out = [math.log1p(overall), math.log1p(tiles.max()), math.log1p(np.percentile(tiles, 75)),
           math.log1p(tiles.min()), abs(ex - ey) / (ex + ey + 1e-6)]
    if not faces:
        return out + [0.0, 0.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
    sharp = []
    for f in faces:
        x, y, fw, fh = f["box"]
        crop = gray[y:y + fh, x:x + fw]
        sharp.append(float(cv2.Laplacian(crop, cv2.CV_32F).var()) if crop.size >= 100 else np.nan)
    main = max(range(len(faces)), key=lambda i: faces[i]["area"])
    closed = sum(f["blink"] > 0.5 for f in faces)
    ms = sharp[main]
    valid = [s for s in sharp if not np.isnan(s)]
    return out + [float(len(faces)), float(closed), closed / len(faces), max(f["blink"] for f in faces),
                  1.0 - faces[main]["blink"], float(np.mean([f["smile"] for f in faces])),
                  math.log1p(ms) if not np.isnan(ms) else np.nan,
                  ms / (overall + 1e-6) if not np.isnan(ms) else np.nan,
                  math.log1p(min(valid)) if valid else np.nan]


def _lsd():
    if not hasattr(_local, "lsd"):
        _local.lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    return _local.lsd




def compute(big, wb, exif, flip=0):
    """Base features (everything except the CLIP embedding). big: preview up to LINE_SIDE px (lines, faces);
    colour stats and segmentation run on a 512 px copy."""
    s = 512 / max(big.shape[:2])
    rgb = cv2.resize(big, (round(big.shape[1] * s), round(big.shape[0] * s)), interpolation=cv2.INTER_AREA) if s < 1 else big
    f = []
    x = rgb.astype(np.float32) / 255.0
    lum = 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]
    hist = np.histogram(lum, bins=32, range=(0, 1))[0].astype(np.float32)
    f += list(hist / max(hist.sum(), 1))
    f += list(np.percentile(lum, (1, 5, 10, 25, 50, 75, 90, 95, 99)))
    f += [lum.mean(), lum.std(), (lum > 0.98).mean(), (lum < 0.02).mean()]
    f += list(x.reshape(-1, 3).mean(0)) + list(x.reshape(-1, 3).std(0))
    lab = cv2.cvtColor(x, cv2.COLOR_RGB2Lab)
    f += [lab[..., 0].mean() / 100, lab[..., 1].mean(), lab[..., 2].mean(), lab[..., 1].std(), lab[..., 2].std()]
    hsv = cv2.cvtColor(x, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1]
    f += [sat.mean(), sat.std(), np.percentile(sat, 90)]
    hh = np.histogram(hsv[..., 0], bins=12, range=(0, 360), weights=sat)[0]
    f += list(hh / max(hh.sum(), 1e-6))
    h, w = lum.shape
    grid = [lum[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4].mean() for i in range(4) for j in range(4)]
    f += grid
    f += [lum[h // 4:3 * h // 4, w // 4:3 * w // 4].mean() - lum.mean(), lum[: h // 3].mean() - lum[2 * h // 3:].mean()]

    mask = vision.segment_people(rgb)
    people = mask > 0
    skin = (mask == 2) | (mask == 3)
    if skin.mean() > 0.002:
        f += [skin.mean(), lum[skin].mean(), lab[..., 1][skin].mean(), lab[..., 2][skin].mean()]
    else:
        f += [skin.mean(), np.nan, np.nan, np.nan]

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    big_gray = cv2.cvtColor(big, cv2.COLOR_RGB2GRAY)
    faces = vision.find_faces(big, float(people.mean()))
    sc = w / big.shape[1]
    if faces:
        main = max(faces, key=lambda fc: fc["area"])
        x, y, fw, fh = (int(v * sc) for v in main["box"])
        roi = (slice(y, y + max(fh, 1)), slice(x, x + max(fw, 1)))
        f += [min(len(faces), 16), main["area"], lum[roi].mean(), lab[..., 1][roi].mean(), lab[..., 2][roi].mean()]
    else:
        f += [0, 0, np.nan, np.nan, np.nan]

    f += [cv2.Laplacian(gray, cv2.CV_32F).var() / 1000.0, (cv2.Canny(gray, 80, 160) > 0).mean()]
    f += [wb[0], wb[1]]
    iso = exif.get("iso")
    f += [math.log2(iso) if iso else np.nan]
    for k in ("aperture", "shutter", "focal", "flash"):
        v = exif.get(k)
        f.append(float(v) if v is not None else np.nan)
    cam = exif.get("camera") or ""
    f.append(float(zlib.crc32(cam.encode()) % 997) if cam else np.nan)
    f.append(w / h)
    if people.mean() > 0.005:
        big_people = cv2.resize(people.astype(np.uint8), (big.shape[1], big.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        subj_sharp = math.log1p(float(cv2.Laplacian(big_gray, cv2.CV_32F)[big_people].var()))
        f += [people.mean(), lum[people].mean(), lum[people].mean() - (lum[~people].mean() if (~people).any() else np.nan),
              subj_sharp, float(np.mean([fc["smile"] for fc in faces])) if faces else np.nan]
    else:
        f += [people.mean(), np.nan, np.nan, np.nan, np.nan]
    f += tilt_features(big_gray)
    f.append(float(flip))
    f += quality_features(big_gray, faces)
    return np.asarray(f, dtype=np.float32)


def thumb_path(photo_path):
    d = os.path.join(cache_dir(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, hashlib.sha1(photo_path.lower().encode("utf-8")).hexdigest() + ".jpg")


def extract(photo_path, exif):
    rgb, wb, flip = load_preview(photo_path, LINE_SIDE)
    tp = thumb_path(photo_path)
    if not os.path.exists(tp):
        im = Image.fromarray(rgb)
        im.thumbnail((THUMB_SIZE, THUMB_SIZE))
        im.save(tp, quality=85)
    return compute(rgb, wb, exif, flip), vision.clip_input(rgb)


def _copy_thumb(old_path, new_path):
    src, dst = thumb_path(old_path), thumb_path(new_path)
    if os.path.exists(src) and not os.path.exists(dst):
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass


def prune_caches():
    """Frees space: deletes thumbnails that no project shows and whose photo isn't in the analysis cache (the cache
    needs a photo's thumbnail to count it as analysed, so those are kept), then compacts both cache databases.
    Returns {"thumbs_removed": n, "bytes_freed": b}."""
    from . import project as proj  # late import: project imports this module
    keep = set()
    for meta in proj.load_projects(True):
        p = proj.load_project(meta["id"]) or meta
        for f in [p.get("cover")] + [r.get("thumb") for r in p.get("results") or []]:
            if f:
                keep.add(os.path.basename(f).lower())
    db = sqlite3.connect(os.path.join(cache_dir(), "features.sqlite"))
    try:
        for (path,) in db.execute("select path from feats"):
            keep.add(os.path.basename(thumb_path(path)).lower())
    finally:
        db.close()
    removed = freed = 0
    d = os.path.join(cache_dir(), "thumbs")
    for fn in os.listdir(d) if os.path.isdir(d) else []:
        if fn.lower() not in keep:
            f = os.path.join(d, fn)
            try:
                size = os.path.getsize(f)
                os.remove(f)
                removed, freed = removed + 1, freed + size
            except OSError:
                pass
    for name in ("features.sqlite", "faces.sqlite"):
        f = os.path.join(cache_dir(), name)
        if os.path.exists(f):
            con = sqlite3.connect(f)
            try:
                con.execute("pragma wal_checkpoint(TRUNCATE)")
                con.execute("vacuum")
            finally:
                con.close()
    return {"thumbs_removed": removed, "bytes_freed": freed}


class FeatureCache:
    def __init__(self):
        self.db = sqlite3.connect(os.path.join(cache_dir(), "features.sqlite"))
        # WAL: readers don't block the writer and commits are much cheaper (a cache can afford synchronous=NORMAL).
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("pragma synchronous=NORMAL")
        self.db.execute("create table if not exists feats (path text primary key, mtime real, size integer, "
                        "version integer, exif text, data blob)")
        self.db.execute("create index if not exists feats_mtime_size on feats (mtime, size)")

    def _key(self, path):
        st = os.stat(path)
        return st.st_mtime, st.st_size

    def get(self, path, exif):
        try:
            mtime, size = self._key(path)
        except OSError:
            return None
        exif_key = repr(sorted(exif.items()))
        r = self.db.execute("select mtime, size, version, exif, data from feats where path=?", (path,)).fetchone()
        if r and r[0] == mtime and r[1] == size and r[2] == FEATURE_VERSION and r[3] == exif_key:
            return np.frombuffer(r[4], dtype=np.float32).copy()
        # Drive-portable: the same file (same name, size, modified time and EXIF) analysed at another path, e.g. a
        # shoot moved to another drive or folder. Re-key it to the new path (and copy its thumbnail).
        name = os.path.basename(path).lower()
        for old, data in self.db.execute("select path, data from feats where mtime=? and size=? and version=? "
                                         "and exif=?", (mtime, size, FEATURE_VERSION, exif_key)):
            if old != path and os.path.basename(old).lower() == name:
                self.db.execute("insert or replace into feats values (?,?,?,?,?,?)",
                                (path, mtime, size, FEATURE_VERSION, exif_key, data))
                _copy_thumb(old, path)
                return np.frombuffer(data, dtype=np.float32).copy()
        return None

    def put(self, path, exif, vec):
        mtime, size = self._key(path)
        self.db.execute("insert or replace into feats values (?,?,?,?,?,?)",
                        (path, mtime, size, FEATURE_VERSION, repr(sorted(exif.items())), vec.astype(np.float32).tobytes()))

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()


def _init_worker():
    cv2.setNumThreads(1)


def _job(path, exif):
    try:
        return extract(path, exif)
    except Exception as e:  # unreadable/corrupt file: reported back, row stays NaN
        return e


def _total_ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 2 ** 30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except (AttributeError, OSError, ValueError):
        return 8.0


def worker_count():
    """One process per CPU thread (leaving two for Lightroom and the UI), limited so the AI models
    (~350 MB per process) fit comfortably in memory."""
    by_cpu = (os.cpu_count() or 4) - 2
    by_ram = int(_total_ram_gb() * 0.6 / 0.35)
    return max(2, min(40, by_cpu, by_ram))


def _run_pool(executor_cls, jobs, on_result, cancelled, **kw):
    with executor_cls(worker_count(), **kw) as ex:
        futs = {ex.submit(_job, path, exif): i for i, path, exif in jobs}
        try:
            for fut in as_completed(futs):
                if cancelled():
                    ex.shutdown(wait=False, cancel_futures=True)
                    return
                on_result(futs[fut], fut.result())
        except BrokenProcessPool:
            ex.shutdown(wait=False, cancel_futures=True)
            raise


def extract_many(photos, progress=None, cancelled=lambda: False):
    """photos: list of CatalogPhoto. Returns (X array with FEATURE_NAMES columns, ok mask). Failed rows are NaN.

    Photos are analysed in separate processes (one per CPU thread) so the work isn't held back by Python's
    global interpreter lock; CLIP scene embeddings are computed in batches on the GPU in this process.
    Falls back to threads if processes can't be started."""
    cache = FeatureCache()
    X = np.full((len(photos), len(FEATURE_NAMES)), np.nan, dtype=np.float32)
    ok = [False] * len(photos)
    todo = []
    for i, p in enumerate(photos):
        v = cache.get(p.path, p.exif)
        if v is not None and len(v) == len(FEATURE_NAMES) and os.path.exists(thumb_path(p.path)):
            X[i], ok[i] = v, True
        else:
            todo.append(i)
    state = {"done": len(photos) - len(todo), "pending": []}
    if progress:
        progress(state["done"], len(photos), "Analyzing photos")

    def flush():
        batch = state["pending"]
        if not batch:
            return
        state["pending"] = []
        emb = vision.clip_embed([c for _, _, c in batch])
        for (i, base, _), e in zip(batch, emb):
            X[i] = np.concatenate([base, e])
            ok[i] = True
            cache.put(photos[i].path, photos[i].exif, X[i])
        cache.commit()

    def on_result(i, result):
        if isinstance(result, Exception):
            print("feature error", photos[i].path, result)
        else:
            state["pending"].append((i, result[0], result[1]))
            if len(state["pending"]) >= 64:
                flush()
        state["done"] += 1
        if progress:
            progress(state["done"], len(photos), "Analyzing photos")

    jobs = [(i, photos[i].path, photos[i].exif) for i in todo]
    if jobs:
        try:
            if len(jobs) < 12:  # not worth starting processes
                raise BrokenProcessPool
            _run_pool(ProcessPoolExecutor, jobs, on_result, cancelled, initializer=_init_worker)
        except (BrokenProcessPool, OSError, RuntimeError):
            flush()
            remaining = [j for j in jobs if not ok[j[0]] and j[0] not in {b[0] for b in state["pending"]}]
            _run_pool(ThreadPoolExecutor, remaining, on_result, cancelled)
        flush()
    cache.close()
    return X, ok


def no_empty_columns(X):
    """scikit-learn 1.9's histogram binning crashes ("window shape cannot be larger than input array shape") when a
    feature column has no values at all (all NaN). Small training sets, e.g. learning from a few tweaked photos with no
    faces in them, can produce one. Such a column carries no information, so give it a constant instead."""
    X = np.asarray(X)
    empty = np.isnan(X).all(axis=0) if X.ndim == 2 and len(X) else np.zeros(0, bool)
    if empty.any():
        X = X.copy()
        X[:, empty] = 0.0
    return X


class Reducer:
    """Turns the 512 CLIP numbers into a compact 'scene' summary (PCA) that tree models can use well.
    Fitted on a profile's training photos and stored with it."""

    def __init__(self, n_components=24):
        self.n = n_components
        self.pca = None
        self.n_base = len(BASE_NAMES)

    def fit(self, X):
        from sklearn.decomposition import PCA
        E = X[:, self.n_base:]
        good = ~np.isnan(E).any(axis=1)
        self.pca = PCA(n_components=self.n, random_state=0).fit(E[good]) if good.sum() > self.n * 4 else None
        return self

    def transform(self, X):
        base = X[:, :self.n_base]
        out = np.full((len(X), self.n), np.nan, dtype=np.float32)
        if self.pca is not None:
            E = X[:, self.n_base:]
            good = ~np.isnan(E).any(axis=1)
            if good.any():
                out[good] = self.pca.transform(E[good])
        return np.hstack([base, out])
