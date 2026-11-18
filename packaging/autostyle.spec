# PyInstaller spec for Virten Studio (Windows and macOS). Run from the project folder:
#   pyinstaller --noconfirm packaging/autostyle.spec
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from autostyle import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"

datas = [
    (os.path.join(ROOT, "looks"), "looks"),
    (os.path.join(ROOT, "models"), "models"),
    (os.path.join(ROOT, "VirtenStudio.lrplugin"), "VirtenStudio.lrplugin"),
    (os.path.join(ROOT, "autostyle", "icon.png"), "autostyle"),
    # Licence files (Settings ▸ About & Open-Source Licenses shows them; required by the LGPL/Apache/BSD/MIT terms)
    (os.path.join(ROOT, "LICENSE.txt"), "."),
    (os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt"), "."),
    (os.path.join(ROOT, "licenses"), "licenses"),
]

# Never ship these. GPL-only Qt modules (Qt's open-source edition licenses them under GPL, not LGPL): Qt Virtual
# Keyboard arrives through Qt's input-method plugins unless filtered. Plus unused bloat: Qt Quick/QML/PDF, and
# matplotlib / setuptools, which mediapipe pulls in but Virten Studio never uses. packaging/check_bundle.py fails the
# build if any of them is still in the app.
EXCLUDED_MODULES = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
                    "PySide6.QtVirtualKeyboard", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets",
                    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
                    "PySide6.QtGraphs", "matplotlib", "setuptools", "pkg_resources", "sounddevice"]
# sounddevice (MediaPipe's optional audio recorder, unused; guarded import) ships PortAudio DLLs built with Steinberg's
# ASIO SDK, whose licence restricts redistribution: it isn't bundled.
DROP_PATTERNS = ("virtualkeyboard", "qt6quick", "qtquick", "qt6qml", "qtqml", "/qml/", "qt6pdf", "qtpdf", "qpdf",
                 "matplotlib", "mpl-data", "setuptools", "pkg_resources", "sounddevice", "portaudio",
                 "opengl32sw")  # Qt's software OpenGL fallback (Mesa): unused, Virten Studio draws with Qt Widgets


def _keep(entry):
    dest = "/" + entry[0].replace("\\", "/").lower()
    return not any(p in dest for p in DROP_PATTERNS)
datas += collect_data_files("mediapipe")
datas += collect_data_files("onnxruntime")
binaries = collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("mediapipe")
hiddenimports = collect_submodules("mediapipe.tasks") + collect_submodules("sklearn.ensemble._hist_gradient_boosting")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    runtime_hooks=[os.path.join(ROOT, "packaging", "rth_no_matplotlib.py")]
    + ([os.path.join(ROOT, "packaging", "rth_cv2_mac.py")] if IS_MAC else []),
    excludes=EXCLUDED_MODULES,
)
a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]


def _write_manifest():
    """dist/bundled-distributions.json: the Python distributions in this build, for check_bundle.py (every one must
    have an entry in THIRD-PARTY-NOTICES.txt)."""
    import json
    from importlib.metadata import packages_distributions
    tops = {name.split(".")[0] for name, *_ in a.pure}
    tops |= {e[0].replace("\\", "/").split("/")[0].split(".")[0] for e in a.binaries + a.datas}
    owners = packages_distributions()
    dists = sorted({d for t in tops for d in owners.get(t, [])})
    os.makedirs(DISTPATH, exist_ok=True)
    with open(os.path.join(DISTPATH, "bundled-distributions.json"), "w", encoding="utf-8") as f:
        json.dump({"platform": sys.platform, "distributions": dists}, f, indent=1)


_write_manifest()
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Virten Studio",
    console=False,
    icon=os.path.join(ROOT, "packaging", "icon.icns" if IS_MAC else "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Virten Studio")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Virten Studio.app",
        icon=os.path.join(ROOT, "packaging", "icon.icns"),
        bundle_identifier="com.angelitojusay.virtenstudio",
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSDesktopFolderUsageDescription": "Virten Studio reads Lightroom catalogs and RAW files you choose.",
            "NSDocumentsFolderUsageDescription": "Virten Studio reads Lightroom catalogs and RAW files you choose.",
            "NSRemovableVolumesUsageDescription": "Virten Studio reads RAW files stored on external drives.",
        },
    )
