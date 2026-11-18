# Development

This guide is for working on the add-on itself. For installing and using it, see the [README](../README.en.md).

## Layout

| Path | Contents |
|---|---|
| `smart_clipping/ops.py` | The modal move operator: what moves, input handling, snapping |
| `smart_clipping/detector.py` | Collecting snap points and searching them in screen space |
| `smart_clipping/drawing.py` | Guide lines and HUD |
| `smart_clipping/prefs.py`, `utils.py` | Preferences and shared helpers |
| `smart_clipping/__init__.py` | `bl_info`, panel, keymaps, scene properties and their migration |
| `tests/` | Headless tests, the UI test, and a scene for manual checks |
| `scripts/` | Version check and release packaging (plain Python 3, no Blender needed) |

## Tests

### Headless

Covers the snap tree, candidate search, and the operator's `execute` without a window. CI runs it on every pull request.

```sh
blender --background --factory-startup --python tests/headless_test_runner.py
blender --background --factory-startup --python tests/headless_test_runner.py -- --case stress_100k
```

Case names are the keys of `CASES` in the runner. It exits with status 1 if any case fails.

### UI

The modal operator can only be exercised in a real window. `tests/ui_operator_test.py` feeds Blender simulated input (`Shift+G`, mouse moves, constraint keys, clicks, `Esc`) and checks parented objects, navigating mid-move, constraints, the redo offset, multi-object moves, hard snap, and Edit Mode.

```sh
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

- It needs a display, and real mouse and keyboard input is ignored while it runs.
- Set `SMARTCLIP_UI_SCREENSHOT_DIR` to a folder to save screenshots of the overlays.

### Manual

`.github/workflows/ui-tests.yml` runs the same test on a virtual display. It is started by hand (Actions > UI Tests) until it has proven stable on GitHub-hosted runners.

How snapping feels is still worth checking by hand after UI changes. `tests/manual_ui_setup.py` builds a scene with targets along each axis, a grid that exceeds the vertex budget, and a collection for Manual Collection scope, then prints what to try.

```sh
blender --python tests/manual_ui_setup.py
```

### Release ZIP

`tests/install_zip_test.py` installs a packaged ZIP the way a user would and checks that it enables, registers, keeps a cleared hotkey off, and disables cleanly. It refuses to run unless the user folders point somewhere disposable:

```sh
python scripts/package_addon.py --output-dir /tmp/dist
BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \
  blender --background --factory-startup --python tests/install_zip_test.py -- /tmp/dist/smart_clipping-vX.Y.Z.zip
```

### Benchmark

`tests/benchmark_snap.py` measures build time, search time, memory, and recall against a brute-force ground truth on synthetic point clouds (1k to 1M points, uniform and crowded, different scene scales). It reports numbers and does not pass or fail. `--impl` points it at another copy of the package, for example a release exported with `git archive vX.Y.Z smart_clipping`, to compare.

```sh
blender --background --factory-startup --python tests/benchmark_snap.py -- --quick
```

## CI

| Workflow | Runs on | What it does |
|---|---|---|
| `blender-ci.yml` | Pushes to `main`, pull requests | Version check, compile check, headless tests and a ZIP install test on Blender 4.0.2 (oldest supported), 4.2.23, and 5.2.4 |
| `codeql.yml` | Pushes, pull requests, monthly | CodeQL scan of the Python code |
| `release-addon.yml` | `v*.*.*` tags, manual runs | Packages, installs the ZIP into Blender 4.0.2, and publishes a release (see below) |
| `ui-tests.yml` | Manual | UI test on a virtual display |

Dependabot proposes GitHub Actions updates monthly.

The workflows get Blender through `.github/scripts/fetch-blender.sh`: the archive and blender.org checksum are cached per version, a cache miss downloads from download.blender.org with mirrors as fallback, and the archive is checked against the checksum on every run. Workflows default to read-only tokens; only the release job can write. The third-party release action is pinned to a commit.

`scripts/package_addon.py` writes files in a fixed order with fixed timestamps, so the same sources always produce the same ZIP and checksum.

## Versions

`bl_info["version"]` in `smart_clipping/__init__.py` is the single source of truth, and the project follows Semantic Versioning.

`python scripts/versioning.py` checks that these agree with it:

- the newest released entry in `CHANGELOG.md`
- `version` and `date-released` in `CITATION.cff`

The README shows the version through the release badge, so it needs no update.

## Releasing

1. Bump `bl_info["version"]`, move the changes under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md`, and update `CITATION.cff`. Run `python scripts/versioning.py`.
2. Merge to `main` with CI passing.
3. Optionally preview the package: `gh workflow run release-addon.yml -f version=X.Y.Z` builds the ZIP, checksum, and release notes as a workflow artifact without publishing anything.
4. Tag the release commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. Install the published ZIP in Blender once to confirm it loads.

The changelog section becomes the body of the GitHub release, so keep it short and written for users. The release workflow fails if the tag does not match `bl_info`; otherwise it attaches `smart_clipping-vX.Y.Z.zip` and `.sha256`.

`python scripts/package_addon.py` builds the same ZIP locally in `dist/`.
