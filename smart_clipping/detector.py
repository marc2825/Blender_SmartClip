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

Candidates are decided in screen space: a point qualifies when its projection
lies within the snap threshold of the moving point (and within the 3D search
radius).  Two interchangeable backends (Advanced Settings > Snap Search) find
the points to check; both check them exactly, so they return the same
candidates in the same order:

- ``GRID`` (default): all points are projected once per view and binned into
  cells the size of the snap threshold; a query reads the cells around the
  moving point.  Projections are redone only when the view changes.
- ``KDTREE`` (experimental): a ``mathutils.kdtree.KDTree`` is built once per
  move, independent of the view.  The points that can project inside the
  snap disk form a cone from the viewpoint (a cylinder in orthographic
  views); a query covers the part of it within the depth range of the 3D
  search radius with a chain of spheres, collects the points in them, and
  projects only those.  A plain range query around the moving point would
  not narrow anything: the search radius spans half the screen.  The tree
  stores single-precision coordinates, so the spheres are slightly enlarged
  and the exact tests follow.  The tree is only a pre-filter: the point
  nearest in 3D is often not the one nearest on screen.

Axis Align (``find_axis_candidates``) uses per-axis sorted values with either
backend.
"""

import math
from dataclasses import dataclass, field
from typing import List

import numpy as np
from mathutils import Vector, kdtree

from .prefs import get_addon_prefs
from .utils import (
    DEFAULT_SEARCH_BACKEND,
    DEFAULT_SNAP_DISTANCE_PX,
    DEFAULT_VERTEX_BUDGET,
    SEARCH_BACKENDS,
    SEARCH_KDTREE,
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
# The KD-tree keeps float32 coordinates.  Its range query is widened by these
# (relative to the radius, and to the coordinate magnitude, which bounds the
# rounding of the stored and queried points) so it never drops a point that is
# within the radius in float64; the exact test follows.
_KD_RADIUS_REL_PAD = 1e-5
_KD_COORD_REL_PAD = 1e-6
# Points converted to Python lists at a time while filling the KD-tree.
_KD_INSERT_CHUNK = 65_536
# Spheres (KD-tree range queries) covering the cone of sight per query.
_KD_MAX_SPHERES = 64
# Views whose matrix is worse conditioned than this are searched without
# narrowing (the cone could be off by more than the padding).
_KD_MAX_CONDITION = 1e10


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
    3D (to the moving point, or along the axis for ALIGN_*).  POINT / BOUNDS
    candidates that tie on both (coincident points) keep the order in which
    they were collected.
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
    # Candidate search method: one of utils.SEARCH_BACKENDS
    backend: str = DEFAULT_SEARCH_BACKEND
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


def _check_backend(backend) -> str:
    if backend not in SEARCH_BACKENDS:
        raise ValueError(f"unknown search backend {backend!r}; expected one of {SEARCH_BACKENDS}")
    return backend


def _backend_from_prefs(prefs) -> str:
    backend = getattr(prefs, "search_backend", None) if prefs else None
    return backend if backend in SEARCH_BACKENDS else DEFAULT_SEARCH_BACKEND


def build_from_points(coords, names=None, exclude=(),
                      backend=DEFAULT_SEARCH_BACKEND) -> BuildResult:
    """Build a BuildResult from raw world coordinates (tools and tests).

    *names*: one object name per point; ``None`` puts all points under
    ``"Points"``.  The search index is built lazily (see prepare_search).
    """
    _check_backend(backend)
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
        backend=backend,
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

    The search backend comes from the add-on preferences; its view-independent
    index (the KD-tree) is built here, as part of starting the move.
    """
    result = _collect_snap_points(context, active_obj, moving_verts, exclude_objects, view)
    prepare_search(result)
    return result


def _collect_snap_points(context, active_obj, moving_verts, exclude_objects, view) -> BuildResult:
    active_obj = active_obj or context.active_object
    prefs = get_addon_prefs(context)
    budget = max(0, prefs.max_vertex_budget if prefs else DEFAULT_VERTEX_BUDGET)
    backend = _backend_from_prefs(prefs)

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
        return BuildResult(backend=backend)

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
            keep = np.isfinite(local).all(axis=1)
            if moving:
                keep[[i for i in moving if 0 <= i < len(local)]] = False
            if not keep.all():
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
        return BuildResult(limit_exceeded=over_budget, skipped_objects=skipped_objects,
                           backend=backend)
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
        backend=backend,
    )


