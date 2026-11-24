# Development

This guide is for working on the add-on itself. For installing and using it, see the [README](../README.en.md).

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
| `smart_clipping/__init__.py` | `bl_info`, panels, menu entries, scene properties and their migration |
| `tests/` | Headless tests, the UI test, and a scene for manual checks |
| `scripts/` | Version check and release packaging (plain Python 3, no Blender needed) |

## Tests

### Headless

Covers snap point collection, candidate search with both backends (they must return identical candidate lists), the operator's `execute` without a window, the move's decisions and words, and the translation (see [Translation](#translation)). CI runs it on every pull request.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/headless_test_runner.py
blender --background --factory-startup --python-exit-code 1 --python tests/headless_test_runner.py -- --case stress_100k
```

Case names are the keys of `CASES` in the runner. It exits with status 1 if any case fails.

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
- Set `SMARTCLIP_UI_SCALE=2` to run them at a larger interface scale (as on HiDPI displays), and `SMARTCLIP_UI_THEME=light` to use Blender's light theme; look at the screenshots for these.
- Some virtual X11 displays report `Ctrl` as released right after a simulated press. The `Ctrl` check then prints `[SKIP]` with the events the move received, instead of failing ([#26](https://github.com/marc2825/Blender_SmartClip/issues/26)).

### On a virtual display

`.github/workflows/ui-tests.yml` runs the same test on a virtual display (Xvfb, software OpenGL, `SMARTCLIP_UI_STEP=0.8`). It runs before every release (see [Releasing](#releasing)) and can be started by hand (Actions > UI Tests, with JSON lists of Blender versions and snap search backends). It does not run on pull requests, where a GUI job on software OpenGL would slow every change down. Each run's summary page lists the result and every failed or skipped check. Screenshots taken there come out black even when the checks pass.

### Manual

How snapping feels is still worth checking by hand after UI changes. `tests/manual_ui_setup.py` builds a scene with targets along each axis, a grid that exceeds the vertex budget, and a collection for Manual Collection scope, then prints what to try.

```sh
blender --python tests/manual_ui_setup.py
```

### Translation

`smart_clipping/i18n.py` holds the Japanese messages, keyed by the English text used in the code. Blender looks names, tooltips and enum items up there by itself; text the add-on builds (viewport labels, format strings, reports) goes through `i18n.iface` / `tip` / `rpt`.

Registered messages apply to all of Blender, so a word Blender already translates (Snap To, Collection, Confirm, Axis, Off, ...) is not registered: the add-on uses Blender's own translation. The headless case `translations` checks that no message gives one of Blender's a different translation, that format placeholders match, and that every name and tooltip the add-on registers comes out in Japanese. When you add or change a label, add its message there. A long Japanese label is cut off in the sidebar's label column, so check new labels at the default sidebar width.

### Release ZIP

`tests/install_zip_test.py` installs a packaged ZIP the way a user would and checks that it enables, carries the license text, registers, keeps a cleared hotkey off, keeps a changed key through Use Shortcut off and on, resets it with Reset Shortcut, disables cleanly, and can be removed. It refuses to run unless the user folders point somewhere disposable:

```sh
python scripts/package_addon.py --output-dir /tmp/dist
BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \
  blender --background --factory-startup --python tests/install_zip_test.py -- /tmp/dist/smart_clipping-vX.Y.Z.zip
```

With `--upgrade-from OLD.zip` before the ZIP, it first installs and enables `OLD.zip`, then installs the new ZIP over it and switches the add-on off and on without a restart, as a user updating from the Preferences does. CI runs this from 1.3.2 ([#23](https://github.com/marc2825/Blender_SmartClip/issues/23)).

What goes into the ZIP is an allowlist in `scripts/package_addon.py`: the files of `smart_clipping/` that git tracks and whose suffix is in `ALLOWED_SUFFIXES` (`.py`), plus `LICENSE`. Untracked files (caches, local notes, settings) never go in, and a tracked file of another kind stops the build until the list covers it. `tests/package_test.py` (plain Python, no Blender) checks the allowlist, the exact contents, the single top folder, the fixed metadata, that two builds are byte-identical, and the checksum:

```sh
python tests/package_test.py
```

### Benchmark

`tests/benchmark_snap.py` runs every search backend on the same synthetic point clouds (10k to 500k points, uniform and crowded, different scene scales) and reports index build time, query time (median, p95), the cost of the first query after a view change, memory, the share of candidates missed against a brute-force ground truth, and whether the backends return identical lists. It prints a Markdown table at the end and does not pass or fail. `--sizes` picks the point counts, and `--impl` points it at another copy of the package, for example a release exported with `git archive vX.Y.Z smart_clipping`, to compare.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/benchmark_snap.py -- --quick
```

#### Grid vs. KD-tree

Measured for [#19](https://github.com/marc2825/Blender_SmartClip/issues/19) with Blender 5.3.0 on Windows 11 (Intel Core Ultra 9 285K), default options: 200 timed queries, 12 view changes, and 40 queries with full candidate lists per case. The clouds fill a 10-unit cube ("crowded": 95% of the points in a blob with σ = 0.05) and are seen in perspective from about 23 units away at 1600 × 900 px; Snap Threshold is 30 px. Times in milliseconds.

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

Measured for [#30](https://github.com/marc2825/Blender_SmartClip/issues/30) on a GitHub-hosted runner (Linux, 4 vCPUs, 16 GB). The memory column is the growth of the resident set during the collection, over what the scene already used ("scene").

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
| `blender-ci.yml` | Pushes to `main`, pull requests | Version check, release ZIP contents check, compile check, headless tests and ZIP install tests (fresh, and over 1.3.2) on Blender 4.0.2 (oldest supported), 4.2.23, and 5.2.4 |
| `codeql.yml` | Pushes, pull requests, monthly | CodeQL scan of the Python code |
| `release-addon.yml` | `v*.*.*` tags, manual runs | UI tests as a gate, then packages, installs the ZIP into Blender 4.0.2, and publishes a release (see below) |
| `ui-tests.yml` | Manual, and called by `release-addon.yml` | UI test on a virtual display |
| `benchmark.yml` | Manual | Snap point collection on large evaluated meshes (see [Large meshes](#large-meshes)) |

Dependabot proposes GitHub Actions updates monthly.

The workflows get Blender through `.github/scripts/fetch-blender.sh`: the archive and blender.org checksum are cached per version, a cache miss downloads from download.blender.org with mirrors as fallback, and the archive is checked against the checksum on every run. Workflows default to read-only tokens; only the release job can write. The third-party release action is pinned to a commit.

`scripts/package_addon.py` writes files in a fixed order with fixed timestamps, so the same sources always produce the same ZIP and checksum.

## Distribution

The add-on is distributed as a legacy add-on ZIP (`bl_info`, module `smart_clipping`) from GitHub Releases, and supports Blender 4.0 and later. The ZIP contains `smart_clipping/LICENSE`.

There is no `blender_manifest.toml` yet. With one, Blender 4.2+ installs the add-on as an extension under `bl_ext.<repository>.smart_clipping`: its preferences start from their defaults, an installed legacy copy can register alongside it, and 4.0 / 4.1 need the legacy ZIP anyway. The Blender Extensions platform also requires a GPL-compatible license (GPL-3.0-or-later for the whole package), which is open in [#20](https://github.com/marc2825/Blender_SmartClip/issues/20). The extension format will be revisited together with that decision.

## Versions

`bl_info["version"]` in `smart_clipping/__init__.py` is the single source of truth, and the project follows Semantic Versioning.

`python scripts/versioning.py` checks that these agree with it:

- the newest released entry in `CHANGELOG.md`
- `version` and `date-released` in `CITATION.cff`
- the version badge in `README.md` and `README.en.md`

The badges are static (`img.shields.io/badge/...`): the ones that ask the GitHub API are often too slow for GitHub's image proxy and show up broken.

## Releasing

1. Bump `bl_info["version"]`, move the changes under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md`, and update `CITATION.cff` and the README version badges. Run `python scripts/versioning.py`.
2. Merge to `main` with CI passing.
3. Optionally preview the package: `gh workflow run release-addon.yml -f version=X.Y.Z` runs the UI tests and builds the ZIP, checksum, and release notes as a workflow artifact without publishing anything.
4. Tag the release commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The UI tests run first, on Blender 4.0.2 and 5.2.4 with both snap search backends; the release is published only when they pass. If one fails for a reason that is not the add-on's (the virtual display), re-run the failed jobs.
5. Install the published ZIP in Blender once to confirm it loads.

The changelog section becomes the body of the GitHub release, so keep it short and written for users. The release workflow fails if the tag does not match `bl_info`; otherwise it attaches `smart_clipping-vX.Y.Z.zip` and `.sha256`.

`python scripts/package_addon.py` builds the same ZIP locally in `dist/`.
