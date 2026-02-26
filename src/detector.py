"""KD-Tree construction (build) and nearest-neighbour query (find) logic.

The tree is built once at invoke time and stays static for the entire modal
session.  A vertex budget controls how many raw vertices are inserted; objects
that would blow the budget fall back to bounding-box corners + origin.
"""

import bisect
from dataclasses import dataclass, field
from typing import List, Optional

from mathutils import Vector, kdtree

from .prefs import get_addon_prefs
from .utils import object_center_world, world_to_screen


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SnapCandidate:
    """A single snap target returned by *find_candidates*.

    type values:
      POINT / BOUNDS                - regular proximity snap
      ALIGN_X / ALIGN_Y / ALIGN_Z  - axis-clipping mode
    """
    type: str
    location: Vector     # world-space snap destination
    reference_co: Vector # the reference point this candidate relates to
    screen_dist: float   # distance from mouse cursor in pixels
    score: float         # priority (lower = better)
    target_name: str = ""


@dataclass
class _PointMeta:
    """Per-point metadata stored alongside the KD-Tree."""
    obj_name: str
    point_type: str  # 'POINT' or 'BOUNDS'


@dataclass
class BuildResult:
    """Everything produced by *build_spatial_tree*."""
    tree: Optional[kdtree.KDTree] = None
    point_meta: List[_PointMeta] = field(default_factory=list)
    point_count: int = 0
    source_vertex_count: int = 0
    limit_exceeded: bool = False
    bounds_objects: List[str] = field(default_factory=list)
    # Stored points + sorted axis arrays for axis-clipping mode
    points: list = field(default_factory=list)
    axis_x: list = field(default_factory=list)  # [(x_val, point_idx), ...]
    axis_y: list = field(default_factory=list)
    axis_z: list = field(default_factory=list)
    # Point indices belonging to the active object (excluded from snap)
    exclude_indices: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# Scope collection
# ---------------------------------------------------------------------------

def _collect_scope_objects(context, active_obj):
    """Return mesh objects that match the current Target Scope setting."""
    scene = context.scene
    scope = scene.target_scope

    if scope == "SELF":
        if active_obj and active_obj.type == "MESH":
            return [active_obj]
        return []

    if scope == "SELECTED":
        return [
            obj for obj in context.selected_objects
            if obj.type == "MESH" and obj is not active_obj
        ]

    if scope == "COLLECTION":
        coll = scene.target_collection
        if coll:
            return [obj for obj in coll.objects if obj.type == "MESH"]
        return []

    # VISIBLE (default)
    return [obj for obj in context.visible_objects if obj.type == "MESH"]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_spatial_tree(context, active_obj=None,
                       moving_vert_indices: "set[int] | None" = None) -> BuildResult:
    """Build a static KD-Tree of snap reference points.

    Objects are sorted by distance from *active_obj* (nearest first).  Vertices
    are inserted until the budget is exhausted; remaining objects contribute
    only their bounding-box corners and origin.

    *moving_vert_indices*: if provided (Edit Mode), only these mesh vertex
    indices of *active_obj* are excluded from snap candidates.  If ``None``
    (Object Mode), **all** vertices of *active_obj* are excluded.
    """
    active_obj = active_obj or context.active_object
    prefs = get_addon_prefs(context)
    budget = prefs.max_vertex_budget if prefs else 50_000

    candidates = _collect_scope_objects(context, active_obj)
    if not candidates:
        return BuildResult()

    # Distance sort: nearest objects get full vertex data.
    active_center = object_center_world(active_obj) if active_obj else object_center_world(candidates[0])
    candidates.sort(key=lambda o: (object_center_world(o) - active_center).length_squared)

    points: list[Vector] = []
    meta: list[_PointMeta] = []
    exclude_indices: set[int] = set()
    total_verts = 0
    limit_exceeded = False
    bounds_objects: list[str] = []

    for obj in candidates:
        mesh = obj.data
        vert_count = len(mesh.vertices)
        mw = obj.matrix_world
        is_active = obj is active_obj

        if total_verts + vert_count <= budget:
            # Full vertex insertion
            start_idx = len(points)
            for v in mesh.vertices:
                points.append(mw @ v.co)
                meta.append(_PointMeta(obj_name=obj.name, point_type="POINT"))
            if is_active:
                if moving_vert_indices is not None:
                    # Edit Mode: only exclude the selected (moving) vertices
                    for vi in moving_vert_indices:
                        exclude_indices.add(start_idx + vi)
                else:
                    # Object Mode: exclude all vertices of the active object
                    exclude_indices.update(range(start_idx, len(points)))
            total_verts += vert_count
        else:
            # Fallback: bounding-box 8 corners + origin
            limit_exceeded = True
            bounds_objects.append(obj.name)
            start_idx = len(points)
            for corner in obj.bound_box:
                points.append(mw @ Vector(corner))
                meta.append(_PointMeta(obj_name=obj.name, point_type="BOUNDS"))
            points.append(mw.translation.copy())
            meta.append(_PointMeta(obj_name=obj.name, point_type="BOUNDS"))
            if is_active and moving_vert_indices is None:
                # Object Mode: exclude bounding box points too
                exclude_indices.update(range(start_idx, len(points)))

    if not points:
        return BuildResult(source_vertex_count=total_verts, limit_exceeded=limit_exceeded,
                           bounds_objects=bounds_objects)

    tree = kdtree.KDTree(len(points))
    for i, co in enumerate(points):
        tree.insert(co, i)
    tree.balance()

    # Sorted axis arrays for axis-clipping mode
    ax = sorted((co.x, i) for i, co in enumerate(points))
    ay = sorted((co.y, i) for i, co in enumerate(points))
    az = sorted((co.z, i) for i, co in enumerate(points))

    return BuildResult(
        tree=tree,
        point_meta=meta,
        point_count=len(points),
        source_vertex_count=total_verts,
        limit_exceeded=limit_exceeded,
        bounds_objects=bounds_objects,
        points=points,
        axis_x=ax,
        axis_y=ay,
        axis_z=az,
        exclude_indices=exclude_indices,
    )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def find_candidates(
    build_result: BuildResult,
    current_co: Vector,
    region,
    rv3d,
    mouse_xy,
    snap_distance_px: int = 30,
    query_radius: float = 7.5,
) -> List[SnapCandidate]:
    """Search the pre-built tree for snap candidates near *current_co*.

    Returns a list sorted by score (best first), containing POINT / BOUNDS
    hits within *query_radius* world units **and** *snap_distance_px* screen
    pixels.  Points in ``build_result.exclude_indices`` (the active object's
    own vertices) are skipped.
    """
    if not build_result or not build_result.tree:
        return []

    exclude = build_result.exclude_indices
    mouse_v = Vector(mouse_xy)
    raw_hits = build_result.tree.find_range(current_co, query_radius)
    result: list[SnapCandidate] = []

    for hit_co, index, _world_dist in raw_hits:
        if index in exclude:
            continue

        screen = world_to_screen(region, rv3d, hit_co)
        if screen is None:
            continue

        screen_dist = (screen - mouse_v).length
        if screen_dist > snap_distance_px:
            continue

        pm = build_result.point_meta[index]
        base_type = "BOUNDS" if pm.point_type == "BOUNDS" else "POINT"

        result.append(SnapCandidate(
            type=base_type,
            location=hit_co.copy(),
            reference_co=current_co.copy(),
            screen_dist=screen_dist,
            score=screen_dist + _world_dist,
            target_name=pm.obj_name,
        ))

    result.sort(key=lambda c: c.score)
    return result


