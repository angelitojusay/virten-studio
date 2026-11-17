"""Assisted culling: suggestions to speed up your own cull in Lightroom. It never rates, labels or rejects.

For a set of photos it finds
- bursts: near-identical frames shot within seconds (capture time + CLIP scene similarity), and timelapse sequences;
- likely rejects, with the reason: blurry, eyes closed, exposure way off, flash didn't fire;
- in bursts of people, the likely best frame, from a model of which frame you kept in past culls (expression, gaze,
  head angle, eye focus; see faces.py).

Tested against your own picks on 12 shoots (each held out): about 80-85 % of likely-reject flags were photos you
cut, and the best-frame hint matched your choice in 46 % of people bursts (35 % by chance). Predicting keepers in
general, or the best frame of scenery bursts, didn't beat chance, so it isn't offered.

Results go to Lightroom as keywords under "Virten Cull" (not exported with your photos) and a few collections, through
the same plugin menu as edits. The model is stored as a hidden profile (kind "cull") so it syncs like one."""
import datetime
import os
import warnings
from collections import defaultdict

import joblib
import numpy as np

from . import catalog as lrcat
from .features import CLIP_NAMES, FEATURE_NAMES, extract_many, no_empty_columns
from .paths import profiles_dir

MODEL_NAME = "_cull-model"
STRICTNESS = {"relaxed": 0, "normal": 1, "strict": 2}

KW_ROOT = "Virten Cull"
REASONS = {"blurry": "Blurry", "eyes": "Eyes closed", "exposure": "Exposure way off", "flash": "Flash didn't fire"}

_IDX = {n: i for i, n in enumerate(FEATURE_NAMES)}
_CLIP = np.array([_IDX[n] for n in CLIP_NAMES])


# ---------------------------------------------------------------- bursts

def _time(p):
    try:
        return datetime.datetime.fromisoformat((p.capture or "")[:23]).timestamp()
    except ValueError:
        return None


def _unit(E):
    E = np.nan_to_num(E.astype(np.float32))
    return E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-6)


MAX_BURST_SECONDS = 20
MAX_BURST_FRAMES = 40


def find_timelapses(photos, X, min_frames=20):
    """Intervalometer sequences: 20+ frames from one camera at a steady interval of a second or more, all showing
    the same scene. They're deliberate, so they're labelled and left out of the suggestions (and the training)."""
    times = [_time(p) for p in photos]
    E = _unit(X[:, _CLIP])
    order = [i for i in sorted(range(len(photos)), key=lambda i: (times[i] or 0, photos[i].path)) if times[i] is not None]
    out = set()
    run = []

    def close(run):
        if len(run) >= min_frames:
            dts = np.diff([times[i] for i in run])
            med = float(np.median(dts))
            if med >= 0.9 and float(np.std(dts)) <= 0.3 * med + 0.5:
                out.update(run)

    for i in order:
        if run:
            j = run[-1]
            dt = times[i] - times[j]
            same = photos[i].exif.get("camera") == photos[j].exif.get("camera")
            steady = len(run) < 2 or abs(dt - (times[j] - times[run[-2]])) <= max(0.5, 0.3 * dt)
            if same and 0.5 <= dt <= 120 and steady and float(E[i] @ E[j]) >= 0.85:
                run.append(i)
                continue
            close(run)
        run = [i]
    close(run)
    return out


def find_bursts(photos, X, gap=2.0, sim=0.88, long_gap=12.0, long_sim=0.95, skip=()):
    """Group frames shot close together that show the same scene. Returns a group id per photo (singletons get
    their own id) in capture order. gap/sim: rapid frames; long_gap/long_sim: the same pose re-shot a bit later.
    A burst is capped at MAX_BURST_SECONDS / MAX_BURST_FRAMES so a long sequence doesn't chain into one group.
    Photos in `skip` (timelapse frames) are each kept on their own."""
    times = [_time(p) for p in photos]
    E = _unit(X[:, _CLIP])
    order = sorted(range(len(photos)), key=lambda i: (times[i] is None, times[i] or 0, photos[i].path))
    group = [-1] * len(photos)
    gid, prev, start, size = -1, None, None, 0
    for i in order:
        joined = False
        if prev is not None and i not in skip and prev not in skip and times[i] is not None and times[prev] is not None:
            dt = times[i] - times[prev]
            s = float(E[i] @ E[prev])
            # Same camera body matters: two shooters' frames interleave in time.
            same_cam = photos[i].exif.get("camera") == photos[prev].exif.get("camera")
            joined = (same_cam and ((dt <= gap and s >= sim) or (dt <= long_gap and s >= long_sim))
                      and times[i] - times[start] <= MAX_BURST_SECONDS and size < MAX_BURST_FRAMES)
        if not joined:
            gid += 1
            start, size = i, 0
        group[i] = gid
        size += 1
        prev = i
    return group


