# Developing SC Co-Pilot

## Run from source

1. Install Python 3.12 (64-bit).
2. Double-click `App/Install.bat`. It installs the packages from `App/requirements.txt`, including Kokoro.
3. Double-click `App/Start SC Co-Pilot.bat`.

Settings, logs and caches go to `%APPDATA%\SC Co-Pilot` and `%LOCALAPPDATA%\SC Co-Pilot`, the same folders the installed version uses. To keep a separate test profile, set the environment variable `SC_COPILOT_HOME` to any folder. You can also drop an empty `portable.txt` next to the app to keep everything in a `userdata` folder beside it.

## Project layout

| Path | What it is |
|---|---|
| `App/sc_copilot.pyw` | The app window, tabs, settings, setup wizard, updates |
| `App/sc_paths.py` | Where files live (program files vs. per-user data) and one-time migration from old builds |
| `App/sc_version.py` | Version number, GitHub repo, subscription service URL, disclaimer |
| `App/sc_update.py` | Checks GitHub Releases and downloads the new installer |
| `App/sc_log.py` | Reads `Game.log` live and turns it into game state; reads old sessions for History |
| `App/sc_binds.py` | Reads keybinds (game defaults from `Data.p4k` + the user's `actionmaps.xml`), presses them, assigns spare keys, repairs clashes |
| `App/sc_brain.py` | Talks to Claude (own key or the subscription service) and gives it tools for game data, keybinds, trade and web search |
| `App/sc_quick.py` | Instant commands matched on the PC without the AI |
| `App/sc_voice.py` | Push-to-talk, speech-to-text, voices |
| `App/sc_fx.py` | Voice effects |
| `App/sc_callouts.py` | Spoken alerts |
| `App/sc_macros.py` | Voice macros |
| `App/sc_trade.py` | UEX prices, routes, places, ships, items, refinery yields |
| `App/sc_overlay.py` | The in-game overlay |
| `App/sc_nvidia.py` | Reads/sets NVIDIA's "Vulkan/OpenGL present method" for Star Citizen through NvAPI |
| `App/legal/` | License, third-party notices, privacy (shipped inside the app) |
| `packaging/` | PyInstaller spec, Inno Setup script, build requirements, release helpers |
| `.github/workflows/build.yml` | Builds and tests the installer on every push; publishes a release for `v*` tags |
| `.github/workflows/pages.yml` | Publishes the website (`docs/site` plus `packs/`) to GitHub Pages |
| `.github/workflows/packs.yml` | Adds a community line pack when a maintainer labels its issue `pack-approved` |
| `App/sc_lines.py` | Every spoken line, the personalities, and line-pack import/export |
| `App/sc_avatar.py` | The overlay's animated avatar (maths in `AvatarModel`, drawing in `Avatar`) |
| `App/sc_hud.py` | Target reader: screen capture and shield/hull measurement |
| `App/brand/` | `logo.svg` (the current logo) and `options/` (the other designs) |
| `packs/` | Community line packs and their `index.json` |
| `docs/site/` | The website |
| `tests/` | pytest tests, run on every build |

## How it works

1. **Reading the log** (`sc_log.py`). A background thread checks `Game.log` four times a second for new lines. Each line goes through `GameState.feed_line()`, which uses regular expressions to spot the interesting ones (`<Vehicle Destroyed>`, `Added notification "Contract Accepted: …"`). Multi-line notifications are stitched back together first. When the game restarts it replaces `Game.log`. The app notices because the first line changed, and it starts a fresh session.
2. **Events → callouts.** The state hands events like `("kill", {...})` to listeners. `sc_callouts.py` turns them into short sentences and drops repeats.
3. **Keybinds** (`sc_binds.py`). The defaults live inside `Data.p4k` in binary XML. The app finds that one file in the archive's index, decompresses it (zstd), decodes the binary XML, then layers the user's `actionmaps.xml` on top. Each action's activation mode (tap, hold, double-tap) decides how long the key is held.
4. **Voice in** (`sc_voice.py`). While push-to-talk is held it records the mic. On release, faster-whisper turns the audio into text locally.
5. **Instant or AI?** (`sc_quick.py`). Short commands match patterns and fire right away. Everything else goes to the AI.
6. **The AI** (`sc_brain.py`). The question goes out with a live status block. Claude can call tools (contracts, combat log, keybinds, press controls, prices, places, web search). The app runs each tool and sends back the result. The answer streams back and is spoken sentence by sentence. In subscription mode the same request goes to the Co-Pilot service, which checks the subscription and forwards it to Anthropic.
7. **Overlay** (`sc_overlay.py`). A borderless window marked always-on-top, click-through and never-activate. It's hidden by fading it out rather than closing it, so it never steals focus from the game.

## Building the installer

The GitHub Actions workflow does this on every push. To build on your own Windows PC:

```
pip install -r packaging/requirements-build.txt
python packaging/make_version_info.py
pyinstaller --noconfirm --clean packaging/sc_copilot.spec --distpath dist --workpath build
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 packaging\installer.iss
```

The installer ends up in `dist/`. Set `SC_INCLUDE_KOKORO=1` before running PyInstaller to bundle Kokoro, but read the licensing note below first.

## Changing the logo

Edit `App/brand/logo.svg` (or pick one from `App/brand/options/`), then run `python packaging/make_icons.py` (or `python packaging/make_icons.py h_vector`). It rebuilds the app icon, the `.ico` used by the `.exe` and installer, and the website icons. It needs `rsvg-convert` and Pillow.

## Releasing a new version

1. Bump `VERSION` in `App/sc_version.py`.
2. Add a `## 1.2.3` section at the top of `CHANGELOG.md`.
3. Commit, then tag and push: `git tag v1.2.3` and `git push origin main v1.2.3`.
4. The workflow builds, self-tests, and publishes a GitHub Release with the installer and your changelog notes. Installed copies see the update within a few hours, or right away from Settings → About → Check for updates.

## Licensing notes

- The app is under the PolyForm Noncommercial License 1.0.0. Others can use and modify it non-commercially. The copyright holder can still sell it or paid extras.
- **Kokoro is left out of the installer** because its pronunciation step uses phonemizer and espeak-ng, which are GPL-3.0. Shipping them inside the installer would put GPL obligations on the bundle. Source installs fetch them from PyPI on the user's own machine instead.
- edge-tts (LGPL-3.0) is shipped as plain `.py` files, and libsndfile and FFmpeg (LGPL) as separate DLLs, so users can swap them, as the LGPL requires.
