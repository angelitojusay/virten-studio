"""Runs the plugin's assisted-cull path against the fake Lightroom SDK (needs: pip install lupa).
Writes a small cull file in a temp folder (nothing near your catalogs), applies it twice and checks that the
second run replaces the first run's suggestions instead of adding to them.

  .venv\\Scripts\\python.exe dev-tools\\cull_plugin_test.py . dev-tools\\fake_lr.lua"""
import os
import sys
import tempfile

sys.path.insert(0, sys.argv[1])


def run():
    sys.stdout.reconfigure(encoding="utf-8")
    from lupa import LuaRuntime
    from autostyle import project
    d = tempfile.mkdtemp(prefix="vs-cull-test-")
    path = os.path.join(d, "test cull.virten")
    first = [("U1", "a.ARW", {"_Keywords": "Likely reject|Blurry;Burst|Other frames", "_Collections": "Likely rejects"}),
             ("U2", "b.ARW", {"_Keywords": "Burst|Best frame;Suggested keeper", "_Collections": "Suggested keepers;Best of each burst"}),
             ("U3", "c.ARW", {"_Keywords": "", "_Collections": ""})]
    second = [("U1", "a.ARW", {"_Keywords": "Suggested keeper", "_Collections": "Suggested keepers"}),
              ("U2", "b.ARW", {"_Keywords": "Likely reject|Eyes closed", "_Collections": "Likely rejects"}),
              ("U3", "c.ARW", {"_Keywords": "", "_Collections": ""})]
    lua = LuaRuntime()
    lua.execute(open(sys.argv[2], encoding="utf-8").read())
    plugin = open(os.path.join(sys.argv[1], "VirtenStudio.lrplugin", "ApplyEdits.lua"), encoding="utf-8").read()
    ok = True
    for run_no, items in ((1, first), (2, second)):
        project.write_edits_file(path, "Assisted cull", items, kind="cull", title="Test shoot")
        lua.globals().EDITS_FILE = path
        lua.execute(plugin)
        print(f"--- run {run_no}")
        for uid, _, s in items:
            got = list(lua.eval(f"PHOTO('{uid}'):keywordPaths()").values())
            want = sorted("Virten Cull|" + k for k in s["_Keywords"].split(";") if k)
            print(f"  {uid}: {got}")
            ok &= got == want
        sets = lua.globals().SETS
        sub = sets["Virten Cull>Test shoot"]
        counts = {c.name: lua.eval("function(c) return c:count() end")(c) for c in sub.getChildCollections(sub).values()}
        print("  collections:", counts)
        exp = {}
        for _, _, s in items:
            for c in filter(None, s["_Collections"].split(";")):
                exp[c] = exp.get(c, 0) + 1
        ok &= all(counts.get(k, 0) == v for k, v in exp.items()) and all(v == exp.get(k, 0) for k, v in counts.items())
        print("  applied file renamed:", os.path.exists(path + ".applied"))
        ok &= os.path.exists(path + ".applied")
        if os.path.exists(path + ".applied"):
            os.remove(path + ".applied")
        print("  message:", str(lua.eval("LOG.messages[#LOG.messages]")).replace("\n", " | ")[:220])
    os.rmdir(d)
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