# ---------------------------------------------------------------- rules (explainable likely-reject reasons)

def flag_reasons(photos, X, groups, strictness="normal", skip=()):
    """Likely-reject reasons per photo. Conservative: a flag means 'look at this', and stricter settings flag more.
    Blur is judged against the other frames of the same burst and on faces, never by overall detail alone:
    sky, sea, fog and night scenes have little fine detail but aren't blurry."""
    k = STRICTNESS.get(strictness, 1)
    v = lambda n: X[:, _IDX[n]].astype(np.float64)
    out = [[] for _ in photos]
    g = np.asarray(groups)
    sharp = v("c_sharp_max_tile")
    face = v("c_face_sharp")
    area = v("face_area")
    # Blurry, within a burst: clearly softer than the sharpest frame of the same moment (log scale: -0.7 is
    # about half the fine detail), on the whole frame or on the main face.
    t_burst = (-1.0, -0.75, -0.55)[k]
    for gid in np.unique(g):
        idx = [i for i in np.where(g == gid)[0] if i not in skip]
        if len(idx) < 2:
            continue
        top = np.nanmax(sharp[idx])
        faces_ok = [i for i in idx if not np.isnan(face[i])]
        ftop = np.nanmax(face[faces_ok]) if len(faces_ok) >= 2 else np.nan
        for i in idx:
            soft = sharp[i] - top < t_burst
            soft_face = not np.isnan(ftop) and not np.isnan(face[i]) and face[i] - ftop < t_burst - 0.1
            if soft or soft_face:
                out[i].append("blurry")
    # Blurry, single frames: only when there's a clear face and it is far softer than this shoot's faces.
    big = ~np.isnan(face) & (area > 0.01)
    if big.sum() >= 10:
        z = (face - np.nanmedian(face[big])) / (np.nanmedian(np.abs(face[big] - np.nanmedian(face[big]))) * 1.4826 + 1e-6)
        for i in np.where(big)[0]:
            if i not in skip and "blurry" not in out[i] and (g == g[i]).sum() == 1 and z[i] < (-3.5, -3.0, -2.5)[k]:
                out[i].append("blurry")
    # Eyes closed: the main face is blinking, or several people are in a small group.
    faces, frac, blink = v("c_faces"), v("c_closed_frac"), v("c_blink_max")
    eyes = v("c_eyes")
    for i in range(len(photos)):
        if i not in skip and faces[i] >= 1 and area[i] > (0.004, 0.003, 0.002)[k]:
            main_closed = not np.isnan(eyes[i]) and eyes[i] < (0.25, 0.35, 0.45)[k]
            group_closed = faces[i] <= 6 and frac[i] >= (0.5, 0.34, 0.25)[k] and blink[i] > 0.7
            if main_closed or group_closed:
                out[i].append("eyes")
    # Exposure way off: nearly black or nearly white overall, or far off from the rest of its burst (a frame the
    # flash or metering missed). Sunsets, snow and night scenes are fine on their own.
    mean = v("lum_mean")
    for i in range(len(photos)):
        if i in skip:
            continue
        dark = mean[i] < (0.02, 0.035, 0.05)[k]
        bright = mean[i] > (0.97, 0.95, 0.92)[k]
        sib = [j for j in np.where(g == g[i])[0] if j != i and j not in skip]
        odd = len(sib) >= 2 and abs(mean[i] - np.median(mean[sib])) > (0.3, 0.22, 0.16)[k]
        if dark or bright or odd:
            out[i].append("exposure")
    # Flash didn't fire: most frames around it (same camera, within a minute) used flash and this one is darker.
    import bisect
    flash = v("flash")
    times = [_time(p) for p in photos]
    timed = sorted((t, j) for j, t in enumerate(times) if t is not None)
    tkeys = [t for t, _ in timed]
    for i in range(len(photos)):
        if i in skip or flash[i] != 0 or times[i] is None:
            continue
        lo_i, hi_i = bisect.bisect_left(tkeys, times[i] - 60), bisect.bisect_right(tkeys, times[i] + 60)
        near = [j for _, j in timed[lo_i:hi_i]
                if j != i and photos[j].exif.get("camera") == photos[i].exif.get("camera")]
        if len(near) >= 3:
            fired = [j for j in near if flash[j] == 1]
            if len(fired) / len(near) >= 0.7 and mean[i] < np.median(mean[fired]) - 0.06:
                out[i].append("flash")
    return out


