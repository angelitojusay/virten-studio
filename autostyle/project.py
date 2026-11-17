"""Editing projects: predict settings for a catalog's photos, hand them to the Lightroom plugin,
and analyze post-edit Lightroom tweaks for profile refinement."""
import datetime
import json
import os
import threading
import time
import uuid as uuidlib

import numpy as np

from . import catalog as lrcat
from . import looks
from .features import FEATURE_VERSION, extract_many, thumb_path
from .model import GROUPS, RANGES, _corrected, _is_num, display_name, load_profile, predict, safe_filename
from .paths import data_dir, projects_file


ARCHIVE_DAYS = 90
_INDEX_FIELDS_DROP = ("results",)
# Background jobs save projects while the UI reads and edits them: every project-file read-modify-write holds this.
_LOCK = threading.RLock()
_RETRIES = 8


def _project_dir():
    d = os.path.join(data_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def _project_path(pid):
    return os.path.join(_project_dir(), f"{pid}.json")


def _retry(fn):
    """fn(), retried while Windows reports the file briefly locked (antivirus, cloud sync or search indexing opening a
    file that was just written), so a busy file isn't mistaken for a missing one."""
    for i in range(_RETRIES):
        try:
            return fn()
        except PermissionError:
            if i == _RETRIES - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _write_json(path, data):
    with _LOCK:
        tmp = path + ".tmp"

        def write():
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, path)
        _retry(write)


