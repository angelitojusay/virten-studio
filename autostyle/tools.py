"""Learned "tools" beyond global sliders: straighten/crop and AI masks (subject, background, sky, skin, teeth).

Masks are written in the same lightweight form Imagen uses (mask type + slider values, no pixels);
Lightroom computes the actual AI selection for each photo when the plugin calls photo:updateAISettings()."""
import uuid
from collections import Counter

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from .features import no_empty_columns

TOOLS = {
    "crop": "Straighten horizon",
    "subject": "Subject mask (relight the people)",
    "background": "Background mask",
    "sky": "Sky mask",
    "skin": "Smooth skin",
    "teeth": "Whiten teeth",
}

# Lightroom AI mask identifiers: MaskSubType 1 = subject, 2 = sky, 0 + category 22 = background,
# 3 = people parts (category 2 = facial skin, 12 = teeth).
MASK_SPEC = {
    "subject": {"name": "Virten Studio Subject", "subtype": 1, "category": None, "origin": "-1, -1"},
    "background": {"name": "Virten Studio Background", "subtype": 0, "category": 22, "origin": "0, 0"},
    "sky": {"name": "Virten Studio Sky", "subtype": 2, "category": None, "origin": "0, 0"},
    "skin": {"name": "Virten Studio Smooth Skin", "subtype": 3, "category": 2, "origin": "0, 0"},
    "teeth": {"name": "Virten Studio Whiten Teeth", "subtype": 3, "category": 12, "origin": "0, 0"},
}
MASK_KINDS = list(MASK_SPEC)


def mask_kind(group):
    if not isinstance(group, dict):
        return None
    name = str(group.get("CorrectionName") or "").lower()
    if "skin" in name:
        return "skin"
    if "teeth" in name:
        return "teeth"
    masks = [m for m in group.get("CorrectionMasks") or [] if isinstance(m, dict)]
    img = [m for m in masks if m.get("What") == "Mask/Image"]
    if not img:
        return "gradient" if any(m.get("What") == "Mask/Gradient" for m in masks) else None
    st, cat = img[0].get("MaskSubType"), img[0].get("MaskSubCategoryID")
    if st == 1:
        return "subject"
    if st == 2 or (st == 0 and cat == 50006):
        return "sky"
    if st == 0 and cat == 22:
        return "background"
    if st == 3 and cat == 2:
        return "skin"
    if st == 3 and cat == 12:
        return "teeth"
    return None


def _groups_by_kind(settings):
    out = {}
    for g in settings.get("MaskGroupBasedCorrections") or []:
        k = mask_kind(g)
        if k and k not in out:
            out[k] = g
    return out


def _reg():
    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=200, learning_rate=0.06,
                                         max_leaf_nodes=24, min_samples_leaf=12, l2_regularization=1.0, random_state=0)


def _clf():
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_leaf_nodes=24,
                                          min_samples_leaf=12, l2_regularization=1.0, random_state=0)


def _varies(arr):
    vals, counts = np.unique(arr, return_counts=True)
    mode = vals[np.argmax(counts)]
    return np.mean(arr != mode) >= 0.15 and len(vals) >= 3, float(mode)


# ---------------------------------------------------------------- straighten / crop

def _is_pure_straighten(s):
    try:
        l, t, r, b = (float(s.get(k, d)) for k, d in (("CropLeft", 0), ("CropTop", 0), ("CropRight", 1), ("CropBottom", 1)))
    except (TypeError, ValueError):
        return False
    return abs(l - (1 - r)) < 2e-3 and abs(t - (1 - b)) < 2e-3


def _fit_through_origin(theta, y):
    """y ≈ a·θ + b·θ² (no intercept)."""
    if len(theta) < 5:
        return [0.0, 0.0]
    A = np.stack([theta, theta ** 2], 1)
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return [float(c) for c in coef]


def active_catalogs(cats, used, min_rate):
    """Catalogs where a tool was used on at least min_rate of photos. Tool use is mostly a per-shoot choice
    (it's switched on per project in the wizard), so per-photo models only learn from shoots that used it."""
    out = set()
    for c in set(cats):
        m = cats == c
        if used[m].mean() >= min_rate:
            out.add(c)
    return np.array([c in out for c in cats])


