"""Simulates the Lightroom plugin on a real project with a fake LR SDK.
Usage: python dev-tools/plugin_test.py <project folder> dev-tools/fake_lr.lua [catalog.lrcat]"""
import os
import sys

sys.path.insert(0, sys.argv[1])


def run():
    sys.stdout.reconfigure(encoding="utf-8")
    from lupa import LuaRuntime
    from autostyle import project, tools
    cat = sys.argv[3] if len(sys.argv) > 3 else "sample.lrcat"  # the Lightroom catalog to test with
    f = {"folders": None, "collections": [], "flag": "any", "ratings": [1], "labels": None, "only_unedited": False}
    ep = project.run_project(project.new_project("plugin test", cat, "My Style (all D: shoots)", filters=f,
                                                 groups=list(tools.TOOLS) + ["tone", "wb", "presence", "color", "curve", "detail"],
                                                 tool_strength={"skin": 0.8}, look="Moody Film", look_strength=0.5))
    print("edits file:", os.path.relpath(ep["edits_file"], os.path.dirname(cat)), "| header:",
          open(ep["edits_file"], encoding="utf-8").readline().strip())
    for choice in ('ok', 'other'):
        lua = LuaRuntime()
        lua.globals().EDITS_FILE = ep["edits_file"]
        lua.globals().CONFIRM_CHOICE = choice
        lua.execute(open(sys.argv[2], encoding="utf-8").read())
        lua.execute(open(os.path.join(sys.argv[1], "VirtenStudio.lrplugin", "ApplyEdits.lua"), encoding="utf-8").read())
        print("--- user clicked", "Apply (masks later)" if choice == "ok" else "Apply + compute masks now"); print(lua.eval("REPORT()"))
        if os.path.exists(ep["edits_file"] + ".applied"): os.replace(ep["edits_file"] + ".applied", ep["edits_file"])
    for fp in (ep["edits_file"], ep["edits_file"] + ".applied"):
        if os.path.exists(fp):
            os.remove(fp)
    project.delete_project(ep["id"])
    os.rmdir(os.path.dirname(ep["edits_file"]))


if __name__ == "__main__":
    run()
