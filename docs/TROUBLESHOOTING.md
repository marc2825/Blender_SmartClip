# Troubleshooting

## Addon does not appear in Blender

1. Confirm you installed the ZIP containing `src/__init__.py`.
2. Confirm Blender version is 4.0 or newer.
3. Open Blender console and look for import errors.

## Hotkey does not trigger

1. Verify addon is enabled.
2. Verify `Enable Smart Clipping` is on in N-panel.
3. Check keymap conflicts for `Shift + Alt + G`.

## No snap candidates found

1. Verify `Target Scope` selection is correct.
2. For `COLLECTION`, ensure `target_collection` is set.
3. Increase `Snap Threshold (px)`.
4. Check object visibility and mesh type.

## Performance issues

1. Reduce `Max Vertex Budget`.
2. Use `COLLECTION` scope with a curated target set.
3. Verify heavy objects are switching to bounds mode in console logs.
