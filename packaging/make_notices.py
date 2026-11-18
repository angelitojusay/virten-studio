"""Writes THIRD-PARTY-NOTICES.txt and licenses/ for everything Virten Studio redistributes.

Run with the build venv (versions and licence files are read from the installed packages):
    .venv\\Scripts\\python.exe packaging\\make_notices.py
Generic licence texts that packages don't ship (LGPL-3.0, GPL-3.0, LGPL-2.1, Apache-2.0, the CLIP and DirectML MIT
licences) are kept in licenses/ and listed in licenses/README.md with their sources. packaging/check_bundle.py checks
after every build that each bundled Python distribution is named on a "Distributions:" line below."""
import os
import sys
import textwrap
from importlib import metadata

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIC = os.path.join(ROOT, "licenses")
sys.path.insert(0, ROOT)
from autostyle import __version__  # noqa: E402

GENERIC = {  # licenses/<file>: where the text comes from
    "LGPL-3.0.txt": "https://github.com/qtproject/pyside-pyside-setup/blob/dev/LICENSES/LGPL-3.0-only.txt (FSF text)",
    "GPL-3.0.txt": "https://www.gnu.org/licenses/gpl-3.0.txt (FSF text; the LGPL-3.0 builds on it)",
    "LGPL-2.1.txt": "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt (FSF text)",
    "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    "DirectML-MIT.txt": "https://github.com/microsoft/DirectML/blob/master/LICENSE",
    "CLIP-MIT.txt": "https://github.com/openai/CLIP/blob/main/LICENSE",
}


