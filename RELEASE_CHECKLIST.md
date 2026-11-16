# Release Checklist

## Pre-Release

1. Run local tests:
   - `blender --background --factory-startup --python tests/headless_test_runner.py`
   - `blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py`
2. Run manual checks:
   - `blender --python tests/manual_ui_setup.py`
3. Bump `bl_info["version"]` (the single source of truth) and update `CHANGELOG.md`,
   `CITATION.cff` (`version`, `date-released`), and the README title to match.
   - `python scripts/versioning.py` must pass.
4. Confirm CI workflow is green on default branch.

## Release

1. Optional dry run: Actions > Release Addon > Run workflow with the version
   (`gh workflow run release-addon.yml -f version=X.Y.Z`); check the artifact's
   ZIP and RELEASE_NOTES.md.
2. Create and push a semantic version tag on the release commit:
   - `git tag vX.Y.Z && git push origin vX.Y.Z`
3. Verify the Release Addon workflow completed and the GitHub Release has
   `smart_clipping-vX.Y.Z.zip` and `.sha256` attached.
4. Verify the ZIP contains only `smart_clipping/*.py`.

## Post-Release

1. Smoke test installing addon from release ZIP.
2. Announce release notes and known limitations.
