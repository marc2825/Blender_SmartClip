# How it works and troubleshooting

This page adds detail to [Usage](../README.en.md#usage) in the README.

## How snap targets are built

When a move starts, snap targets are built from the vertices of the meshes in Target Scope and are not rebuilt during the move. The geometry is taken after modifiers, except for objects in Edit Mode, which use their edit mesh. Objects that are not meshes, such as curves and text, are never snap targets.

What is being moved is left out of the targets: in Object Mode the selected objects and their children, in Edit Mode the vertices being moved. As a result, Self Only gives no targets in Object Mode. Selected gives none in Object Mode either, because every selected object moves.

At most Max Vertex Budget vertices are registered, starting with the objects closest to what is being moved. The object that crosses the limit is down-sampled to fit the remaining budget, and objects farther away contribute only their bounding-box corners and origin. The Performance section of the panel shows how many vertices were registered and how many objects were down-sampled or reduced to their box.

## How candidates are chosen

A vertex becomes a candidate when it is within Snap Threshold of the moving point projected on screen, not of the mouse cursor. The moving point is the active object's origin in Object Mode and the center of the selected vertices in Edit Mode. If the active object does not move, the average origin of the moving objects is used.

The search range in 3D follows the view: it matches half the screen at the depth of the moving point. Candidates are therefore found the same way relative to the screen whether the scene is modeled in millimeters or kilometers.

## Moving

Selecting both a parent and its child does not move the child twice. Axes locked with Lock Location do not move. Orbiting, panning, or zooming during a move does not make the selection jump.

## Troubleshooting

If the add-on does not appear in the list, check that you installed the ZIP from Releases (it contains `smart_clipping/__init__.py`) and that Blender is 4.0 or later. After upgrading from 1.1.x or earlier, remove the old version (module `src`). Errors are shown in the system console (on Windows, Window > Toggle System Console).

If `Shift+G` does not start a move, check that Enable Smart Clipping is on in the panel and that you are in Object Mode or mesh Edit Mode with an active object. If the assignment was removed, Add Default Hotkeys in the add-on preferences restores it.

If no candidates appear, check Target Scope and, for Manual Collection, the chosen collection. What is being moved is never a candidate (see [How snap targets are built](#how-snap-targets-are-built)). Candidates are measured from the moving point, so the cursor being over a vertex is not enough when the point itself is far from it; bring the point closer or raise Snap Threshold.

If starting a move takes long in a large scene, lower Max Vertex Budget or narrow the targets with Manual Collection.
