# Development

This guide is for working on the add-on itself. For installing and using it, see the [README](../README.en.md).

## Layout

| Path | Contents |
|---|---|
| `smart_clipping/ops.py` | The modal move operator: what moves, input handling, snapping |
| `smart_clipping/detector.py` | Building the snap tree and searching it |
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

How snapping feels is still worth checking by hand after UI changes. `tests/manual_ui_setup.py` builds a scene with targets along each axis, a grid that exceeds the vertex budget, and a collection for Manual Collection scope, then prints what to try.

```sh
blender --python tests/manual_ui_setup.py
```

## CI

| Workflow | Runs on | What it does |
|---|---|---|
| `blender-ci.yml` | Pushes to `main`, pull requests | Version check, compile check, headless tests on Blender 4.0.2 (oldest supported), 4.2.23, and 5.2.4 |
| `codeql.yml` | Pushes, pull requests, monthly | CodeQL scan of the Python code |
| `release-addon.yml` | `v*.*.*` tags, manual runs | Packages and publishes a release (see below) |

Dependabot proposes GitHub Actions updates monthly.

`blender-ci.yml` caches the Blender archive per version. On a cache miss it downloads from download.blender.org, falls back to mirrors, and checks the archive against the checksum published on blender.org.

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
