"""Licence compliance gate for a built Virten Studio app. Run right after PyInstaller (the build scripts and the GitHub
workflow do), with the build venv's Python:

    python packaging/check_bundle.py "dist/Virten Studio"            (Windows)
    python packaging/check_bundle.py "dist/Virten Studio.app"        (macOS)

Fails (exit 1) when the app contains a GPL-only library (e.g. Qt Virtual Keyboard) or a component that must not ship,
when LICENSE.txt / THIRD-PARTY-NOTICES.txt / licenses/ are missing, when rawpy was built with LibRaw's GPL demosaic
packs, or when a bundled Python distribution (dist/bundled-distributions.json, written by the spec) has no entry in
THIRD-PARTY-NOTICES.txt."""
import json
import os
import re
import sys

# Qt modules that Qt's open-source edition licenses under the GPL only (not the LGPL), as file-name fragments.
GPL_ONLY_QT = ("virtualkeyboard", "qtcharts", "qt6charts", "datavisualization", "qtgraphs", "qt6graphs", "quick3d",
               "shadertools", "qtlottie", "qt6lottie", "quicktimeline", "waylandcompositor", "httpserver",
               "networkauth", "qtcoap", "qt6coap", "qtmqtt", "qt6mqtt", "opcua", "qtinsight", "qt6insight")
# Removed on purpose (unused bloat, or a licence that doesn't allow redistribution: ASIO-enabled PortAudio).
MUST_NOT_SHIP = ("qt6quick", "qt6qml", "qt6pdf", "qtquick", "qtqml", "qtpdf", "matplotlib", "setuptools",
                 "pkg_resources", "portaudio", "sounddevice", "opengl32sw")



def _bundle_files(bundle):
    for d, dirs, names in os.walk(bundle):
        for n in dirs + names:
            yield os.path.relpath(os.path.join(d, n), bundle).replace("\\", "/")


def _resource_dir(bundle):
    """Where the app keeps LICENSE.txt and friends (PyInstaller's onedir _internal, or the .app's Resources)."""
    for sub in ("_internal", "Contents/Resources", "Contents/Frameworks", "."):
        p = os.path.join(bundle, sub)
        if os.path.isfile(os.path.join(p, "THIRD-PARTY-NOTICES.txt")):
            return p
    return None


def noticed_distributions(notices_text):
    names = set()
    for line in re.findall(r"Distributions:\s*(.+)", notices_text):
        names |= {n.strip().lower().replace("_", "-") for n in line.split(",") if n.strip()}
    return names


def check(bundle, manifest=None, check_rawpy=True):
    """Problems found in the built app at bundle (an empty list means it passes)."""
    problems = []
    if not os.path.isdir(bundle):
        return [f"{bundle} isn't a folder (build the app first)"]
    files = list(_bundle_files(bundle))
    for rel in files:
        low = rel.lower()
        base = low.rsplit("/", 1)[-1]
        if any(p in base for p in GPL_ONLY_QT):  # any file or folder: .dll, .dylib, .framework, .so.6, plugins…
            problems.append(f"GPL-only Qt component in the app: {rel}")
        elif any(p in base for p in MUST_NOT_SHIP) and "virten" not in base:
            problems.append(f"Excluded component is back in the app: {rel}")
    res = _resource_dir(bundle)
    if not res:
        problems.append("THIRD-PARTY-NOTICES.txt isn't in the app")
    else:
        for need in ("LICENSE.txt", "licenses"):
            if not os.path.exists(os.path.join(res, need)):
                problems.append(f"{need} isn't in the app (next to THIRD-PARTY-NOTICES.txt)")
        lic = os.path.join(res, "licenses")
        if os.path.isdir(lic) and not any(f.endswith(".txt") for f in os.listdir(lic)):
            problems.append("The app's licenses folder is empty")
        with open(os.path.join(res, "THIRD-PARTY-NOTICES.txt"), encoding="utf-8") as f:
            noticed = noticed_distributions(f.read())
        if manifest and os.path.isfile(manifest):
            with open(manifest, encoding="utf-8") as f:
                bundled = json.load(f).get("distributions") or []
            missing = sorted(d for d in bundled if d.lower().replace("_", "-") not in noticed)
            if missing:
                problems.append("Bundled without an entry in THIRD-PARTY-NOTICES.txt (add it in "
                                "packaging/make_notices.py): " + ", ".join(missing))
        elif manifest:
            problems.append(f"{manifest} is missing (the spec writes it during the build)")
    if check_rawpy:
        try:
            import rawpy
            gpl = {k: v for k, v in (rawpy.flags or {}).items() if "GPL" in k and v}
            if gpl:
                problems.append(f"rawpy was built with LibRaw's GPL demosaic packs: {gpl}")
        except ImportError:
            problems.append("rawpy isn't importable in this environment (run with the build venv)")
    return problems


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    bundle = argv[1]
    manifest = os.path.join(os.path.dirname(os.path.abspath(bundle)), "bundled-distributions.json")
    problems = check(bundle, manifest)
    if problems:
        print("Licence check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    n = sum(1 for _ in _bundle_files(bundle))
    print(f"Licence check OK: {n} files, no GPL-only or excluded components, notices cover every bundled package.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
