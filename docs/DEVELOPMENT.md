# Development

This guide is for working on the add-on itself. For installing and using it, see the [README](../README.en.md).

The add-on lives in `smart_clipping/`: `ops.py` holds the modal move operator, `detector.py` builds the snap tree and searches it, `drawing.py` draws the guides and HUD, and `prefs.py` and `utils.py` hold preferences and shared helpers. Tests are in `tests/` and release scripts in `scripts/`. The scripts need only a regular Python 3 interpreter; the add-on and tests run inside Blender.

## Tests

The headless tests cover the snap tree, candidate search, and the operator's `execute` without opening a window. CI runs them on every pull request.

```sh
blender --background --factory-startup --python tests/headless_test_runner.py
blender --background --factory-startup --python tests/headless_test_runner.py -- --case stress_100k
```

The case names are the keys of `CASES` in the runner. The runner exits with status 1 if any case fails.

The modal operator can only be exercised in a real window. `tests/ui_operator_test.py` starts Blender's UI, feeds it simulated input (`Shift+G`, mouse moves, constraint keys, clicks, `Esc`), and checks parented objects, navigating mid-move, constraints, the redo offset, multi-object moves, hard snap, and Edit Mode. It needs a display, and real mouse and keyboard input is ignored while it runs. Set `SMARTCLIP_UI_SCREENSHOT_DIR` to a folder to save screenshots of the overlays.

```sh
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

How snapping feels is still worth checking by hand after UI changes. `tests/manual_ui_setup.py` builds a scene with targets along each axis, a grid that exceeds the vertex budget, and a collection for Manual Collection scope, and prints what to try.

```sh
blender --python tests/manual_ui_setup.py
```

## CI

`.github/workflows/blender-ci.yml` runs on pushes to `main` and on pull requests. It checks version consistency, compiles every Python file, and runs the headless tests on Blender 4.0.2 (the oldest supported version), 4.2.23, and 5.2.4. CodeQL (`codeql.yml`) scans the Python code on the same events and once a month. Dependabot proposes GitHub Actions updates monthly.

## Versions

`bl_info["version"]` in `smart_clipping/__init__.py` is the single source of truth. `python scripts/versioning.py` checks that the newest released entry in `CHANGELOG.md`, `version` and `date-released` in `CITATION.cff`, and the title line of `README.md` agree with it. The project follows Semantic Versioning.

## Releasing

1. Bump `bl_info["version"]`, move the changes under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md`, and update `CITATION.cff` and the README title. The changelog section becomes the body of the GitHub release, so keep it short and written for users. Run `python scripts/versioning.py`.
2. Merge to `main` with CI passing. To preview the package, `gh workflow run release-addon.yml -f version=X.Y.Z` builds the ZIP, its checksum, and the release notes as a workflow artifact without publishing anything.
3. Tag the release commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The Release Addon workflow fails if the tag does not match `bl_info`; otherwise it publishes the release with `smart_clipping-vX.Y.Z.zip` and `.sha256` attached.
4. Install the published ZIP in Blender once to confirm it loads.

`python scripts/package_addon.py` builds the same ZIP locally in `dist/`.
