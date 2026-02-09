# Testing Guide

## Automated (Headless)

Run all test cases:

```powershell
blender --background --factory-startup --python tests/headless_test_runner.py
```

Run one case:

```powershell
blender --background --factory-startup --python tests/headless_test_runner.py -- --case stress_100k
```

## Manual (Interactive UI)

Prepare a validation scene:

```powershell
blender --python tests/manual_ui_setup.py
```

Then validate:

1. N-panel settings
2. Soft snap guides
3. Ctrl hard snap behavior
4. HUD updates
5. Object mode transform application
6. Edit mode vertex transform application
