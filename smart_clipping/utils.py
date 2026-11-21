from mathutils import Matrix, Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

# Shared defaults (used when addon preferences are unavailable).
DEFAULT_SNAP_DISTANCE_PX = 30
DEFAULT_VERTEX_BUDGET = 50_000

# Snap candidate search methods (Advanced Settings).  Both return the same
# candidates; see detector.py.
SEARCH_GRID = "GRID"
SEARCH_KDTREE = "KDTREE"
SEARCH_BACKENDS = (SEARCH_GRID, SEARCH_KDTREE)
DEFAULT_SEARCH_BACKEND = SEARCH_GRID

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
