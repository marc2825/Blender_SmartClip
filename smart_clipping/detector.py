"""KD-Tree construction (build) and nearest-neighbour query (find) logic.

The tree is built once at invoke time and stays static for the entire modal
session.  Targets use the evaluated geometry (modifiers applied), except
objects in Edit Mode, whose (flushed) edit mesh is used so vertex indices
match the BMesh.  A vertex budget controls how many raw vertices are
inserted.  An object that does not fit into the remaining budget is
down-sampled to fill what is left, and every over-budget object also
contributes its bounding-box corners + origin so it stays reachable.
"""

import bisect
from dataclasses import dataclass, field
from typing import List, Optional

from mathutils import Vector, kdtree

from .prefs import get_addon_prefs
from .utils import (
    DEFAULT_SNAP_DISTANCE_PX,
    DEFAULT_VERTEX_BUDGET,
    object_center_world,
    world_to_screen,
)

# Upper bound on how many tree hits are projected to screen per query.
MAX_QUERY_HITS = 512
# Upper bound on sorted-axis entries scanned per direction in axis-align mode.
MAX_AXIS_SCAN = 20_000
# |view direction . axis| above this means the axis points (almost) straight
# into the screen: alignment along it is invisible and cannot be steered by
# the mouse, so it is skipped.
VIEW_PARALLEL_LIMIT = 0.98


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
    # Objects represented only by bounding-box corners + origin
    bounds_objects: List[str] = field(default_factory=list)
    # Objects whose vertices were down-sampled to fit the budget
    # (they also carry bounding-box corners + origin)
    partial_objects: List[str] = field(default_factory=list)
    # Stored points + sorted axis arrays for axis-clipping mode
    points: list = field(default_factory=list)
    axis_x: list = field(default_factory=list)  # [(x_val, point_idx), ...]
    axis_y: list = field(default_factory=list)
    axis_z: list = field(default_factory=list)
    # Point indices that must never be returned as snap targets
    # (the moving vertices in Edit Mode)
    exclude_indices: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# Scope collection
# ---------------------------------------------------------------------------

def _collect_scope_objects(context, active_obj):
    """Return mesh objects that match the current Target Scope setting."""
    scene = context.scene
    scope = scene.smartclip_target_scope

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
        coll = scene.smartclip_target_collection
        if coll:
            # all_objects includes objects of nested child collections
            return [obj for obj in coll.all_objects if obj.type == "MESH"]
        return []

    # VISIBLE (default)
    return [obj for obj in context.visible_objects if obj.type == "MESH"]


def _sync_edit_meshes(objects):
    """Flush pending Edit Mode changes so ``mesh.vertices`` is current.

    While an object is in Edit Mode its live geometry is in a BMesh and
    ``obj.data.vertices`` keeps the state from the last mode switch.
    """
    for obj in objects:
        if obj.mode == "EDIT":
            obj.update_from_editmode()


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_spatial_tree(context, active_obj=None, moving_verts=None,
                       exclude_objects=None) -> BuildResult:
    """Build a static KD-Tree of snap reference points.

    Objects are sorted by distance from *active_obj* (nearest first).  Vertices
    are inserted until the budget is exhausted: the object that crosses the
    limit is down-sampled to fill the remaining budget, later objects only get
    their bounding-box corners and origin.

    *moving_verts*: Edit Mode - ``{object: set(vertex indices)}`` of the
    vertices being moved; only these are excluded from snap candidates.
    ``None`` means Object Mode: the moving objects (*exclude_objects*,
    default ``[active_obj]``) and their descendants move as a whole, so they
    are not inserted at all (and do not consume budget).
    """
    active_obj = active_obj or context.active_object
    prefs = get_addon_prefs(context)
    budget = prefs.max_vertex_budget if prefs else DEFAULT_VERTEX_BUDGET

    candidates = _collect_scope_objects(context, active_obj)
    moving_by_ptr = {}
    if moving_verts is None:
        movers = exclude_objects if exclude_objects is not None else [active_obj]
        skip = set()
        for obj in movers:
            if obj is None:
                continue
            skip.add(obj.as_pointer())
            skip.update(child.as_pointer() for child in obj.children_recursive)
        candidates = [obj for obj in candidates if obj.as_pointer() not in skip]
    else:
        moving_by_ptr = {obj.as_pointer(): set(idx) for obj, idx in moving_verts.items()}
    if not candidates:
        return BuildResult()

    _sync_edit_meshes(candidates)
    depsgraph = context.evaluated_depsgraph_get()

    # Distance sort: nearest objects get full vertex data.
    active_center = object_center_world(active_obj) if active_obj else object_center_world(candidates[0])
    candidates.sort(key=lambda o: (object_center_world(o) - active_center).length_squared)

    points: list[Vector] = []
    meta: list[_PointMeta] = []
    exclude_indices: set[int] = set()
    total_verts = 0
    limit_exceeded = False
    bounds_objects: list[str] = []
    partial_objects: list[str] = []

    for obj in candidates:
        if obj.mode == "EDIT":
            source, mesh, owns_mesh = obj, obj.data, False
        else:
            source = obj.evaluated_get(depsgraph)
            mesh, owns_mesh = source.to_mesh(), True
        try:
            verts = mesh.vertices
            vert_count = len(verts)
            mw = source.matrix_world
            moving = moving_by_ptr.get(obj.as_pointer())
            remaining = budget - total_verts

            if vert_count <= remaining:
                indices = range(vert_count)
            else:
                limit_exceeded = True
                if remaining > 0:
                    step = -(-vert_count // remaining)  # ceil division
                    indices = range(0, vert_count, step)
                    partial_objects.append(obj.name)
                else:
                    indices = range(0)
                    bounds_objects.append(obj.name)

            for vi in indices:
                if moving and vi in moving:
                    exclude_indices.add(len(points))
                points.append(mw @ verts[vi].co)
                meta.append(_PointMeta(obj_name=obj.name, point_type="POINT"))
            total_verts += len(indices)

            if len(indices) < vert_count:
                # Over budget: keep the object reachable through its bounds
                for corner in source.bound_box:
                    points.append(mw @ Vector(corner))
                    meta.append(_PointMeta(obj_name=obj.name, point_type="BOUNDS"))
                points.append(mw.translation.copy())
                meta.append(_PointMeta(obj_name=obj.name, point_type="BOUNDS"))
        finally:
            if owns_mesh:
                source.to_mesh_clear()

    if not points:
        return BuildResult(source_vertex_count=total_verts, limit_exceeded=limit_exceeded,
                           bounds_objects=bounds_objects, partial_objects=partial_objects)

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
        partial_objects=partial_objects,
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
    snap_distance_px: int = DEFAULT_SNAP_DISTANCE_PX,
    query_radius: float = 7.5,
    max_hits: int = MAX_QUERY_HITS,
) -> List[SnapCandidate]:
    """Search the pre-built tree for snap candidates near *current_co*.

    Returns a list sorted by score (best first), containing POINT / BOUNDS
    hits within *query_radius* world units **and** *snap_distance_px* screen
    pixels.  Points in ``build_result.exclude_indices`` are skipped.  At most
    *max_hits* of the nearest remaining hits are projected to screen.
    """
    if not build_result or not build_result.tree:
        return []

    exclude = build_result.exclude_indices
    mouse_v = Vector(mouse_xy)
    # find_range returns hits sorted nearest-first
    raw_hits = build_result.tree.find_range(current_co, query_radius)
    result: list[SnapCandidate] = []
    projected = 0

    for hit_co, index, world_dist in raw_hits:
        if index in exclude:
            continue
        projected += 1
        if projected > max_hits:
            break

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
            score=screen_dist + world_dist,
            target_name=pm.obj_name,
        ))

    result.sort(key=lambda c: c.score)
    return result


