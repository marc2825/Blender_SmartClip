# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [2.0.3] - 2026-11-25

### Changed

- The license is now GPL-3.0-or-later instead of MIT, as Blender asks of add-ons. Releases up to 2.0.2 stay under MIT. (#20)
- The English README is now `README.md`, shown first on GitHub; the Japanese one moved to `README.ja.md`.

## [2.0.2] - 2026-11-24

### Fixed

- When an axis or plane constraint, Lock Location or an object constraint keeps the moving point off the snap point, the label says "Projected" and how far it is, instead of "Snapped". (#28)
- Confirming after changing Align Only or Snap To with `A` / `S` without moving is now one undo step. (#33)
- The snap point limit warning was missing when the limit was used up exactly. (#32)
- The label next to the snap point no longer goes under the sidebar, and the lines in the lower left stay above the Adjust Last Operation panel. (#31)

### Changed

- The add-on preferences show which of Blender's functions the shortcut is used instead of (Select Grouped / Select Similar for `Shift+G`). (#29)
- The release ZIP holds only the add-on's Python files and the license. (#36)
- Docs: what snapping lands on, performance with large meshes, a demo of the current UI, and SECURITY.md for reporting vulnerabilities privately. (#30, #34, #37)

## [2.0.1] - 2026-11-24

### Fixed

- Installing over 1.x and switching the add-on off and on without restarting Blender failed with an `ImportError`. (#23)
- The tooltip of the panel-header checkbox named `Shift+G` even when the shortcut key had been changed. (#25)
- The bug report form and SUPPORT.md used the 1.x setting names. (#25)

### Changed

- The release ZIP includes the license text (`smart_clipping/LICENSE`). (#24)

## [2.0.0] - 2026-11-24

The interface is redesigned. Right click now cancels a move, and a snap point within reach is snapped onto exactly without holding a button; **Snap Behavior → Gradual Pull** brings back the 1.x pull.

### Added

- Japanese interface. The panel, preferences, tooltips, status bar, viewport labels and messages follow **Preferences → Interface → Translation**.
- The status bar lists the keys during a move.
- During a move, `A` switches Align Only (Off → X → Y → Z) and `S` switches Snap To. The changes are kept when the move is confirmed and put back when it is cancelled.
- Viewport labels during a move: next to the snap point, what it is and whether the move is snapped to it; next to the moving point, the distance moved in the scene's units and the constraint. A dashed ring shows the snap distance. The lower left shows Snap To, Align Only, and notes when there is nothing to snap to (with the reason), when a constraint pauses Align Only, and when the snap point limit is reached.
- Snap point markers are hollow while pulled and filled once snapped, and their shape tells a vertex (circle), a bounding-box point (square) and a lined-up coordinate (diamond) apart.
- **Move with Guides** in the Object and Mesh > Transform menus. When it cannot run, its tooltip says why.
- The shortcut key for Object Mode and Edit Mode can be changed in the add-on preferences; **Reset Shortcut** sets `Shift+G` again.
- **Advanced → Snap Search** in the add-on preferences: an experimental **3D KD-tree** search next to the default **Screen-space Grid**. Both find the same candidates; the grid stays the default and was faster in almost every measured case (see `docs/DEVELOPMENT.md`). (#19)

### Changed

- Right click cancels a move, as in Blender's own transform. It used to hold the hard snap.
- New preference **Snap Behavior**: **Snap Exactly** (default) lands exactly on a snap point within the snap distance, and holding `Ctrl` moves freely. **Gradual Pull** is the 1.x behavior, and holding `Ctrl` snaps exactly.
- Align Only no longer falls back to snapping onto vertices when a constraint leaves none of its axes free to move; it pauses and says so.
- Renamed: Target Scope → **Snap To** (Self Only, Selected, All Visible, Manual Collection → Same Mesh, Selected Objects, Visible Objects, Collection), Axis Align → **Align Only**, Snap Threshold → **Snap Distance**, Max Vertex Budget → **Snap Point Limit**, Hard Snap Color → **Snap Color**, Smart Clipping Move → **Move with Guides**, Add Default Hotkeys / Clear Hotkeys → **Use Shortcut** and **Reset Shortcut**. Saved settings and Python identifiers are unchanged.
- Sidebar panel: the on/off checkbox moved into the panel header and greys the panel out; Move with Guides is at the top; Snap Distance is in the panel; Snap Behavior, Snap Point Limit and the colors are in the **Limits and Display** sub-panel. The Performance box is replaced by a warning shown only after a move that reached the snap point limit.
- The lower-left HUD line is replaced by the labels above, drawn on a background in the theme's tooltip colors. Lines and markers follow the interface scale, and constraint axes use the theme's axis colors.
- The add-on preferences are grouped into Snapping, Display, Shortcut and Advanced. The static list of modal keys is gone; the status bar shows them.
- What the last move collected is kept in memory instead of the scene property `smartclip_runtime_info`, which was removed, so nothing about a move is saved into `.blend` files.

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
