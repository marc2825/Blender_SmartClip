"""Snap point collection (build) and candidate search (find).

Snap points are collected once when a move starts and stay static for the
whole modal session.  Targets use the evaluated geometry (modifiers applied),
except meshes being edited, whose flushed edit mesh is used so vertex indices
match the BMesh.  Vertices that are being moved are left out before anything
is counted.

``Max Vertex Budget`` caps the total number of snap points.  Objects are taken
nearest first (objects in view first when the view is known).  The first
object that does not fit is represented by its bounding-box corners and origin
plus a uniform random sample of its vertices, keeping up to a tenth of the
budget for later objects; those get the nine stand-in points (or their own
vertices when they have no more than nine) while the budget lasts, and the
rest are skipped.

Candidate search runs in screen space.  All points are projected once per
view and binned into cells the size of the snap threshold; a query reads the
cells around the moving point and checks those points exactly, so no point
within the threshold is missed however crowded the scene is.  Projections are
redone only when the view changes.
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np
from mathutils import Vector

from .prefs import get_addon_prefs
from .utils import (
    DEFAULT_SNAP_DISTANCE_PX,
    DEFAULT_VERTEX_BUDGET,
    object_center_world,
    world_to_screen,
)

# Bounding-box corners + origin used as stand-ins for an over-budget object.
PROXY_POINTS = 9
# Candidates closer than this on screen count as overlapping; among them the
# one nearest in 3D wins.
SCREEN_TIE_PX = 2.0
# Number of best candidates returned (the ranking itself covers all of them).
MAX_RESULTS = 16
# Distinct axis values examined per direction and axis in Axis Align mode.
# Screen distance grows monotonically away from the current value, so the
# nearest values are always among them.
MAX_AXIS_VALUES = 8
# |view direction . axis| above this means the axis points (almost) straight
# into the screen: alignment along it is invisible and cannot be steered by
# the mouse, so it is skipped.
VIEW_PARALLEL_LIMIT = 0.98
# Fixed seed so down-sampling is reproducible.
_SAMPLE_SEED = 0x5C11
_CELL_LIMIT = 2 ** 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SnapCandidate:
    """A single snap target returned by the find functions.

    type values:
      POINT / BOUNDS                - regular proximity snap
      ALIGN_X / ALIGN_Y / ALIGN_Z  - axis-clipping mode

    Lists of candidates are ordered best first: by screen distance, with
    candidates within ``SCREEN_TIE_PX`` of each other ordered by distance in
    3D (to the moving point, or along the axis for ALIGN_*).
    """
    type: str
    location: Vector     # world-space snap destination
    reference_co: Vector # the reference point this candidate relates to
    screen_dist: float   # distance from the moving point on screen, in pixels
    score: float         # sort key derived from screen_dist (lower = better)
    target_name: str = ""


@dataclass
class _PointMeta:
    """Per-point metadata (convenience view of a BuildResult)."""
    obj_name: str
    point_type: str  # 'POINT' or 'BOUNDS'


def _empty_coords():
    return np.zeros((0, 3), dtype=np.float64)


@dataclass
class BuildResult:
    """Snap points produced by *build_spatial_tree* / *build_from_points*."""
    coords: np.ndarray = field(default_factory=_empty_coords)       # (N, 3) world
    obj_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int32))
    is_bounds: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    obj_names: List[str] = field(default_factory=list)
    # Real vertices registered (stand-in points not included)
    source_vertex_count: int = 0
    limit_exceeded: bool = False
    # Objects represented only by bounding-box corners + origin
    bounds_objects: List[str] = field(default_factory=list)
    # Objects whose vertices were down-sampled (they also carry the stand-ins)
    partial_objects: List[str] = field(default_factory=list)
    # Objects left out because the budget was used up
    skipped_objects: List[str] = field(default_factory=list)
    # Point indices that must never be returned (for callers that register
    # points they want to keep out of the results)
    exclude_indices: set = field(default_factory=set)
    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def point_count(self) -> int:
        return len(self.coords)

    @property
    def points(self) -> List[Vector]:
        return [Vector(c) for c in self.coords]

    @property
    def point_meta(self) -> List[_PointMeta]:
        return [_PointMeta(obj_name=self.obj_names[o], point_type="BOUNDS" if b else "POINT")
                for o, b in zip(self.obj_index.tolist(), self.is_bounds.tolist())]


def build_from_points(coords, names=None, exclude=()) -> BuildResult:
    """Build a BuildResult from raw world coordinates (tools and tests).

    *names*: one object name per point; ``None`` puts all points under
    ``"Points"``.
    """
    coords = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
    if names is None:
        obj_names = ["Points"]
        obj_index = np.zeros(len(coords), dtype=np.int32)
    else:
        unique = {}
        obj_index = np.array([unique.setdefault(n, len(unique)) for n in names], dtype=np.int32)
        obj_names = list(unique)
    return BuildResult(
        coords=coords,
        obj_index=obj_index,
        is_bounds=np.zeros(len(coords), dtype=bool),
        obj_names=obj_names,
        source_vertex_count=len(coords),
        exclude_indices=set(exclude),
    )


# ---------------------------------------------------------------------------
# Scope collection
# ---------------------------------------------------------------------------

def _edited_meshes(context, active_obj):
    """Meshes in Edit Mode (active first), or ``[]`` outside Edit Mode."""
    if active_obj is None or active_obj.mode != "EDIT":
        return []
    found = [active_obj] if active_obj.type == "MESH" else []
    for obj in getattr(context, "objects_in_mode", None) or ():
        if obj.type == "MESH" and obj.mode == "EDIT" and obj not in found:
            found.append(obj)
    return found


def _collect_scope_objects(context, active_obj):
    """Return mesh objects that match the current Target Scope setting.

    Whatever is being moved is removed later (whole objects in Object Mode,
    the moving vertices in Edit Mode), so the scopes list what could be a
    target in principle.
    """
    scene = context.scene
    scope = scene.smartclip_target_scope

    if scope == "SELF":
        # The meshes being edited (several with multi-object editing); in
        # Object Mode the active object, which then moves as a whole.
        edited = _edited_meshes(context, active_obj)
        if edited:
            return edited
        if active_obj and active_obj.type == "MESH":
            return [active_obj]
        return []

    if scope == "SELECTED":
        found = [obj for obj in context.selected_objects if obj.type == "MESH"]
        for obj in _edited_meshes(context, active_obj):
            if obj not in found:
                found.append(obj)
        return found

    if scope == "COLLECTION":
        coll = scene.smartclip_target_collection
        if coll:
            # all_objects includes objects of nested child collections;
            # hidden objects are skipped like in the All Visible scope.
            return [obj for obj in coll.all_objects
                    if obj.type == "MESH" and obj.visible_get()]
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


def _local_coords(mesh) -> np.ndarray:
    """Object-space vertex coordinates of *mesh* as an (N, 3) float32 array."""
    count = len(mesh.vertices)
    buf = np.empty(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", buf)
    return buf.reshape(count, 3)


def _to_world(local, matrix) -> np.ndarray:
    m = np.array(matrix, dtype=np.float64)
    return local.astype(np.float64) @ m[:3, :3].T + m[:3, 3]


def _proxy_coords(source) -> np.ndarray:
    m = np.array(source.matrix_world, dtype=np.float64)
    corners = np.array([tuple(c) for c in source.bound_box], dtype=np.float64)
    world = corners @ m[:3, :3].T + m[:3, 3]
    return np.vstack([world, m[:3, 3]])


def _in_view(obj, view) -> bool:
    region, rv3d = view
    screen = world_to_screen(region, rv3d, object_center_world(obj))
    if screen is None:
        return False
    return -0.25 * region.width <= screen.x <= 1.25 * region.width and \
        -0.25 * region.height <= screen.y <= 1.25 * region.height


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_spatial_tree(context, active_obj=None, moving_verts=None,
                       exclude_objects=None, view=None) -> BuildResult:
    """Collect the snap points for one move.

    *moving_verts*: Edit Mode - ``{object: set(vertex indices)}`` of the
    vertices being moved.  They are left out of every object that uses the
    same mesh datablock, before the budget is counted.  ``None`` means Object
    Mode: the moving objects (*exclude_objects*, default ``[active_obj]``)
    and their descendants move as a whole, so they are left out entirely.

    *view*: optional ``(region, rv3d)``; objects in view are taken first.
    """
    active_obj = active_obj or context.active_object
    prefs = get_addon_prefs(context)
    budget = max(0, prefs.max_vertex_budget if prefs else DEFAULT_VERTEX_BUDGET)

    candidates = _collect_scope_objects(context, active_obj)
    moving_by_data = {}
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
        _sync_edit_meshes(moving_verts.keys())
        for obj, idx in moving_verts.items():
            moving_by_data.setdefault(obj.data.as_pointer(), set()).update(idx)
    if not candidates:
        return BuildResult()

    _sync_edit_meshes(candidates)
    depsgraph = context.evaluated_depsgraph_get()

    # Nearest objects first (and objects in view before the rest).
    anchor = object_center_world(active_obj) if active_obj else object_center_world(candidates[0])

    def order_key(obj):
        hidden = 0 if view is None or _in_view(obj, view) else 1
        return hidden, (object_center_world(obj) - anchor).length_squared

    candidates.sort(key=order_key)

    chunks, chunk_obj, chunk_bounds = [], [], []
    obj_names: List[str] = []
    remaining = budget
    total_verts = 0
    over_budget = False
    bounds_objects, partial_objects, skipped_objects = [], [], []
    rng = np.random.default_rng(_SAMPLE_SEED)

    def add(coords, bounds):
        chunks.append(coords)
        chunk_obj.append(np.full(len(coords), len(obj_names) - 1, dtype=np.int32))
        chunk_bounds.append(np.full(len(coords), bounds, dtype=bool))

    for pos, obj in enumerate(candidates):
        if remaining <= 0:
            skipped_objects.append(obj.name)
            continue
        moving = moving_by_data.get(obj.data.as_pointer())
        if obj.mode == "EDIT" or moving is not None:
            # The edit mesh, so indices match the moving vertex indices
            source, mesh, owns_mesh = obj, obj.data, False
        else:
            source = obj.evaluated_get(depsgraph)
            mesh, owns_mesh = source.to_mesh(), True
        try:
            local = _local_coords(mesh)
            if moving:
                keep = np.ones(len(local), dtype=bool)
                keep[[i for i in moving if 0 <= i < len(local)]] = False
                local = local[keep]
            count = len(local)
            obj_names.append(obj.name)

            fits = count <= remaining and (not over_budget or count <= PROXY_POINTS)
            if fits:
                add(_to_world(local, source.matrix_world), False)
                remaining -= count
                total_verts += count
                continue

            first_overflow = not over_budget
            over_budget = True
            if remaining < PROXY_POINTS:
                obj_names.pop()
                skipped_objects.append(obj.name)
                continue
            add(_proxy_coords(source), True)
            remaining -= PROXY_POINTS
            sample = 0
            if first_overflow:
                # Fill the budget with a sample of this object, keeping up to
                # a tenth of it for the stand-ins of the objects after it.
                later = len(candidates) - pos - 1
                reserve = min(PROXY_POINTS * later, budget // 10, remaining)
                sample = min(count, remaining - reserve)
            if sample > 0:
                pick = np.sort(rng.choice(count, size=sample, replace=False))
                add(_to_world(local[pick], source.matrix_world), False)
                remaining -= sample
                total_verts += sample
                partial_objects.append(obj.name)
            else:
                bounds_objects.append(obj.name)
        finally:
            if owns_mesh:
                source.to_mesh_clear()

    if not chunks:
        return BuildResult(limit_exceeded=over_budget, skipped_objects=skipped_objects)
    return BuildResult(
        coords=np.concatenate(chunks),
        obj_index=np.concatenate(chunk_obj),
        is_bounds=np.concatenate(chunk_bounds),
        obj_names=obj_names,
        source_vertex_count=total_verts,
        limit_exceeded=over_budget,
        bounds_objects=bounds_objects,
        partial_objects=partial_objects,
        skipped_objects=skipped_objects,
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _exclude_mask(build):
    if not build.exclude_indices:
        return None
    mask = build._cache.get("exclude")
    if mask is None or len(mask) != build.point_count:
        mask = np.zeros(build.point_count, dtype=bool)
        idx = [i for i in build.exclude_indices if 0 <= i < build.point_count]
        mask[idx] = True
        build._cache["exclude"] = mask
    return mask


def _screen_index(build, region, rv3d, cell_px):
    """Project every point for this view and bin it into screen cells.

    Cached on *build* until the view, region size, or cell size changes.
    """
    pm = np.array(rv3d.perspective_matrix, dtype=np.float64)
    key = (pm.tobytes(), int(region.width), int(region.height), float(cell_px))
    cached = build._cache.get("screen")
    if cached is not None and cached[0] == key:
        return cached[1]

    coords = build.coords
    w = coords @ pm[3, :3] + pm[3, 3]
    front = np.flatnonzero(w > 0.0)          # same rule as location_3d_to_region_2d
    hom = coords[front] @ pm[:2, :3].T + pm[:2, 3]
    wf = w[front]
    sx = region.width / 2.0 * (1.0 + hom[:, 0] / wf)
    sy = region.height / 2.0 * (1.0 + hom[:, 1] / wf)
    cx = np.clip(np.floor(sx / cell_px), -_CELL_LIMIT, _CELL_LIMIT).astype(np.int64)
    cy = np.clip(np.floor(sy / cell_px), -_CELL_LIMIT, _CELL_LIMIT).astype(np.int64)
    keys = (cx + _CELL_LIMIT) * (2 * _CELL_LIMIT + 1) + (cy + _CELL_LIMIT)
    order = np.argsort(keys, kind="stable")
    index = {
        "keys": keys[order],
        "points": front[order],
        "sx": sx[order],
        "sy": sy[order],
        "cell": float(cell_px),
    }
    build._cache["screen"] = (key, index)
    return index


def _cell_key(cx, cy):
    cx = max(-_CELL_LIMIT, min(_CELL_LIMIT, cx))
    cy = max(-_CELL_LIMIT, min(_CELL_LIMIT, cy))
    return (cx + _CELL_LIMIT) * (2 * _CELL_LIMIT + 1) + (cy + _CELL_LIMIT)


def _rank(screen_dist, tie_break):
    """Indices ordering candidates best first (see SnapCandidate)."""
    return np.lexsort((tie_break, np.floor(screen_dist / SCREEN_TIE_PX)))


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
    query_radius: "float | None" = None,
    max_results: int = MAX_RESULTS,
) -> List[SnapCandidate]:
    """Return the snap candidates around *current_co*, best first.

    A candidate is a point within *snap_distance_px* of *mouse_xy* on screen
    (the projection of *current_co*), in front of the viewer, within
    *query_radius* world units of *current_co* (``None`` = any distance), and
    not in ``build_result.exclude_indices``.  All such points are ranked; the
    best *max_results* are returned.
    """
    if build_result is None or build_result.point_count == 0:
        return []
    thr = float(snap_distance_px)
    index = _screen_index(build_result, region, rv3d, max(thr, 1.0))
    keys = index["keys"]
    if len(keys) == 0:
        return []

    mx, my = float(mouse_xy[0]), float(mouse_xy[1])
    cell = index["cell"]
    cx0, cx1 = int(np.floor((mx - thr) / cell)), int(np.floor((mx + thr) / cell))
    cy0, cy1 = int(np.floor((my - thr) / cell)), int(np.floor((my + thr) / cell))
    slices = []
    for cx in range(cx0, cx1 + 1):
        lo = np.searchsorted(keys, _cell_key(cx, cy0), side="left")
        hi = np.searchsorted(keys, _cell_key(cx, cy1), side="right")
        if hi > lo:
            slices.append(np.arange(lo, hi))
    if not slices:
        return []
    sel = np.concatenate(slices)
    d_screen = np.hypot(index["sx"][sel] - mx, index["sy"][sel] - my)
    keep = d_screen <= thr
    pts = index["points"][sel][keep]
    d_screen = d_screen[keep]

    exclude = _exclude_mask(build_result)
    if exclude is not None and len(pts):
        ok = ~exclude[pts]
        pts, d_screen = pts[ok], d_screen[ok]
    if len(pts) == 0:
        return []
    cur = np.array(current_co, dtype=np.float64)
    d_world = np.linalg.norm(build_result.coords[pts] - cur, axis=1)
    if query_radius is not None:
        ok = d_world <= query_radius
        pts, d_screen, d_world = pts[ok], d_screen[ok], d_world[ok]
        if len(pts) == 0:
            return []

    order = _rank(d_screen, d_world)[:max_results]
    names = build_result.obj_names
    result = []
    for k in order:
        i = int(pts[k])
        result.append(SnapCandidate(
            type="BOUNDS" if build_result.is_bounds[i] else "POINT",
            location=Vector(build_result.coords[i]),
            reference_co=current_co.copy(),
            screen_dist=float(d_screen[k]),
            score=float(d_screen[k]),
            target_name=names[build_result.obj_index[i]],
        ))
    return result


# ---------------------------------------------------------------------------
# Axis-clipping query
# ---------------------------------------------------------------------------

_AXES = {"X": (0, "ALIGN_X"), "Y": (1, "ALIGN_Y"), "Z": (2, "ALIGN_Z")}


def _view_direction(rv3d) -> "Vector | None":
    view_matrix = getattr(rv3d, "view_matrix", None)
    if view_matrix is None:
        return None
    direction = Vector(view_matrix[2][:3])
    if direction.length < 1e-9:
        return None
    return direction.normalized()


def _axis_sorted(build, axis_idx):
    cached = build._cache.get(("axis", axis_idx))
    if cached is None:
        values = build.coords[:, axis_idx]
        order = np.argsort(values, kind="stable")
        cached = (values[order], order)
        build._cache[("axis", axis_idx)] = cached
    return cached


def find_axis_candidates(
    build_result: BuildResult,
    current_co: Vector,
    region,
    rv3d,
    mouse_xy,
    snap_distance_px: int = DEFAULT_SNAP_DISTANCE_PX,
    axis_flags: set = frozenset(),
    max_values: int = MAX_AXIS_VALUES,
) -> List[SnapCandidate]:
    """Find axis-alignment candidates, best first.

    A candidate keeps *current_co* and replaces one axis with a coordinate
    value of a snap point.  It is accepted when its projection lies within
    *snap_distance_px* of *mouse_xy* (the projection of *current_co*).  The
    projection of the line through *current_co* along an axis moves
    monotonically away from *mouse_xy* in each direction until it reaches the
    vanishing point, so the walk outwards over distinct values can stop at the
    first value beyond the threshold or behind the viewer.  ``reference_co``
    is the snap point with that value nearest to *current_co* (drawn as the
    dashed line).  Axes nearly parallel to the view direction are skipped.
    """
    if build_result is None or build_result.point_count == 0 or not axis_flags:
        return []

    thr = float(snap_distance_px)
    mouse_v = Vector((float(mouse_xy[0]), float(mouse_xy[1])))
    exclude = _exclude_mask(build_result)
    view_dir = _view_direction(rv3d)
    coords = build_result.coords
    cur = np.array(current_co, dtype=np.float64)
    found = []  # (screen_dist, axis_dist, candidate)

    for flag in sorted(axis_flags):
        cfg = _AXES.get(flag)
        if not cfg:
            continue
        axis_idx, snap_type = cfg
        if view_dir is not None and abs(view_dir[axis_idx]) > VIEW_PARALLEL_LIMIT:
            continue
        values, order = _axis_sorted(build_result, axis_idx)
        target = float(current_co[axis_idx])
        start = int(np.searchsorted(values, target, side="left"))

        for step in (-1, 1):
            pos = start - 1 if step < 0 else start
            examined = 0
            while 0 <= pos < len(values) and examined < max_values:
                value = values[pos]
                lo = int(np.searchsorted(values, value, side="left"))
                hi = int(np.searchsorted(values, value, side="right"))
                pos = lo - 1 if step < 0 else hi
                members = order[lo:hi]
                if exclude is not None:
                    members = members[~exclude[members]]
                    if len(members) == 0:
                        continue
                examined += 1
                align = current_co.copy()
                align[axis_idx] = float(value)
                screen = world_to_screen(region, rv3d, align)
                if screen is None:
                    break
                d = (screen - mouse_v).length
                if d > thr:
                    break
                ref = members[np.argmin(np.linalg.norm(coords[members] - cur, axis=1))]
                found.append((d, abs(float(value) - target), SnapCandidate(
                    type=snap_type,
                    location=align,
                    reference_co=Vector(coords[ref]),
                    screen_dist=d,
                    score=d,
                    target_name=build_result.obj_names[build_result.obj_index[ref]],
                )))

    if not found:
        return []
    d_screen = np.array([f[0] for f in found])
    d_axis = np.array([f[1] for f in found])
    return [found[k][2] for k in _rank(d_screen, d_axis)]