# ---------------------------------------------------------------------------
# Axis-clipping query
# ---------------------------------------------------------------------------

_AXES = {
    "X": (0, "axis_x", "ALIGN_X"),
    "Y": (1, "axis_y", "ALIGN_Y"),
    "Z": (2, "axis_z", "ALIGN_Z"),
}


def _view_direction(rv3d) -> "Vector | None":
    view_matrix = getattr(rv3d, "view_matrix", None)
    if view_matrix is None:
        return None
    direction = Vector(view_matrix[2][:3])
    if direction.length < 1e-9:
        return None
    return direction.normalized()


def find_axis_candidates(
    build_result: BuildResult,
    current_co: Vector,
    region,
    rv3d,
    mouse_xy,
    snap_distance_px: int = DEFAULT_SNAP_DISTANCE_PX,
    axis_flags: set = frozenset(),
    max_scan: int = MAX_AXIS_SCAN,
) -> List[SnapCandidate]:
    """Find axis-alignment candidates.

    For each enabled axis, the sorted axis array is walked outwards from
    *current_co*'s value.  A candidate location keeps the other axes at
    *current_co* and replaces only the aligned axis with the reference value;
    it is accepted while its projection lies within *snap_distance_px* of
    *mouse_xy* (which should be the projection of *current_co*, so the screen
    distance grows monotonically as the walk moves away and the walk can stop
    at the first miss).  ``reference_co`` stores the full 3-D position of the
    source vertex (for the dashed-line visualisation); among vertices sharing
    a value the one closest to *current_co* is used.
    """
    if not build_result or not build_result.points or not axis_flags:
        return []

    exclude = build_result.exclude_indices
    points = build_result.points
    mouse_v = Vector(mouse_xy)
    view_dir = _view_direction(rv3d)

    result: list[SnapCandidate] = []

    for flag in sorted(axis_flags):
        cfg = _AXES.get(flag)
        if not cfg:
            continue
        axis_idx, attr, snap_type = cfg
        entries = getattr(build_result, attr)
        if not entries:
            continue
        if view_dir is not None and abs(view_dir[axis_idx]) > VIEW_PARALLEL_LIMIT:
            continue

        target_val = current_co[axis_idx]
        start = bisect.bisect_left(entries, (target_val,))
        # Best candidate per distinct axis value: {val: (tie_break, candidate)}
        best: dict = {}

        for step in (-1, 1):
            i = start - 1 if step < 0 else start
            scanned = 0
            last_val = None
            align_co = None
            screen_dist = 0.0
            while 0 <= i < len(entries) and scanned < max_scan:
                val, pt_idx = entries[i]
                i += step
                scanned += 1
                if pt_idx in exclude:
                    continue

                if val != last_val:
                    last_val = val
                    align_co = current_co.copy()
                    align_co[axis_idx] = val
                    screen = world_to_screen(region, rv3d, align_co)
                    if screen is None:
                        break
                    screen_dist = (screen - mouse_v).length
                    if screen_dist > snap_distance_px:
                        break

                ref_co = points[pt_idx]
                tie = (ref_co - current_co).length_squared
                prev = best.get(val)
                if prev is not None and prev[0] <= tie:
                    continue
                meta = build_result.point_meta[pt_idx]
                best[val] = (tie, SnapCandidate(
                    type=snap_type,
                    location=align_co.copy(),
                    reference_co=ref_co.copy(),
                    screen_dist=screen_dist,
                    score=screen_dist + abs(val - target_val),
                    target_name=meta.obj_name,
                ))

        result.extend(cand for _tie, cand in best.values())

    result.sort(key=lambda c: c.score)
    return result