def train_crop(X, settings, hold, log, cats, weights=None):
    weights = np.ones(len(settings)) if weights is None else weights
    all_angle = np.array([float(s.get("CropAngle") or 0) for s in settings])
    active = active_catalogs(cats, np.abs(all_angle) > 0.05, 0.5)
    rate = float(active.mean())
    if active.sum() < 50:
        log("crop", "skipped: too few straightened shoots")
        return None, {}
    X, hold, settings, angle = X[active], hold[active], [s for s, a in zip(settings, active) if a], all_angle[active]
    weights = weights[active]
    pure = np.array([abs(a) > 0.05 and _is_pure_straighten(s) for a, s in zip(angle, settings)])
    th = angle[pure]
    left = np.array([float(s.get("CropLeft", 0)) for s in settings])[pure]
    top = np.array([float(s.get("CropTop", 0)) for s in settings])[pure]
    pos, neg = th > 0, th < 0
    geometry = {"pos_left": _fit_through_origin(np.abs(th[pos]), left[pos]),
                "pos_top": _fit_through_origin(np.abs(th[pos]), top[pos]),
                "neg_left": _fit_through_origin(np.abs(th[neg]), left[neg]),
                "neg_top": _fit_through_origin(np.abs(th[neg]), top[neg])}
    metrics = {}
    if hold.sum() >= 10:
        m = _reg().fit(no_empty_columns(X[~hold]), angle[~hold])
        pred = m.predict(X[hold])
        metrics["Straighten angle"] = {"mae": float(np.mean(np.abs(pred - angle[hold]))),
                                       "baseline_mae": float(np.mean(np.abs(angle[hold]))), "unit": "°"}
    model = _reg().fit(no_empty_columns(X), angle, sample_weight=weights)
    return {"model": model, "geometry": geometry, "rate": rate, "shoots": len(set(cats[active])),
            "extra_crop_rate": float(1 - pure.sum() / max(1, (np.abs(angle) > 0.05).sum()))}, metrics


def _poly(c, x):
    return c[0] * x + c[1] * x * x


def predict_crop(tool, x_row_pred):
    theta = float(np.clip(x_row_pred, -5, 5))
    if abs(theta) < 0.1:
        return {}
    g, a = tool["geometry"], abs(theta)
    left = _poly(g["pos_left" if theta > 0 else "neg_left"], a)
    top = _poly(g["pos_top" if theta > 0 else "neg_top"], a)
    left, top = float(np.clip(left, 0, 0.2)), float(np.clip(top, 0, 0.2))
    return {"HasCrop": True, "CropAngle": round(theta, 4), "CropLeft": round(left, 6), "CropTop": round(top, 6),
            "CropRight": round(1 - left, 6), "CropBottom": round(1 - top, 6)}


# ---------------------------------------------------------------- masks

def train_masks(X_all, settings_all, hold_all, log, cats, weights=None):
    weights = np.ones(len(settings_all)) if weights is None else weights
    by_kind_all = [_groups_by_kind(s) for s in settings_all]
    tools, metrics = {}, {}
    for kind in MASK_KINDS:
        present_all = np.array([kind in b for b in by_kind_all])
        if present_all.sum() < 20:
            continue
        active = active_catalogs(cats, present_all, 0.05)
        X, hold, present, w = X_all[active], hold_all[active], present_all[active], weights[active]
        by_kind = [b for b, a in zip(by_kind_all, active) if a]
        rate = float(present.mean())  # how often, within shoots that used it
        t = {"rate": rate, "shoots": len(set(cats[active])), "classifier": None, "constants": {}, "models": {}}
        if rate < 0.9:
            # Within shoots that used the tool, try to learn which photos got it. Keep the classifier only if it
            # clearly beats "apply to every photo"; otherwise Lightroom's AI simply finds nothing on photos
            # without that content (e.g. no people for skin).
            if hold.sum() >= 30 and len(set(present[~hold])) == 2 and len(set(present[hold])) == 2:
                c = _clf().fit(no_empty_columns(X[~hold]), present[~hold])
                acc = float(np.mean(c.predict(X[hold]) == present[hold]))
                base = float(max(present[hold].mean(), 1 - present[hold].mean()))
                if acc >= base + 0.05:
                    metrics[f"{TOOLS[kind]}: which photos"] = {"accuracy": acc, "baseline_accuracy": base}
                    t["classifier"] = _clf().fit(no_empty_columns(X), present)
        groups = [b[kind] for b in by_kind if kind in b]
        idx = np.where(present)[0]
        keys = sorted({k for g in groups for k, v in g.items()
                       if (k.startswith("Local") or k == "CorrectionAmount") and isinstance(v, (int, float))
                       and not isinstance(v, bool)})
        for k in keys:
            vals = np.array([float(g[k]) if isinstance(g.get(k), (int, float)) else np.nan for g in groups])
            have = ~np.isnan(vals)
            if have.mean() < 0.5:
                continue
            varies, mode = _varies(vals[have])
            if mode == 0 and not varies and k != "CorrectionAmount":
                continue
            if not varies:
                t["constants"][k] = mode
                continue
            rows = idx[have]
            h = hold[rows]
            if h.sum() >= 10 and (~h).sum() >= 20:
                m = _reg().fit(no_empty_columns(X[rows[~h]]), vals[have][~h])
                pred = m.predict(X[rows[h]])
                base = np.median(vals[have][~h])
                metrics[f"{TOOLS[kind]}: {k.replace('Local', '').replace('2012', '')}"] = {
                    "mae": float(np.mean(np.abs(pred - vals[have][h]))),
                    "baseline_mae": float(np.mean(np.abs(base - vals[have][h])))}
            t["models"][k] = _reg().fit(no_empty_columns(X[rows]), vals[have], sample_weight=w[rows])
        tools[kind] = t
        log(kind, f"learned from {present.sum()} photos in {len(set(cats[active]))} shoots ({rate:.0%} of their photos)")
    return tools, metrics


