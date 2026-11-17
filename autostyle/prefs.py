"""Small persistent UI preferences (e.g. the last tool choices in the project wizard)."""
import json
import os

from .paths import data_dir


def _path():
    return os.path.join(data_dir(), "settings.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(**values):
    """Merges values into settings.json (written to a .tmp file first, so a crash can't leave it half-written)."""
    data = load()
    data.update(values)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path())
