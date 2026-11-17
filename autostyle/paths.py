"""Where Virten Studio keeps its data, per operating system.

Windows: %APPDATA%\\Virten Studio        Lightroom plugins: %APPDATA%\\Adobe\\Lightroom\\Modules
macOS:   ~/Library/Application Support/Virten Studio
         Lightroom plugins: ~/Library/Application Support/Adobe/Lightroom/Modules"""
import os
import subprocess
import sys

APP_NAME = "Virten Studio"
OLD_APP_NAME = "AutoStyle"  # the app's earlier name; migrate.py moves its data over
PLUGIN_FOLDER = "VirtenStudio.lrplugin"
OLD_PLUGIN_FOLDER = "AutoStyle.lrplugin"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"


def _app_support():
    if IS_WINDOWS:
        return os.environ.get("APPDATA") or os.path.expanduser("~")
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def data_dir():
    d = os.path.join(_app_support(), APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir():
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def profiles_dir():
    d = os.path.join(data_dir(), "profiles")
    os.makedirs(d, exist_ok=True)
    return d


def log_file():
    """Diagnostic log (run.py sends errors, tracebacks and printed messages here)."""
    return os.path.join(data_dir(), "virten.log")


def projects_file():
    return os.path.join(data_dir(), "projects.json")


def lightroom_modules_dir():
    return os.path.join(_app_support(), "Adobe", "Lightroom", "Modules")


def camera_raw_presets_dir():
    return os.path.join(_app_support(), "Adobe", "CameraRaw", "Settings")


def resource_dir():
    """Folder holding bundled resources (plugin, looks, models): the app bundle when packaged."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugin_source_dir():
    return os.path.join(resource_dir(), PLUGIN_FOLDER)


def appdata_redirected():
    """True when this process's %APPDATA% writes land in a packaged app's private copy. Claude Desktop is a packaged
    Windows app: anything started from it saves to %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming instead,
    where the installed Virten Studio never sees it. Windows doesn't report this to the process, so it's probed."""
    if not IS_WINDOWS:
        return False
    import glob
    import uuid
    name = f"vs-redirect-probe-{uuid.uuid4().hex}.tmp"
    probe = os.path.join(_app_support(), name)
    try:
        with open(probe, "w") as f:
            f.write("probe")
        pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "*", "LocalCache", "Roaming", name)
        return bool(glob.glob(pattern))
    except OSError:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def relaunch_outside_package(log_dir):
    """If AppData is redirected, re-runs this script through Explorer (which starts it outside the package, so it
    saves to the real AppData) and exits. The new run's output goes to a log file in log_dir."""
    if not appdata_redirected():
        return
    import time
    os.makedirs(log_dir, exist_ok=True)
    script = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    log = os.path.join(log_dir, f"{script} {time.strftime('%Y%m%d-%H%M%S')}.log")
    args = " ".join(f'"{a}"' for a in [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:])
    bat = log[:-4] + ".bat"
    with open(bat, "w", encoding="mbcs") as f:
        f.write(f'@echo off\r\ncd /d "{os.getcwd()}"\r\nset PYTHONIOENCODING=utf-8\r\n'
                f'{args} > "{log}" 2>&1\r\necho EXIT %ERRORLEVEL% >> "{log}"\r\n')
    subprocess.Popen(["explorer.exe", bat])
    print("AppData is redirected here (started from Claude Desktop), so this was relaunched outside it.")
    print("Progress:", log, "(it ends with an EXIT line)")
    sys.exit(0)


def open_with_system(path):
    """Open a file or folder with its default app (Explorer/Finder, or run an installer)."""
    if IS_WINDOWS:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
