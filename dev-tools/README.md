# Dev tools

Helper scripts used while building VS. Run from the `Virten Studio` folder with the project venv:

| Script | What it does | Example |
|---|---|---|
| `make_mac_kit.py` | Builds the Mac build kit tar.gz | `.venv\Scripts\python.exe dev-tools\make_mac_kit.py . "G:\My Drive\Virten Studio Sync\Mac"` |
| `retrain_my_style.py` | Retrains "My Style": catalogs in `catalogs.txt`, main-style catalogs as extra args (rest at 1/3 weight) | `.venv\Scripts\python.exe dev-tools\retrain_my_style.py . dev-tools\catalogs.txt "D:\Shoots\Wedding.lrcat" ...` |
| `plugin_test.py` + `fake_lr.lua` | Simulates the Lightroom plugin with a fake LR SDK (needs `pip install lupa`) | `.venv\Scripts\python.exe dev-tools\plugin_test.py . dev-tools\fake_lr.lua "D:\Shoots\Wedding.lrcat"` |
| `lua_syntax_check.py` | Syntax-checks Lua files | `.venv\Scripts\python.exe dev-tools\lua_syntax_check.py VirtenStudio.lrplugin\ApplyEdits.lua` |
| `catalogs.txt` | The D: catalogs used for training | |

**Started from Claude Desktop?** Windows redirects its AppData writes into Claude's private copy
(`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming`), where the installed VS can't see them. Scripts that save VS
data call `autostyle.paths.relaunch_outside_package()`, which detects this and reruns the script through Explorer;
its output then goes to `dev-tools\logs\`. Reading data from a Claude session is fine (you may see the private copy).

Windows build: `packaging\build_windows.bat` (installer + publish to Google Drive).