# ---------------------------------------------------------------------------
# Axis-clipping query
# ---------------------------------------------------------------------------

def find_axis_candidates(
    build_result: BuildResult,
    current_co: Vector,
    region,
    rv3d,
    mouse_xy,
    snap_distance_px: int = 15,
    axis_flags: set = frozenset(),
    query_radius: float = 2.0,
) -> List[SnapCandidate]:
    """Find axis-alignment candidates.

    For each enabled axis, binary-search the sorted axis array for reference
    vertices whose coordinate on that axis is close to *current_co*.
    The candidate location keeps the other axes at *current_co*, replacing
    only the aligned axis with the reference value.  ``reference_co`` stores
    the full 3-D position of the source vertex (for dashed-line visualisation).
    """
    if not build_result or not build_result.points or not axis_flags:
        return []

    exclude = build_result.exclude_indices
    mouse_v = Vector(mouse_xy)
    # Generous world-space threshold so distant axis values are reachable.
    threshold = max(query_radius * 20, 10.0)

    _axes = {
        "X": (0, build_result.axis_x, "ALIGN_X"),
        "Y": (1, build_result.axis_y, "ALIGN_Y"),
        "Z": (2, build_result.axis_z, "ALIGN_Z"),
    }

    result: list[SnapCandidate] = []

    for flag in axis_flags:
        cfg = _axes.get(flag)
        if not cfg:
            continue
        axis_idx, sorted_entries, snap_type = cfg
        if not sorted_entries:
            continue

        target_val = current_co[axis_idx]
        lo = bisect.bisect_left(sorted_entries, (target_val - threshold,))
        hi = bisect.bisect_right(sorted_entries, (target_val + threshold,))

        # Deduplicate: keep the best score per rounded axis value
        best: dict[float, SnapCandidate] = {}

        for i in range(lo, min(hi, lo + 5000)):
            val, pt_idx = sorted_entries[i]
            if pt_idx in exclude:
                continue
            axis_dist = abs(val - target_val)

            # Alignment point: current position with one axis replaced
            align_co = current_co.copy()
            align_co[axis_idx] = val

            # Only reject points behind the camera
            screen = world_to_screen(region, rv3d, align_co)
            if screen is None:
                continue
            screen_dist = (screen - mouse_v).length

            ref_co = build_result.points[pt_idx]
            meta = build_result.point_meta[pt_idx]

            rounded = round(val, 3)
            score = axis_dist * 100.0
            prev = best.get(rounded)
            if prev is None or score < prev.score:
                best[rounded] = SnapCandidate(
                    type=snap_type,
                    location=align_co,
                    reference_co=ref_co.copy(),
                    screen_dist=screen_dist,
                    score=score,
                    target_name=meta.obj_name,
                )

        result.extend(best.values())

    result.sort(key=lambda c: c.score)
    return result
