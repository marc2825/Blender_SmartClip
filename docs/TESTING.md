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
3. Right-click hard snap behavior (hold right mouse button during modal)
4. Axis Align mode (X / Y / Z toggles in N-Panel)
5. Axis / plane constraint during modal (X / Y / Z, Shift+X / Y / Z)
6. HUD updates
7. Object mode transform application
8. Edit mode vertex transform application