def ver(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "?"


def dist_files(dist, *names):
    """Licence files a distribution ships (dist-info first, then the package folder)."""
    out = []
    d = metadata.distribution(dist)
    for f in d.files or []:
        if f.name in names or str(f).replace("\\", "/") in names:
            out.append(d.locate_file(f))
    return out


def copy(src, dest_name):
    with open(src, encoding="utf-8-sig", errors="replace") as f:
        text = f.read().replace("\r\n", "\n").strip() + "\n"
    with open(os.path.join(LIC, dest_name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return dest_name


def pkg(dist, files, prefix):
    """Copies a distribution's licence files to licenses/<prefix>-<name>; returns the new names."""
    got = []
    for src in dist_files(dist, *files):
        name = os.path.basename(str(src))
        got.append(copy(src, f"{prefix}-{name if name.lower().endswith(('.txt', '.md')) else name + '.txt'}"))
    if not got:
        raise SystemExit(f"No licence file found for {dist} ({files})")
    return got


MODELS = [
    dict(title="MediaPipe Face Landmarker (models/face_landmarker.task)",
         body="""Google's face landmark bundle: BlazeFace short-range face detector, Face Mesh V2 (478 landmarks) and
Blendshape V2 (52 expression scores). Virten Studio uses the landmarks and scores only to measure blinks, smiles,
head pose and eye sharpness for editing and culling suggestions; it does not identify people.
Licence: Apache License 2.0 ("LICENSED UNDER Apache License, Version 2.0" in each model card). Copyright Google LLC.
Model: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
Model cards: https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf
             https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf
             https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf
The model cards list surveillance, identity recognition and life-critical decisions as out of scope.
Licence text: licenses/Apache-2.0.txt""", texts=["Apache-2.0.txt"]),
    dict(title="MediaPipe Selfie Multiclass Segmentation 256x256 (models/selfie_multiclass_256x256.tflite)",
         body="""Google's person segmentation model (background, hair, body skin, face skin, clothes, accessories),
used for the subject / background / skin masks and the preview simulations.
Licence: Apache License 2.0 (model card). Copyright Google LLC.
Model: https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite
Model card: https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Multiclass%20Segmentation.pdf
Licence text: licenses/Apache-2.0.txt""", texts=["Apache-2.0.txt"]),
    dict(title="OpenAI CLIP ViT-B/32 image encoder (models/clip_vision.onnx)",
         body="""The vision half of OpenAI's CLIP ViT-B/32 (openai/clip-vit-base-patch32), as converted to ONNX by
Xenova (https://huggingface.co/Xenova/clip-vit-base-patch32, MIT). Virten Studio uses its 512-number image embedding
as one input to predict editing settings and culling hints. It is not used to classify, identify or track people.
Licence: MIT License, Copyright (c) 2021 OpenAI (https://github.com/openai/CLIP).
Model-card scope note: OpenAI's model card describes CLIP as a research output and says its deployed use is
currently out of scope of the uses OpenAI evaluated it for. That card is guidance, not a licence term; the weights are
released under the MIT License above. Virten Studio does not use CLIP for surveillance, facial recognition or any
decision about people, and its results are suggestions the photographer reviews.
Licence text: licenses/CLIP-MIT.txt""", texts=["CLIP-MIT.txt"]),
]


def libraries():
    L = []

    def add(title, dists, licence, copyright_, source, texts, notes=""):
        L.append(dict(title=title, dists=dists, licence=licence, copyright=copyright_, source=source, texts=texts,
                      notes=notes))

    qt = ver("PySide6")
    add(f"Qt for Python (PySide6 {qt}, shiboken6 {ver('shiboken6')}) and the Qt {qt} libraries",
        ["PySide6", "PySide6_Essentials", "PySide6_Addons", "PySide6_Pdf", "PySide6_WebEngine", "shiboken6"],
        "GNU Lesser General Public License v3.0 (LGPL-3.0-only)", "Copyright (C) The Qt Company Ltd. and other contributors",
        "https://download.qt.io/official_releases/QtForPython/ (PySide6) and https://download.qt.io/official_releases/qt/ (Qt)",
        ["LGPL-3.0.txt", "GPL-3.0.txt"],
        """Used unmodified and dynamically linked. The Qt and PySide6 libraries are separate files in the app (Windows:
_internal\\PySide6 and _internal\\shiboken6; macOS: Virten Studio.app/Contents/Frameworks/PySide6 and shiboken6):
you may replace them with your own builds of the same versions from the source above. Only LGPL-licensed Qt modules are
included (Core, Gui, Widgets, Network, Svg and their plugins); GPL-only Qt modules such as Qt Virtual Keyboard are not.""")
    add(f"rawpy {ver('rawpy')}", ["rawpy"], "MIT License", "Copyright (c) 2014 Maik Riechert",
        "https://github.com/letmaik/rawpy", pkg("rawpy", ("LICENSE",), "rawpy"))
    add("LibRaw 0.22 (inside rawpy)", [], "GNU LGPL v2.1 (chosen from LibRaw's LGPL-2.1 / CDDL-1.0 dual licence)",
        "Copyright (C) 2008-2026 LibRaw LLC", "https://www.libraw.org/download",
        pkg("rawpy", ("LICENSE.LibRaw",), "LibRaw") + ["LGPL-2.1.txt"],
        """Dynamically linked (Windows: _internal\\rawpy\\raw_r.dll) and replaceable. Built without LibRaw's GPL2/GPL3
demosaic packs.""")
    ocv = ver("opencv-contrib-python")
    add(f"OpenCV {ocv.rsplit('.', 1)[0]} (opencv-contrib-python {ocv})", ["opencv-contrib-python", "opencv-python"],
        "Apache License 2.0", "Copyright (C) the OpenCV project contributors", "https://github.com/opencv/opencv-python",
        pkg("opencv-contrib-python", ("LICENSE.txt",), "OpenCV") + ["Apache-2.0.txt"],
        "Built without OpenCV's non-free modules. Its other bundled components are listed in OpenCV-LICENSE-3RD-PARTY.txt.")
    add("FFmpeg (inside OpenCV: opencv_videoio_ffmpeg)", [], "GNU LGPL v2.1 or later",
        "Copyright (c) the FFmpeg developers", "https://ffmpeg.org/download.html and "
        "https://github.com/opencv/opencv_3rdparty/tree/ffmpeg (OpenCV's FFmpeg build scripts)",
        pkg("opencv-contrib-python", ("LICENSE-3RD-PARTY.txt",), "OpenCV") + ["LGPL-2.1.txt"],
        "A separate, dynamically loaded library (Windows: _internal\\cv2\\opencv_videoio_ffmpeg*.dll) built by OpenCV "
        "with LGPL components only; Virten Studio doesn't use it for video.")
    add(f"MediaPipe {ver('mediapipe')}", ["mediapipe"], "Apache License 2.0", "Copyright Google LLC",
        "https://github.com/google-ai-edge/mediapipe", pkg("mediapipe", ("LICENSE", "NOTICE"), "MediaPipe"))
    ort = ver("onnxruntime-directml") if ver("onnxruntime-directml") != "?" else ver("onnxruntime")
    ort_dir = os.path.dirname(metadata.distribution(
        "onnxruntime-directml" if ver("onnxruntime-directml") != "?" else "onnxruntime").locate_file("onnxruntime/LICENSE"))
    add(f"ONNX Runtime {ort} (onnxruntime-directml on Windows, onnxruntime on macOS)",
        ["onnxruntime-directml", "onnxruntime"], "MIT License", "Copyright (c) Microsoft Corporation",
        "https://github.com/microsoft/onnxruntime",
        [copy(os.path.join(ort_dir, "LICENSE"), "onnxruntime-LICENSE.txt"),
         copy(os.path.join(ort_dir, "ThirdPartyNotices.txt"), "onnxruntime-ThirdPartyNotices.txt")])
    add("DirectML (Windows: DirectML.dll, inside onnxruntime-directml)", [], "MIT License",
        "Copyright (c) Microsoft Corporation", "https://github.com/microsoft/DirectML", ["DirectML-MIT.txt"])
    add(f"NumPy {ver('numpy')} (with OpenBLAS and its bundled libraries)", ["numpy"],
        "BSD 3-Clause (plus 0BSD, MIT, Zlib and CC0 parts)", "Copyright (c) 2005-2026 NumPy Developers",
        "https://numpy.org", pkg("numpy", ("LICENSE.txt",), "NumPy"))
    add(f"SciPy {ver('scipy')} (with OpenBLAS and its bundled libraries)", ["scipy"], "BSD 3-Clause",
        "Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers", "https://scipy.org",
        pkg("scipy", ("LICENSE.txt",), "SciPy"),
        "SciPy's bundled libgfortran is GPL-3.0 with the GCC Runtime Library Exception (see SciPy-LICENSE.txt).")
    add(f"scikit-learn {ver('scikit-learn')}", ["scikit-learn"], "BSD 3-Clause",
        "Copyright (c) 2007-2026 The scikit-learn developers", "https://scikit-learn.org",
        pkg("scikit-learn", ("COPYING",), "scikit-learn"))
    add(f"joblib {ver('joblib')}", ["joblib"], "BSD 3-Clause", "Copyright (c) 2008-2026 The joblib developers",
        "https://github.com/joblib/joblib", pkg("joblib", ("LICENSE.txt",), "joblib"))
    add(f"threadpoolctl {ver('threadpoolctl')}", ["threadpoolctl"], "BSD 3-Clause",
        "Copyright (c) 2019, threadpoolctl contributors", "https://github.com/joblib/threadpoolctl",
        pkg("threadpoolctl", ("LICENSE",), "threadpoolctl"))
    add(f"cloudpickle {ver('cloudpickle')}", ["cloudpickle"], "BSD 3-Clause",
        "Copyright (c) 2012-now, CloudPickle developers and contributors", "https://github.com/cloudpipe/cloudpickle",
        pkg("cloudpickle", ("LICENSE",), "cloudpickle"))
    add(f"narwhals {ver('narwhals')}", ["narwhals"], "MIT License", "Copyright (c) 2024 Marco Gorelli",
        "https://github.com/narwhals-dev/narwhals", pkg("narwhals", ("LICENSE.md",), "narwhals"))
    add(f"Pillow {ver('pillow')} (with libjpeg-turbo, libpng, zlib, FreeType, libwebp, libavif and other image libraries)",
        ["pillow"], "MIT-CMU (HPND); bundled libraries under their own licences (listed in Pillow-LICENSE.txt)",
        "Copyright (c) 1997-2011 Secret Labs AB, (c) 1995-2011 Fredrik Lundh and contributors, (c) 2010 Jeffrey A. "
        "Clark and contributors", "https://python-pillow.org", pkg("pillow", ("LICENSE",), "Pillow"))
    add(f"protobuf {ver('protobuf')}", ["protobuf"], "BSD 3-Clause", "Copyright 2008 Google Inc.",
        "https://github.com/protocolbuffers/protobuf", pkg("protobuf", ("LICENSE",), "protobuf"))
    add(f"Abseil Python (absl-py {ver('absl-py')})", ["absl-py"], "Apache License 2.0", "Copyright The Abseil Authors",
        "https://github.com/abseil/abseil-py", pkg("absl-py", ("LICENSE",), "absl-py"))
    add(f"FlatBuffers {ver('flatbuffers')}", ["flatbuffers"], "Apache License 2.0", "Copyright Google Inc.",
        "https://github.com/google/flatbuffers", ["Apache-2.0.txt"])
    add(f"six {ver('six')}", ["six"], "MIT License", "Copyright (c) 2010-2024 Benjamin Peterson",
        "https://github.com/benjaminp/six", pkg("six", ("LICENSE",), "six"))
    add(f"cffi {ver('cffi')}", ["cffi"], "MIT License", "Copyright (C) 2005-2007, Armin Rigo and others",
        "https://github.com/python-cffi/cffi", pkg("cffi", ("LICENSE",), "cffi"))
    add(f"pycparser {ver('pycparser')}", ["pycparser"], "BSD 3-Clause", "Copyright (c) 2008-2024, Eli Bendersky",
        "https://github.com/eliben/pycparser", pkg("pycparser", ("LICENSE",), "pycparser"))
    add(f"certifi {ver('certifi')}", ["certifi"], "Mozilla Public License 2.0", "Copyright the certifi authors",
        "https://github.com/certifi/python-certifi", pkg("certifi", ("LICENSE",), "certifi"),
        "Unmodified; its source is at the address above.")
    add(f"Python {sys.version.split()[0]} (the runtime inside the app, with OpenSSL 3, libffi, SQLite, bzip2, xz, "
        "zlib and expat)", [], "Python Software Foundation License Version 2 (OpenSSL: Apache 2.0; the others: "
        "permissive licences, all in Python-LICENSE.txt)", "Copyright (c) 2001-2026 Python Software Foundation",
        "https://www.python.org/downloads/source/",
        [copy(os.path.join(sys.base_prefix, "LICENSE.txt"), "Python-LICENSE.txt")])
    add("Microsoft Visual C++ runtime (Windows: vcruntime140*.dll, msvcp140*.dll, vcomp140.dll)", [],
        "Microsoft Visual C++ Redistributable licence terms", "Copyright (c) Microsoft Corporation",
        "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist", [],
        "Redistributed unmodified as permitted by Microsoft's redistribution terms for these runtime files.")
    add(f"PyInstaller {ver('pyinstaller')} (bootloader)", ["pyinstaller"],
        "GPL-2.0-or-later with the PyInstaller bootloader exception", "Copyright (c) 2010-2026, PyInstaller Development Team",
        "https://github.com/pyinstaller/pyinstaller", [],
        "The exception allows distributing the bootloader with programs under any licence; Virten Studio's own code "
        "is not covered by the GPL.")
    return L


def wrap(text, indent="   "):
    return "\n".join(textwrap.fill(line, 116, initial_indent=indent, subsequent_indent=indent,
                                   break_on_hyphens=False, break_long_words=False) if line else ""
                     for line in text.splitlines())  # never split a URL


def main():
    os.makedirs(LIC, exist_ok=True)
    for name in GENERIC:
        if not os.path.exists(os.path.join(LIC, name)):
            raise SystemExit(f"licenses/{name} is missing (see GENERIC in this script for its source)")
    libs = libraries()
    out = [f"THIRD-PARTY NOTICES FOR VIRTEN STUDIO {__version__}", "",
           wrap("Virten Studio includes the open-source software and AI models below. Each is licensed for "
                "redistribution in free and commercial software, including software whose author accepts optional "
                "donations. Their copyright notices and licence texts follow; the same texts are in the licenses folder "
                "installed with the app (Settings > About & Open-Source Licenses).", ""), "",
           wrap("Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United "
                "States and/or other countries. Virten Studio is an independent product and is not affiliated with, "
                "sponsored by, or endorsed by Adobe Inc.", ""), "",
           "1. AI MODELS (bundled in the models folder)", "=" * 78]
    for i, m in enumerate(MODELS, 1):
        out += ["", f"1.{i} {m['title']}", wrap(m["body"])]
    out += ["", "", "2. LIBRARIES", "=" * 78]
    for i, l in enumerate(libs, 1):
        out += ["", f"2.{i} {l['title']}", wrap(f"Licence: {l['licence']}"), wrap(l["copyright"]),
                wrap(f"Source: {l['source']}")]
        if l["dists"]:
            out.append(wrap("Distributions: " + ", ".join(l["dists"])))
        if l["notes"]:
            out.append(wrap(l["notes"]))
        if l["texts"]:
            out.append(wrap("Licence text: " + ", ".join(f"licenses/{t}" for t in dict.fromkeys(l["texts"]))))
    texts = list(dict.fromkeys([t for m in MODELS for t in m["texts"]] + [t for l in libs for t in l["texts"]]))
    out += ["", "", "3. LICENCE TEXTS", "=" * 78]
    for t in texts:
        with open(os.path.join(LIC, t), encoding="utf-8") as f:
            out += ["", "-" * 78, f"licenses/{t}", "-" * 78, "", f.read().rstrip()]
    with open(os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    used = set(texts)
    stale = [f for f in os.listdir(LIC) if f.endswith((".txt", ".md")) and f not in used and f != "README.md"]
    for f in stale:
        os.remove(os.path.join(LIC, f))
    rows = [f"| `{t}` | {GENERIC.get(t) or 'copied from the installed Python package (' + t.split('-', 1)[0] + ')'} |"
            for t in sorted(used)]
    with open(os.path.join(LIC, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# Licence texts\n\nLicence texts for what Virten Studio redistributes. `packaging/make_notices.py` "
                "copies the package ones from the build environment and writes `THIRD-PARTY-NOTICES.txt` from them.\n\n"
                "| File | From |\n|---|---|\n" + "\n".join(rows) + "\n")
    size = os.path.getsize(os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt"))
    print(f"THIRD-PARTY-NOTICES.txt: {len(MODELS)} models, {len(libs)} libraries, {len(texts)} licence texts, "
          f"{size // 1024} KB; removed stale: {stale or 'none'}")


if __name__ == "__main__":
    main()
