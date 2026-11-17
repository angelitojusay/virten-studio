import os
import sys
import time

sys.path.insert(0, sys.argv[1])
if __name__ == "__main__":  # from a Claude session, rerun via Explorer so the profile lands in the real AppData
    from autostyle.paths import relaunch_outside_package
    relaunch_outside_package(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
MAIN = [os.path.normpath(c) for c in sys.argv[3:]]


def run():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    from autostyle import model, project
    cats = [os.path.normpath(l.strip().lstrip("﻿")) for l in open(sys.argv[2], encoding="utf-8")
            if l.strip().lstrip("﻿").startswith("D:")]
    weights = {c: (1.0 if c in MAIN else model.SUPPORTING_WEIGHT) for c in cats}
    print("main:", [os.path.basename(c) for c in MAIN], "| supporting:", sum(w < 1 for w in weights.values()))
    last = [0]

    def prog(a, b, s):
        if time.time() - last[0] > 60:
            print(s, a, b)
            last[0] = time.time()
    t = time.time()
    p = model.train_profile("My Style", cats, prog, feedback=project.feedback_for(cats), catalog_weights=weights)
    print(f"DONE in {time.time() - t:.0f}s: {p['n_photos']} photos; tools {p['available_tools']}")
    for k in ("Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012", "Blacks2012", "Vibrance"):
        m = p["metrics"].get(k)
        if m:
            print(f"  {k:16s} ±{m['mae']:.2f}  (one preset: ±{m['baseline_mae']:.2f})")
    print("  straighten", {a: round(b, 2) for a, b in p["tool_metrics"].get("Straighten angle", {}).items() if isinstance(b, float)})


if __name__ == "__main__":
    run()
