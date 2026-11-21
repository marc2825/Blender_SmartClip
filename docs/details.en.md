# Guide

This page expands on [Usage](../README.en.md#usage) in the README.

## Controls

| Input | Action |
|---|---|
| `Shift+G` / **Smart Clipping Move** in the panel | Start a move |
| Left click / `Enter` | Confirm |
| `Esc` | Cancel and restore the original position |
| Hold right mouse button | Sit exactly on the candidate (hard snap) |
| `X` / `Y` / `Z` | Move along that axis only |
| `Shift+X` / `Shift+Y` / `Shift+Z` | Move in the plane excluding that axis |
| Middle mouse / wheel | Orbit, pan, or zoom without ending the move |
| Numpad / `Home` | Switch views, zoom, or frame all without ending the move |

Mouse and numpad input works mid-move only where the keymap binds it to view navigation; shortcuts that change anything else, such as `Ctrl+Numpad+` (Select More) or `Alt+Wheel` (change frame), do not fire.

Press the same key again to release an axis or plane constraint. Constraints use the global axes; a constrained axis is drawn in red (X), green (Y), or blue (Z), and snapped positions stay on the constrained axis or plane.

Close to a candidate, the selection is pulled toward it, more strongly the closer it gets (soft snap). The guide lines and the lower-left HUD show which object you are heading for and the distance.

## What moves and what snaps

| Mode | What moves | What snaps |
|---|---|---|
| Object Mode | All selected objects (only the active one when Target Scope is Selected) | The active object's origin |
| Edit Mode | Selected vertices of the meshes being edited | The center of the selected vertices |

After confirming, correct the move numerically with **Offset** in the **Adjust Last Operation** panel.

## Target Scope

| Target Scope | Snap targets |
|---|---|
| Self Only | The meshes being edited (all of them with multi-object editing). Use it in Edit Mode to snap to other vertices of the same mesh |
| Selected | Selected meshes: in Object Mode the ones other than the active object, in Edit Mode including the rest of the meshes being edited |
| All Visible (default) | Every visible mesh |
| Manual Collection | Visible meshes in the chosen collection and its child collections |

## Axis Align

Turning on X, Y, or Z under **Axis Align** in the panel aligns to that axis's coordinate values instead of vertex positions. With Z on, for example, a vertex at z = 1 offers z = 1 as a candidate while X and Y stay where they are. A dashed line leads to the vertex the value comes from.

- With several axes on, only one axis is aligned at a time.
- A value is a candidate only if the aligned position is within Snap Threshold on screen.
- An axis nearly parallel to the view direction, such as Z in top view, is skipped.

## Preferences

Set in **Preferences → Add-ons → Smart Clipping**.

| Setting | Default | Meaning |
|---|---|---|
| Snap Threshold (px) | 30 | Screen distance within which candidates are found |
| Max Vertex Budget | 50,000 | Maximum number of vertices registered as snap targets ([Vertex budget](#vertex-budget)) |
| Guide Color / Hard Snap Color | Magenta / cyan | Colors of the guides and HUD (the second during hard snap) |

**Add Default Hotkeys** and **Clear Hotkeys** on the same page restore or remove the `Shift+G` assignment. A removed assignment is saved in the preferences and stays removed after restarting Blender.

**Enable Smart Clipping** in the panel is a per-scene setting; in scenes where it is off, `Shift+G` does Blender's default. The assignment itself is shared by all scenes unless you remove it.

## How snap targets are built

Snap targets are built when a move starts and are not rebuilt during the move.

### Geometry

- Targets are vertices of the meshes in Target Scope. Objects that are not meshes, such as curves and text, are never targets.
- The geometry is taken after modifiers.
- Objects in Edit Mode, and objects sharing their mesh, use the edit mesh without modifiers: leaving out the moving vertices needs vertex indices, which do not carry over to modified geometry.

### What is being moved is excluded

What is being moved is never a snap target:

- Object Mode: the moving objects and their children
- Edit Mode: the moving vertices (other vertices of the same mesh remain targets if Target Scope includes that mesh), also on objects that share the mesh

Moving vertices are not counted, so they do not use up the vertex budget.

So Self Only gives no targets in Object Mode. With Selected, only the active object moves and the other selected objects are the targets.

### Vertex budget

Max Vertex Budget caps the total number of snap points. Objects in view come first, and among them the ones closest to what is being moved.

1. Objects that fit in the budget register all their vertices.
2. The object that crosses the limit registers its bounding-box corners and origin (9 points) plus a random sample of its vertices.
3. Objects farther away register only their corners and origin; up to a tenth of the budget is kept for them.
4. Objects after the budget is used up are left out.

The Performance section of the panel shows the number of registered points and how many objects were down-sampled, reduced to their box, or left out.

## How candidates are chosen

A vertex is a candidate when it lies within Snap Threshold of the moving point projected on screen. The mouse cursor position is not used. Every vertex that qualifies is checked, so crowded geometry does not hide candidates.

Among several candidates, the one closest on screen wins; candidates overlapping within 2 pixels on screen are decided by which is closer to the moving point in 3D. The choice does not depend on the scene scale or zoom.

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