# ---------------------------------------------------------------- the keeper model

def model_path():
    return os.path.join(profiles_dir(), MODEL_NAME + ".virten-profile")


def load_model():
    p = model_path()
    if not os.path.exists(p):
        return None
    try:
        m = joblib.load(p)
        return m if isinstance(m, dict) and m.get("kind") == "cull" else None
    except Exception:
        return None


def is_keeper(p):
    """Your own decision in a finished cull: any star (or a Pick flag) = keeper."""
    return (p.rating or 0) >= 1 or p.pick > 0


def training_photos(catalog_path):
    """Photos of a finished cull: raws still on disk."""
    return [p for p in lrcat.list_photos(catalog_path) if p.is_raw and os.path.exists(p.path)]


def people_burst_frames(photos, X, groups, skip=()):
    """Frames of bursts where the quick analysis saw a face in every frame (they get the high-res face look)."""
    fi = _IDX["c_faces"]
    by = defaultdict(list)
    for i, gid in enumerate(groups):
        if i not in skip:
            by[gid].append(i)
    return [i for idx in by.values() if len(idx) > 1 and all(X[j, fi] >= 1 for j in idx) for i in idx]


def _burst_rel(F, g, how):
    out = np.zeros_like(F)
    for k in np.unique(g):
        idx = np.where(g == k)[0]
        sub = F[idx]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ref = np.nanmean(sub, 0) if how == "mean" else np.nanmax(sub, 0)
        ref = np.where(np.isnan(ref), 0, ref)
        out[idx] = np.where(np.isnan(sub), 0, sub - ref)
    return out


def face_matrix(F, g):
    """Each frame's faces, and how they differ from the burst's average and best (that's the choice you make)."""
    return np.hstack([F, _burst_rel(F, g, "mean"), _burst_rel(F, g, "max")])


def _people_bursts(idx, groups, F):
    """{burst id: [frame indexes]} for bursts where the high-res look found a face in every frame."""
    by = defaultdict(list)
    for i in idx:
        by[groups[i]].append(i)
    return {gid: ii for gid, ii in by.items() if len(ii) > 1 and all(i in F and F[i][0] > 0 for i in ii)}


