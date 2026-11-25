# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

from mathutils import Matrix, Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

# Shared defaults (used when addon preferences are unavailable).
DEFAULT_SNAP_DISTANCE_PX = 30
DEFAULT_VERTEX_BUDGET = 50_000

# Snap Distance (px at interface scale 1, the preference's range) and the
# factor PageUp / PageDown or Alt+Wheel change it by during a move.
SNAP_DISTANCE_MIN_PX = 1
SNAP_DISTANCE_MAX_PX = 1000
SNAP_DISTANCE_STEP = 1.25

# Snap candidate search methods (Advanced Settings).  Both return the same
# candidates; see detector.py.
SEARCH_GRID = "GRID"
SEARCH_KDTREE = "KDTREE"
SEARCH_BACKENDS = (SEARCH_GRID, SEARCH_KDTREE)
DEFAULT_SEARCH_BACKEND = SEARCH_GRID

# What happens when a snap point is within the snap distance (preferences).
SNAP_EXACT = "EXACT"   # jump onto it; Ctrl held = no snapping
SNAP_PULL = "PULL"     # pull towards it (the behavior up to 1.3); Ctrl held = exact
DEFAULT_SNAP_BEHAVIOR = SNAP_EXACT

# Snap state of the move at the moment (drawing and labels).
STATE_NONE = "NONE"        # snapping on, no snap point within reach
STATE_FREE = "FREE"        # snapping switched off by holding Ctrl
STATE_PULLING = "PULLING"  # pulled towards a snap point (Gradual Pull)
STATE_SNAPPED = "SNAPPED"  # exactly on a snap point
# Snap Exactly, but the moving point cannot get onto the snap point: an axis /
# plane constraint, Location Lock or an object constraint keeps it off, so it
# is as close as it can get (on the constraint: the projection).
STATE_PROJECTED = "PROJECTED"

# Snap To (scene setting).  The identifiers are stored in .blend files.
SCOPE_ITEMS = [
    ("SELF", "Same Mesh",
     "Snap to other vertices of the meshes being edited (Edit Mode)"),
    ("SELECTED", "Selected Objects",
     "Snap to the other selected meshes. In Object Mode only the active object moves"),
    ("VISIBLE", "Visible Objects",
     "Snap to every visible mesh, nearest first, up to the snap point limit"),
    ("COLLECTION", "Collection",
     "Snap to the visible meshes in a collection and its child collections"),
]
SCOPE_ORDER = tuple(item[0] for item in SCOPE_ITEMS)
SCOPE_NAMES = {item[0]: item[1] for item in SCOPE_ITEMS}

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def object_center_world(obj) -> Vector:
    """Return the world-space bounding-box center of *obj* (fallback: origin)."""
    if obj.type == "MESH" and obj.bound_box:
        center_local = sum((Vector(c) for c in obj.bound_box), Vector()) / 8.0
        return obj.matrix_world @ center_local
    return obj.matrix_world.translation.copy()


def world_to_screen(region, rv3d, world_co) -> "Vector | None":
    """Project a 3-D world coordinate to 2-D region pixel coordinates."""
    return location_3d_to_region_2d(region, rv3d, world_co)


def screen_to_world(region, rv3d, mouse_xy, depth_location) -> Vector:
    """Unproject a 2-D region coordinate back to 3-D using *depth_location*."""
    return region_2d_to_location_3d(region, rv3d, mouse_xy, depth_location)


def pixel_world_size(region, rv3d, world_co) -> "float | None":
    """World-space length of one screen pixel at the depth of *world_co*.

    ``None`` when *world_co* is behind the viewpoint.
    """
    screen = world_to_screen(region, rv3d, world_co)
    if screen is None:
        return None
    a = screen_to_world(region, rv3d, screen, world_co)
    b = screen_to_world(region, rv3d, screen + Vector((1.0, 0.0)), world_co)
    if a is None or b is None:
        return None
    return (b - a).length


def world_to_location_matrix(obj) -> Matrix:
    """Return the 3x3 matrix mapping a world-space translation delta to a
    delta of ``obj.location``.

    ``obj.location`` is expressed in the parent space (parent matrix combined
    with ``matrix_parent_inverse``), not in world space, so writing a world
    coordinate into it directly makes parented objects jump.
    """
    if obj.parent is None:
        return Matrix.Identity(3)
    if obj.parent_type == "OBJECT":
        parent_space = obj.parent.matrix_world @ obj.matrix_parent_inverse
    else:
        # Bone / vertex parents: derive the parent space from the evaluated result.
        parent_space = obj.matrix_world @ obj.matrix_basis.inverted_safe()
    return parent_space.to_3x3().inverted_safe()


