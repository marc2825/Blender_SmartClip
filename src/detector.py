from dataclasses import dataclass
from typing import List, Optional

from mathutils import Vector, kdtree

from .prefs import get_addon_prefs
from .utils import object_center_world, world_to_screen


@dataclass
class SnapCandidate:
    type: str  # 'AXIS_X', 'AXIS_Y', 'AXIS_Z', 'POINT', 'BOUNDS'
    location: Vector
    reference_co: Vector
    screen_dist: float
    score: float
    target_name: str = ""


@dataclass
class PointMeta:
    obj_name: str
    point_type: str  # 'POINT' or 'BOUNDS'


@dataclass
class BuildResult:
    tree: Optional[kdtree.KDTree]
    point_meta: List[PointMeta]
    point_count: int
    source_vertex_count: int
    limit_exceeded: bool
    bounds_objects: List[str]


def _collect_scope_objects(context, active_obj):
    scene = context.scene
    scope = scene.target_scope

    if scope == "SELF":
        candidates = [active_obj] if active_obj and active_obj.type == "MESH" else []
    elif scope == "SELECTED":
        candidates = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj != active_obj
        ]
    elif scope == "COLLECTION":
        coll = scene.target_collection
        if coll:
            candidates = [obj for obj in coll.objects if obj.type == "MESH"]
        else:
            candidates = []
    else:  # VISIBLE
        candidates = [obj for obj in context.visible_objects if obj.type == "MESH"]

    return candidates


def build_spatial_tree(context, active_obj=None) -> BuildResult:
    active_obj = active_obj or context.active_object
    prefs = get_addon_prefs(context)
    budget_limit = prefs.max_vertex_budget if prefs else 50_000

    candidates = _collect_scope_objects(context, active_obj)
    if not candidates:
        print("[src] No mesh objects in selected scope.")
        return BuildResult(None, [], 0, 0, False, [])

    if active_obj:
        active_center = object_center_world(active_obj)
    else:
        active_center = object_center_world(candidates[0])

    sorted_objs = sorted(
        candidates,
        key=lambda obj: (object_center_world(obj) - active_center).length,
    )

    order_log = ", ".join(obj.name for obj in sorted_objs[:10])
    print(f"[src] Build order (near->far): {order_log}")

    points = []
    meta = []
    total_verts = 0
    limit_exceeded = False
    bounds_objects = []

    for obj in sorted_objs:
        mesh = obj.data
        vert_count = len(mesh.vertices)
        if total_verts + vert_count <= budget_limit:
            for v in mesh.vertices:
                points.append(obj.matrix_world @ v.co)
                meta.append(PointMeta(obj_name=obj.name, point_type="POINT"))
            total_verts += vert_count
        else:
            limit_exceeded = True
            bounds_objects.append(obj.name)
            print(f"[src] Obj {obj.name} switched to Bounds Mode")

            for corner in obj.bound_box:
                points.append(obj.matrix_world @ Vector(corner))
                meta.append(PointMeta(obj_name=obj.name, point_type="BOUNDS"))

            points.append(obj.matrix_world.translation.copy())
            meta.append(PointMeta(obj_name=obj.name, point_type="BOUNDS"))

    if not points:
        print("[src] No points captured for KD-Tree.")
        return BuildResult(None, [], 0, total_verts, limit_exceeded, bounds_objects)

    tree = kdtree.KDTree(len(points))
    for i, co in enumerate(points):
        tree.insert(co, i)
    tree.balance()

    print(
        "[src] KD-Tree built:",
        f"points={len(points)} source_verts={total_verts} budget={budget_limit}",
    )
    return BuildResult(tree, meta, len(points), total_verts, limit_exceeded, bounds_objects)


def find_candidates(
    build_result: BuildResult,
    current_co: Vector,
    region,
    rv3d,
    mouse_xy,
    snap_distance_px: int,
    epsilon: float = 0.01,
    query_radius: float = 2.0,
):
    if not build_result or not build_result.tree:
        return []

    mouse_v = Vector(mouse_xy)
    raw_hits = build_result.tree.find_range(current_co, query_radius)
    candidates = []

    for hit_co, index, world_dist in raw_hits:
        screen = world_to_screen(region, rv3d, hit_co)
        if screen is None:
            continue

        screen_dist = (screen - mouse_v).length
        if screen_dist > snap_distance_px:
            continue

        hit_meta = build_result.point_meta[index]
        base_type = "BOUNDS" if hit_meta.point_type == "BOUNDS" else "POINT"

        candidates.append(
            SnapCandidate(
                type=base_type,
                location=hit_co.copy(),
                reference_co=current_co.copy(),
                screen_dist=screen_dist,
                score=screen_dist + world_dist,
                target_name=hit_meta.obj_name,
            )
        )

        delta = hit_co - current_co

        if abs(delta.x) < epsilon:
            loc_x = current_co.copy()
            loc_x.x = hit_co.x
            candidates.append(
                SnapCandidate(
                    type="AXIS_X",
                    location=loc_x,
                    reference_co=hit_co.copy(),
                    screen_dist=screen_dist,
                    score=screen_dist + abs(delta.x) * 100.0,
                    target_name=hit_meta.obj_name,
                )
            )

        if abs(delta.y) < epsilon:
            loc_y = current_co.copy()
            loc_y.y = hit_co.y
            candidates.append(
                SnapCandidate(
                    type="AXIS_Y",
                    location=loc_y,
                    reference_co=hit_co.copy(),
                    screen_dist=screen_dist,
                    score=screen_dist + abs(delta.y) * 100.0,
                    target_name=hit_meta.obj_name,
                )
            )

        if abs(delta.z) < epsilon:
            loc_z = current_co.copy()
            loc_z.z = hit_co.z
            candidates.append(
                SnapCandidate(
                    type="AXIS_Z",
                    location=loc_z,
                    reference_co=hit_co.copy(),
                    screen_dist=screen_dist,
                    score=screen_dist + abs(delta.z) * 100.0,
                    target_name=hit_meta.obj_name,
                )
            )

    candidates.sort(key=lambda c: c.score)
    return candidates
