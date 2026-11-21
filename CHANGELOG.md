# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added

- **Advanced Settings → Snap Search** in the add-on preferences: an experimental **3D KD-tree** search next to the default **Screen-space Grid**. Both find the same candidates; the grid stays the default and was faster in almost every measured case (see `docs/DEVELOPMENT.md`). (#19)

### Changed

- The panel's Performance line reads `Snap points: N` instead of `Vertices in tree: N`, and ends with `[KD-tree]` when the KD-tree search is used.

## [1.3.2] - 2026-11-21

### Fixed

- During a move, navigation keys and mouse input are passed to Blender only when the keymap binds them to view navigation. In 1.3.1, `Ctrl+Numpad+/-` could change the selection in Edit Mode and `Ctrl+Numpad0` could set the camera; `Alt+Wheel` could change the current frame in earlier versions as well.

## [1.3.1] - 2026-11-20

### Fixed

- Target Scope: in Edit Mode, Selected now includes the unselected vertices of the active mesh, and Self Only includes every mesh being edited, not only the active one. Manual Collection no longer snaps to hidden objects.
- Confirming a move before moving the mouse no longer adds an undo step.
- Numpad views, zoom and `Home` work during a move.
- Vertices with invalid (NaN or infinite) coordinates are ignored.
- Calling the operator from a script with a linked (non-editable) active object no longer moves it or fails.

## [1.3.0] - 2026-11-18

### Fixed

- Snap candidates could be missed in crowded scenes, and which one won depended on the scene scale. Every candidate is now checked, and the one closest on screen wins (overlapping ones are decided by 3D distance).
- Clear Hotkeys came back after toggling Enable Smart Clipping or opening a file. It now stays cleared, also across restarts, and Enable Smart Clipping only affects its own scene.
- Snap point markers were not drawn on Blender 4.0.
- In Edit Mode, the vertices being moved used up Max Vertex Budget, also on objects sharing the mesh.
- Adjust Last Operation could put parented objects in the wrong place right after an undo.
- Disabling the add-on during a move left the selection half-moved.
- Down-sampling a large mesh could keep only one row of a grid.

### Changed

- Much faster on large scenes: about 0.5 ms instead of 360 ms per mouse move with 100,000 points, and 0.03 s instead of 1.6 s to start moving next to a 1M-vertex mesh.
- Max Vertex Budget now counts every snap point, including bounding-box stand-ins. Objects in view come first; objects beyond the budget are left out and shown in the panel.

## [1.2.1] - 2026-11-18

### Fixed

- In Object Mode, Target Scope = Selected found no snap targets in 1.2.0 because every selected object moved. Now only the active object moves and snaps to the other selected objects, as in 1.1.x.

### Changed

- Documentation reorganized: English README in `README.en.md`, behavior details and troubleshooting in `docs/details.md`, developer guide in `docs/DEVELOPMENT.md`.

### Maintenance

- CI caches the Blender download and falls back to mirrors, verified against blender.org checksums.

## [1.2.0] - 2026-11-16

### Upgrading from 1.1.x

- The add-on module is now `smart_clipping` (was `src`) and the download is `smart_clipping-v1.2.0.zip`. Remove the old add-on before installing. Add-on preferences reset to defaults; scene settings saved in `.blend` files carry over automatically.
- Scene properties for scripts are renamed: `target_scope` / `target_collection` → `smartclip_target_scope` / `smartclip_target_collection`.

### Added

- Moves all selected objects (Object Mode) and the selected vertices of every mesh in Edit Mode.
- Snaps to geometry with modifiers applied.
- The final move can be adjusted as `Offset` in the Adjust Last Operation panel.

### Fixed

- Parented objects drifted from the cursor and snapped to the wrong place. (#8)
- The selection jumped after orbiting, panning or zooming mid-move.
- Snapping could break an axis / plane constraint.
- Edit Mode ignored edits made since entering Edit Mode.
- Axis Align ignored the snap threshold and pulled from far away. (#8)
- An aborted move could leave guides on screen; `COLLECTION` scope skipped child collections; plane constraints showed no guide lines. (#8)

### Changed

- The object that exceeds the vertex budget is down-sampled instead of reduced to its bounding box. (#8)
- The search radius follows the view scale and per-move cost is capped. (#8)
- Blender's built-in `Shift+G` is no longer disabled; Smart Clipping's hotkey just takes precedence while it is enabled.
- Guide lines keep their width on Metal / Vulkan.

### Maintenance

- CI on Blender 4.0 / 4.2 LTS / 5.2 LTS, GitHub Actions updated (#5, #6), version files checked against `bl_info` (#7).

## [1.1.0] - 2026-02-26

### Added

- **Axis Align mode**: X / Y / Z toggles in the N-Panel snap the moving object/vertex to the corresponding axis coordinate of nearby reference vertices (instead of snapping to exact vertex positions).
- **Axis / plane constraint during modal**: Press `X` / `Y` / `Z` to lock movement to a single axis, or `Shift+X` / `Shift+Y` / `Shift+Z` to lock to a plane — same behaviour as Blender's native `G` → `X`/`Y`/`Z`. Toggle the same key again to return to free movement. Works together with Soft Snap, Hard Snap, and Axis Align.
- Colored constraint axis line in the viewport (red=X, green=Y, blue=Z) while a constraint is active.
- HUD now shows the active constraint (`Axis: X` / `Plane: YZ`) in addition to snap info.

### Changed

- **Hard Snap changed from Ctrl to right-click hold**: Hold right mouse button during modal to hard-snap to the nearest candidate. ESC is now the sole cancel key.
- Snap candidate search now uses the projected position of the moving vertex/object (not the raw mouse cursor) as the screen-space filter reference, fixing offset snap detection when the cursor is not aligned with the geometry.

### Fixed

- In Edit Mode, only the selected (moving) vertices are excluded from snap candidates; unselected vertices of the same mesh remain as valid snap targets.
- Axis Align guide line now draws correctly from the current position to the alignment point (solid line), with a dashed line continuing to the reference vertex.
- Headless test `case_scene_properties_registered` used wrong property names (`src_enabled`, `src_runtime_info`); corrected to `smartclip_enabled`, `smartclip_runtime_info`, and added checks for `smartclip_align_x/y/z`.

## [1.0.0] - 2026-02-08

### Added

- Initial Smart Clipping addon implementation.
- Modal move operator with static KD-tree snapshot.
- Vertex budget fallback to bounds mode for large scenes.
- N-panel controls and addon preferences.
- Headless and manual test scripts.
- GitHub Actions for CI and release packaging.