def constraint_axes(mode: "str | None") -> frozenset:
    """Axes along which movement is allowed for a constraint mode.

    ``None`` = free; ``"X"``/``"Y"``/``"Z"`` = single axis;
    ``"YZ"``/``"XZ"``/``"XY"`` = plane.
    """
    if not mode:
        return frozenset(_AXIS_INDEX)
    return frozenset(mode)


def apply_constraint(movement: Vector, mode: "str | None") -> Vector:
    """Zero-out the movement components blocked by the constraint *mode*."""
    m = movement.copy()
    if not mode:
        return m
    allowed = constraint_axes(mode)
    for axis, idx in _AXIS_INDEX.items():
        if axis not in allowed:
            m[idx] = 0.0
    return m


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# ----------------------------------------------------------------------
# Decisions of the move, kept free of bpy state so they can be tested
# ----------------------------------------------------------------------

_ALIGN_CYCLE = ((), ("X",), ("Y",), ("Z",))


def next_align_axes(axes) -> tuple:
    """Align Only after pressing A: Off -> X -> Y -> Z -> Off.

    Several axes (set in the panel) go back to Off.
    """
    current = tuple(sorted(axes))
    if current not in _ALIGN_CYCLE:
        return ()
    return _ALIGN_CYCLE[(_ALIGN_CYCLE.index(current) + 1) % len(_ALIGN_CYCLE)]


def scope_available(scope, is_edit, has_collection, has_other_selected) -> bool:
    """Whether Snap To *scope* can have anything to snap to during this move.

    Object Mode moves whole objects, which never snap to themselves, so Same
    Mesh has nothing there; Selected Objects needs a selected mesh that is not
    moving.  Collection needs a collection.
    """
    if scope == "SELF":
        return is_edit
    if scope == "SELECTED":
        return is_edit or has_other_selected
    if scope == "COLLECTION":
        return has_collection
    return scope in SCOPE_ORDER


def next_scope(current, is_edit, has_collection, has_other_selected) -> str:
    """Snap To after pressing S: the next available scope in SCOPE_ORDER."""
    start = SCOPE_ORDER.index(current) if current in SCOPE_ORDER else -1
    for step in range(1, len(SCOPE_ORDER) + 1):
        scope = SCOPE_ORDER[(start + step) % len(SCOPE_ORDER)]
        if scope_available(scope, is_edit, has_collection, has_other_selected):
            return scope
    return current


def snap_rule(behavior, ctrl_held) -> tuple:
    """``(search, exact)``: look for a snap point at all, and land on it exactly.

    Snap Exactly: snaps onto the point; Ctrl held moves freely.
    Gradual Pull: pulls towards the point; Ctrl held snaps exactly.
    """
    if behavior == SNAP_PULL:
        return True, bool(ctrl_held)
    return not ctrl_held, True


def step_snap_distance(px, steps) -> int:
    """Snap Distance after *steps* presses: up (+) or down (-) by SNAP_DISTANCE_STEP.

    Every step changes it by at least 1 px, within the preference's range.
    """
    value = int(px)
    for _ in range(abs(int(steps))):
        if steps > 0:
            value = max(value + 1, round(value * SNAP_DISTANCE_STEP))
        else:
            value = min(value - 1, round(value / SNAP_DISTANCE_STEP))
    return max(SNAP_DISTANCE_MIN_PX, min(SNAP_DISTANCE_MAX_PX, value))


def snap_distance_on_screen(px, ui_scale) -> float:
    """Snap Distance in screen pixels: the setting (px at interface scale 1)
    times the interface scale, so it keeps its size next to the text."""
    return float(px) * (ui_scale if ui_scale and ui_scale > 0.0 else 1.0)


def snap_distance_steps(event_type, value, alt=False, ctrl=False, shift=False,
                        oskey=False) -> int:
    """Steps an event changes Snap Distance by during a move (0: none).

    PageUp / PageDown (as proportional size in Blender's move), or the wheel
    with Alt alone held; the wheel without it still zooms the view.
    """
    if value != "PRESS":
        return 0
    if event_type == "PAGE_UP":
        return 1
    if event_type == "PAGE_DOWN":
        return -1
    if alt and not (ctrl or shift or oskey):
        if event_type == "WHEELUPMOUSE":
            return 1
        if event_type == "WHEELDOWNMOUSE":
            return -1
    return 0


def pull_ratio(screen_dist, threshold_px, strength) -> float:
    """Share of the way to a snap point that Gradual Pull moves (0..strength)."""
    return clamp01(1.0 - screen_dist / max(1.0, threshold_px)) * strength
