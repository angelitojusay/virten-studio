"""Measures how closely Virten Studio's "After" preview matches Lightroom Classic, using the previews Lightroom itself
rendered (the catalog's "<name> Previews.lrdata"): for edited, uncropped photos, render_preview(embedded JPEG, the
photo's develop settings, its as-shot white balance) is compared with Lightroom's preview of the same settings (Adobe RGB ->
sRGB), cropped like Lightroom's, in CIELAB at a small size. preview.CAL was fitted with this data (1.6.3). Read-only: the catalog and previews.db are opened read-only/immutable; nothing is written.

    .venv\\Scripts\\python.exe dev-tools\\calibrate_preview.py <catalog.lrcat> [<catalog.lrcat> ...] [--n 40]

Reports per catalog and overall: mean colour difference (dE76), chroma ratio ours/Lightroom (1.00 = same
saturation), lightness offset and contrast (L* spread) ratio, for our preview and for the untouched embedded JPEG."""
import io
import os
import sqlite3
import sys

import cv2
import numpy as np
from PIL import Image, ImageCms

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from autostyle import catalog as lrcat, features, preview  # noqa: E402

SIZE = 96
_SRGB = ImageCms.createProfile("sRGB")


def lightroom_previews(catalog_path):
    """{image id_local: path of Lightroom's current preview, the level closest to 1080 px (at least 320 px)}. Edited
    photos usually only have a 'smallRender' preview (644 px) of their current settings, which is plenty here."""
    pdir = os.path.splitext(catalog_path)[0] + " Previews.lrdata"
    db_path = os.path.join(pdir, "previews.db")
    if not os.path.isfile(db_path):
        return {}
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        levels = {}
        for u, d, n in con.execute("select uuid, digest, longDimension from PyramidLevel"):
            levels.setdefault((u, d), []).append(int(n))
        out = {}
        for img, uuid, digest in con.execute("select imageId, uuid, digest from ImageCacheEntry"):
            sizes = [n for n in levels.get((uuid, digest), []) if n >= 320]
            if sizes:
                n = min(sizes, key=lambda s: abs(s - 1080))
                f = os.path.join(pdir, uuid[0], uuid[:4], f"{uuid}-{digest}_{n}")
                if os.path.isfile(f):
                    out[int(img)] = f
        return out
    finally:
        con.close()


def load_lightroom_preview(path):
    """Lightroom's preview as sRGB uint8 (its JPEGs are Adobe RGB (1998))."""
    im = Image.open(path)
    icc = im.info.get("icc_profile")
    im = im.convert("RGB")
    if icc:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        im = ImageCms.profileToProfile(im, src, _SRGB, outputMode="RGB")
    return np.asarray(im)


def lr_crop(rgb, s, sign=1.0):
    """The photo as Lightroom crops it: rotated by CropAngle about the crop centre, then the crop rectangle
    (CropLeft / Top / Right / Bottom, image fractions; missing = no crop on that side)."""
    def v(k, default):
        x = s.get(k)
        return float(x) if isinstance(x, (int, float)) else default
    left, top, right, bottom = v("CropLeft", 0.0), v("CropTop", 0.0), v("CropRight", 1.0), v("CropBottom", 1.0)
    ang = v("CropAngle", 0.0)
    h, w = rgb.shape[:2]
    cx, cy = (left + right) / 2 * w, (top + bottom) / 2 * h
    if abs(ang) > 1e-3:
        m = cv2.getRotationMatrix2D((cx, cy), sign * ang, 1.0)
        rgb = cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    cw, ch = max(4, round((right - left) * w)), max(4, round((bottom - top) * h))
    x0 = int(np.clip(round(cx - cw / 2), 0, w - cw))
    y0 = int(np.clip(round(cy - ch / 2), 0, h - ch))
    return rgb[y0:y0 + ch, x0:x0 + cw]


def _uncropped(s):
    return (abs(float(s.get("CropAngle", 0) or 0)) < 0.01 and float(s.get("CropLeft", 0) or 0) < 0.002
            and float(s.get("CropTop", 0) or 0) < 0.002 and float(s.get("CropRight", 1) or 1) > 0.998
            and float(s.get("CropBottom", 1) or 1) > 0.998)


def _small(rgb, shape=None):
    if shape is None:
        k = SIZE / max(rgb.shape[:2])
        shape = (max(8, round(rgb.shape[1] * k)), max(8, round(rgb.shape[0] * k)))
    return cv2.resize(rgb, shape, interpolation=cv2.INTER_AREA)


