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

1. Create a semantic version tag:
   - `vMAJOR.MINOR.PATCH`
2. Push the tag.
3. Verify GitHub Release workflow completed successfully.
4. Verify release artifact includes only:
   - `src/*.py`

## Post-Release

1. Smoke test installing addon from release ZIP.
2. Announce release notes and known limitations.
