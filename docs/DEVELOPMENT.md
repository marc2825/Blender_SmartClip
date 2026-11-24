# Development

This guide is for working on the add-on itself. For installing and using it, see the [README](../README.md).

## Layout

| Path | Contents |
|---|---|
| `smart_clipping/ops.py` | The modal move operator: what moves, input handling, snapping, the status bar |
| `smart_clipping/detector.py` | Collecting snap points and searching them: a screen-space grid (default) or a 3D KD-tree (Advanced), which return the same candidates |
| `smart_clipping/drawing.py` | Viewport overlay: guide lines, markers, labels, the snap distance ring, the mode lines |
| `smart_clipping/hud.py` | The words shown during a move (labels, mode lines, status bar), kept apart from drawing so they can be tested |
| `smart_clipping/i18n.py` | Japanese translation of the interface |
| `smart_clipping/keymap.py` | The `Shift+G` keymap items and Use Shortcut |
| `smart_clipping/prefs.py`, `utils.py` | Preferences, shared helpers, and the move's decisions (the A / S cycles, what Ctrl does) as plain functions |
| `smart_clipping/__init__.py` | `bl_info`, panels, menu entries, scene properties and their migration, the check for another copy |
| `smart_clipping/blender_manifest.toml` | The extension manifest (Blender 4.2+); goes into the extension ZIP only |
| `tests/` | Headless tests, the UI test, and a scene for manual checks |
| `scripts/` | Version check and release packaging (plain Python 3, no Blender needed) |

## Tests

### Headless