def metrics(ours, truth):
    """dE76, chroma ratio (pixels with real colour), L* offset and L* spread ratio between two sRGB uint8 images."""
    a = cv2.cvtColor(ours, cv2.COLOR_RGB2Lab).astype(np.float32)
    b = cv2.cvtColor(truth, cv2.COLOR_RGB2Lab).astype(np.float32)
    a[..., 0] *= 100 / 255
    b[..., 0] *= 100 / 255
    a[..., 1:] -= 128
    b[..., 1:] -= 128
    de = float(np.sqrt(((a - b) ** 2).sum(-1)).mean())
    ca, cb = np.hypot(a[..., 1], a[..., 2]), np.hypot(b[..., 1], b[..., 2])
    colourful = cb > 8
    chroma = float(ca[colourful].mean() / cb[colourful].mean()) if colourful.sum() > 20 else float("nan")
    skin = colourful & (np.degrees(np.arctan2(b[..., 2], b[..., 1])) % 360 > 25) & \
        (np.degrees(np.arctan2(b[..., 2], b[..., 1])) % 360 < 75)
    skin_c = float(ca[skin].mean() / cb[skin].mean()) if skin.sum() > 20 else float("nan")
    return {"dE": de, "chroma": chroma, "skin_chroma": skin_c, "dL": float(a[..., 0].mean() - b[..., 0].mean()),
            "contrast": float(a[..., 0].std() / max(b[..., 0].std(), 1e-3))}


def pairs(catalog_path, n=40, global_only=False):
    """[(photo, settings, as-shot (temp, tint) or None, base rgb, Lightroom rgb)] for photos with a Lightroom preview
    whose crop lines up with ours (edited photos first)."""
    previews = lightroom_previews(catalog_path)
    photos = [p for p in lrcat.list_photos(catalog_path) if p.is_raw and p.image_id in previews and p.exists_on_disk]
    photos.sort(key=lambda p: not p.touched)
    shot = lrcat.as_shot_white_balance(catalog_path, photos)
    out = []
    for p in photos:
        if len(out) >= n:
            break
        s = p.settings
        if not s or (global_only and s.get("MaskGroupBasedCorrections")):
            continue
        try:
            base, wb, _ = features.load_preview(p.path, max_side=1080)
            truth = load_lightroom_preview(previews[p.image_id])
        except Exception as e:  # unreadable RAW or preview
            print("  skipped", os.path.basename(p.path), e)
            continue
        cropped = lr_crop(base, s)
        if abs((cropped.shape[1] / cropped.shape[0]) / (truth.shape[1] / truth.shape[0]) - 1) > 0.04:
            continue  # crop / orientation doesn't line up: skip rather than guess
        as_shot = shot.get(p.image_id) or preview.estimate_as_shot(wb[0], wb[1], (p.exif or {}).get("camera"))
        out.append((p, s, as_shot, base, truth))
    return out


def evaluate(data):
    """Median metrics of Virten Studio's preview against Lightroom ('before' = the untouched embedded JPEG), compared
    over the centre of Lightroom's crop."""
    rows = {"after": [], "before": []}
    for _p, s, as_shot, base, truth in data:
        t = _small(truth)
        shape = (t.shape[1], t.shape[0])
        masks = preview.compute_ai_masks(base) if s.get("MaskGroupBasedCorrections") else None
        after = preview.render_preview(base, s, *(as_shot or (None, None)), ai_masks=masks)
        h, w = t.shape[:2]
        c = (slice(h // 12, h - h // 12), slice(w // 12, w - w // 12))
        for key, img in (("after", after), ("before", base)):
            rows[key].append(metrics(np.ascontiguousarray(_small(lr_crop(img, s), shape)[c]), np.ascontiguousarray(t[c])))
    return {k: {m: float(np.nanmedian([r[m] for r in v])) for m in v[0]} for k, v in rows.items() if v}


def main(argv):
    n = 40
    if "--n" in argv:
        n = int(argv[argv.index("--n") + 1])
        argv = argv[:argv.index("--n")] + argv[argv.index("--n") + 2:]
    allp = []
    for cat in argv[1:]:
        data = pairs(cat, n)
        allp += data
        if data:
            r = evaluate(data)
            print(f"{os.path.basename(cat):28} {len(data):3} photos  after: " + "  ".join(
                f"{k} {v:.2f}" for k, v in r["after"].items()) + "  | embedded JPEG: " + "  ".join(
                f"{k} {v:.2f}" for k, v in r["before"].items()))
    if allp:
        r = evaluate(allp)
        print(f"{'ALL':28} {len(allp):3} photos  after: " + "  ".join(f"{k} {v:.2f}" for k, v in r["after"].items()))


if __name__ == "__main__":
    main(sys.argv)
