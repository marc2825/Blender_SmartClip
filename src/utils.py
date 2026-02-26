from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d


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


def world_delta_to_local(obj, world_delta: Vector) -> Vector:
    """Convert a world-space translation delta to object-local space."""
    return obj.matrix_world.inverted_safe().to_3x3() @ world_delta


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
