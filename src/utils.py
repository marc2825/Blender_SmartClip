from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d


def object_center_world(obj) -> Vector:
    if obj.type == "MESH" and getattr(obj, "bound_box", None):
        center_local = sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8.0
        return obj.matrix_world @ center_local
    return obj.matrix_world.translation.copy()


def world_to_screen(region, rv3d, world_co):
    return location_3d_to_region_2d(region, rv3d, world_co)


def mouse_to_world(region, rv3d, mouse_xy, depth_location):
    return region_2d_to_location_3d(region, rv3d, mouse_xy, depth_location)


def world_delta_to_local(obj, world_delta: Vector) -> Vector:
    return obj.matrix_world.inverted_safe().to_3x3() @ world_delta


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
