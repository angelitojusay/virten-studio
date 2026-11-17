"""Copies a freshly built installer into the sync folder's app/ folder and records it in latest.json, so every
computer running Virten Studio offers the update.   python packaging/publish.py <installer> windows|mac"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autostyle import __version__, sync  # noqa: E402


def main():
    installer, platform = sys.argv[1], sys.argv[2]
    d = sync.sync_dir()
    if not d:
        print("Sync isn't set up in Virten Studio's Settings; skipping publish.")
        return
    app_dir = os.path.join(d, "app")
    os.makedirs(app_dir, exist_ok=True)
    shutil.copy2(installer, os.path.join(app_dir, os.path.basename(installer)))
    # Keep only the newest installer per platform so old versions don't pile up in the cloud folder.
    ext = os.path.splitext(installer)[1].lower()
    for old in os.listdir(app_dir):
        if old.lower().endswith(ext) and old != os.path.basename(installer):
            os.remove(os.path.join(app_dir, old))
    latest = os.path.join(app_dir, "latest.json")
    try:
        with open(latest, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        info = {}
    info[platform] = {"version": __version__, "file": os.path.basename(installer)}
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    print(f"Published {os.path.basename(installer)} to {app_dir}")


if __name__ == "__main__":
    main()