def _read_index():
    """The project index; [] only when there's none yet. Raises (OSError / ValueError) when it exists but can't be
    read, so callers that rewrite it never replace the real list with an empty one."""
    def read():
        try:
            with open(projects_file(), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    return _retry(read)


def _summary(project):
    """What the project list needs (the per-photo results live in their own file)."""
    s = {k: v for k, v in project.items() if k not in _INDEX_FIELDS_DROP}
    res = project.get("results") or []
    s["cover"] = res[0]["thumb"] if res else s.get("cover")
    return s


def load_projects(include_archived=False):
    """Project summaries, newest first. Older versions kept everything in projects.json; split it on first load.
    For display: an unreadable index gives [] here (the file is left alone)."""
    with _LOCK:
        try:
            index = _index()
        except (OSError, ValueError) as e:
            print("couldn't read the project list:", e)
            return []
    return [p for p in index if include_archived or not p.get("archived_at")]


def _index():
    """All project summaries, for changing the index (raises rather than returning a truncated list). Hold _LOCK."""
    index = _read_index()
    if any("results" in p for p in index):
        for p in index:
            if "results" in p:
                _write_json(_project_path(p["id"]), p)
        index = [_summary(p) for p in index]
        _write_json(projects_file(), index)
    return index


def load_project(pid):
    """The full project, including per-photo results."""
    def read():
        with open(_project_path(pid), encoding="utf-8") as f:
            return json.load(f)
    with _LOCK:
        try:
            return _retry(read)
        except (OSError, ValueError):
            return next((p for p in load_projects(True) if p["id"] == pid), None)


def upsert_project(project):
    with _LOCK:
        _write_json(_project_path(project["id"]), project)
        index = [p for p in _index() if p["id"] != project["id"]]
        index.insert(0, _summary(project))
        _write_json(projects_file(), index)


def delete_project(pid):
    with _LOCK:
        _write_json(projects_file(), [p for p in _index() if p["id"] != pid])
        if os.path.exists(_project_path(pid)):
            _retry(lambda: os.remove(_project_path(pid)))


def archived_projects():
    return [p for p in load_projects(True) if p.get("archived_at")]


def mark_archived(pid, when=None):
    """Instant part of archiving: flags the project in the small index so the list updates right away.
    finish_archive() then updates the full record and makes the cloud backup (run it in the background)."""
    when = when or datetime.datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        index = _index()
        for p in index:
            if p["id"] == pid:
                p["archived_at"] = when
        _write_json(projects_file(), index)
    return when


def finish_archive(pid, when):
    with _LOCK:
        p = load_project(pid)
        if not p:
            return None
        p["archived_at"] = when
        _write_json(_project_path(pid), p)
    try:
        return backup_project(p)
    except OSError as e:
        print("backup failed", e)
        return None


def archive_project(pid):
    """Moves a project to Archived (kept ARCHIVE_DAYS) and, when sync is on, backs it up to the cloud folder.
    Returns the backup path (or None)."""
    with _LOCK:
        p = load_project(pid)
        if not p:
            return None
        p["archived_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        upsert_project(p)
    try:
        return backup_project(p)
    except OSError as e:
        print("backup failed", e)
        return None


def restore_project(pid):
    with _LOCK:
        p = load_project(pid)
        if p:
            p.pop("archived_at", None)
            upsert_project(p)


def removal_date(project):
    t = datetime.datetime.fromisoformat(project["archived_at"])
    return t + datetime.timedelta(days=ARCHIVE_DAYS)


def purge_archived():
    """Removes archived projects older than ARCHIVE_DAYS (their cloud backups are kept). Returns how many."""
    now = datetime.datetime.now()
    old = [p for p in archived_projects() if removal_date(p) <= now]
    for p in old:
        delete_project(p["id"])
    return len(old)


def backup_dir():
    from . import sync
    d = sync.sync_dir()
    if not d:
        return None
    out = os.path.join(d, "projects")
    os.makedirs(out, exist_ok=True)
    return out


def backup_project(project):
    """Zip of the project record, its thumbnails and the edits file, in <sync folder>/projects."""
    import zipfile
    out_dir = backup_dir()
    if not out_dir:
        return None
    p = load_project(project["id"]) or project
    stamp = (p.get("created") or "")[:10]
    path = os.path.join(out_dir, f"{safe_filename(p['name'])} {stamp} {p['id'][:8]}.virten-project.zip")
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(p, indent=1))
        for r in p.get("results") or []:
            if os.path.exists(r.get("thumb", "")):
                z.write(r["thumb"], "thumbs/" + os.path.basename(r["thumb"]), compress_type=zipfile.ZIP_STORED)
        edits = p.get("edits_file") or ""
        for f in (edits, edits + ".applied"):
            if f and os.path.exists(f):
                z.write(f, "edits/" + os.path.basename(f))
    os.replace(tmp, path)
    return path


def import_backup(zip_path):
    """Brings a backed-up project back into Virten Studio (into Archived, with a fresh 90 days)."""
    import zipfile
    from .paths import cache_dir
    with zipfile.ZipFile(zip_path) as z:
        p = json.loads(z.read("project.json"))
        thumbs = os.path.join(cache_dir(), "thumbs")
        os.makedirs(thumbs, exist_ok=True)
        for name in z.namelist():
            if name.startswith("thumbs/") and not name.endswith("/"):
                dest = os.path.join(thumbs, os.path.basename(name))
                if not os.path.exists(dest):
                    with open(dest, "wb") as f:
                        f.write(z.read(name))
    for r in p.get("results") or []:
        r["thumb"] = os.path.join(thumbs, os.path.basename(r.get("thumb", "")))
    p["archived_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    upsert_project(p)
    return p


FLAG_FILTERS = {
    "not_rejected": "All except rejected",
    "picked": "Picked (flagged) only",
    "unflagged": "Unflagged only",
    "any": "Any flag status",
}
LABELS = ["Red", "Yellow", "Green", "Blue", "Purple", ""]


def matches(p, f):
    """f: filter dict as saved on a project (folders, collections, flag, ratings, labels, only_unedited)."""
    if f.get("folders") is not None and p.folder not in f["folders"]:
        return False
    if f.get("collections") and not (p.collections & set(f["collections"])):
        return False
    flag = f.get("flag", "not_rejected")
    if (flag == "not_rejected" and p.pick < 0) or (flag == "picked" and p.pick <= 0) or (flag == "unflagged" and p.pick != 0):
        return False
    if f.get("ratings") is not None and int(p.rating or 0) not in f["ratings"]:
        return False
    if f.get("labels") is not None and (p.label or "") not in f["labels"]:
        return False
    if f.get("only_unedited", True) and p.is_edited:
        return False
    return True


def select_photos(catalog_path, filters, cached_photos=None):
    photos = cached_photos if cached_photos is not None else lrcat.list_photos(catalog_path)
    return [p for p in photos if p.is_raw and matches(p, filters) and p.exists_on_disk]


def _fmt(v):
    if isinstance(v, bool):
        return "B", "true" if v else "false"
    if isinstance(v, (int, float)):
        return "N", repr(v)
    if isinstance(v, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return "C", ",".join(repr(x) for x in v)
    if isinstance(v, str):
        return "S", v.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if isinstance(v, (list, dict)):
        return "J", json.dumps(v, ensure_ascii=True, separators=(",", ":"))
    return None, None


def write_edits_file(path, profile_name, items, kind=None, title=None):
    """items: list of (uuid, photo_path, settings). Line-based so the Lua plugin can parse it simply.
    kind="cull": no develop settings; each photo carries _Keywords / _Collections ("a;b") that the plugin adds
    under the "Virten Cull" keyword and a collection set named after `title`."""
    lines = ["VIRTEN\t1", f"PROFILE\t{profile_name}"]
    if kind:
        lines.append(f"KIND\t{kind}")
    if title:
        lines.append(f"TITLE\t{title}")
    for uid, ppath, settings in items:
        lines.append(f"PHOTO\t{uid}\t{ppath}")
        for k, v in settings.items():
            t, sv = _fmt(v)
            if t:
                lines.append(f"{t}\t{k}\t{sv}")
        lines.append("END")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def run_project(project, progress=None, cancelled=lambda: False):
    """Fills project['results'] and writes the .virten edits file next to the catalog."""
    if progress:
        progress(0, 1, "Reading catalog")
    photos = select_photos(project["catalog"], project.get("filters") or {})
    if not photos:
        raise ValueError("No matching RAW photos were found in this catalog with the chosen filters.")
    profile = load_profile(project["profile"]) if project.get("profile") else None  # None: Look only
    if profile and profile.get("feature_version") != FEATURE_VERSION:
        raise ValueError(f"The profile “{project['profile']}” was made with an older version of Virten Studio. "
                         "Retrain it under Profiles (photo analysis is cached, so it's quick).")
    look = looks.get_look(project["look"]) if project.get("look") else None
    if not profile and not look:
        raise ValueError(f"The Look “{project.get('look')}” wasn't found. Choose another Look or a profile.")
    X, ok = extract_many(photos, progress, cancelled)  # also makes the thumbnails for the results grid
    if cancelled():
        raise InterruptedError
    photos = [p for p, o in zip(photos, ok) if o]
    X = X[np.array(ok)]
    if progress:
        progress(0, 1, "Predicting edits")
    bias = project.get("exposure_bias", 0.0)
    if profile:
        base_settings = predict(profile, X, project.get("groups"), bias, [p.dims for p in photos],
                                project.get("tool_strength"))
        if project.get("burst_consistency", True):
            project["burst_smoothed"] = smooth_bursts(photos, X, base_settings)
    else:  # no per-photo corrections: the Look alone, on top of each photo's current settings
        base_settings = [{"Exposure2012": round(bias, 2)} if bias else {} for _ in photos]
    if look:
        settings = [looks.apply_look(s, look, project.get("look_strength", 1.0), dims=p.dims)
                    for s, p in zip(base_settings, photos)]
    else:
        settings = base_settings

    out_dir = os.path.join(os.path.dirname(project["catalog"]), "Virten Studio")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    edits_path = os.path.join(out_dir, f"{safe_filename(project['name'])} {stamp}.virten")
    label = (project["profile"] + (f" + {look['name']}" if look else "")) if profile else look["name"]
    write_edits_file(edits_path, label, [(p.uuid, p.path, s) for p, s in zip(photos, settings)])

    project["edits_file"] = edits_path
    project["status"] = "ready"
    project["count"] = len(photos)
    # base_settings (before the Look) and dims let Exposure Bias / Look Strength be re-exported instantly.
    project["results"] = [{"uuid": p.uuid, "path": p.path, "thumb": thumb_path(p.path),
                           "dims": list(p.dims), "base_settings": b, "settings": s,
                           "exif": photo_exif(p), "capture": p.capture or ""}
                          for p, b, s in zip(photos, base_settings, settings)]
    upsert_project(project)
    if progress:
        progress(1, 1, "Done")
    return project


def photo_exif(photo):
    """The catalog's shooting info for the info panels: {"iso", "aperture", "shutter", "focal", "camera"}, with
    Lightroom's APEX values converted to an f-number and seconds (None where the catalog has nothing)."""
    e = photo.exif or {}

    def num(k):
        v = e.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    av, tv = num("aperture"), num("shutter")
    return {"iso": num("iso"), "focal": num("focal"), "camera": e.get("camera") or "",
            "aperture": round(2 ** (av / 2), 1) if av is not None else None,  # APEX Av -> f-number
            "shutter": 2 ** -tv if tv is not None else None}  # APEX Tv -> seconds


def exif_for_results(catalog_path, results):
    """{path: (exif, capture)} for results saved before 1.6 without shooting info (read from the catalog)."""
    want = {r["path"] for r in results}
    return {p.path: (photo_exif(p), p.capture or "") for p in lrcat.list_photos(catalog_path) if p.path in want}


# ---------------------------------------------------------------- quick develop / re-export

# Sliders Quick Develop can nudge, with their ranges (Temperature in Kelvin).
QUICK_DEVELOP_KEYS = {"Exposure2012": (-5.0, 5.0), "Temperature": (2000, 50000), "Tint": (-150, 150),
                      "Contrast2012": (-100, 100), "Highlights2012": (-100, 100), "Shadows2012": (-100, 100),
                      "Whites2012": (-100, 100), "Blacks2012": (-100, 100), "Clarity2012": (-100, 100),
                      "Vibrance": (-100, 100), "Saturation": (-100, 100)}
WB_KEYS = ("Temperature", "Tint")


def _qd_value(key, v):
    lo, hi = QUICK_DEVELOP_KEYS[key]
    v = min(max(float(v), lo), hi)
    return round(v, 2) if key == "Exposure2012" else int(round(v))


def effective_base_settings(r):
    """A photo's settings before the Look: Virten Studio's prediction (base_settings) plus the user's Quick Develop
    nudges (user_deltas). Older results without base_settings fall back to the exported settings."""
    s = dict(r.get("base_settings") if "base_settings" in r else (r.get("settings") or {}))
    deltas = r.get("user_deltas") or {}
    for k, d in deltas.items():
        if k in QUICK_DEVELOP_KEYS:
            s[k] = _qd_value(k, float(s.get(k, 0) or 0) + float(d))
    if any(k in deltas for k in WB_KEYS):
        s["WhiteBalance"] = "Custom"
    return s


def _check_reexportable(p):
    results = p.get("results") or []
    if not results:
        raise ValueError("This project has no saved per-photo edits to re-export.")
    if p.get("look") and any("base_settings" not in r for r in results):
        # Older projects only kept the final settings, which already include the Look: applying it again would
        # double it.
        raise ValueError("This project was made with an older version of Virten Studio, so its Look can't be "
                         "changed here. Run it again as a new project.")
    for r in results:  # older project without a Look: its exported settings are the base
        r.setdefault("base_settings", dict(r.get("settings") or {}))
    return results


def _set_look(p, look_name, look_strength):
    if look_name is not False:
        p["look"] = look_name
    if look_strength is not None:
        p["look_strength"] = float(look_strength)
    look = looks.get_look(p["look"]) if p.get("look") else None
    if p.get("look") and not look:
        raise ValueError(f"The Look “{p['look']}” wasn't found.")
    if not p.get("profile") and not look:
        raise ValueError("A Look-only project needs a Look.")
    return look


def _write_project_edits(p, look):
    """Recomputes every photo's final settings (base + user nudges, then the Look) and writes a fresh .virten file,
    replacing a previous one that hasn't been applied yet so the plugin finds only one."""
    items = []
    for r in p["results"]:
        dims = tuple(r.get("dims") or (0, 0))
        base = effective_base_settings(r)
        final = looks.apply_look(base, look, p.get("look_strength", 1.0), dims=dims) if look else base
        r["settings"] = final
        items.append((r.get("uuid") or "", r["path"], final))
    out_dir = os.path.join(os.path.dirname(p["catalog"]), "Virten Studio")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    edits_path = os.path.join(out_dir, f"{safe_filename(p['name'])} {stamp}.virten")
    label = (p["profile"] + (f" + {look['name']}" if look else "")) if p.get("profile") else look["name"]
    write_edits_file(edits_path, label, items)
    old = p.get("edits_file")
    if old and old != edits_path and os.path.exists(old):  # not applied yet: superseded by the new file
        os.remove(old)
    p["edits_file"] = edits_path
    upsert_project(p)
    return p


def apply_quick_develop(project, photo_indices=None, deltas=None, reset=False, look_name=False, look_strength=None):
    """Lightroom Library-style Quick Develop on a finished project, without re-analysing anything.

    photo_indices: result indices to change (None = every photo). deltas: relative nudges, e.g.
    {"Exposure2012": +0.33, "Temperature": -150, "Shadows2012": 10} (see QUICK_DEVELOP_KEYS). They accumulate in each
    photo's r["user_deltas"] on top of the untouched prediction r["base_settings"]; reset=True clears the selected
    photos' nudges first. Values are clamped to Lightroom's ranges, and Temperature/Tint set WhiteBalance "Custom".
    Temperature/Tint can't be nudged on photos that have no white balance of their own in the project (White Balance
    panel off, or Look only): Lightroom's As Shot value isn't known here. Those are skipped and counted in
    p["quick_develop_skipped"]. look_name/look_strength change the Look as in reexport_project_edits. Every photo's
    final settings are recomputed and the .virten file rewritten."""
    p = load_project(project["id"]) or project
    results = _check_reexportable(p)
    deltas = {k: float(v) for k, v in (deltas or {}).items() if v}
    unknown = sorted(set(deltas) - set(QUICK_DEVELOP_KEYS))
    if unknown:
        raise ValueError(f"Quick Develop can't change: {', '.join(unknown)}")
    if photo_indices is None:
        idx = range(len(results))
    else:
        idx = sorted({int(i) for i in photo_indices})
        if any(i < 0 or i >= len(results) for i in idx):
            raise ValueError("A selected photo isn't part of this project.")
    skipped = 0
    for i in idx:
        r = results[i]
        user = {} if reset else dict(r.get("user_deltas") or {})
        base = r["base_settings"]
        missed = False
        for k, d in deltas.items():
            if k in WB_KEYS and k not in base:
                missed = True
                continue
            b = float(base.get(k, 0) or 0)
            new = _qd_value(k, b + float(user.get(k, 0)) + d)  # clamp the result, not the nudge
            nudge = round(new - b, 2) if k == "Exposure2012" else int(round(new - b))
            if nudge:
                user[k] = nudge
            else:
                user.pop(k, None)
        skipped += missed
        if user:
            r["user_deltas"] = user
        else:
            r.pop("user_deltas", None)
    look = _set_look(p, look_name, look_strength)
    p["quick_develop_skipped"] = skipped
    return _write_project_edits(p, look)


def reexport_project_edits(project, exposure_bias=None, look_name=False, look_strength=None):
    """Fast re-generation of the .virten edits file when the user adjusts Exposure Bias or the Look (name or
    strength) on a finished project: no photo analysis or model prediction. look_name=False keeps the current Look,
    None removes it. Quick Develop nudges (user_deltas) are kept. Replaces a previous edits file that hasn't been
    applied yet, so the plugin finds only one."""
    p = load_project(project["id"]) or project
    results = _check_reexportable(p)
    old_bias = float(p.get("exposure_bias") or 0.0)
    new_bias = old_bias if exposure_bias is None else float(exposure_bias)
    bias_delta = new_bias - old_bias
    look = _set_look(p, look_name, look_strength)
    p["exposure_bias"] = new_bias
    # Exposure bias only touches exposure where the original run set it (the Light panel was on, or Look only).
    bias_applies = not p.get("profile") or "tone" in (p.get("groups") or GROUPS)
    lo, hi = RANGES["Exposure2012"]
    if abs(bias_delta) > 1e-6:
        for r in results:
            base = r["base_settings"]
            if bias_applies or "Exposure2012" in base:
                base["Exposure2012"] = round(min(max(float(base.get("Exposure2012", 0.0)) + bias_delta, lo), hi), 2)
    return _write_project_edits(p, look)


# ---------------------------------------------------------------- burst-consistent editing

def smooth_bursts(photos, X, settings):
    """Frames of one burst should match: pulls each frame's white balance (65 % own prediction, 35 % burst median, in
    mireds for Temperature) and, for frames lit like the rest of the burst (preview brightness within 0.12 of the
    burst median), exposure (75 % own, 25 % median) together. settings is changed in place; returns how many photos
    changed. Timelapse frames are left alone."""
    from . import cull
    from .features import FEATURE_NAMES
    groups = cull.find_bursts(photos, X, skip=cull.find_timelapses(photos, X))
    lum = X[:, FEATURE_NAMES.index("lum_mean")].astype(float)
    members = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    changed = set()
    for idx in members.values():
        if len(idx) < 2:
            continue
        temps = [i for i in idx if isinstance(settings[i].get("Temperature"), (int, float))]
        if len(temps) >= 2:
            med = float(np.median([1e6 / settings[i]["Temperature"] for i in temps]))
            for i in temps:
                new = int(round(1e6 / (0.65 * (1e6 / settings[i]["Temperature"]) + 0.35 * med)))
                if new != settings[i]["Temperature"]:
                    settings[i]["Temperature"] = new
                    changed.add(i)
        tints = [i for i in idx if isinstance(settings[i].get("Tint"), (int, float))]
        if len(tints) >= 2:
            med = float(np.median([settings[i]["Tint"] for i in tints]))
            for i in tints:
                new = int(round(0.65 * settings[i]["Tint"] + 0.35 * med))
                if new != settings[i]["Tint"]:
                    settings[i]["Tint"] = new
                    changed.add(i)
        lit = [i for i in idx if not np.isnan(lum[i])]
        if len(lit) >= 2:
            med_lum = float(np.median(lum[lit]))
            same = [i for i in lit if abs(lum[i] - med_lum) <= 0.12
                    and isinstance(settings[i].get("Exposure2012"), (int, float))]
            if len(same) >= 2:
                med = float(np.median([settings[i]["Exposure2012"] for i in same]))
                for i in same:
                    new = round(0.75 * settings[i]["Exposure2012"] + 0.25 * med, 2)
                    if new != settings[i]["Exposure2012"]:
                        settings[i]["Exposure2012"] = new
                        changed.add(i)
    return len(changed)


def analyze_project_tweaks(project):
    """Compares the current develop settings in the Lightroom catalog against what Virten Studio predicted
    for this project. Returns a breakdown of tweaked vs untouched photos and average slider deltas."""
    p = load_project(project["id"]) or project
    cat_path = p.get("catalog") or ""
    if not os.path.exists(cat_path):
        raise ValueError(f"Catalog not found at:\n{cat_path}")

    pred_by_path = {os.path.normpath(r["path"]): r for r in (p.get("results") or [])}
    if not pred_by_path:
        raise ValueError("This project has no saved per-photo predictions to compare against.")

    tracked_keys = GROUPS["tone"]["keys"] + GROUPS["wb"]["keys"] + GROUPS["presence"]["keys"]
    tweaked_photos, approved_photos, unapplied_photos = [], [], []
    deltas_by_key = {k: [] for k in tracked_keys}

    for cp in lrcat.list_photos(cat_path):
        np_path = os.path.normpath(cp.path)
        r = pred_by_path.get(np_path)
        if r is None:
            continue
        pred_s = r.get("settings") or {}
        final_s = cp.settings
        if not cp.is_edited:
            unapplied_photos.append(np_path)
            continue

        is_tweaked = _corrected(final_s, pred_s)
        photo_deltas = {}
        for k in tracked_keys:
            a, b = final_s.get(k), pred_s.get(k)
            if _is_num(a) and _is_num(b):
                d = float(a) - float(b)
                if abs(d) > (0.04 if k == "Exposure2012" else (40 if k == "Temperature" else 1.5)):
                    photo_deltas[k] = round(d, 2) if k == "Exposure2012" else int(round(d))
                    if is_tweaked:
                        deltas_by_key[k].append(d)

        if is_tweaked:
            tweaked_photos.append({"path": cp.path, "thumb": r.get("thumb", ""), "name": os.path.basename(cp.path),
                                   "last_step": cp.last_step, "deltas": photo_deltas, "predicted": pred_s,
                                   "final": final_s})
        else:
            approved_photos.append(cp.path)

    avg_deltas = {}
    for k, vals in deltas_by_key.items():
        if len(vals) >= 2:
            rnd = (lambda v: round(v, 2)) if k == "Exposure2012" else (lambda v: int(round(v)))
            avg_deltas[k] = {"mean": rnd(float(np.mean(vals))), "median": rnd(float(np.median(vals))),
                             "count": len(vals), "label": display_name(k)}

    return {
        "total_project_photos": len(pred_by_path),
        "tweaked_count": len(tweaked_photos),
        "approved_count": len(approved_photos),
        "unapplied_count": len(unapplied_photos),
        "tweaked_photos": tweaked_photos,
        "approved_paths": approved_photos,
        "avg_deltas": avg_deltas,
        "used_look": p.get("look"),
        "look_strength": p.get("look_strength", 1.0),
    }


def run_cull(project, progress=None, cancelled=lambda: False):
    """Assisted cull: finds bursts, timelapses, likely rejects and (with a trained model) the likely best frame of
    bursts of people, and writes a .virten file the plugin turns into keywords and collections. Ratings, labels,
    flags and develop settings are never changed."""
    from . import cull
    if progress:
        progress(0, 1, "Reading catalog")
    photos = select_photos(project["catalog"], project.get("filters") or {})
    if len(photos) < 2:
        raise ValueError("No matching RAW photos were found in this catalog with the chosen filters.")
    X, ok = extract_many(photos, progress, cancelled)
    if cancelled():
        raise InterruptedError
    photos = [p for p, o in zip(photos, ok) if o]
    X = X[np.array(ok)]
    if progress:
        progress(0, 1, "Finding bursts and likely rejects")
    results = cull.analyse(photos, X, project.get("strictness", "normal"), progress=progress, cancelled=cancelled)
    if cancelled():
        raise InterruptedError
    out_dir = os.path.join(os.path.dirname(project["catalog"]), "Virten Studio")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"{safe_filename(project['name'])} cull {stamp}.virten")
    items = [(p.uuid, p.path, {"_Keywords": ";".join(cull.keywords_for(r)),
                               "_Collections": ";".join(cull.collections_for(r))})
             for p, r in zip(photos, results)]
    write_edits_file(path, "Assisted cull", items, kind="cull", title=project["name"])
    order = sorted(range(len(photos)), key=lambda i: (photos[i].capture or "", photos[i].path))
    project.update(edits_file=path, status="ready", count=len(photos), summary=cull.summarize(results),
                   model=bool(cull.load_model()),
                   results=[{"path": photos[i].path, "thumb": thumb_path(photos[i].path), "settings": {},
                             "capture": photos[i].capture, "exif": photo_exif(photos[i]),
                             "dims": list(photos[i].dims), **results[i]} for i in order])
    upsert_project(project)
    if progress:
        progress(1, 1, "Done")
    return project


def cull_learning_catalogs():
    """Catalogs to learn culling from: the shoots your profiles learned from, plus culls you marked as finished
    ("Learn from this cull"), still on disk. Culls in progress are left out: half-done ratings would mislead it."""
    from .model import list_profiles
    from . import cull
    cats = []
    for meta in list_profiles():
        cats += meta.get("catalogs") or []
    cats += [p["catalog"] for p in load_projects(True) if p.get("kind") == "cull" and p.get("learned")]
    m = cull.load_model()
    cats += (m or {}).get("catalogs") or []
    return [c for c in dict.fromkeys(os.path.normpath(c) for c in cats) if os.path.exists(c)]


def new_project(name, catalog_path, profile, **opts):
    return {"id": uuidlib.uuid4().hex, "name": name, "catalog": catalog_path, "profile": profile,
            "created": datetime.datetime.now().isoformat(timespec="seconds"), "status": "new", **opts}


def learning_candidates(profile_meta):
    """Catalogs from applied projects that the profile hasn't learned from yet, and Virten Studio's predictions
    for their photos (used to spot the photos you corrected)."""
    known = set(profile_meta.get("catalogs") or [])
    new = []
    for p in load_projects(True):
        if p.get("kind") != "cull" and edits_applied(p) and p["catalog"] not in known and p["catalog"] not in new and os.path.exists(p["catalog"]):
            new.append(p["catalog"])
    return new


def feedback_for(catalogs):
    """{photo path (normalised): settings Virten Studio exported} for projects on these catalogs."""
    catalogs = {os.path.normpath(c) for c in catalogs}
    fb = {}
    for meta in load_projects(True):
        if os.path.normpath(meta["catalog"]) in catalogs and meta.get("kind") != "cull":
            p = load_project(meta["id"]) or {}
            for r in p.get("results") or []:
                fb[os.path.normpath(r["path"])] = r["settings"]
    return fb


def edits_applied(project):
    f = project.get("edits_file")
    return bool(f) and not os.path.exists(f) and os.path.exists(f + ".applied")
