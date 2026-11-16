# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [2.0.0] - 2026-11-16

### ⚠ Breaking changes / upgrading from 1.x
- **The add-on module was renamed from `src` to `smart_clipping`** and the release ZIP is now `smart_clipping-vX.Y.Z.zip`. Disable and remove the old add-on (module `src`) before installing; enabling both makes their registrations collide. Add-on preferences (snap threshold, vertex budget, colors) start from their defaults.
- Scene properties got the add-on prefix: `target_scope` → `smartclip_target_scope`, `target_collection` → `smartclip_target_collection`. Values saved by 1.x are migrated automatically when a file is opened (Blender 4.x and 5.x storage).
- Axis Align only suggests values whose aligned position is within `Snap Threshold (px)` on screen (it used to pull toward values anywhere within a large world-space window).

### Added
- Object Mode moves **all selected objects** (a selected child is not moved twice, `lock_location` is respected); Edit Mode moves the selected vertices of **every mesh in Edit Mode**.
- Snap targets use the **evaluated geometry** (modifiers applied), so you snap to what you see.
- **Adjust Last Operation**: the final move is stored as `Offset` and can be edited in the redo panel (F9); the operator can also be called from scripts with `offset=(x, y, z)`.
- `scripts/versioning.py`: `bl_info["version"]` is the single source of truth; CI checks that `CHANGELOG.md`, `CITATION.cff`, and the README title agree, `scripts/package_addon.py` refuses a version that differs from `bl_info`, and the release body is taken from this changelog. (#7)
- `tests/ui_operator_test.py`: end-to-end test of the modal operator with simulated input events.
- Headless tests for partial budget fill, recursive collections, Edit Mode sync, parent-space conversion, constraints, Axis Align gating, multi-object moves, evaluated targets, redo/execute, and property migration.

### Fixed
- Object Mode: moving a parented object mixed world and parent space (`location` received world coordinates), so it drifted away from the cursor, broke axis constraints, and hard-snapped next to the target instead of onto it. Movement is now converted into the parent space. (#8)
- Orbiting / panning / zooming the view during a move no longer makes the selection jump.
- Snapping (soft, hard, Axis Align) no longer breaks an active axis / plane constraint: the result is projected onto the constraint, and Axis Align only considers the constrained axes.
- Edit Mode: geometry edited since entering Edit Mode was ignored (the snap tree read stale mesh data, and moving-vertex indices could mismatch). The edit mesh is now flushed before building the tree.
- The operator now implements `cancel()` and catches internal errors, restoring the selection and removing draw handlers instead of leaving them behind; leftover handlers are also removed on addon unregister. (#8)
- Axis Align ignored `Snap Threshold (px)` and searched even along the view direction. The axis parallel to the view is now skipped and the nearest value is found even in dense data. (#8)
- `COLLECTION` scope now includes objects in nested child collections. (#8)
- Plane constraints now draw guide lines for both axes. (#8)
- The redo panel showed nothing usable (the operator had no `execute`).
- `CITATION.cff` version / release date synced. (#7)

### Changed
- Vertex budget: the object crossing the limit is down-sampled into the remaining budget instead of collapsing to its bounding box; later objects still use bounding-box corners. Moving objects are no longer inserted (they were always excluded) and so no longer consume budget. (#8)
- Per-query cost is bounded and scale-aware: the KD-Tree search radius covers half the viewport at the depth of the moving point (it was a fixed 5–500 world units), and at most 512 nearest non-excluded hits are projected to screen. (#8)
- The addon no longer disables Blender's built-in `Shift+G` items: its own items are placed at the head of the keymaps and simply take precedence while Smart Clipping is enabled. Hotkey state is re-synced when a file is loaded.
- Guide lines use the `POLYLINE_UNIFORM_COLOR` shader so their width is honoured on Metal / Vulkan; long dashed lines are capped at 200 dashes; the HUD scales with the UI scale.
- The operator's `poll` no longer requires a 3D Viewport, so `execute` (redo, scripts) works from any context; the interactive move reports a warning when started outside a 3D Viewport.

### Maintenance
- CI runs the headless tests on Blender 4.0.2, 4.2 LTS, and 5.2 LTS.
- `actions/checkout` v4 → v7, `github/codeql-action` v3 → v4, `actions/upload-artifact` v4 → v7 (#5), `softprops/action-gh-release` v2 → v3 (#6).
- Release workflow: release name, body from the changelog, dry-run artifacts include the notes.

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
