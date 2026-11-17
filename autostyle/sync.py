"""Keeps profiles, imported looks and app updates in a cloud-synced folder (e.g. OneDrive) so a desktop and a
laptop share the latest learned styles. Newest version wins; deletions leave a small marker so they propagate.
App updates also come from the project's GitHub Releases, so computers without the sync folder get them too."""
import datetime
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from . import __version__, prefs
from .paths import cache_dir, profiles_dir

SUBDIRS = ("profiles", "looks", "app")


def sync_dir():
    d = prefs.load().get("sync_dir")
    return d if d and os.path.isdir(d) else None


def set_sync_dir(path):
    prefs.save(sync_dir=path)
    if path:
        for s in SUBDIRS:
            os.makedirs(os.path.join(path, s), exist_ok=True)


def cloud_folders():
    """[(service, suggested Virten Studio sync folder)] for cloud drives on this computer, Google Drive first."""
    import glob
    import string
    out = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            if os.path.isdir(f"{letter}:\\My Drive"):  # Google Drive for desktop's virtual drive
                out.append(("Google Drive", os.path.join(f"{letter}:\\My Drive", "Virten Studio Sync")))
                break
    else:  # macOS: ~/Library/CloudStorage/GoogleDrive-<account>/My Drive, OneDrive-<account>
        for d in sorted(glob.glob(os.path.expanduser("~/Library/CloudStorage/GoogleDrive-*/My Drive"))):
            out.append(("Google Drive", os.path.join(d, "Virten Studio Sync")))
            break
    legacy = os.path.join(os.path.expanduser("~"), "Google Drive")
    if not out and os.path.isdir(legacy):
        out.append(("Google Drive", os.path.join(legacy, "Virten Studio Sync")))
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if not od:
        mac_od = sorted(glob.glob(os.path.expanduser("~/Library/CloudStorage/OneDrive-*")))
        od = mac_od[0] if mac_od else None
    if od and os.path.isdir(od):
        out.append(("OneDrive", os.path.join(od, "Virten Studio Sync")))
    return out


def _sub(name):
    d = sync_dir()
    if not d:
        return None
    p = os.path.join(d, name)
    os.makedirs(p, exist_ok=True)
    return p


def _created(meta_path):
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f).get("created", "")
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------- profiles

def push_profile(profile_file):
    """Copy a just-saved profile (and its .json summary) to the sync folder."""
    d = _sub("profiles")
    if not d:
        return
    base = os.path.basename(profile_file)
    for src in (profile_file, profile_file + ".json"):
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, os.path.basename(src) + ".tmp"))
            os.replace(os.path.join(d, os.path.basename(src) + ".tmp"), os.path.join(d, os.path.basename(src)))
    marker = os.path.join(d, base + ".deleted")
    if os.path.exists(marker):
        os.remove(marker)


def push_profile_delete(profile_file):
    d = _sub("profiles")
    if not d:
        return
    base = os.path.basename(profile_file)
    for fn in (base, base + ".json"):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            os.remove(p)
    with open(os.path.join(d, base + ".deleted"), "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds"))


def pull_profiles():
    """Bring newer profiles from the sync folder; returns names that changed locally."""
    d = _sub("profiles")
    if not d:
        return []
    changed = []
    local = profiles_dir()
    for fn in os.listdir(d):
        remote_file = os.path.join(d, fn)
        if fn.endswith(".virten-profile.deleted"):
            base = fn[: -len(".deleted")]
            lp = os.path.join(local, base)
            with open(remote_file, encoding="utf-8") as f:
                deleted_at = f.read().strip()
            if os.path.exists(lp) and _created(lp + ".json") <= deleted_at:
                for p in (lp, lp + ".json"):
                    if os.path.exists(p):
                        os.remove(p)
                changed.append(base)
            continue
        if not fn.endswith(".virten-profile") or not os.path.exists(remote_file + ".json"):
            continue
        lp = os.path.join(local, fn)
        if _created(remote_file + ".json") > _created(lp + ".json"):
            shutil.copy2(remote_file, lp + ".tmp")
            os.replace(lp + ".tmp", lp)
            shutil.copy2(remote_file + ".json", lp + ".json")
            changed.append(fn)
    return changed


