# Virten Studio

A local, subscription-free take on the Imagen workflow for Lightroom Classic, on Windows and macOS. (Earlier versions were called AutoStyle; Virten Studio moves their data over automatically.)

- It **learns your editing style** from catalogs you've already edited, and applies it to new shoots.
- **Looks:** cinematic and film styles, plus any Lightroom preset imported as a Look, layered on top of your style.
- **AI tools:** straighten horizon, subject/background/sky masks, smooth skin and whiten teeth, each with its own strength slider.
- **Sync:** profiles, Looks and app updates are shared between computers through Google Drive or OneDrive.

## Typical workflow (same as Imagen, without the upload)
1. Cull in Lightroom as usual, rating your keepers 1â˜….
2. **Projects â–¸ New Project**: choose the catalog and filter to â˜…1. Pick your profile, an optional Look and strength, and toggle the AI tools (straighten, skinâ€¦). Click **Start Editing**.
3. In Lightroom, choose **Library â–¸ Plug-in Extras â–¸ Apply Virten Studio Editsâ€¦**. The edits appear with a "Virten Studio" history step, and Lightroom computes the AI masks.

Lightroom can stay open the whole time; Virten Studio only reads the catalog.

## Keeping it learning
- **Profiles â–¸ Learn from new edits** retrains a profile with your finished shoots. Photos where you corrected Virten Studio count double, and recent shoots count more.
- **Teach a profileâ€¦** on a finished project lets you choose which profile learns from it, so a cinematic job doesn't drift your natural profile.

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

How well it works, tested on 12 of your shoots against your own picks (each shoot held out): 80–92 % of likely-reject
flags were photos you cut; the best-frame hint matched your pick in 46 % of people bursts (35 % by chance). Predicting
keepers in general, or the best frame of scenery bursts, didn't beat chance, so the app doesn't offer it.

## Archiving and backups
- **Archive** a finished project from its row or its page. It moves to **Projects â–¸ Archived** for 90 days, then it's removed from Virten Studio automatically.
- With sync on, archiving also saves a backup zip to `Virten Studio Sync/projects` on your cloud drive. The zip holds the per-photo edits, thumbnails and the Lightroom edits file, about 25 MB for a 1,000-photo wedding. Backups stay after the 90 days.
- **Import backupâ€¦** (on the Archived tab) brings a backup back.
- Your Lightroom catalogs are never changed by archiving.

## What the AI looks at
- **Editing:** brightness/color statistics of the camera preview, camera white balance, EXIF, the people in the frame (MediaPipe segmentation), faces, blinks and sharpness, and a CLIP "scene" description (ceremony, dance floor, portraitâ€¦).
- **Hardware:** photo analysis runs in parallel on all CPU cores. CLIP runs on the GPU (DirectML on Windows, CoreML on Apple Silicon), falling back to the CPU automatically.

## Where things live
| | Windows | macOS |
|---|---|---|
| Profiles, projects, analysis cache | `%APPDATA%\Virten Studio` | `~/Library/Application Support/Virten Studio` |
| Lightroom plugin | `%APPDATA%\Adobe\Lightroom\Modules\VirtenStudio.lrplugin` | `~/Library/Application Support/Adobe/Lightroom/Modules/VirtenStudio.lrplugin` |
| Sync folder | chosen in Settings (e.g. `G:\My Drive\Virten Studio Sync`; it must be in My Drive, not a backed-up computer folder, so the Mac can see it) | chosen in Settings (Google Drive is detected automatically) |
| Edits files for Lightroom | `<catalog folder>\Virten Studio\*.virten` | same |

## Running from source (Windows)
Run `setup.bat` once, then use `Virten Studio.bat`.

## Building installers
- **Windows:** run `packaging\build_windows.bat`. This needs PyInstaller (installed by the script), plus Inno Setup 6 for `VirtenStudio-Setup-<version>.exe`. The installer upgrades an existing AutoStyle install in place.
- **macOS:** on the Mac, double-click `Build Virten Studio.command` (or run `bash packaging/build_mac.sh`). It produces `dist/VirtenStudio-<version>.dmg`. The app isn't signed with an Apple certificate, so the first time you open it, right-click **Virten Studio â–¸ Open**.
- **Self-test:** `run.py --selftest` (or the packaged app with `--selftest`) checks the models, GPU and the bundled plugin. The build scripts run it automatically.

Both build scripts also copy the installer into the sync folder's `app/` folder. Every computer running Virten Studio then offers **Update to x.y.z** in the sidebar.

## Not included (yet)
- Composition cropping (by design: straightening only).
- Creative profiles/Looks embedded in a Lightroom preset's profile.
- A learned straightening model (it uses line detection, typically within about Â±0.7Â°).
