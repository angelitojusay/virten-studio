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
]
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
    runtime_hooks=[os.path.join(ROOT, "packaging", "rth_cv2_mac.py")] if IS_MAC else [],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore"],
)
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