# ---------------------------------------------------------------- looks

def sync_looks():
    from .looks import user_dir
    d = _sub("looks")
    if not d:
        return
    local = user_dir()
    names = set(os.listdir(local)) | set(os.listdir(d))
    for fn in names:
        if not fn.endswith(".json"):
            continue
        a, b = os.path.join(local, fn), os.path.join(d, fn)
        marker = b + ".deleted"
        if os.path.exists(marker):
            if os.path.exists(a) and os.path.getmtime(a) <= os.path.getmtime(marker):
                os.remove(a)
            continue
        ta = os.path.getmtime(a) if os.path.exists(a) else -1
        tb = os.path.getmtime(b) if os.path.exists(b) else -1
        if ta > tb:
            shutil.copy2(a, b)
        elif tb > ta:
            shutil.copy2(b, a)


def push_look_delete(look_file):
    d = _sub("looks")
    if not d:
        return
    p = os.path.join(d, os.path.basename(look_file))
    if os.path.exists(p):
        os.remove(p)
    with open(p + ".deleted", "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------- app updates

GITHUB_REPO = "angelitojusay/virten-studio"  # default; Settings (prefs "github_repo") or a checkout's git remote win
GITHUB_TIMEOUT = 4  # seconds: an offline computer must not hang the update check
_GH_CACHE_SECONDS = 15 * 60  # ask GitHub at most once per 15 minutes (60 unauthenticated requests/hour per IP)
_gh_cache = {}
_git_repo = []
INSTALLER_EXT = ".dmg" if sys.platform == "darwin" else ".exe"


def _ver(v):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


def _repo_from_git():
    """'owner/name' of `git remote get-url origin` when running from a git checkout (the packaged app has none)."""
    if not _git_repo:
        repo = None
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not getattr(sys, "frozen", False) and os.path.isdir(os.path.join(src, ".git")):
            try:
                url = subprocess.run(["git", "-C", src, "remote", "get-url", "origin"], capture_output=True, text=True,
                                     timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
                m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
                repo = m.group(1) if m else None
            except (OSError, subprocess.SubprocessError):
                pass
        _git_repo.append(repo)
    return _git_repo[0]


def github_repo():
    """'owner/name' of the GitHub repository whose Releases carry app updates: the one set in Settings, else the git
    remote of a source checkout, else GITHUB_REPO."""
    return (prefs.load().get("github_repo") or "").strip() or _repo_from_git() or GITHUB_REPO


def _github_headers(raw=False):
    """A read-only token (Settings, for a private repository) is sent when there is one."""
    h = {"User-Agent": "VirtenStudio-Updater",
         "Accept": "application/octet-stream" if raw else "application/vnd.github+json"}
    token = (prefs.load().get("github_token") or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub serves release files from a signed storage URL on another host: the token mustn't go there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def _open(url, headers, timeout):
    return urllib.request.build_opener(_DropAuthOnRedirect).open(urllib.request.Request(url, headers=headers),
                                                                  timeout=timeout)


def github_latest_release(force=False):
    """The repository's latest published release (GitHub's JSON) or None when offline, rate limited or there's no
    release. Asked at most once per _GH_CACHE_SECONDS unless force."""
    repo = github_repo()
    hit = _gh_cache.get(repo)
    if hit and not force and time.time() - hit[0] < _GH_CACHE_SECONDS:
        return hit[1]
    data = None
    try:
        with _open(f"https://api.github.com/repos/{repo}/releases/latest", _github_headers(), GITHUB_TIMEOUT) as r:
            data = json.load(r)
    except (OSError, ValueError, http.client.HTTPException) as e:
        print("GitHub update check:", e)
    _gh_cache[repo] = (time.time(), data if isinstance(data, dict) else None)
    return _gh_cache[repo][1]


def _github_update():
    rel = github_latest_release()
    if not rel or rel.get("draft") or rel.get("prerelease"):
        return None
    ver = str(rel.get("tag_name") or "").strip().lstrip("vV")
    if not _ver(ver) or _ver(ver) <= _ver(__version__):
        return None
    private = bool((prefs.load().get("github_token") or "").strip())
    for a in rel.get("assets") or []:
        name = a.get("name") or ""
        if not name.lower().endswith(INSTALLER_EXT):
            continue
        # A private repository's files are only reachable through the API URL (with the token).
        url = a.get("url") if private and a.get("url") else a.get("browser_download_url")
        if url and url.startswith("https://"):
            if os.path.basename(urllib.parse.urlsplit(url).path) != name:
                url += "#" + urllib.parse.quote(name)  # the file name, for download_update
            return ver, url
    return None


def _sync_folder_update():
    """app/latest.json holds one entry per OS, e.g. {"windows": {"version": "1.2.0", "file":
    "VirtenStudio-Setup-1.2.0.exe"}, "mac": {"version": "1.2.0", "file": "VirtenStudio-1.2.0.dmg"}}"""
    d = _sub("app")
    if not d:
        return None
    try:
        with open(os.path.join(d, "latest.json"), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    entry = info.get("mac" if sys.platform == "darwin" else "windows")
    if not isinstance(entry, dict) or not entry.get("file"):
        return None
    installer = os.path.join(d, entry["file"])
    if _ver(entry.get("version", "0")) > _ver(__version__) and os.path.isfile(installer):
        return entry["version"], installer
    return None


def available_update():
    """(version, installer) for the newest Virten Studio this computer can install, or None. Looks in the sync
    folder (an installer already on disk) and the latest GitHub Release (.dmg on a Mac, .exe on Windows). installer
    is a local path, or an https:// URL to fetch with download_update(). On a tie the local file wins."""
    found = [u for u in (_sync_folder_update(), _github_update()) if u]
    if not found:
        return None
    return max(found, key=lambda u: (_ver(u[0]), not u[1].startswith("https://")))


def download_update(url_or_path, progress=None, cancelled=lambda: False):
    """Local path of the installer: returned as-is when it's already on disk, else downloaded in 256 KB chunks to
    <cache>/updates (via a .tmp file, so a half-finished download is never mistaken for an installer). Older
    downloaded installers are removed. Raises InterruptedError when cancelled()."""
    if os.path.isfile(url_or_path):
        return url_or_path
    if not str(url_or_path).startswith("https://"):
        raise ValueError(f"Not an installer on disk or an https:// address: {url_or_path}")
    parts = urllib.parse.urlsplit(url_or_path)
    name = os.path.basename(urllib.parse.unquote(parts.fragment or parts.path)) or f"VirtenStudio-update{INSTALLER_EXT}"
    d = os.path.join(cache_dir(), "updates")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, name)
    tmp = dest + ".tmp"
    try:
        with _open(urllib.parse.urlunsplit(parts._replace(fragment="")), _github_headers(raw=True), 30) as r, \
                open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            if progress:
                progress(0, total, "Downloading update")
            while True:
                if cancelled():
                    raise InterruptedError
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, "Downloading update")
        if total and done != total:
            raise OSError(f"The download stopped early ({done:,} of {total:,} bytes).")
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    for other in os.listdir(d):  # keep only this installer
        if other != name:
            try:
                os.remove(os.path.join(d, other))
            except OSError:
                pass
    return dest


def sync_all():
    if not sync_dir():
        return []
    changed = pull_profiles()
    # Push local profiles the sync folder doesn't have yet (e.g. right after turning sync on).
    d = _sub("profiles")
    for fn in os.listdir(profiles_dir()):
        if fn.endswith(".virten-profile"):
            lp = os.path.join(profiles_dir(), fn)
            if _created(lp + ".json") > _created(os.path.join(d, fn + ".json")) and \
                    not os.path.exists(os.path.join(d, fn + ".deleted")):
                push_profile(lp)
    sync_looks()
    return changed
