"""Read-only access to Lightroom Classic catalogs (.lrcat, SQLite).

Catalogs are opened with ``mode=ro`` so they read through Lightroom's live
write-ahead journal (.lrcat-wal) while Lightroom is open, falling back to
``immutable=1`` on read-only media. Nothing is ever written to them."""
import os
import sqlite3
import zlib
from dataclasses import dataclass, field

from .lua import parse_settings

RAW_EXTS = {"ARW", "CR2", "CR3", "NEF", "NRW", "RAF", "ORF", "RW2", "PEF", "SRW", "DNG", "3FR", "IIQ", "ERF", "X3F"}
TONE_KEYS = ("Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012")

# Single-pass CTE pre-aggregates the history table once instead of running
# two correlated subqueries per photo row.
_QUERY = """
with hist as (
    select image,
           max(case when name not like 'Import%' then 1 else 0 end) as touched,
           max(dateCreated) as max_date
    from Adobe_libraryImageDevelopHistoryStep
    group by image
),
latest_step as (
    select h.image, h.name as last_step
    from Adobe_libraryImageDevelopHistoryStep h
    join hist on hist.image = h.image and hist.max_date = h.dateCreated
    group by h.image
)
select i.id_local, i.id_global, rf.absolutePath, rf.relativePathFromCatalog, fo.pathFromRoot,
       f.baseName, f.extension, i.pick, i.rating, d.text,
       coalesce(hist.touched, 0) as touched,
       e.isoSpeedRating, e.aperture, e.shutterSpeed, e.focalLength, e.flashFired, cm.value,
       i.fileWidth, i.fileHeight, i.colorLabels, i.captureTime,
       coalesce(ls.last_step, '') as last_step
from Adobe_images i
join AgLibraryFile f on f.id_local = i.rootFile
join AgLibraryFolder fo on fo.id_local = f.folder
join AgLibraryRootFolder rf on rf.id_local = fo.rootFolder
left join Adobe_imageDevelopSettings d on d.image = i.id_local
left join AgHarvestedExifMetadata e on e.image = i.id_local
left join AgInternedExifCameraModel cm on cm.id_local = e.cameraModelRef
left join hist on hist.image = i.id_local
left join latest_step ls on ls.image = i.id_local
where i.masterImage is null
"""


@dataclass
class CatalogPhoto:
    catalog: str
    uuid: str
    path: str
    ext: str
    folder: str
    pick: float
    rating: float
    settings_text: str
    touched: bool
    exif: dict = field(default_factory=dict)
    dims: tuple = (0, 0)
    image_id: int = 0
    label: str = ""
    capture: str = ""
    collections: frozenset = frozenset()
    last_step: str = ""
    _settings: dict = None
    _exists: bool = None

    @property
    def is_raw(self):
        return self.ext.upper() in RAW_EXTS

    @property
    def exists_on_disk(self):
        if self._exists is None:
            self._exists = os.path.exists(self.path)
        return self._exists

    @property
    def settings(self):
        if self._settings is None:
            try:
                self._settings = parse_settings(self.settings_text)
            except ValueError:
                self._settings = {}
        return self._settings

    @property
    def is_edited(self):
        """Has a real develop edit: a non-import history step and tone/WB moved off defaults."""
        if not self.touched:
            return False
        s = self.settings
        if s.get("WhiteBalance") not in (None, "As Shot"):
            return True
        return any(abs(float(s.get(k, 0) or 0)) > 1e-6 for k in TONE_KEYS)

    @property
    def app_edit_untouched(self):
        """The latest edit is Virten Studio's own (or AutoStyle's) and you didn't change it afterwards.
        Training skips these by default so a profile doesn't learn from its own unverified guesses;
        photos you tweaked afterwards have a newer history step and count with extra weight."""
        return self.last_step.startswith(("Virten Studio:", "AutoStyle:"))

    @property
    def is_grayscale(self):
        return bool(self.settings.get("ConvertToGrayscale"))


def connect(catalog_path):
    """Read-only connection. Lightroom keeps its newest changes (ratings, edits) in a write-ahead journal
    (.lrcat-wal) while it's open, so read through the journal; fall back to reading the main file alone if the
    journal can't be opened (e.g. a read-only drive)."""
    base = "file:" + catalog_path.replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    try:
        con = sqlite3.connect(base + "?mode=ro", uri=True, timeout=10)
        con.execute("select count(*) from Adobe_images").fetchone()
        return con
    except sqlite3.Error:
        return sqlite3.connect(base + "?mode=ro&immutable=1", uri=True)