def prepare_search(build: BuildResult) -> None:
    """Build the view-independent search index of *build* now.

    Only the KD-tree has one; the screen grid depends on the view and is
    built by the first query in each view.  Queries build a missing index
    themselves, so calling this is optional.
    """
    if build is not None and build.backend == SEARCH_KDTREE and build.point_count:
        _kdtree_index(build)


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


def _perspective(rv3d) -> np.ndarray:
    return np.array(rv3d.perspective_matrix, dtype=np.float64)


def _project(coords, pm, width, height):
    """Project *coords* (N, 3) to region pixels with perspective matrix *pm*.

    Returns ``(ok, sx, sy)``: the row indices of the points that project (in
    front of the viewer and finite, as in location_3d_to_region_2d) and their
    pixel coordinates.  Only element-wise arithmetic is used, so a point gets
    bit-identical values whichever rows it is projected with; this is what
    lets both search backends rank candidates identically.
    """
    x, y, z = coords[:, 0], coords[:, 1], coords[:, 2]
    with np.errstate(invalid="ignore", over="ignore"):
        w = x * pm[3, 0] + y * pm[3, 1] + z * pm[3, 2] + pm[3, 3]
        ok = np.flatnonzero(np.isfinite(w) & (w > 0.0) & np.isfinite(coords).all(axis=1))
        x, y, z, w = x[ok], y[ok], z[ok], w[ok]
        hx = x * pm[0, 0] + y * pm[0, 1] + z * pm[0, 2] + pm[0, 3]
        hy = x * pm[1, 0] + y * pm[1, 1] + z * pm[1, 2] + pm[1, 3]
        sx = width / 2.0 * (1.0 + hx / w)
        sy = height / 2.0 * (1.0 + hy / w)
    finite = np.isfinite(sx) & np.isfinite(sy)
    if not finite.all():
        ok, sx, sy = ok[finite], sx[finite], sy[finite]
    return ok, sx, sy


def _distances(coords, co) -> np.ndarray:
    """Euclidean distances from *co* (float64 (3,)) to each row of *coords*."""
    with np.errstate(invalid="ignore", over="ignore"):
        d = coords - co
        return np.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2])


def _screen_index(build, region, rv3d, cell_px):
    """Project every point for this view and bin it into screen cells.

    Cached on *build* until the view, region size, or cell size changes.
    """
    pm = _perspective(rv3d)
    key = (pm.tobytes(), int(region.width), int(region.height), float(cell_px))
    cached = build._cache.get("screen")
    if cached is not None and cached[0] == key:
        return cached[1]

    front, sx, sy = _project(build.coords, pm, float(region.width), float(region.height))
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


def _rank(screen_dist, tie_break, last=None):
    """Indices ordering candidates best first (see SnapCandidate).

    *last* (e.g. point indices) decides what is still tied, so the order
    does not depend on the order the candidates were gathered in.
    """
    keys = (tie_break, np.floor(screen_dist / SCREEN_TIE_PX))
    return np.lexsort(keys if last is None else (last,) + keys)


def _grid_hits(build, region, rv3d, mouse_xy, thr):
    """Points within *thr* px of *mouse_xy* on screen, via the screen grid."""
    index = _screen_index(build, region, rv3d, max(thr, 1.0))
    keys = index["keys"]
    if len(keys) == 0:
        return None
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
        return None
    sel = np.concatenate(slices)
    d_screen = np.hypot(index["sx"][sel] - mx, index["sy"][sel] - my)
    keep = d_screen <= thr
    return index["points"][sel][keep], d_screen[keep]


def _kdtree_index(build):
    """KD-tree over the finite points of *build* (cached)."""
    cached = build._cache.get("kdtree")
    if cached is not None and cached["count"] == build.point_count:
        return cached
    coords = build.coords
    finite = np.flatnonzero(np.isfinite(coords).all(axis=1))
    tree = kdtree.KDTree(len(finite))
    insert = tree.insert
    for start in range(0, len(finite), _KD_INSERT_CHUNK):
        part = finite[start:start + _KD_INSERT_CHUNK]
        for i, co in zip(part.tolist(), coords[part].tolist()):
            insert(co, i)
    tree.balance()
    pts = coords[finite]
    cached = {
        "count": build.point_count,
        "tree": tree,
        "finite": finite,
        "extent": float(np.abs(pts).max()) if len(finite) else 0.0,
        # bounding box, rows min / max
        "box": np.array([pts.min(axis=0), pts.max(axis=0)]) if len(finite) else np.zeros((2, 3)),
    }
    build._cache["kdtree"] = cached
    return cached


