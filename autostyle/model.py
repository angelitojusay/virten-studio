"""Personal edit profiles: learn Lightroom develop settings from past edits and predict them for new photos."""
import datetime
import json
import os
import re
from collections import Counter

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from . import catalog as lrcat
from . import looks, sync, tools
from .features import FEATURE_NAMES, FEATURE_VERSION, Reducer, extract_many, no_empty_columns
from .paths import profiles_dir

HSL = [f"{a}Adjustment{c}" for a in ("Hue", "Saturation", "Luminance")
       for c in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")]

GROUPS = {
    "tone": {"label": "Light (exposure, contrast, highlights, shadows, whites, blacks)",
             "keys": ["Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012"]},
    "wb": {"label": "White balance (temperature, tint)", "keys": ["Temperature", "Tint"]},
    "presence": {"label": "Presence (texture, clarity, dehaze, vibrance, saturation)",
                 "keys": ["Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation"]},
    "color": {"label": "Color mixer, color grading and calibration",
              "keys": HSL + ["ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeMidtoneLum",
                             "ColorGradeShadowLum", "ColorGradeHighlightLum", "ColorGradeBlending",
                             "ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum",
                             "SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
                             "SplitToningHighlightSaturation", "SplitToningBalance",
                             "ShadowTint", "RedHue", "RedSaturation", "GreenHue", "GreenSaturation",
                             "BlueHue", "BlueSaturation"]},
    "curve": {"label": "Tone curve",
              "keys": ["ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights",
                       "ParametricShadowSplit", "ParametricMidtoneSplit", "ParametricHighlightSplit",
                       "ToneCurveName2012", "ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green",
                       "ToneCurvePV2012Blue"]},
    "detail": {"label": "Profile, sharpening, noise reduction, lens, vignette and grain",
               "keys": ["CameraProfile", "Sharpness", "SharpenRadius", "SharpenDetail", "SharpenEdgeMasking",
                        "LuminanceSmoothing", "LuminanceNoiseReductionDetail", "LuminanceNoiseReductionContrast",
                        "ColorNoiseReduction", "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness",
                        "LensProfileEnable", "AutoLateralCA", "PostCropVignetteAmount", "PostCropVignetteMidpoint",
                        "PostCropVignetteFeather", "PostCropVignetteRoundness", "PostCropVignetteStyle",
                        "PostCropVignetteHighlightContrast", "GrainAmount", "GrainSize", "GrainFrequency"]},
}
KEY_GROUP = {k: g for g, d in GROUPS.items() for k in d["keys"]}
ALL_KEYS = list(KEY_GROUP)

RANGES = {"Exposure2012": (-5, 5), "Temperature": (2000, 50000), "Tint": (-150, 150)}
for _k in ["Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012", "Texture", "Clarity2012",
           "Dehaze", "Vibrance", "Saturation"] + HSL:
    RANGES[_k] = (-100, 100)

DISPLAY = {"Exposure2012": "Exposure", "Contrast2012": "Contrast", "Highlights2012": "Highlights",
           "Shadows2012": "Shadows", "Whites2012": "Whites", "Blacks2012": "Blacks", "Clarity2012": "Clarity",
           "ColorGradeBlending": "Grade Blending", "PostCropVignetteAmount": "Vignette",
           "ToneCurveName2012": "Tone Curve", "ToneCurvePV2012": "Point Curve", "ToneCurvePV2012Red": "Red Curve",
           "ToneCurvePV2012Green": "Green Curve", "ToneCurvePV2012Blue": "Blue Curve",
           "SplitToningShadowHue": "Split Shadow Hue", "SplitToningShadowSaturation": "Split Shadow Sat",
           "SplitToningHighlightHue": "Split High Hue", "SplitToningHighlightSaturation": "Split High Sat",
           "SplitToningBalance": "Split Balance", "SharpenEdgeMasking": "Masking", "SharpenRadius": "Radius",
           "SharpenDetail": "Sharpen Detail", "LuminanceSmoothing": "Luminance NR",
           "LuminanceNoiseReductionDetail": "Lum NR Detail", "LuminanceNoiseReductionContrast": "Lum NR Contrast",
           "ColorNoiseReduction": "Color NR", "ColorNoiseReductionDetail": "Color NR Detail",
           "ColorNoiseReductionSmoothness": "Color NR Smooth", "PostCropVignetteMidpoint": "Vignette Mid",
           "PostCropVignetteFeather": "Vignette Feather", "PostCropVignetteRoundness": "Vignette Round",
           "PostCropVignetteStyle": "Vignette Style", "PostCropVignetteHighlightContrast": "Vignette Hi Con",
           "LensProfileEnable": "Lens Profile", "AutoLateralCA": "Remove CA", "GrainFrequency": "Grain Roughness"}
_GRADE_ZONE = {"Midtone": "Mid", "Shadow": "Shadow", "Highlight": "High", "Global": "Global"}
_HSL_SHORT = {"Hue": "Hue", "Saturation": "Sat", "Luminance": "Lum"}


def display_name(key):
    """Short slider name that fits the inspector: "Orange Sat", "Curve Shadows", "Midtone Split", "Vignette"."""
    if key in DISPLAY:
        return DISPLAY[key]
    m = re.fullmatch(r"(Hue|Saturation|Luminance)Adjustment(\w+)", key)
    if m:
        return f"{m.group(2)} {_HSL_SHORT[m.group(1)]}"
    m = re.fullmatch(r"ColorGrade(Midtone|Shadow|Highlight|Global)(Hue|Sat|Lum)", key)
    if m:
        return f"Grade {_GRADE_ZONE[m.group(1)]} {m.group(2)}"
    m = re.fullmatch(r"Parametric(Shadows|Darks|Lights|Highlights)", key)
    if m:
        return f"Curve {m.group(1)}"
    m = re.fullmatch(r"Parametric(Shadow|Midtone|Highlight)Split", key)
    if m:
        return f"{m.group(1)} Split"
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _freeze(v):
    return json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v


def _thaw(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            pass
    return v


def safe_filename(name):
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "profile"


def gather_training_photos(catalog_paths, progress=None, snapshot_step=None, feedback=None,
                           only_tweaked_catalogs=None, include_approved_catalogs=None, strip_look_catalogs=None):
    """Gathers edited RAW photos for training.
    snapshot_step: learn the settings as they were right after this history step (e.g. "Imagen: LOVE & LIGHT")
    instead of your final edits; photos without that step are skipped.
    only_tweaked_catalogs: catalogs where ONLY photos you changed after Virten Studio's edit are included.
    include_approved_catalogs: catalogs where even untouched Virten Studio edits are kept (you approved them).
    strip_look_catalogs: {catalog: (look name, strength)}: remove that Look's offsets before learning. The matching
    predictions in `feedback` are stripped too (the dict is updated in place), so "did you correct it" compares
    like with like."""
    feedback = feedback if feedback is not None else {}
    only_tweaked = {os.path.normpath(c) for c in (only_tweaked_catalogs or ())}
    inc_approved = {os.path.normpath(c) for c in (include_approved_catalogs or ())}
    strip_looks = {os.path.normpath(k): v for k, v in (strip_look_catalogs or {}).items()}

    photos = []
    for i, c in enumerate(catalog_paths):
        nc = os.path.normpath(c)
        if progress:
            progress(i, len(catalog_paths), f"Reading {os.path.basename(c)}")
        snaps = lrcat.step_snapshots(c, snapshot_step) if snapshot_step else None
        look_info = strip_looks.get(nc)
        look_obj = looks.get_look(look_info[0]) if look_info and look_info[0] else None
        look_str = float(look_info[1]) if look_info and len(look_info) > 1 else 1.0

        for p in lrcat.list_photos(c):
            if snaps is not None:
                if p.image_id not in snaps:
                    continue
                p.settings_text, p._settings, p.last_step = snaps[p.image_id], None, snapshot_step
            if not (p.is_raw and p.is_edited and not p.is_grayscale and p.exists_on_disk):
                continue

            if _qualifies(p, nc, feedback, only_tweaked, inc_approved, look_obj, look_str):
                photos.append(p)
    return photos


def _qualifies(p, nc, feedback, only_tweaked, inc_approved, look_obj, look_str):
    """The per-shoot learning rules (shared by live catalogs and offline snapshot rows). May strip a Look from the
    photo's settings and from its prediction in `feedback`."""
    key = os.path.normpath(p.path)
    pred = feedback.get(key) or feedback.get(p.path)
    if nc in only_tweaked:
        if not pred or not _corrected(p.settings, pred):
            return False
    elif nc not in inc_approved:
        if p.app_edit_untouched:
            return False
    if look_obj:
        p._settings = looks.strip_look_offsets(p.settings, look_obj, look_str)
        if pred:
            feedback[key] = looks.strip_look_offsets(pred, look_obj, look_str)
    return True


# ---------------------------------------------------------------- offline training snapshots

def snapshot_path(name):
    """<profile>.dataset.npz: the photo analysis and settings a profile was trained on, so a later retrain can still
    use shoots whose catalog or RAW files have moved off the drive. Kept on this computer only (not synced)."""
    return profile_path(name) + ".dataset.npz"


def save_snapshot(name, photos, X):
    """photos: the CatalogPhotos trained on (their original, un-stripped settings text is stored); X: their raw
    feature rows (before the profile's CLIP reducer)."""
    path = snapshot_path(name)
    tmp = path + ".tmp"
    arr = lambda vals: np.array([v or "" for v in vals], dtype=str)  # noqa: E731
    with open(tmp, "wb") as f:
        np.savez_compressed(
            f, X=np.asarray(X, dtype=np.float32), feature_version=np.array(FEATURE_VERSION),
            catalogs=arr(os.path.normpath(p.catalog) for p in photos), paths=arr(p.path for p in photos),
            captures=arr(p.capture for p in photos), last_steps=arr(p.last_step for p in photos),
            settings=arr(p.settings_text for p in photos))
    os.replace(tmp, path)


def load_snapshot(name):
    """The profile's snapshot as a dict of arrays, or None (missing, unreadable or from another feature version)."""
    path = snapshot_path(name)
    if not name or not os.path.exists(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            snap = {k: z[k] for k in z.files}
    except (OSError, ValueError, KeyError):
        return None
    return snap if int(snap.get("feature_version", -1)) == FEATURE_VERSION else None


def snapshot_counts(name):
    """{catalog (normalised): photos in the profile's snapshot}."""
    snap = load_snapshot(name)
    return dict(Counter(str(c) for c in snap["catalogs"])) if snap is not None else {}


def _snapshot_rows(snap, catalogs, feedback, only_tweaked, inc_approved, strip_looks):
    """CatalogPhotos and raw feature rows for these catalogs from a snapshot, filtered by the same learning rules."""
    photos, rows = [], []
    if snap is None:
        return photos, np.zeros((0, len(FEATURE_NAMES)), np.float32)
    wanted = {os.path.normpath(c) for c in catalogs}
    for i, cat in enumerate(snap["catalogs"]):
        nc = str(cat)
        if nc not in wanted:
            continue
        path = str(snap["paths"][i])
        p = lrcat.CatalogPhoto(catalog=nc, uuid="", path=path, ext=os.path.splitext(path)[1].lstrip("."),
                               folder=os.path.dirname(path), pick=0, rating=0, settings_text=str(snap["settings"][i]),
                               touched=True, capture=str(snap["captures"][i]), last_step=str(snap["last_steps"][i]))
        look_info = strip_looks.get(nc)
        look_obj = looks.get_look(look_info[0]) if look_info and look_info[0] else None
        look_str = float(look_info[1]) if look_info and len(look_info) > 1 else 1.0
        if _qualifies(p, nc, feedback, only_tweaked, inc_approved, look_obj, look_str):
            photos.append(p)
            rows.append(snap["X"][i])
    X = np.stack(rows).astype(np.float32) if rows else np.zeros((0, len(FEATURE_NAMES)), np.float32)
    return photos, X


def _target(key, v):
    # Temperature behaves far more linearly in mireds than in Kelvin.
    return 1e6 / v if key == "Temperature" else v


def _untarget(key, v):
    return 1e6 / v if key == "Temperature" else v


SUPPORTING_WEIGHT = 1 / 3  # tested on your shoots: supporting examples at 1/3 weight cut white-balance error ~43%


def _regressor():
    # Larger model: on your shoots it lowered white-balance and contrast error vs the original settings.
    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=600, learning_rate=0.04,
                                         max_leaf_nodes=31, min_samples_leaf=8, l2_regularization=0.5,
                                         random_state=0)


def _holdout_mask(groups, rng):
    """Hold out whole catalogs (~20% of photos) so accuracy reflects unseen shoots, not burst neighbours."""
    cats = list(Counter(groups).items())
    n = len(groups)
    if len(cats) >= 3:
        rng.shuffle(cats)
        held, count = set(), 0
        for c, k in cats:
            if count >= 0.2 * n:
                break
            if count + k <= 0.4 * n:
                held.add(c)
                count += k
        if held:
            return np.array([g in held for g in groups])
    return rng.random(n) < 0.2


def _corrected(final, predicted):
    tol = {"Exposure2012": 0.08, "Temperature": 100, "Tint": 2.5}
    for k in GROUPS["tone"]["keys"] + GROUPS["wb"]["keys"] + GROUPS["presence"]["keys"]:
        a, b = final.get(k), predicted.get(k)
        if _is_num(a) and _is_num(b) and abs(float(a) - float(b)) > tol.get(k, 4):
            return True
    return False


def sample_weights(photos, feedback, tweak_boost=2.0):
    """Recent shoots count more (half weight per 2 years, minimum 1/4), and photos where you corrected
    Virten Studio's suggestion count `tweak_boost` times (default 2x), so the profile keeps following how your
    style evolves."""
    today = datetime.date.today()
    w = np.ones(len(photos))
    n_corrected = 0
    for i, p in enumerate(photos):
        try:
            d = datetime.date.fromisoformat((p.capture or "")[:10])
            w[i] = max(0.25, 0.5 ** (max(0, (today - d).days) / 730))
        except ValueError:
            pass
        pred = feedback.get(os.path.normpath(p.path)) or feedback.get(p.path)
        if pred and _corrected(p.settings, pred):
            w[i] *= float(tweak_boost)
            n_corrected += 1
    return w, n_corrected


def train_profile(name, catalog_paths, progress=None, cancelled=lambda: False, feedback=None, catalog_weights=None,
                  snapshot_step=None, tweak_boost=2.0, only_tweaked_catalogs=None, include_approved_catalogs=None,
                  strip_look_catalogs=None):
    """feedback: {photo path: settings Virten Studio predicted}. Photos you then corrected count double.
    catalog_weights: {catalog: weight}; 'supporting' shoots (SUPPORTING_WEIGHT) help without defining the style."""
    feedback = dict(feedback or {})  # a copy: gathering strips Look offsets from it for strip_look_catalogs
    # Shoots that are offline (catalog missing, or none of its RAW files on disk any more) come from the profile's
    # training snapshot, so moving old shoots off the drive doesn't stop a retrain from using them.
    snap = load_snapshot(name)
    snap_cats = set(snapshot_counts(name)) if snap is not None else set()
    online = [c for c in catalog_paths if os.path.exists(c)]
    photos = gather_training_photos(online, progress, snapshot_step, feedback=feedback,
                                    only_tweaked_catalogs=only_tweaked_catalogs,
                                    include_approved_catalogs=include_approved_catalogs,
                                    strip_look_catalogs=strip_look_catalogs)
    have = Counter(os.path.normpath(p.catalog) for p in photos)
    offline = [c for c in catalog_paths if os.path.normpath(c) in snap_cats
               and (not os.path.exists(c) or not have[os.path.normpath(c)])]
    snap_photos, snap_X = _snapshot_rows(
        snap, offline, feedback, {os.path.normpath(c) for c in (only_tweaked_catalogs or ())},
        {os.path.normpath(c) for c in (include_approved_catalogs or ())},
        {os.path.normpath(k): v for k, v in (strip_look_catalogs or {}).items()})
    if len(photos) + len(snap_photos) < 30:
        raise ValueError(f"Only {len(photos) + len(snap_photos)} qualifying RAW photos were found on disk. "
                         "At least 30 are needed (if learning from tweaks on a single small shoot, keep your profile's "
                         "base catalogs checked so your tweaks refine your existing foundation).")
    X, ok = extract_many(photos, progress, cancelled)
    if cancelled():
        raise InterruptedError
    photos = [p for p, o in zip(photos, ok) if o] + snap_photos
    X = np.vstack([X[np.array(ok, dtype=bool)], snap_X]) if len(snap_X) else X[np.array(ok, dtype=bool)]
    X_raw = X
    reducer = Reducer().fit(X)
    X = reducer.transform(X)
    settings = [p.settings for p in photos]
    groups = [p.catalog for p in photos]
    n = len(photos)
    weights, n_corrected = sample_weights(photos, feedback, tweak_boost=tweak_boost)
    cw = {os.path.normpath(k): v for k, v in (catalog_weights or {}).items()}
    weights = weights * np.array([cw.get(os.path.normpath(p.catalog), 1.0) for p in photos])

    constants, regress, int_keys, ranges = {}, [], set(), {}
    for key in ALL_KEYS:
        vals = [s.get(key) for s in settings if key in s]
        if len(vals) < 0.5 * n:
            continue
        frozen = Counter()
        for s, w in zip(settings, weights):
            if key in s:
                frozen[_freeze(s[key])] += w
        mode = frozen.most_common(1)[0][0]
        if all(_is_num(v) for v in vals):
            arr = np.asarray(vals, dtype=float)
            if np.mean(arr != mode) >= 0.15 and len(np.unique(arr)) >= 3:
                regress.append(key)
                if np.all(arr == np.round(arr)):
                    int_keys.add(key)
                lo, hi = RANGES.get(key, (float(arr.min()), float(arr.max())))
                ranges[key] = (max(lo, float(np.percentile(arr, 0.5))), min(hi, float(np.percentile(arr, 99.5))))
                continue
        constants[key] = _thaw(mode)
    pv = Counter(s.get("ProcessVersion") for s in settings).most_common(1)[0][0]

    rng = np.random.default_rng(0)
    hold = _holdout_mask(groups, rng)
    models, metrics = {}, {}
    for i, key in enumerate(regress):
        if cancelled():
            raise InterruptedError
        if progress:
            progress(i, len(regress), f"Learning {display_name(key)}")
        y = np.array([_target(key, s[key]) if key in s else np.nan for s in settings], dtype=float)
        have = ~np.isnan(y)
        tr, te = have & ~hold, have & hold
        if te.sum() >= 10 and tr.sum() >= 20:
            m = _regressor().fit(no_empty_columns(X[tr]), y[tr])
            pred = np.array([_untarget(key, v) for v in m.predict(X[te])])
            truth = np.array([_untarget(key, v) for v in y[te]])
            base = np.median([_untarget(key, v) for v in y[tr]])
            metrics[key] = {"mae": float(np.mean(np.abs(pred - truth))),
                            "baseline_mae": float(np.mean(np.abs(base - truth))), "n_test": int(te.sum())}
        models[key] = _regressor().fit(no_empty_columns(X[have]), y[have], sample_weight=weights[have])

    if progress:
        progress(0, 1, "Learning straighten and masks")
    tool_log = []
    log = lambda k, msg: tool_log.append(f"{k}: {msg}")
    learned_tools, tool_metrics = {}, {}
    cat_arr = np.array(groups)
    crop, m = tools.train_crop(X, settings, hold, log, cat_arr, weights)
    if crop:
        learned_tools["crop"] = crop
        tool_metrics.update(m)
    masks, m = tools.train_masks(X, settings, hold, log, cat_arr, weights)
    learned_tools.update(masks)
    tool_metrics.update(m)

    profile = {
        "name": name, "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "feature_version": FEATURE_VERSION, "feature_names": FEATURE_NAMES, "n_photos": n, "reducer": reducer,
        "catalogs": sorted(set(groups)), "models": models, "constants": constants,
        "int_keys": sorted(int_keys), "ranges": ranges, "metrics": metrics, "process_version": pv,
        "tools": learned_tools, "tool_metrics": tool_metrics, "tool_log": tool_log,
        "available_tools": [k for k in tools.TOOLS if k in learned_tools],
        "n_corrected": n_corrected,
        "catalog_weights": cw,
        "snapshot_step": snapshot_step,
        "from_snapshot": {os.path.normpath(c): sum(1 for p in snap_photos if p.catalog == os.path.normpath(c))
                          for c in offline},
    }
    save_profile(profile)
    try:
        save_snapshot(name, photos, X_raw)
    except OSError as e:  # the profile itself is saved; only the offline fallback is missing
        print("snapshot save failed", e)
    if progress:
        progress(1, 1, "Done")
    return profile


def profile_path(name):
    return os.path.join(profiles_dir(), safe_filename(name) + ".virten-profile")


def save_profile(profile):
    joblib.dump(profile, profile_path(profile["name"]), compress=3)
    meta = {k: profile.get(k) for k in ("name", "created", "n_photos", "catalogs", "metrics", "tool_metrics",
                                        "available_tools", "feature_version", "catalog_weights",
                                        "snapshot_step", "n_corrected", "from_snapshot")}
    meta["tool_rates"] = {k: t["rate"] for k, t in (profile.get("tools") or {}).items()}
    meta["tool_shoots"] = {k: t.get("shoots", 0) for k, t in (profile.get("tools") or {}).items()}
    with open(profile_path(profile["name"]) + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    try:
        sync.push_profile(profile_path(profile["name"]))
    except OSError as e:  # sync folder offline: the next sync catches up
        print("sync push failed", e)


def list_profiles():
    out = []
    for fn in sorted(os.listdir(profiles_dir())):
        if fn.endswith(".virten-profile.json"):
            try:
                with open(os.path.join(profiles_dir(), fn), encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("kind") != "cull":  # skip the retired AI Culling model if an old copy is around
                    out.append(meta)
            except (OSError, ValueError):
                pass
    return out


def import_profile(path):
    profile = joblib.load(path)
    if not isinstance(profile, dict) or "models" not in profile or "name" not in profile:
        raise ValueError("That file isn't a Virten Studio profile.")
    save_profile(profile)
    return profile


def load_profile(name):
    return joblib.load(profile_path(name))


def delete_profile(name):
    for p in (profile_path(name), profile_path(name) + ".json", snapshot_path(name)):
        if os.path.exists(p):
            os.remove(p)
    try:
        sync.push_profile_delete(profile_path(name))
    except OSError as e:
        print("sync delete failed", e)


def predict(profile, X, groups=None, exposure_bias=0.0, dims=None, strength=None):
    """Return a list of develop-settings dicts, one per row of X. groups may include slider groups and tool keys."""
    groups = set(groups or list(GROUPS) + list(tools.TOOLS))
    if profile.get("reducer") is not None:
        X = profile["reducer"].transform(X)
    extras = tools.predict_tools(profile, X, groups, dims or [(0, 0)] * len(X), strength)
    preds = {k: m.predict(X) for k, m in profile["models"].items() if KEY_GROUP[k] in groups}
    ints = set(profile["int_keys"])
    out = []
    for i in range(len(X)):
        s = {k: v for k, v in profile["constants"].items() if KEY_GROUP[k] in groups}
        for k, arr in preds.items():
            v = _untarget(k, float(arr[i]))
            if k == "Exposure2012":
                v += exposure_bias
            lo, hi = profile["ranges"].get(k, RANGES.get(k, (-1e9, 1e9)))
            if k == "Exposure2012":
                lo, hi = RANGES[k]
            v = min(max(v, lo), hi)
            s[k] = int(round(v)) if k in ints else round(v, 2)
        if exposure_bias and "Exposure2012" not in s and "tone" in groups:
            s["Exposure2012"] = round(exposure_bias, 2)
        if "Temperature" in s or "Tint" in s:
            s["WhiteBalance"] = "Custom"
        s.update(extras[i])
        out.append(s)
    return out
