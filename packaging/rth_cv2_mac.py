# PyInstaller runtime hook (macOS): lets OpenCV's loader find its native module inside the .app.
#
# cv2/__init__.py pops itself from sys.modules and re-imports "cv2", expecting the native cv2*.so to be found
# first on sys.path. In a .app, Python files live in Contents/Resources and binaries in Contents/Frameworks, so the
# loader's own check fails, sys.path finds the cv2 package again, and it stops with "recursion is detected during
# loading of cv2". This finder answers that inner import with the native module, wherever it was bundled.
import glob
import importlib.machinery
import importlib.util
import os
import sys


def _native_cv2():
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    contents = os.path.dirname(os.path.abspath(base))
    for d in (os.path.join(base, "cv2"), os.path.join(contents, "Frameworks", "cv2"),
              os.path.join(contents, "Resources", "cv2"), base):
        hits = sorted(glob.glob(os.path.join(d, "cv2*.so")) + glob.glob(os.path.join(d, "cv2*.pyd")))
        if hits:
            return hits[0]
    return None


class _NativeCV2Finder:
    def find_spec(self, name, path=None, target=None):
        # Only the loader's inner import: it sets sys.OpenCV_LOADER and has removed "cv2" from sys.modules.
        if name != "cv2" or not getattr(sys, "OpenCV_LOADER", False) or "cv2" in sys.modules:
            return None
        so = _native_cv2()
        if not so:
            return None
        return importlib.util.spec_from_file_location("cv2", so, loader=importlib.machinery.ExtensionFileLoader("cv2", so))


if sys.platform == "darwin" or os.environ.get("VS_TEST_CV2_HOOK"):
    sys.meta_path.insert(0, _NativeCV2Finder())