def train(catalogs, progress=None, cancelled=lambda: False, save=True):
    """Learn which frame you keep in bursts of people, from finished culls (any star = kept). Only bursts where you
    kept some frames but not all teach it anything. Saves (and syncs) the model unless save=False."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from . import faces
    rows, ys, shoots = [], [], []
    for n, c in enumerate(catalogs):
        if cancelled():
            raise InterruptedError
        if progress:
            progress(n, len(catalogs), f"Reading {os.path.basename(c)}")
        photos = training_photos(c)
        if len(photos) < 30 or not any(is_keeper(p) for p in photos):
            continue
        X, ok = extract_many(photos, progress, cancelled)
        photos = [p for p, o in zip(photos, ok) if o]
        X = X[np.array(ok)]
        tl = find_timelapses(photos, X)
        groups = find_bursts(photos, X, skip=tl)
        cand = people_burst_frames(photos, X, groups, tl)
        kept = np.array([is_keeper(p) for p in photos])
        by = defaultdict(list)  # only bursts you actually chose within
        for i in cand:
            by[groups[i]].append(i)
        cand = [i for ii in by.values() if 0 < kept[ii].sum() < len(ii) for i in ii]
        if not cand:
            continue
        fv = faces.analyse_many([photos[i].path for i in cand], progress, cancelled)
        F = {i: fv[photos[i].path] for i in cand if photos[i].path in fv}
        pb = _people_bursts(cand, groups, F)
        idx = [i for ii in pb.values() for i in ii]
        if not idx:
            continue
        g = np.array([groups[i] for i in idx])
        rows.append(face_matrix(np.stack([F[i] for i in idx]), g))
        ys.append(kept[idx].astype(np.int8))
        shoots.append((c, len(pb)))
    n_bursts = sum(b for _, b in shoots)
    if n_bursts < 30:
        raise ValueError(f"Only {n_bursts} bursts of people where you kept some frames but not all were found. "
                         "At least 30 are needed; finish a few more culls of people shoots and try again.")
    if progress:
        progress(0, 1, "Learning your picks")
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20,
                                         l2_regularization=1.0, random_state=0).fit(no_empty_columns(np.vstack(rows)), np.concatenate(ys))
    model = {"kind": "cull", "name": MODEL_NAME, "version": 2, "clf": clf, "catalogs": [s[0] for s in shoots],
             "shoots": shoots, "n_bursts": n_bursts, "face_version": faces.FACE_VERSION,
             "created": datetime.datetime.now().isoformat(timespec="seconds"), "n_photos": int(sum(len(y) for y in ys))}
    if save:
        save_model(model)
    if progress:
        progress(1, 1, "Done")
    return model


def save_model(model):
    import json
    from . import sync
    joblib.dump(model, model_path(), compress=3)
    meta = {k: model[k] for k in ("kind", "name", "created", "n_photos", "catalogs", "n_bursts")}
    meta.update(metrics={}, tool_metrics={}, available_tools=[], feature_version=None, catalog_weights={},
                snapshot_step=None)
    with open(model_path() + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    try:
        sync.push_profile(model_path())
    except OSError:
        pass


# ---------------------------------------------------------------- running a cull

def analyse(photos, X, strictness="normal", model=None, progress=None, cancelled=lambda: False):
    """-> list of dicts per photo: group (burst number, 0 = none), burst_size, people (burst of people), best (the
    likely best frame of a people burst), score, reasons [...], timelapse. Timelapse frames get no flags or hints.
    The best-frame hint needs a trained model; without one, bursts and flags still work."""
    from collections import Counter
    tl = find_timelapses(photos, X)
    groups = find_bursts(photos, X, skip=tl)
    reasons = flag_reasons(photos, X, groups, strictness, skip=tl)
    sizes = Counter(groups)
    model = model if model is not None else load_model()
    score, best_set, people = {}, set(), set()
    cand = people_burst_frames(photos, X, groups, tl)
    from . import faces
    # A model trained on a different face-analysis version would be fed the wrong numbers: skip the hint instead.
    if model and model.get("version") == 2 and model.get("face_version") == faces.FACE_VERSION and cand:
        fv = faces.analyse_many([photos[i].path for i in cand], progress, cancelled)
        F = {i: fv[photos[i].path] for i in cand if photos[i].path in fv}
        for gid, idx in _people_bursts(cand, groups, F).items():
            s = model["clf"].predict_proba(face_matrix(np.stack([F[i] for i in idx]), np.full(len(idx), gid)))[:, 1]
            people.update(idx)
            for i, v in zip(idx, s):
                score[i] = float(v)
            ok = [i for i in idx if not reasons[i]]  # never point at a frame that's flagged as a likely reject
            if ok:
                best_set.add(max(ok, key=lambda i: score[i]))
    burst_no, nxt = {}, 1  # bursts numbered 1..n in capture order, for display
    for i in sorted(range(len(photos)), key=lambda i: (_time(photos[i]) or 0, photos[i].path)):
        gid = groups[i]
        if sizes[gid] > 1 and gid not in burst_no:
            burst_no[gid] = nxt
            nxt += 1
    return [{"group": burst_no.get(groups[i], 0), "burst_size": sizes[groups[i]] if sizes[groups[i]] > 1 else 1,
             "people": i in people, "best": i in best_set,
             "score": round(score[i], 3) if i in score else None, "reasons": reasons[i], "timelapse": i in tl}
            for i in range(len(photos))]


def keywords_for(r):
    """Lightroom keywords (paths under KW_ROOT, '|' = child) for one result."""
    if r.get("timelapse"):
        return ["Timelapse"]
    kws = [f"Likely reject|{REASONS[reason]}" for reason in r["reasons"]]
    if r["burst_size"] > 1:
        kws.append("Burst")
    if r["best"]:
        kws.append("Likely best frame")
    return kws


def collections_for(r):
    out = []
    if r["reasons"]:
        out.append("Likely rejects")
    if r["best"]:
        out.append("Likely best frames (people)")
    return out


def summarize(results):
    by = {k: sum(1 for r in results if k in r["reasons"]) for k in REASONS}
    return {"photos": len(results), "likely_rejects": sum(1 for r in results if r["reasons"]),
            "bursts": len({r["group"] for r in results if r["group"]}),
            "in_bursts": sum(1 for r in results if r["group"]),
            "people_bursts": len({r["group"] for r in results if r.get("people")}),
            "best_hints": sum(1 for r in results if r["best"]), "by_reason": by,
            "timelapse": sum(1 for r in results if r.get("timelapse"))}


def describe(r):
    """One line for the results grid."""
    if r.get("timelapse"):
        return "timelapse frame"
    parts = []
    if r["reasons"]:
        parts.append("✗ " + ", ".join(REASONS[x] for x in r["reasons"]))
    if r["best"]:
        parts.append(f"◆ likely best of burst {r['group']}")
    elif r["group"]:
        parts.append(f"burst {r['group']}")
    return " · ".join(parts)
