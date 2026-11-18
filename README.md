# Virten Studio

**Virten Studio — Companion Workflow for Adobe® Lightroom® Classic Catalogs**

A local, subscription-free AI editing assistant for Lightroom Classic catalogs, on Windows and macOS. It learns how you
edit, then prepares the edits for new shoots on your own computer: no uploads, no accounts. (Earlier versions were
called AutoStyle; Virten Studio moves their data over automatically.)

- It **learns your editing style** from catalogs you've already edited, and applies it to new shoots.
- **Looks:** cinematic and film styles, plus any Lightroom preset imported as a Look, layered on top of your style.
- **AI tools:** straighten horizon, subject/background/sky masks, smooth skin and whiten teeth, each with its own strength slider.
- **Sync:** profiles, Looks and app updates are shared between your computers through Google Drive or OneDrive.

## Typical workflow (everything stays on your computer)
1. Cull in Lightroom as usual, rating your keepers 1★.
2. **Projects ▸ New Project**: choose the catalog and filter to ★1. Pick your profile, an optional Look and strength, and toggle the AI tools (straighten, skin…). Click **Start Editing**.
3. In Lightroom, choose **Library ▸ Plug-in Extras ▸ Apply Virten Studio Edits…**. The edits appear with a "Virten Studio" history step, and Lightroom computes the AI masks.

Lightroom can stay open the whole time; Virten Studio only reads the catalog.

## Keeping it learning
- **Profiles ▸ Learn from new edits** retrains a profile with your finished shoots. Photos where you corrected Virten Studio count double, and recent shoots count more.
- **Teach a profile…** on a finished project lets you choose which profile learns from it, so a cinematic job doesn't drift your natural profile.
- A profile can also learn your edits as they were at a named history step (an "AI Edit Step"), for example a warm "Signature Warmth" pass you apply before fine-tuning. Only learn from edits you made, or have the rights to use.

## Assisted culling (1.4.0)
**Projects ▸ + New Cull** looks through a shoot (usually the unrated photos) and adds *suggestions* to Lightroom. It
never changes your star ratings, flags, color labels or edits.
- **Burst**: near-identical frames shot within seconds, so you can compare them side by side.
- **Timelapse**: intervalometer sequences, labelled and left out of everything else.
- **Likely reject**, with the reason: blurry (compared with the other frames of the same burst, or a soft face), eyes
  closed, exposure way off, flash didn't fire. Relaxed / Normal / Strict.
- **Likely best frame** in bursts of people: learned from which frame you kept in past culls (expression, gaze, head
  angle, eye focus, from a high-resolution look at the faces). Train it under **Profiles ▸ Assisted culling**.

Apply it with **Library ▸ Plug-in Extras ▸ Apply Virten Studio Edits…** like an edits file: suggestions arrive as keywords
under **Virten Cull** (not included when you export) and collections in a **Virten Cull ▸ <project>** set. Re-running
replaces earlier suggestions. When you've finished culling, **Learn from this cull** on the project teaches the model
your picks (any star = kept).

How well it works, tested on 12 real event shoots against the photographer's own picks (each shoot held out): 80–92 %
of likely-reject flags were photos that were cut; the best-frame hint matched the pick in 46 % of people bursts (35 % by
chance). Predicting keepers in general, or the best frame of scenery bursts, didn't beat chance, so the app doesn't
offer it.

## Archiving and backups
- **Archive** a finished project from its row or its page. It moves to **Projects ▸ Archived** for 90 days, then it's removed from Virten Studio automatically.
- With sync on, archiving also saves a backup zip to `Virten Studio Sync/projects` on your cloud drive. The zip holds the per-photo edits, thumbnails and the Lightroom edits file, about 25 MB for a 1,000-photo wedding. Backups stay after the 90 days.
- **Import backup…** (on the Archived tab) brings a backup back.
- Your Lightroom catalogs are never changed by archiving.

## What the AI looks at
- **Editing:** brightness/color statistics of the camera preview, camera white balance, EXIF, the people in the frame (MediaPipe segmentation), faces, blinks and sharpness, and a CLIP "scene" description (ceremony, dance floor, portrait…).
- **Hardware:** photo analysis runs in parallel on all CPU cores. CLIP runs on the GPU (DirectML on Windows, CoreML on Apple Silicon), falling back to the CPU automatically.

