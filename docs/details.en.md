# Guide

This page expands on [Installation and usage](../README.md#installation-and-usage) and [Keys during a move](../README.md#keys-during-a-move) in the README.

## Extension or legacy add-on

From 2.1.0 every release has two ZIPs with the same add-on inside:

| ZIP | Blender | Installs as |
|---|---|---|
| `snaxis-vX.Y.Z-extension.zip` | 4.2 or later | An extension (module `bl_ext.user_default.snaxis` when installed from disk) |
| `snaxis-vX.Y.Z.zip` | 4.0 or later | A legacy add-on (module `smart_clipping`) |

On Blender 4.2 or later, use the extension. Both are installed with **Preferences → Add-ons → Install from Disk** (on 4.2 or later you can also drag the ZIP into Blender); do not unzip them.

**One at a time.** Both register the same tool, panel, scene settings and shortcut, so turn one off (or remove it) before enabling the other; with both on, the second replaces the first's registration, and turning either off leaves the other broken until Blender restarts. The 2.1.0 extension (still named Smart Clipping, id `smart_clipping`) is such another copy: remove it before installing the `snaxis` extension.

**Moving from the legacy add-on to the extension:**

1. Note your add-on preferences (Snap Behavior, Snap Distance, Snap Point Limit, the colors, Snap Search) and a changed shortcut key. They do not carry over: Blender keeps them per add-on, and the extension starts from the defaults.
2. In **Preferences → Add-ons**, turn the legacy add-on off and remove it (listed as Snaxis, or Smart Clipping up to 2.1.0).
3. Install the extension ZIP, enable it, and set the preferences and key again.

Snap To, its collection and Align Only are saved in each `.blend` file, so they carry over. Moving back works the same way.

## Controls

| Input | Action |
|---|---|
| `Shift+F` / **Move with Guides** in the panel or in the Object / Mesh > Transform menu | Start a move |
| Left click / `Enter` | Confirm |
| Right click / `Esc` | Cancel and restore the original position |
| Hold `Ctrl` | Move freely without snapping (with Gradual Pull: snap exactly) |
| `X` / `Y` / `Z` | Move along that axis only |
| `Shift+X` / `Shift+Y` / `Shift+Z` | Move in the plane excluding that axis |
| `A` | Switch Align Only: Off → X → Y → Z → Off |
| `S` | Switch Snap To to the next one that can have something to snap to |
| `PageUp` / `PageDown`, or `Alt` + wheel | Make the snap distance larger / smaller (by a quarter each step, 1 to 1000 px) |
| Middle mouse / wheel | Orbit, pan, or zoom without ending the move |
| Numpad / `Home` | Switch views, zoom, or frame all without ending the move |

The status bar lists these keys during a move.

Mouse and numpad input works mid-move only where the keymap binds it to view navigation; shortcuts that change anything else, such as `Ctrl+Numpad+` (Select More), do not fire. `Alt` + wheel changes the snap distance instead of the frame; the wheel alone still zooms.

Press the same key again to release an axis or plane constraint. Constraints use the global axes; a constrained axis is drawn in the theme's axis color, and snapped positions stay on the constrained axis or plane. A vertex off the axis or plane is projected onto it: the move goes to the nearest point on it and the label says "Projected".

Settings switched with `A`, `S` and the snap distance keys are kept when you confirm and put back when you cancel. Confirming without moving keeps them too, as one operation, like changing them in the panel (in Object Mode, Undo with `Ctrl+Z` puts them back). Confirming when nothing changed records nothing.

## What the viewport shows during a move

| Where | What |
|---|---|
| Next to the snap point | Whether the move is snapped to it and what it is, for example "Snapped Cube vertex". With Gradual Pull: "Pulling" and the remaining distance. When a constraint or Lock Location keeps the moving point off it: "Projected" and the distance to it |
| The snap point's marker | Hollow while the point is only pulled toward it or projected, filled once snapped. Its shape tells what it is: a circle for a vertex, a square for a bounding-box point (see [Snap point limit](#snap-point-limit)), a diamond for a lined-up coordinate |
| Next to the moving point | How far it moved, in the scene's units (Scene > Units: the unit system, Unit Scale and Length), and along which axis or plane |
| Dashed ring around the moving point | The snap distance: vertices inside it are within reach. Hidden while snapping is off |
| Lower left of the viewport | The current Snap To and Align Only (and the snap distance once changed), and notes: nothing to snap to (with the reason and what to do), Align Only paused by a constraint, snap point limit reached |

Colors come from the theme and the Guide / Snap colors; sizes follow the interface scale.

## Snap Behavior

| Snap Behavior | When a snap point is within the snap distance | While `Ctrl` is held |
|---|---|---|
| Snap Exactly (default) | The moving point lands exactly on it | No snapping |
| Gradual Pull | The moving point is pulled toward it, more strongly the closer it gets (the behavior up to 1.3) | Lands exactly on it |

## What moves and what snaps

| Mode | What moves | What snaps |
|---|---|---|
| Object Mode | All selected objects (only the active one when Snap To is Selected Objects) | The active object's origin |
| Edit Mode | Selected vertices of the meshes being edited | The center of the selected vertices |

After confirming, correct the move numerically with **Offset** in the **Adjust Last Operation** panel.

## Snap To

| Snap To | Snap targets |
|---|---|
| Same Mesh | The meshes being edited (all of them with multi-object editing). Use it in Edit Mode to snap to other vertices of the same mesh |
| Selected Objects | Selected meshes: in Object Mode the ones other than the active object, in Edit Mode including the rest of the meshes being edited |
| Visible Objects (default) | Every visible mesh |
| Collection | Visible meshes in the chosen collection and its child collections |

`S` during a move skips the ones that cannot have anything to snap to: Same Mesh in Object Mode, Selected Objects in Object Mode when no other mesh is selected, and Collection when no collection is chosen. Switching collects the snap points again, which takes a moment in large scenes.

## Align Only

Turning on X, Y, or Z under **Align Only** (in the panel, or with `A` during a move) lines up that coordinate with nearby vertices instead of snapping onto them. With Z on, for example, a vertex at z = 1 offers z = 1 while X and Y stay where they are. A dashed line leads to the vertex the value comes from.

- With several axes on in the panel, only one axis is lined up at a time. `A` goes through the single axes.
- A value is a candidate only if the lined-up position is within the snap distance on screen.
- An axis nearly parallel to the view direction, such as Z in top view, is skipped.
- When a constraint leaves none of the turned-on axes free to move (X on with a Y constraint), lining up pauses and the selection moves without snapping; the lower left of the viewport says so.

## Settings

The sidebar panel (**Tool** tab) holds what changes from task to task; its **Limits and Display** sub-panel and the add-on preferences (**Preferences → Add-ons → Snaxis**) hold the rest.

| Setting | Where | Default | Meaning |
|---|---|---|---|
| Checkbox in the panel header | Panel | On | Use Snaxis in this scene. Off: Move with Guides does not start here, and its key does what else is assigned to it |
| Snap To | Panel | Visible Objects | Which meshes to snap to ([Snap To](#snap-to)) |
| Align Only | Panel | Off | Line up a coordinate instead of snapping onto vertices ([Align Only](#align-only)) |
| Snap Distance | Panel, preferences | 30 px | How close on screen the moving point must come to a snap point, at interface scale 1: at scale 2 the ring is twice as large. `PageUp` / `PageDown` or `Alt` + wheel change it during a move |
| Snap Behavior | Limits and Display, preferences | Snap Exactly | [Snap Behavior](#snap-behavior) |
| Snap Point Limit | Limits and Display, preferences | 50,000 | Most snap points collected when a move starts ([Snap point limit](#snap-point-limit)) |
| Guide Color / Snap Color | Limits and Display, preferences | Magenta / cyan | Guide line and marker before snapping / while snapped |
| Snap Search | Preferences (Advanced) | Screen-space Grid | How candidates are looked up ([Snap Search](#how-candidates-are-looked-up-snap-search)) |

Snap To and Align Only are saved in the `.blend` file per scene; the others are add-on preferences.

**Shortcut** in the add-on preferences: the key of Move with Guides in the 3D Viewport, `Shift+F` by default (a key Blender does not use there). The checkbox turns it off; a changed key shows a button that sets it back. It is the same item as in Preferences → Keymap > 3D View, and Blender keeps changes with the preferences. Up to 2.2.0 the default was `Shift+G` in the Object Mode and Mesh keymaps, in place of Select Grouped / Select Similar; a key changed there does not carry over, so set it again here.

## Language

The interface is in English and Japanese: the panel, preferences, tooltips, status bar, viewport labels, and messages. It follows **Preferences → Interface → Translation** (the language and its Interface, Tooltips, and Reports switches).

## How snap targets are built

Snap targets are built when a move starts and again when `S` switches Snap To; otherwise they are not rebuilt during the move.

### Geometry

- Targets are vertices of the meshes in Snap To. Objects that are not meshes, such as curves and text, are never targets.
- The geometry is taken after modifiers.
- Objects in Edit Mode, and objects sharing their mesh, use the edit mesh without modifiers: leaving out the moving vertices needs vertex indices, which do not carry over to modified geometry.

### What is being moved is excluded

What is being moved is never a snap target:

- Object Mode: the moving objects and their children
- Edit Mode: the moving vertices (other vertices of the same mesh remain targets if Snap To includes that mesh), also on objects that share the mesh

Moving vertices are not counted, so they do not use up the snap point limit.

So Same Mesh gives no targets in Object Mode. With Selected Objects, only the active object moves and the other selected objects are the targets.

### Snap point limit

Snap Point Limit caps the total number of snap points. Objects in view come first, and among them the ones closest to what is being moved.

1. Objects that fit in the limit register all their vertices.
2. The object that crosses the limit registers its bounding-box corners and origin (9 points) plus a random sample of its vertices.
3. Objects farther away register only their corners and origin; up to a tenth of the limit is kept for them.
4. Objects after the limit is used up are left out.

After a move that hit the limit, the panel shows "Snap point limit reached" with how many objects were simplified (sampled or reduced to their box) and left out. During the move, the lower left of the viewport says so.

The limit bounds the points that are kept. Starting a move (and switching Snap To with `S`) still reads every vertex of the meshes in scope, with modifiers, before thinning them out. Measured on a mesh of 16 million evaluated vertices, that took about 0.7–0.8 seconds and about 430 MB of extra memory (about a fifth of what the scene itself used), both growing about linearly with the vertex count (Blender 4.0.2 / 5.2.4, [measurements](DEVELOPMENT.md#large-meshes)).

- The default of 50,000 is enough in most scenes.
- Raising the limit to 1,000,000 adds little to the start of a move (4 million vertices: about 0.2 s → 0.3 s), but every mouse move gets slower the more points are kept (see [Snap Search](#how-candidates-are-looked-up-snap-search)).
- If starting a move is slow in a scene with tens of millions of vertices, set Snap To to Selected Objects or Collection to leave the heavy meshes out.

## How candidates are chosen

A vertex is a candidate when it lies within the snap distance of the moving point projected on screen. The mouse cursor position is not used. Every vertex that qualifies is checked, so crowded geometry does not hide candidates.

Among several candidates, the one closest on screen wins; candidates overlapping within 2 pixels on screen are decided by which is closer to the moving point in 3D. The choice does not depend on the scene scale or zoom.

The moving point is:

- Object Mode: the active object's origin, or the average origin of the moving objects if the active object does not move
- Edit Mode: the center of the selected vertices

The search range in 3D matches half the screen at the depth of the moving point, so candidates are found the same way relative to the screen whether the scene is modeled in millimeters or kilometers.

### How candidates are looked up (Snap Search)

**Snap Search** under **Advanced** in the add-on preferences chooses how candidates are looked up. Both methods find the same candidates and pick the same one; only the speed differs.

| Snap Search | How it works |
|---|---|
| Screen-space Grid (default) | All snap points are projected onto the screen and sorted into a grid. Each mouse move checks only the grid cells around the moving point. After the view changes, the next mouse move projects them again |
| 3D KD-tree (experimental) | A 3D KD-tree of the snap points is built when the move starts. Each mouse move takes from it only the points in the region that appears within the snap distance on screen (a cone from the viewpoint), then projects and checks those. Changing the view does not rebuild it |

In measurements the Screen-space Grid was faster in almost every case: with 100,000 points, a mouse move took about 0.2 ms with the grid and about 4 ms with the KD-tree. The KD-tree gets much slower when points crowd around the moving point: with 100,000 crowded points a mouse move took about 0.5 s. It also takes longer to start a move (about 1.2 s for 500,000 points). Keep the default unless you are comparing the two. The results are in the [developer guide](DEVELOPMENT.md#grid-vs-kd-tree).

## Moving

- Selecting both a parent and its child does not move the child twice.
- Axes locked with Lock Location do not move, and object constraints (Limit Location and others) apply. When they keep the moving point off a snap point, it goes as close as it can and the label says "Projected".
- Orbiting, panning, or zooming during a move does not make the selection jump.

## Troubleshooting

### The add-on does not appear in the list

- Check that you installed a ZIP from Releases: on Blender 4.0 / 4.1 the one without `-extension` (it contains `smart_clipping/__init__.py`); the extension ZIP needs Blender 4.2 or later.
- Check that Blender is 4.0 or later.
- After upgrading from 1.1.x or earlier, remove the old version (module `src`).

Errors are shown in the system console (on Windows, Window > Toggle System Console).

### Something is off after an update

Restart Blender after installing a new version over an older one: until then, Blender keeps parts of the old version loaded, and switching the add-on off and on does not replace them.

### Shift+F does not start a move

- Hover over **Move with Guides** in the panel: when it cannot run, the tooltip says why.
- Check that the checkbox in the panel header is on.
- Check that you are in Object Mode or mesh Edit Mode with an active object.
- Check the shortcut in the add-on preferences (**Shortcut**): it may be turned off or changed; the button next to a changed key sets `Shift+F` again.

### No candidates appear

- The lower left of the viewport says when there is nothing to snap to, and why.
- Check Snap To and, for Collection, the chosen collection. `S` during a move switches Snap To.
- What is being moved is never a candidate (see [What is being moved is excluded](#what-is-being-moved-is-excluded)).
- Candidates are measured from the moving point, shown by the dashed ring. The cursor being over a vertex is not enough when the point is far from it; bring the point closer or raise Snap Distance.
- While `Ctrl` is held (Snap Exactly), or when a constraint pauses Align Only, nothing snaps.

### Starting a move is slow

In large scenes, lower Snap Point Limit or narrow the targets with Snap To set to Collection.