def _resolve(catalog_path, abs_root, rel_root, path_from_root, base, ext):
    name = f"{base}.{ext}"
    p = os.path.normpath((abs_root or "") + (path_from_root or "") + name)
    if os.path.exists(p) or not rel_root:
        return p
    alt = os.path.normpath(os.path.join(os.path.dirname(catalog_path), rel_root, path_from_root or "", name))
    return alt if os.path.exists(alt) else p


_COLLECTION_MEMBERS = """
select ci.image, ci.collection from AgLibraryCollectionImage ci
join AgLibraryCollection c on c.id_local = ci.collection
where c.creationId = 'com.adobe.ag.library.collection'
"""


def list_collections(catalog_path):
    """Regular (non-smart) collections: [(id, display name, photo count)]."""
    con = connect(catalog_path)
    try:
        rows = con.execute("""select c.id_local, c.name, c.systemOnly, p.name,
                                     (select count(*) from AgLibraryCollectionImage ci where ci.collection = c.id_local)
                              from AgLibraryCollection c left join AgLibraryCollection p on p.id_local = c.parent
                              where c.creationId = 'com.adobe.ag.library.collection'""").fetchall()
    finally:
        con.close()
    out = []
    for cid, name, system, parent, count in rows:
        display = "Quick Collection" if system and name == "quick collection" else name
        if parent:
            display = f"{parent} ▸ {display}"
        if count:
            out.append((cid, display, count))
    return sorted(out, key=lambda r: r[1].lower())


def _step_text(text):
    """History-step settings are stored as text, or as zlib-compressed bytes with a 4-byte length prefix."""
    if isinstance(text, bytes):
        try:
            return zlib.decompress(text[4:]).decode("utf-8")
        except zlib.error:
            return None
    return text


IGNORED_STEPS = ("Import", "Export", "Virten Studio:", "AutoStyle:", "Crop", "Paste", "Reset", "Select Variation")


def history_step_counts(catalog_paths):
    """{step name: photos} for named history steps worth learning from (e.g. "Imagen: LOVE & LIGHT")."""
    counts = {}
    for c in catalog_paths:
        try:
            con = connect(c)
            for name, n in con.execute("select name, count(distinct image) from Adobe_libraryImageDevelopHistoryStep "
                                       "group by name"):
                if name and not name.startswith(IGNORED_STEPS) and n >= 20:
                    counts[name] = counts.get(name, 0) + n
            con.close()
        except sqlite3.Error:
            pass
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def step_snapshots(catalog_path, step_name):
    """{image id: settings text} as they were right after the named history step (the latest one per photo)."""
    con = connect(catalog_path)
    try:
        rows = con.execute("select image, text from Adobe_libraryImageDevelopHistoryStep where name = ? "
                           "order by dateCreated", (step_name,)).fetchall()
    finally:
        con.close()
    return {img: t for img, t in ((img, _step_text(text)) for img, text in rows) if t}


def list_photos(catalog_path):
    con = connect(catalog_path)
    try:
        rows = con.execute(_QUERY).fetchall()
        membership = {}
        for img, coll in con.execute(_COLLECTION_MEMBERS):
            membership.setdefault(img, set()).add(coll)
        membership = {k: frozenset(v) for k, v in membership.items()}
    finally:
        con.close()
    photos = []
    for (_id, uuid, abs_root, rel_root, pfr, base, ext, pick, rating, text, touched,
         iso, ap, sh, fl, flash, cam, fw, fh, color, captured, last_step) in rows:
        path = _resolve(catalog_path, abs_root, rel_root, pfr, base, ext)
        photos.append(CatalogPhoto(
            catalog=catalog_path, uuid=uuid, path=path, ext=ext or "", folder=os.path.dirname(path),
            pick=pick or 0, rating=rating or 0, settings_text=text or "", touched=bool(touched),
            exif={"iso": iso, "aperture": ap, "shutter": sh, "focal": fl, "flash": flash, "camera": cam or ""},
            dims=(fw or 0, fh or 0), image_id=_id, label=color or "", capture=captured or "",
            last_step=last_step or "", collections=membership.get(_id, frozenset()),
        ))
    return photos


def summarize(catalog_path):
    """Counts used by the GUI: total, raw, edited raw (colour) on disk, unedited raw."""
    photos = list_photos(catalog_path)
    raw = [p for p in photos if p.is_raw]
    edited = [p for p in raw if p.is_edited and not p.is_grayscale and p.exists_on_disk]
    return {"total": len(photos), "raw": len(raw), "trainable": len(edited),
            "unedited": sum(1 for p in raw if not p.is_edited)}


def find_catalogs(root, max_depth=5):
    found = []
    root = os.path.abspath(root)
    base_depth = root.rstrip("\\/").count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.endswith((".lrdata", "Previews.lrdata")) and not d.startswith("$")]
        for f in filenames:
            if f.lower().endswith(".lrcat"):
                found.append(os.path.join(dirpath, f))
    return found
