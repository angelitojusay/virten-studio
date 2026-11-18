# PyInstaller runtime hook (Windows and macOS builds).
# matplotlib isn't bundled with Virten Studio (it's large and unused). MediaPipe still imports matplotlib.pyplot at
# module level, but only for drawing_utils.plot_landmarks(), a 3D debug plot Virten Studio never calls. Register a
# stand-in so that import succeeds; anything that actually uses matplotlib gets a clear ImportError.
import sys
import types


class _NotBundled(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise ImportError(f"matplotlib isn't included in Virten Studio ({self.__name__}.{name} was requested)")


if "matplotlib" not in sys.modules:
    _mpl = _NotBundled("matplotlib")
    _plt = _NotBundled("matplotlib.pyplot")
    _mpl.pyplot = _plt
    sys.modules["matplotlib"] = _mpl
    sys.modules["matplotlib.pyplot"] = _plt
