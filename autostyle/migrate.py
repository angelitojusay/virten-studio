"""One-time move from AutoStyle (the app's earlier name) to Virten Studio. Safe to run on every start:
each step only acts when the old item exists and the new one doesn't, and nothing is ever deleted except the
old Lightroom plugin folder once the new plugin is installed."""
import glob
import json
import os
import shutil

from .paths import (OLD_APP_NAME, OLD_PLUGIN_FOLDER, PLUGIN_FOLDER, _app_support, data_dir, lightroom_modules_dir,
                    plugin_source_dir)

OLD_PROFILE_EXT, PROFILE_EXT = ".autostyle-profile", ".virten-profile"
OLD_SYNC_NAME, SYNC_NAME = "AutoStyle Sync", "Virten Studio Sync"


def _rename_profile_files(folder):
    if not os.path.isdir(folder):
        return
    for f in os.listdir(folder):
        if OLD_PROFILE_EXT in f:
            src, dst = os.path.join(folder, f), os.path.join(folder, f.replace(OLD_PROFILE_EXT, PROFILE_EXT))
            if not os.path.exists(dst):
                os.replace(src, dst)


def _merge(src, dst):
    """Moves everything from src into dst, keeping anything dst already has; removes src if it ends up empty."""
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        try:
            if os.path.isdir(s) and os.path.isdir(d):
                _merge(s, d)
            elif not os.path.exists(d):
                os.replace(s, d)  # same drive: an instant rename, never a half-finished copy
        except OSError as e:  # locked (e.g. being scanned): leave it, the next start finishes the move
            print("couldn't move", s, e)
    try:
        os.rmdir(src)
    except OSError:
        pass  # something couldn't be moved (already present in the new folder); leave it


def _rewrite_paths(folder, old, new):
    """Project records store thumbnail paths inside the data folder; point them at the new location."""
    files = glob.glob(os.path.join(folder, "projects", "*.json")) + [os.path.join(folder, "projects.json")]
    for f in files:
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
            esc_old, esc_new = json.dumps(old)[1:-1], json.dumps(new)[1:-1]
            if esc_old in text:
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(text.replace(esc_old, esc_new))


def run():
    """Returns a list of human-readable notes about what moved (empty when there was nothing to do)."""
    notes = []
    old_dir = os.path.join(_app_support(), OLD_APP_NAME)
    new_dir = os.path.join(_app_support(), "Virten Studio")
    if os.path.isdir(old_dir):
        if not os.path.exists(new_dir):
            os.rename(old_dir, new_dir)
        else:
            # The new folder may already exist (e.g. created empty on first launch): merge, never overwrite.
            _merge(old_dir, new_dir)
        _rewrite_paths(new_dir, old_dir + os.sep, new_dir + os.sep)
        notes.append("Moved your profiles, projects and settings to Virten Studio.")
    _rename_profile_files(os.path.join(data_dir(), "profiles"))

    from . import prefs
    sync_dir = prefs.load().get("sync_dir")
    if sync_dir and os.path.basename(sync_dir.rstrip("\\/")) == OLD_SYNC_NAME:
        new_sync = os.path.join(os.path.dirname(sync_dir.rstrip("\\/")), SYNC_NAME)
        try:
            if os.path.isdir(sync_dir) and not os.path.exists(new_sync):
                os.rename(sync_dir, new_sync)
                notes.append(f"Renamed your sync folder to “{SYNC_NAME}”.")
            if os.path.isdir(new_sync):
                prefs.save(sync_dir=new_sync)
                _rename_profile_files(os.path.join(new_sync, "profiles"))
        except OSError as e:  # e.g. the cloud drive is offline: keep using the old folder for now
            print("sync folder rename failed", e)

    modules = lightroom_modules_dir()
    old_plugin, new_plugin = os.path.join(modules, OLD_PLUGIN_FOLDER), os.path.join(modules, PLUGIN_FOLDER)
    if os.path.isdir(old_plugin):
        try:
            if os.path.isdir(plugin_source_dir()):
                if os.path.exists(new_plugin):
                    shutil.rmtree(new_plugin)
                shutil.copytree(plugin_source_dir(), new_plugin)
            shutil.rmtree(old_plugin)
            notes.append("Replaced the AutoStyle Lightroom plugin with Virten Studio's. Restart Lightroom Classic "
                         "to load it.")
        except OSError as e:  # Lightroom may have the files open; try again next start
            print("plugin swap failed", e)
    return notes
