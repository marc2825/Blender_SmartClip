# How it works and troubleshooting

This page adds detail to [Usage](../README.en.md#usage) in the README.

## How snap targets are built

Snap targets are built when a move starts and are not rebuilt during the move.

### Geometry

- Targets are vertices of the meshes in Target Scope. Objects that are not meshes, such as curves and text, are never targets.
- The geometry is taken after modifiers.
- Objects in Edit Mode use their edit mesh.

### What is being moved is excluded

What is being moved is never a snap target:

- Object Mode: the moving objects and their children
- Edit Mode: the moving vertices (other vertices of the same mesh remain targets if Target Scope includes that mesh)

So Self Only gives no targets in Object Mode. With Selected, only the active object moves and the other selected objects are the targets.

### Vertex budget

At most Max Vertex Budget vertices are registered, starting with the objects closest to what is being moved.

1. Objects that fit in the budget register all their vertices.
2. The object that crosses the limit is down-sampled to fit what is left.
3. Objects farther away register only their bounding-box corners and origin.

The Performance section of the panel shows the number of registered vertices and how many objects were down-sampled or reduced to their box.

## How candidates are chosen

A vertex is a candidate when it lies within Snap Threshold of the moving point projected on screen. The mouse cursor position is not used.

The moving point is:

- Object Mode: the active object's origin, or the average origin of the moving objects if the active object does not move
- Edit Mode: the center of the selected vertices

The search range in 3D matches half the screen at the depth of the moving point, so candidates are found the same way relative to the screen whether the scene is modeled in millimeters or kilometers.

## Moving

- Selecting both a parent and its child does not move the child twice.
- Axes locked with Lock Location do not move.
- Orbiting, panning, or zooming during a move does not make the selection jump.

## Troubleshooting

### The add-on does not appear in the list

- Check that you installed the ZIP from Releases (it contains `smart_clipping/__init__.py`).
- Check that Blender is 4.0 or later.
- After upgrading from 1.1.x or earlier, remove the old version (module `src`).

Errors are shown in the system console (on Windows, Window > Toggle System Console).

### Shift+G does not start a move

- Check that Enable Smart Clipping is on in the panel.
- Check that you are in Object Mode or mesh Edit Mode with an active object.
- If the assignment was removed, Add Default Hotkeys in the add-on preferences restores it.

### No candidates appear

- Check Target Scope and, for Manual Collection, the chosen collection.
- What is being moved is never a candidate (see [What is being moved is excluded](#what-is-being-moved-is-excluded)).
- Candidates are measured from the moving point. The cursor being over a vertex is not enough when the point is far from it; bring the point closer or raise Snap Threshold.

### Starting a move is slow

In large scenes, lower Max Vertex Budget or narrow the targets with Manual Collection.