## How close the preview is to Lightroom
- The Before / After preview renders your edits on the camera's embedded preview, calibrated against Lightroom
  Classic's own renders of 274 real photos (`dev-tools/calibrate_preview.py`). White balance is shown relative to each
  photo's as-shot white balance. Tone sliders work on luminance, Vibrance protects skin, and saturation rolls off
  softly at the edge of the colour space instead of clipping. It's a preview: Lightroom's own render is the final word.
- **Colour-managed display:** previews and thumbnails are sRGB. On a wide-gamut monitor (Display P3, Adobe RGB-class)
  Virten Studio converts them to the monitor's colour profile, like Lightroom does, so they don't look oversaturated.
  On Windows this uses the monitor profile set in Windows' Color Management. Turn it off under **Settings ▸ Display**.

## Where things live
| | Windows | macOS |
|---|---|---|
| Profiles, projects, analysis cache | `%APPDATA%\Virten Studio` | `~/Library/Application Support/Virten Studio` |
| Lightroom plugin | `%APPDATA%\Adobe\Lightroom\Modules\VirtenStudio.lrplugin` | `~/Library/Application Support/Adobe/Lightroom/Modules/VirtenStudio.lrplugin` |
| Sync folder | chosen in Settings (e.g. `G:\My Drive\Virten Studio Sync`; it must be in My Drive, not a backed-up computer folder, so the Mac can see it) | chosen in Settings (Google Drive is detected automatically) |
| Edits files for Lightroom | `<catalog folder>\Virten Studio\*.virten` | same |

## Privacy
- Photos, catalogs, profiles and projects never leave your computer, except through the sync folder you choose (your own cloud drive). There's no telemetry, analytics or account.
- **Update checks:** at startup (and after a sync), Virten Studio asks GitHub for the latest release of this app: one request to `api.github.com`, with no IDs, file names or hardware data. Turn it off under **Settings ▸ Updates ▸ Check for updates automatically at startup**; **Check for updates** then runs only when you click it.
- **Buy Me a Coffee** opens in your browser only when you click it.

## Running from source (Windows)
Run `setup.bat` once, then use `Virten Studio.bat`.

## Building installers
- **Windows:** run `packaging\build_windows.bat`. This needs PyInstaller (installed by the script), plus Inno Setup 6 for `VirtenStudio-Setup-<version>.exe`. The installer upgrades an existing AutoStyle install in place.
- **macOS:** on the Mac, double-click `Build Virten Studio.command` (or run `bash packaging/build_mac.sh`). It produces `dist/VirtenStudio-<version>.dmg`. The app isn't signed with an Apple certificate, so the first time you open it, right-click **Virten Studio ▸ Open**.
- **GitHub Actions:** pushing a `v*` tag builds both installers and publishes them as a GitHub Release (`.github/workflows/build.yml`).
- **Self-test:** `run.py --selftest` (or the packaged app with `--selftest`) checks the models, GPU and the bundled plugin. The build scripts run it automatically.
- **Licence check:** `packaging/check_bundle.py` runs after every build and fails it if a GPL-only component (such as Qt Virtual Keyboard) or an un-noticed package ends up in the app, or the licence files are missing.

Both build scripts also copy the installer into the sync folder's `app/` folder. Every computer running Virten Studio then offers **Update to x.y.z** in the sidebar.

## Not included (yet)
- Composition cropping (by design: straightening only).
- Creative profiles/Looks embedded in a Lightroom preset's profile.
- A learned straightening model (it uses line detection, typically within about ±0.7°).

## Licence and open-source components
- Virten Studio is free to use under its end-user licence: [LICENSE.txt](LICENSE.txt).
- It includes open-source software and AI models under their own licences (LGPL-3.0 Qt for Python, LGPL-2.1 LibRaw and FFmpeg, Apache-2.0 MediaPipe and its face and segmentation models, MIT CLIP, ONNX Runtime and DirectML, BSD scikit-learn / SciPy / NumPy, and more): see [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) and the [licenses](licenses) folder. **Settings ▸ About & Open-Source Licenses** shows the same texts in the app.

## Support
Virten Studio is free, local-first and has no tracking. If it saves you time, you can [buy me a coffee](https://buymeacoffee.com/roat). Nothing in the app is locked or limited either way.

## Trademarks
Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United States and/or other
countries. Virten Studio is an independent product and is not affiliated with, sponsored by, or endorsed by Adobe Inc.
Other product names are used only to describe compatibility and may be trademarks of their respective owners.
