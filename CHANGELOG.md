# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

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