def _sight_cone(pm, width, height, mouse_xy, thr):
    """The points that project within *thr* px of *mouse_xy*, as a cone.

    Returns ``(depth_row, c0, d, spread0, spread1)``, or ``None`` when no point
    can project.  The depth of a point p is ``s = depth_row . (p, 1)`` (clip w
    in perspective, clip z in orthographic views).  Among the points at depth
    s, those projecting inside the disk lie within ``spread0 + spread1 * s``
    of ``c0 + d * s``: at a fixed depth the screen-to-world mapping is affine,
    so the disk maps to an ellipse whose semi-axes bound that distance.
    Raises LinAlgError for a degenerate matrix.
    """
    xn = 2.0 * float(mouse_xy[0]) / width - 1.0
    yn = 2.0 * float(mouse_xy[1]) / height - 1.0
    tx, ty = 2.0 * thr / width, 2.0 * thr / height
    perspective = np.abs(pm[3, :3]).max() > 0.0
    rows = [0, 1, 3] if perspective else [0, 1, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        condition = np.linalg.cond(pm[rows, :3])
    if not condition <= _KD_MAX_CONDITION:
        raise np.linalg.LinAlgError("view matrix too close to singular")
    if perspective:
        # x_ndc * w = row0 . (p, 1), y likewise, w = row3 . (p, 1)
        qi = np.linalg.inv(pm[rows, :3])
        c0 = qi @ -pm[rows, 3]
        d = qi @ np.array((xn, yn, 1.0))
        spread0 = 0.0
        spread1 = math.hypot(np.linalg.norm(qi[:, 0]) * tx, np.linalg.norm(qi[:, 1]) * ty)
        return pm[3], c0, d, spread0, spread1
    w = pm[3, 3]                       # orthographic: w is the same everywhere
    if not w > 0.0:
        return None
    qi = np.linalg.inv(pm[rows, :3])
    c0 = qi @ np.array((xn * w - pm[0, 3], yn * w - pm[1, 3], -pm[2, 3]))
    d = qi[:, 2].copy()
    spread0 = math.hypot(np.linalg.norm(qi[:, 0]) * tx * w, np.linalg.norm(qi[:, 1]) * ty * w)
    return pm[2], c0, d, spread0, 0.0


def _depth_bounds(lo, hi, d_len, spread0, spread1):
    """Split the depth range [lo, hi] so each piece's covering sphere stays small.

    A piece is about as long as the cone is wide there, so the spheres hold a
    few times the points of the cone itself; at most ``_KD_MAX_SPHERES``
    pieces (the one nearest to the apex absorbs the rest).
    """
    if spread1 > 0.0:                  # perspective: the cone widens with depth
        growth = math.log1p(2.0 * spread1 / d_len)
        if not growth > 0.0:
            return np.array((lo, hi))
        first = hi * math.exp(-(_KD_MAX_SPHERES - 1) * growth)
        if first > 0.0 and lo < first:
            return np.concatenate(([lo], np.geomspace(first, hi, _KD_MAX_SPHERES)))
        if lo > 0.0:
            pieces = max(1, math.ceil(math.log(hi / lo) / growth))
            return np.geomspace(lo, hi, pieces + 1)
        return np.array((lo, hi))
    pieces = min(_KD_MAX_SPHERES, max(1, math.ceil(d_len * (hi - lo) / (2.0 * spread0))))
    return np.linspace(lo, hi, pieces + 1)


def _kdtree_range(build, current_co, query_radius, region, rv3d, mouse_xy, thr):
    """Indices of the points that may be candidates (a superset).

    A candidate projects within *thr* px of *mouse_xy* and lies within
    *query_radius* of *current_co*: it is inside the cone of sight through
    the snap disk (_sight_cone), at a depth the search ball and the points'
    bounding box allow.  That part of the cone is covered by a chain of
    spheres, each searched with the KD-tree.  The radii are widened for the
    tree's float32 coordinates; the caller applies the exact tests.
    """
    index = _kdtree_index(build)
    finite = index["finite"]
    if len(finite) == 0:
        return finite
    cur = np.array([float(c) for c in current_co], dtype=np.float64)
    radius = math.inf if query_radius is None else float(query_radius)
    if math.isnan(radius) or radius < 0.0 or (not math.isinf(radius) and not np.isfinite(cur).all()):
        return finite[:0]              # nothing passes the exact tests either
    pm = _perspective(rv3d)
    try:
        cone = _sight_cone(pm, float(region.width), float(region.height), mouse_xy,
                           max(thr, 0.5) * (1.0 + 1e-6))
    except np.linalg.LinAlgError:
        return finite                  # degenerate view: no narrowing
    if cone is None:
        return finite[:0]
    depth_row, c0, d, spread0, spread1 = cone
    d_len = float(np.linalg.norm(d))
    if not (np.isfinite(c0).all() and math.isfinite(d_len) and d_len > 0.0
            and math.isfinite(spread0 + spread1)):
        return finite

    # Depth range: the bounding box of the points, the ball, in front (w > 0).
    corners = np.array([[x, y, z] for x in index["box"][:, 0]
                        for y in index["box"][:, 1] for z in index["box"][:, 2]])
    box_depth = corners @ depth_row[:3] + depth_row[3]
    lo, hi = float(box_depth.min()), float(box_depth.max())
    if not math.isinf(radius):
        mid = float(cur @ depth_row[:3] + depth_row[3])
        reach = radius * float(np.linalg.norm(depth_row[:3]))
        lo, hi = max(lo, mid - reach), min(hi, mid + reach)
    pad = 1e-6 * (abs(lo) + abs(hi)) + 1e-12
    lo, hi = lo - pad, hi + pad
    if spread1 > 0.0:
        lo = max(lo, 0.0)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return finite
    if hi < lo:
        return finite[:0]

    bounds = _depth_bounds(lo, hi, d_len, spread0, spread1)
    a, b = bounds[:-1], bounds[1:]
    centers = c0 + np.outer((a + b) / 2.0, d)
    radii = d_len * (b - a) / 2.0 + spread0 + spread1 * np.maximum(np.abs(a), np.abs(b))
    if not math.isinf(radius):
        near = np.linalg.norm(centers - cur, axis=1) <= radii + radius * (1.0 + 1e-6)
        centers, radii = centers[near], radii[near]
    radii = (radii * (1.0 + _KD_RADIUS_REL_PAD)
             + _KD_COORD_REL_PAD * (index["extent"] + np.abs(centers).max(axis=1, initial=0.0)))
    if not np.all(radii < 1e30):       # beyond float32 range: no narrowing
        return finite
    find_range = index["tree"].find_range
    found = []
    for center, r in zip(centers.tolist(), radii.tolist()):
        hits = find_range(center, r)
        if hits:
            found.append(np.fromiter((hit[1] for hit in hits), dtype=np.intp, count=len(hits)))
    if not found:
        return finite[:0]
    return np.unique(np.concatenate(found))


def _kdtree_hits(build, current_co, region, rv3d, mouse_xy, thr, query_radius):
    """Points within *thr* px of *mouse_xy*, narrowed down by the KD-tree."""
    idx = _kdtree_range(build, current_co, query_radius, region, rv3d, mouse_xy, thr)
    if len(idx) == 0:
        return None
    ok, sx, sy = _project(build.coords[idx], _perspective(rv3d),
                          float(region.width), float(region.height))
    d_screen = np.hypot(sx - float(mouse_xy[0]), sy - float(mouse_xy[1]))
    keep = d_screen <= thr
    return idx[ok][keep], d_screen[keep]


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
    backend: "str | None" = None,
) -> List[SnapCandidate]:
    """Return the snap candidates around *current_co*, best first.

    A candidate is a point within *snap_distance_px* of *mouse_xy* on screen
    (the projection of *current_co*), in front of the viewer, within
    *query_radius* world units of *current_co* (``None`` = any distance), and
    not in ``build_result.exclude_indices``.  All such points are ranked; the
    best *max_results* are returned.

    *backend* overrides ``build_result.backend``; the result is the same
    either way, only the work done to find it differs.
    """
    if build_result is None or build_result.point_count == 0:
        return []
    backend = _check_backend(backend or build_result.backend)
    thr = float(snap_distance_px)
    if backend == SEARCH_KDTREE:
        hits = _kdtree_hits(build_result, current_co, region, rv3d, mouse_xy, thr, query_radius)
    else:
        hits = _grid_hits(build_result, region, rv3d, mouse_xy, thr)
    if hits is None:
        return []
    pts, d_screen = hits

    exclude = _exclude_mask(build_result)
    if exclude is not None and len(pts):
        ok = ~exclude[pts]
        pts, d_screen = pts[ok], d_screen[ok]
    if len(pts) == 0:
        return []
    cur = np.array(current_co, dtype=np.float64)
    d_world = _distances(build_result.coords[pts], cur)
    if query_radius is not None:
        ok = d_world <= query_radius
        pts, d_screen, d_world = pts[ok], d_screen[ok], d_world[ok]
        if len(pts) == 0:
            return []

    order = _rank(d_screen, d_world, pts)[:max_results]
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
        order = order[np.isfinite(build.coords[order]).all(axis=1)]
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
