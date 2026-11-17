import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _LogStream:
    """File-like object that sends whole lines to a logger (stands in for a missing stdout/stderr)."""

    def __init__(self, logger, level):
        self.logger, self.level, self.buf = logger, level, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(s)

    def flush(self):
        if self.buf.strip():
            self.logger.log(self.level, self.buf.rstrip())
        self.buf = ""

    def isatty(self):
        return False


def setup_logging():
    """Rotating diagnostic log in the data folder (2 MB, 2 backups). Uncaught exceptions (main and worker threads)
    are written there. The windowed build has no console (sys.stdout/stderr are None), so printed messages and
    tracebacks go to the log too instead of being lost."""
    import logging
    import threading
    from logging.handlers import RotatingFileHandler
    from autostyle import __version__
    from autostyle.paths import log_file
    handler = RotatingFileHandler(log_file(), maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    log = logging.getLogger("virten")
    log.info("Virten Studio %s starting (%s, Python %s)", __version__, sys.platform, sys.version.split()[0])
    if sys.stderr is None:
        sys.stderr = _LogStream(logging.getLogger("stderr"), logging.ERROR)
    if sys.stdout is None:
        sys.stdout = _LogStream(logging.getLogger("stdout"), logging.INFO)

    def excepthook(exc_type, exc, tb):
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        if sys.__excepthook__ and sys.__stderr__ is not None:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
    threading.excepthook = lambda a: log.critical(f"Uncaught exception in thread {a.thread.name if a.thread else '?'}",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return log


def selftest():
    """Checks the packaged app has everything it needs; writes a report and exits 0 (ok) or 1."""
    import traceback
    from autostyle.paths import data_dir
    report = os.path.join(data_dir(), "selftest.txt")
    lines, ok = [], True
    try:
        import numpy as np
        import rawpy  # noqa: F401
        from PySide6 import QtWidgets  # noqa: F401
        from autostyle import __version__, features, looks, vision
        lines.append(f"Virten Studio {__version__}")
        lines.append(f"accelerator: {vision.accelerator()[1]}")
        img = np.full((480, 640, 3), 128, np.uint8)
        lines.append(f"faces: {len(vision.find_faces(img))}  segmentation: {vision.segment_people(img).shape}")
        lines.append(f"clip: {vision.clip_embed([vision.clip_input(img)]).shape}")
        lines.append(f"looks: {len(looks.list_looks())}  workers: {features.worker_count()}")
        from autostyle import cull, faces
        faces._landmarker()  # face model with expression scores and head angle (assisted culling)
        lines.append(f"assisted culling: face analysis v{faces.FACE_VERSION} ({faces.N_FEATURES} values), "
                     f"model {'trained' if cull.load_model() else 'not trained yet'}")
        from autostyle.paths import plugin_source_dir
        lua_files = [os.path.join(plugin_source_dir(), n) for n in ('Info.lua', 'ApplyEdits.lua')]
        for fpath in lua_files:
            with open(fpath, 'rb') as fh:
                if fh.read(3) == b'\xef\xbb\xbf':
                    raise RuntimeError(f'{fpath} starts with a byte-order mark; Lightroom cannot load it')
        lines.append("plugin bundled: True (no byte-order marks)")
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("RESULT: " + ("OK" if ok else "FAILED"))
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for the photo-analysis worker processes in the packaged app
    try:
        setup_logging()
    except OSError as e:  # e.g. a read-only data folder: run without the log rather than not at all
        print("logging unavailable:", e)
    if "--selftest" in sys.argv:
        selftest()
    from autostyle.gui import main
    main()
