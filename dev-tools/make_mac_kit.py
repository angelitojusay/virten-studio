import os, sys, tarfile, io
root, out_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
from autostyle import __version__
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"VirtenStudio-{__version__}-mac-build-kit.tar.gz")
files = ["run.py", "requirements.txt", "README.md"]
for d in ("autostyle", "looks", "models", "VirtenStudio.lrplugin"):
    for dp, dn, fn in os.walk(os.path.join(root, d)):
        dn[:] = [x for x in dn if x != "__pycache__"]
        files += [os.path.relpath(os.path.join(dp, f), root) for f in fn if not f.endswith(".pyc")]
files += ["packaging/autostyle.spec", "packaging/build_mac.sh", "packaging/publish.py", "packaging/rth_cv2_mac.py"]
def add(tar, src_rel, arc_rel, mode=0o644, text=False):
    data = open(os.path.join(root, src_rel), "rb").read()
    if text:
        data = data.replace(b"\r\n", b"\n")
    ti = tarfile.TarInfo("Virten Studio/" + arc_rel.replace(os.sep, "/"))
    ti.size, ti.mode = len(data), mode
    tar.addfile(ti, io.BytesIO(data))
with tarfile.open(out, "w:gz") as tar:
    for f in files:
        is_text = f.endswith((".py", ".sh", ".spec", ".txt", ".md", ".lua", ".json"))
        add(tar, f, f, 0o755 if f.endswith(".sh") else 0o644, is_text)
    add(tar, "packaging/Build Virten Studio.command", "Build Virten Studio.command", 0o755, True)
print(out, round(os.path.getsize(out) / 1e6), "MB,", len(files) + 1, "files")