def _hex():
    return uuid.uuid4().hex.upper()


def whole_image_area(dims):
    w, h = dims if dims and dims[0] and dims[1] else (3, 2)
    long_side = 1440
    if w >= h:
        ww, hh = long_side, round(long_side * h / w)
    else:
        ww, hh = round(long_side * w / h), long_side
    return f"0/1,0/1,{hh}/1,{ww}/1"


def build_mask_group(kind, values, dims):
    spec = MASK_SPEC[kind]
    sync, digest = _hex(), _hex()
    mask = {"What": "Mask/Image", "MaskActive": True, "MaskName": spec["name"], "MaskBlendMode": 0,
            "MaskInverted": False, "MaskSyncID": sync, "MaskValue": 1, "WholeImageArea": whole_image_area(dims),
            "Origin": spec["origin"], "MaskDigest": digest, "InputDigest": digest, "InputDigestVersion": 1,
            "ReferencePoint": "0.5 0.5", "MaskSubType": spec["subtype"]}
    if spec["category"] is not None:
        mask["MaskSubCategoryID"] = spec["category"]
    group = {"What": "Correction", "CorrectionName": spec["name"], "CorrectionActive": True,
             "CorrectionAmount": float(values.pop("CorrectionAmount", 1.0)), "CorrectionSyncID": sync,
             "CorrectionMasks": [mask]}
    group.update(values)
    return group


def build_gradient_group(name, zero, full, values):
    """A linear gradient correction, in the form Lightroom stores it: the effect fades from full strength at
    `full` to nothing at `zero` ((x, y) as fractions of the image). values: Local* sliders, -1..1."""
    sync = _hex()
    mask = {"What": "Mask/Gradient", "MaskActive": True, "MaskName": name, "MaskBlendMode": 0,
            "MaskInverted": False, "MaskSyncID": sync, "MaskValue": 1,
            "ZeroX": float(zero[0]), "ZeroY": float(zero[1]), "FullX": float(full[0]), "FullY": float(full[1])}
    group = {"What": "Correction", "CorrectionName": name, "CorrectionActive": True, "CorrectionAmount": 1.0,
             "CorrectionSyncID": _hex(), "CorrectionReferenceX": (zero[0] + full[0]) / 2,
             "CorrectionReferenceY": (zero[1] + full[1]) / 2, "CorrectionMasks": [mask]}
    group.update(values)
    return group


def _highlight_protection(X):
    """0.25-1 per photo: how much of the subject mask's brightening to keep. A subject that is already brightly
    lit in a bright scene (e.g. skin and a white shirt in direct sun) gets less, so it doesn't blow out."""
    from .features import FEATURE_NAMES
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    subj = np.nan_to_num(X[:, idx["subj_lum"]], nan=0.4)
    face = np.nan_to_num(X[:, idx["face_lum"]], nan=0.0)
    bright = np.maximum(subj, face)
    p95 = np.nan_to_num(X[:, idx["lum_p95"]], nan=0.5)
    keep = np.clip((0.72 - bright) / 0.22, 0.25, 1.0)
    return np.where(p95 > 0.85, keep, 1.0)


def predict_tools(profile, X, enabled, dims_list, strength=None):
    """Returns a list (one per row) of extra settings: crop keys and/or MaskGroupBasedCorrections.
    strength: {tool: multiplier}; 1.0 = how you edited before, 0.5 = half as strong, 2.0 = twice."""
    strength = strength or {}
    tools = profile.get("tools") or {}
    out = [{} for _ in range(len(X))]
    if "crop" in enabled and tools.get("crop"):
        angles = tools["crop"]["model"].predict(X)
        for i, a in enumerate(angles):
            out[i].update(predict_crop(tools["crop"], a))
    for kind in MASK_KINDS:
        t = tools.get(kind)
        if kind not in enabled or not t:
            continue
        apply = t["classifier"].predict_proba(X)[:, 1] >= 0.5 if t["classifier"] is not None else np.ones(len(X), bool)
        preds = {k: m.predict(X) for k, m in t["models"].items()}
        protect = _highlight_protection(X) if kind == "subject" else np.ones(len(X))
        for i in np.where(apply)[0]:
            vals = dict(t["constants"])
            for k, arr in preds.items():
                vals[k] = float(arr[i])
            k_mult = float(strength.get(kind, 1.0))
            brighten = k_mult * protect[i]
            for k in list(vals):
                if k.startswith("Local") and k != "LocalCurveRefineSaturation":
                    mult = brighten if vals[k] > 0 else k_mult  # protection only tones down brightening
                    vals[k] = round(float(np.clip(vals[k] * mult, -1, 1)), 6)
            out[i].setdefault("MaskGroupBasedCorrections", []).append(build_mask_group(kind, vals, dims_list[i]))
    return out