Covers snap point collection, candidate search with both backends (they must return identical candidate lists), the operator's `execute` without a window, the move's decisions and words, and the translation (see [Translation](#translation)). CI runs it on every pull request.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/headless_test_runner.py
blender --background --factory-startup --python-exit-code 1 --python tests/headless_test_runner.py -- --case stress_100k
```

Case names are the keys of `CASES` in the runner. It exits with status 1 if any case fails; a case that cannot run in that Blender (the translations when it cannot switch to Japanese) is counted as skipped, not passed.

`--module NAME` runs the cases against the add-on Blender already has enabled under that name instead of the source folder; CI uses it for the installed extension (see [Extension](#extension)).

Pass `--python-exit-code 1` to every Blender that runs a test script (CI does): without it, an exception the script does not catch, such as the add-on failing to register, ends Blender with exit code 0 and the run looks green.

### UI

The modal operator can only be exercised in a real window. `tests/ui_operator_test.py` feeds Blender simulated input (`Shift+G`, mouse moves, constraint keys, `Ctrl`, `A`, `S`, clicks, `Esc`) and checks parented objects, navigating mid-move, constraints, the redo offset, multi-object moves, exact snapping, snap points the move cannot reach (a constraint, Lock Location or Limit Location: "Projected", with Undo / Redo / cancel), `Ctrl`, right click cancelling, the `A` / `S` switches (put back on cancel, one undo step when confirmed without moving), what the shortcut takes over, the status bar, and Edit Mode. It keeps the sidebar open with the panels in the Item tab, so drawing errors in them fail the run.

```sh
blender --factory-startup --enable-event-simulate --python-exit-code 1 --python tests/ui_operator_test.py
```

- It needs a display, and real mouse and keyboard input is ignored while it runs.
- Set `SMARTCLIP_UI_SCREENSHOT_DIR` to a folder to save screenshots of the overlays.
- Set `SMARTCLIP_UI_BACKEND=KDTREE` to run the checks with the KD-tree search instead of the default grid.
- Set `SMARTCLIP_UI_LANGUAGE=ja_JP` to run them with the interface in Japanese.
- Set `SMARTCLIP_UI_MODULE=bl_ext.user_default.snaxis` (and the user folders the extension is installed in, without `--factory-startup`) to test the installed extension instead of the source folder.
- Set `SMARTCLIP_UI_SCALE=2` to run them at a larger interface scale (as on HiDPI displays), and `SMARTCLIP_UI_THEME=light` to use Blender's light theme; look at the screenshots for these.
- Some virtual X11 displays report `Ctrl` as released right after a simulated press. The `Ctrl` check then prints `[SKIP]` with the events the move received, instead of failing ([#26](https://github.com/marc2825/Snaxis/issues/26)).

### On a virtual display

`.github/workflows/ui-tests.yml` runs the same test on a virtual display (Xvfb, software OpenGL, `SMARTCLIP_UI_STEP=0.8`). It runs before every release (see [Releasing](#releasing)) and can be started by hand (Actions > UI Tests, with JSON lists of Blender versions and snap search backends). With `installed`, it builds the extension ZIP, installs it as [Extension](#extension) describes, and runs the test against it. It does not run on pull requests, where a GUI job on software OpenGL would slow every change down. Each run's summary page lists the result and every failed or skipped check. Screenshots taken there come out black even when the checks pass.

### Manual

How snapping feels is still worth checking by hand after UI changes. `tests/manual_ui_setup.py` builds a scene with targets along each axis, a grid that exceeds the vertex budget, and a collection for Manual Collection scope, then prints what to try.

```sh
blender --python tests/manual_ui_setup.py
```

`tests/record_teaser.py` records the README demo (`assets/teaser.gif`) from the current UI with simulated input, so it can be made again when the UI changes; its docstring has the `ffmpeg` command that turns the frames into the GIF.

### Translation

`smart_clipping/i18n.py` holds the Japanese messages, keyed by the English text used in the code. Blender looks names, tooltips and enum items up there by itself; text the add-on builds (viewport labels, format strings, reports) goes through `i18n.iface` / `tip` / `rpt`.

Registered messages apply to all of Blender, so a word Blender already translates (Snap To, Collection, Confirm, Axis, Off, ...) is not registered: the add-on uses Blender's own translation. The headless case `translations` checks that no message gives one of Blender's a different translation, that format placeholders match, and that every name and tooltip the add-on registers comes out in Japanese. When you add or change a label, add its message there. A long Japanese label is cut off in the sidebar's label column, so check new labels at the default sidebar width.

### Release ZIPs

`tests/install_zip_test.py` installs the legacy ZIP the way a user would and checks that it enables, carries the license text, registers, keeps a cleared hotkey off, keeps a changed key through Use Shortcut off and on, resets it with Reset Shortcut, disables cleanly, and can be removed. It refuses to run unless the user folders point somewhere disposable:

```sh
python scripts/package_addon.py --output-dir /tmp/dist
BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \
  blender --background --factory-startup --python-exit-code 1 --python tests/install_zip_test.py -- /tmp/dist/snaxis-vX.Y.Z.zip
```

With `--upgrade-from OLD.zip` before the ZIP, it first installs and enables `OLD.zip`, then installs the new ZIP over it and switches the add-on off and on without a restart, as a user updating from the Preferences does. CI runs this from 1.3.2 ([#23](https://github.com/marc2825/Snaxis/issues/23)).

`tests/upgrade_settings_test.py` checks that an update keeps the user's settings: in one Blender session it installs and enables an older ZIP, changes every preference and the key, and installs the new ZIP over it; the next session (without `--factory-startup`) must load the new version with those settings. CI runs it from 2.1.0, the last release named Smart Clipping (downloaded from its release and checked against its `.sha256`):

```sh
BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \
  blender --background --factory-startup --python-exit-code 1 --python tests/upgrade_settings_test.py -- \
    --phase before smart_clipping-v2.1.0.zip /tmp/dist/snaxis-vX.Y.Z.zip
(same variables) blender --background --python-exit-code 1 --python tests/upgrade_settings_test.py -- \
    --phase after smart_clipping-v2.1.0.zip /tmp/dist/snaxis-vX.Y.Z.zip
```

`scripts/package_addon.py` builds both ZIPs from the same files, with an explicit list of what goes in: the files of `smart_clipping/` that git tracks and whose suffix is in `SOURCE_SUFFIXES` (`.py`), plus `LICENSE`, and `smart_clipping/blender_manifest.toml` in the extension only.

| ZIP | Layout | For |
|---|---|---|
| `snaxis-vX.Y.Z.zip` | `smart_clipping/` with the sources and `LICENSE`, no manifest | Blender 4.0+ as a legacy add-on (4.2+ installs it as one too) |
| `snaxis-vX.Y.Z-extension.zip` | The sources, `LICENSE` and `blender_manifest.toml` at the root, as `blender --command extension build` lays them out | Blender 4.2+ and extensions.blender.org |

Untracked files (caches, local notes, settings) never go in, and a tracked file of another kind (another `.toml` included) stops the build until the lists cover it. The manifest must have the version of `bl_info`. Each ZIP gets a `.sha256`. `tests/package_test.py` (plain Python, no Blender) checks the lists, the exact contents and layout of both ZIPs, that the sources, `LICENSE` and manifest are the repository's, the SPDX lines, the fixed metadata, that two builds are byte-identical, the checksums, and the manifest rules a build does not check (version, license, a tagline of up to 64 characters without end punctuation or "Blender", no empty values, no permissions):

```sh
python tests/package_test.py
```

### Extension

Blender's own tools check the manifest and the ZIP (Blender 4.2+):

```sh
blender --command extension validate smart_clipping
blender --command extension validate dist/snaxis-vX.Y.Z-extension.zip
```

`tests/extension_install_test.py` installs the extension ZIP with the operator Install from Disk uses, into the User Default repository, in two Blender sessions with the same disposable user folders:

- `install` (with `--factory-startup`): it registers under `bl_ext.user_default.snaxis` (operator, panels, scene properties, keymap items, translations, preferences) with no top-level `smart_clipping` module; every preference and the key are changed and saved. Then the legacy ZIP is installed and enabling it must fail with the "already enabled" message, leaving the extension exactly as it was through the legacy add-on being disabled and removed.
- `reload` (without `--factory-startup`): the extension is enabled again at start-up with the saved preferences and key. Then the other order: the extension off (nothing left registered), the legacy add-on on, scene settings carried over and its preferences and key at their defaults, the extension refused and uninstalled with the legacy add-on untouched, and finally the extension installed again on its defaults and saved.

```sh
export BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts \
       BLENDER_USER_CONFIG=/tmp/bl/config BLENDER_USER_EXTENSIONS=/tmp/bl/extensions
blender --background --factory-startup --python-exit-code 1 --python tests/extension_install_test.py -- \
  --phase install dist/snaxis-vX.Y.Z-extension.zip dist/snaxis-vX.Y.Z.zip
blender --background --python-exit-code 1 --python tests/extension_install_test.py -- \
  --phase reload dist/snaxis-vX.Y.Z-extension.zip dist/snaxis-vX.Y.Z.zip
blender --background --python-exit-code 1 --python tests/headless_test_runner.py -- \
  --module bl_ext.user_default.snaxis
```

The last line runs every headless case against the installed extension.

### Benchmark

`tests/benchmark_snap.py` runs every search backend on the same synthetic point clouds (10k to 500k points, uniform and crowded, different scene scales) and reports index build time, query time (median, p95), the cost of the first query after a view change, memory, the share of candidates missed against a brute-force ground truth, and whether the backends return identical lists. It prints a Markdown table at the end and does not pass or fail. `--sizes` picks the point counts, and `--impl` points it at another copy of the package, for example a release exported with `git archive vX.Y.Z smart_clipping`, to compare.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/benchmark_snap.py -- --quick
```

#### Grid vs. KD-tree

Measured for [#19](https://github.com/marc2825/Snaxis/issues/19) with Blender 5.3.0 on Windows 11 (Intel Core Ultra 9 285K), default options: 200 timed queries, 12 view changes, and 40 queries with full candidate lists per case. The clouds fill a 10-unit cube ("crowded": 95% of the points in a blob with σ = 0.05) and are seen in perspective from about 23 units away at 1600 × 900 px; Snap Threshold is 30 px. Times in milliseconds.

| Cloud | Points | Index build, grid / KD-tree | Mouse move, grid (median / p95) | Mouse move, KD-tree (median / p95) | First move after a view change, grid / KD-tree (median) |
|---|---|---|---|---|---|
| uniform | 10,000 | 0.9 / 24 | 0.07 / 0.09 | 0.49 / 0.62 | 0.57 / 0.44 |
| uniform | 50,000 | 3.6 / 138 | 0.15 / 0.23 | 2.1 / 2.7 | 3.0 / 2.1 |
| uniform | 100,000 | 7.4 / 257 | 0.24 / 0.33 | 4.4 / 6.8 | 6.8 / 4.3 |
| uniform | 500,000 | 53 / 1,242 | 1.2 / 1.7 | 32 / 39 | 52 / 44 |
| crowded | 10,000 | 2.4 / 25 | 0.82 / 1.0 | 5.9 / 8.3 | 1.1 / 5.8 |
| crowded | 50,000 | 2.1 / 133 | 4.5 / 6.3 | 71 / 83 | 6.3 / 68 |
| crowded | 100,000 | 5.0 / 248 | 9.8 / 13 | 468 / 537 | 14 / 464 |
| crowded | 500,000 | 34 / 1,366 | 61 / 77 | 11,054 / 12,206 | 90 / 11,028 |

| Points | Memory kept by the index, grid / KD-tree (MB) | Peak Python allocation while building, grid / KD-tree (MB) |
|---|---|---|
| 10,000 | 0.3 / 0.3 | 0.9 / 2.3 |
| 50,000 | 1.5 / 1.7 | 4.4 / 11.3 |
| 100,000 | 3.1 / 3.4 | 8.9 / 15.2 |
| 500,000 | 15.3 / 17.2 | 44.4 / 29.1 |

- Accuracy: both returned every ground-truth candidate (miss rate 0) and the ground-truth best as the first result in every query, and their full candidate lists were identical, also at scene scales 0.001 and 1000.
- Starting a move next to a 1M-vertex mesh: 34 ms (grid) vs. 167 ms (KD-tree) with Max Vertex Budget 50,000, and 57 ms vs. 2,486 ms with a budget of 1,000,000.
- The grid is faster everywhere except the first mouse move after a view change in uniform clouds, where the KD-tree takes 15–37% less time. Once the cone of sight is narrowed down, the KD-tree's cost is the number of points around the cursor: `mathutils.kdtree` returns and sorts one Python tuple per point found, while the grid works on numpy arrays. Crowded scenes are the worst case.

#### Large meshes

`tests/benchmark_build.py` measures collecting the snap points, which happens when a move starts and when `S` switches Snap To, on grids with a Subdivision Surface modifier (so the points come from the evaluated mesh): the time, the growth of the resident memory over what the scene already used (Linux), and what was kept. It runs one scenario per Blender and skips a scenario that would need more than half of the available memory. `.github/workflows/benchmark.yml` runs a set of scenarios on a GitHub-hosted runner and puts the table in the run's summary.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/benchmark_build.py -- \
  --verts 4000000 --objects 1 --budget 50000
```

Measured for [#30](https://github.com/marc2825/Snaxis/issues/30) on a GitHub-hosted runner (Linux, 4 vCPUs, 16 GB). The memory column is the growth of the resident set during the collection, over what the scene already used ("scene").

| Evaluated vertices | Objects | Snap Point Limit | Start of a move, 4.0.2 / 5.2.4 (s) | Memory growth, 4.0.2 / 5.2.4 (MiB) | Scene, 5.2.4 (MiB) |
|---|---|---|---|---|---|
| 1,000,000 | 1 | 50,000 | 0.05 / 0.07 | 34 / 35 | 466 |
| 1,000,000 | 1 | 1,000,000 | 0.17 / 0.13 | 89 / 92 | 450 |
| 4,000,000 | 1 | 50,000 | 0.18 / 0.21 | 107 / 109 | 784 |
| 4,000,000 | 1 | 1,000,000 | 0.32 / 0.30 | 158 / 171 | 783 |
| 4,000,000 | 8 | 50,000 | 0.16 / 0.21 | 26 / 26 | 770 |
| 4,000,000 | 8 | 1,000,000 | 0.23 / 0.26 | 77 / 81 | 770 |
| 9,000,000 | 1 | 50,000 | 0.40 / 0.47 | 239 / 233 | 1,369 |
| 9,000,000 | 1 | 1,000,000 | 0.55 / 0.56 | 290 / 283 | 1,372 |
| 16,000,000 | 1 | 50,000 | 0.69 / 0.83 | 427 / 432 | 2,175 |

- Time and memory grow about linearly with the vertices read: about 0.05 s and 27 MiB per million vertices of one mesh. Reading the evaluated coordinates is most of it; the limit adds a little (the points kept).
- Split over eight meshes the peak is lower, since each mesh's arrays are freed before the next is read.
- Switching Snap To with `S` costs the same as the start (within a few percent).
- This was judged acceptable, so the collection is unchanged; the guide gives the numbers and when to narrow Snap To instead.

## CI

| Workflow | Runs on | What it does |
|---|---|---|
| `blender-ci.yml` | Pushes to `main`, pull requests | Version check, release ZIP contents check, compile check, headless tests and legacy ZIP install tests (fresh, over 1.3.2, and over 2.1.0 keeping the settings across a restart) on Blender 4.0.2 (oldest supported), 4.2.23, and 5.2.4; on 4.2.23, 5.2.4 and 5.3.0 the extension: Blender's validate and build, [Extension](#extension)'s install tests, and the headless tests against the installed extension |
| `codeql.yml` | Pushes, pull requests, monthly | CodeQL scan of the Python code |
| `release-addon.yml` | `v*.*.*` tags, manual runs | UI tests as a gate (the source folder, and the installed extension), then packages both ZIPs, installs the legacy ZIP into Blender 4.0.2, validates and installs the extension into 4.2.23, and publishes a release (see below) |
| `ui-tests.yml` | Manual, and called by `release-addon.yml` | UI test on a virtual display, on the source folder or the installed extension |
| `benchmark.yml` | Manual | Snap point collection on large evaluated meshes (see [Large meshes](#large-meshes)) |

Dependabot proposes GitHub Actions updates monthly.

The workflows get Blender through `.github/scripts/fetch-blender.sh`: the archive and blender.org checksum are cached per version, a cache miss downloads from download.blender.org with mirrors as fallback, and the archive is checked against the checksum on every run. Workflows default to read-only tokens; only the release job can write. The third-party release action is pinned to a commit.

`scripts/package_addon.py` writes files in a fixed order with fixed timestamps, so the same sources always produce the same ZIPs and checksums.

## Tested environments

What was checked for the latest release, and what was not. Update it with each release.

**2.1.1** (2026-11-25), the rename to Snaxis

| Where | Blender | What | Result |
|---|---|---|---|
| Windows 11, real display (Intel Core i7-12700F, 16 GB) | 5.3.0 | Extension ZIP (`snaxis`): Blender's validate; install and restart phases; headless tests and UI test (Japanese) against the installed extension | Valid; 25 / 25 and 36 / 36; 57 / 57; 91 / 91 |
| Same | 5.3.0 | Headless tests and UI test from the source folder | 57 / 57, 91 / 91 |
| Same | 4.0.2, 5.3.0 | Legacy ZIP over the published 2.1.0 (Smart Clipping): install test without a restart, and settings across a restart (`tests/upgrade_settings_test.py`) | 19 / 19; 4 / 4 and 6 / 6 each |
| Same | 5.3.0 | The 2.1.0 extension (id `smart_clipping`) next to the `snaxis` one: the second refused, the first intact, then removed and the new one enabled | All as expected |
| GitHub Actions, Linux | 4.2.23, 5.2.4, 5.3.0 | Extension: validate and build, install and restart phases, headless tests against the installed extension | All pass, nothing skipped |
| GitHub Actions, Linux, Xvfb | 4.2.23, 5.2.4, 5.3.0 | UI test against the installed extension, with the grid and the KD-tree | 91 / 91 each, nothing skipped |
| GitHub Actions, Linux | 4.0.2, 4.2.23, 5.2.4 | Headless tests from the source folder, ZIP contents (49 checks), legacy ZIP install tests (fresh, over 1.3.2, over 2.1.0 keeping the settings) | All pass, nothing skipped |
| GitHub Actions, Linux, Xvfb | 4.0.2, 5.2.4 | UI test from the source folder, the grid and the KD-tree (release gate) | See the release run |

The UI test checks behavior and that the panels draw without errors; on the virtual display the screenshots come out black, so what the overlay looks like was checked on the real display only (screenshots in `assets/listing/`, Blender 5.3.0).

Not checked:

- macOS, and Linux on a real display (only the virtual display in CI)
- the extension installed from extensions.blender.org itself (only from the ZIP, as Install from Disk does), and updating it there
- a real HiDPI monitor (interface scale 2 stands in for it), several windows, Quad View, pen tablets
- how snapping feels to a person (`tests/manual_ui_setup.py` builds a scene for that)

## Distribution

From 2.1.0 the same sources ship in two ZIPs on GitHub Releases ([#38](https://github.com/marc2825/Snaxis/issues/38)): the legacy add-on (`bl_info`, module `smart_clipping`, Blender 4.0+) and the extension (`blender_manifest.toml`, module `bl_ext.<repository>.snaxis`, Blender 4.2+), which is also what goes to extensions.blender.org. [docs/EXTENSIONS.md](EXTENSIONS.md) has the listing text, the check against the platform's rules, and the submission steps.

**Name.** The add-on was called Smart Clipping up to 2.1.0 and is Snaxis from 2.1.1 (the repository moved from `Blender_SmartClip` to `Snaxis`; GitHub redirects the old links). Everything users see says Snaxis: `bl_info` and manifest names, the panel, messages, the docs, the logo, and the ZIPs (`snaxis-vX.Y.Z.zip`, `snaxis-vX.Y.Z-extension.zip`). For compatibility the internal identifiers did not change: the source folder and the legacy add-on's module `smart_clipping` (so that installing over Smart Clipping keeps the preferences and key, `tests/upgrade_settings_test.py`), the operator ids `view3d.smartclip_move` and `smartclip.*` (keymaps and scripts), the Scene properties `smartclip_*` (values saved in `.blend` files), the class and panel names `SMARTCLIP_*`, and the `SMARTCLIP_UI_*` test variables. The extension, not yet on the platform at the rename, took the id `snaxis`; the 2.1.0 extension from GitHub (id `smart_clipping`) is another copy to the check below.

What differs between the two at run time:

- **Module name**: the code uses `__package__` (preferences, translations) and never a literal module name.
- **`bl_info`**: kept for the legacy add-on; Blender ignores it in an extension and uses the manifest.
- **Updating in place**: the legacy add-on drops its own old submodules from `sys.modules` when it is re-enabled after an update (`__init__.py`, [#23](https://github.com/marc2825/Snaxis/issues/23)). Only a top-level module does this: Blender's extension manager unloads an extension's submodules itself, and the platform asks extensions to leave `sys` alone.
- **Both enabled**: they register the same operators, panels, Scene properties and keymap items. `register()` first looks for the panel of another copy (`bpy.types.SMARTCLIP_PT_panel` from another module) and raises `AlreadyEnabledError` before registering anything, so Blender leaves the second copy off with that message, never calls its `unregister()`, and the first copy keeps everything. Copies from two extension repositories are told apart the same way. Versions before 2.1.0 do not check.
- **Preferences and a changed key** are stored per module name, so they do not carry over between the two; scene settings (stored in the `.blend` file) do. The guide tells users how to switch.

### License and publishing conditions

The whole repository is GPL-3.0-or-later from 2.0.3 ([#20](https://github.com/marc2825/Snaxis/issues/20)). Releases up to 2.0.2 were published under MIT and stay so. Every Python file starts with `SPDX-FileCopyrightText` and `SPDX-License-Identifier: GPL-3.0-or-later`; add the same two lines to new files.

| Channel | License | Conditions |
|---|---|---|
| GitHub Releases (both ZIPs) | GPL-3.0-or-later; 2.0.2 and earlier MIT | Each ZIP carries the license text (`smart_clipping/LICENSE`, or `LICENSE` in the extension), and its sources keep their SPDX lines (`tests/package_test.py`, `tests/install_zip_test.py`). For Blender's own position on add-ons and the GPL, see its [license page](https://www.blender.org/about/license/) and [FAQ](https://www.blender.org/support/faq/). |
| [Blender Extensions](https://extensions.blender.org/) (from 2.1.0) | GPL-3.0-or-later, declared as `license = ["SPDX:GPL-3.0-or-later"]` | From the [terms of service](https://extensions.blender.org/terms-of-service/): add-ons must be wholly compliant with GPL v3 or later (1.1); images, SVG files, fonts and other assets bundled in the extension must be CC0 (1.2); copyright holders of bundled code are credited in the manifest (1.3); "Blender" is not part of the name (2.1), and no Blender logo appears in icons, thumbnails or previews (2.2); the code is reviewable Python only (3.5, 3.6); the extension is self-contained and loads no remote code (5.1). The [manifest](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html) needs `blender_version_min` of at least 4.2.0 and a tagline of up to 64 characters without end punctuation; see also [Licenses](https://docs.blender.org/manual/en/latest/advanced/extensions/licenses.html). |

The release ZIPs hold no images or fonts. `assets/` (logo, demo) is part of the repository under its license, and would have to be CC0 before any of it goes into an extension package.

## Versions

`bl_info["version"]` in `smart_clipping/__init__.py` is the single source of truth, and the project follows Semantic Versioning.

`python scripts/versioning.py` checks that these agree with it:

- `version` in `smart_clipping/blender_manifest.toml`
- the newest released entry in `CHANGELOG.md`
- `version` and `date-released` in `CITATION.cff`
- the version badge in `README.md` and `README.ja.md`

The badges are static (`img.shields.io/badge/...`): the ones that ask the GitHub API are often too slow for GitHub's image proxy and show up broken.

## Releasing

1. Bump `bl_info["version"]` and `version` in `smart_clipping/blender_manifest.toml`, move the changes under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md`, and update `CITATION.cff` and the README version badges. Run `python scripts/versioning.py`.
2. Merge to `main` with CI passing.
3. Optionally preview the package: `gh workflow run release-addon.yml -f version=X.Y.Z` runs the UI tests and builds both ZIPs, their checksums, and the release notes as a workflow artifact without publishing anything.
4. Tag the release commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The UI tests run first, on Blender 4.0.2 and 5.2.4 with both snap search backends, and against the installed extension on 4.2.23 and 5.2.4; the release is published only when they pass. If one fails for a reason that is not the add-on's (the virtual display), re-run the failed jobs.
5. Install the published ZIPs in Blender once to confirm they load.
6. Upload the published extension ZIP to extensions.blender.org as a new version ([docs/EXTENSIONS.md](EXTENSIONS.md)).

The changelog section becomes the body of the GitHub release, so keep it short and written for users. The release workflow fails if the tag does not match `bl_info`; otherwise it attaches `snaxis-vX.Y.Z.zip`, `snaxis-vX.Y.Z-extension.zip` and a `.sha256` for each.

`python scripts/package_addon.py` builds the same ZIPs locally in `dist/` (`--format legacy` or `extension` for one of them).
