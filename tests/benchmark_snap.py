"""
Performance and accuracy benchmark for snap candidate search (not a pass/fail test).

Usage:
  blender --background --factory-startup --python tests/benchmark_snap.py
  blender --background --factory-startup --python tests/benchmark_snap.py -- --quick
  blender --background --factory-startup --python tests/benchmark_snap.py -- --sizes 10000,500000 --json out.json
  blender --background --factory-startup --python tests/benchmark_snap.py -- --impl PATH/TO/smart_clipping

Every search backend of the package (screen-space grid, 3D KD-tree) runs on
the same synthetic point clouds, views and queries.  ``--impl`` benchmarks
another copy of the package (e.g. an older version exported with
``git archive``) instead of the one in this repository; versions without
backends run once as "default".

Each query is compared with a brute-force ground truth over all points:

- candidate:   within ``THRESHOLD_PX`` on screen of the moving point and
               within the world search radius, in front of the camera
- best:        smallest screen distance; points within ``TIE_PX`` of each
               other on screen are ordered by world distance
- miss_rate:   mean share of the ground-truth candidates the search does not
               return when asked for all of them (queries without any
               candidate are skipped; the first ``--checked`` queries)
- agreement:   share of queries whose top result is the ground-truth best
- identical:   share of the checked queries whose full candidate list equals
               that of the first backend (same points, order, and distances)

Timings:

- index_ms:        building the search index: the KD-tree (once per move) or
                   the grid's projection and binning (once per view)
- query_ms_*:      a query in an unchanged view (median, p95)
- view_change_ms_*: the first query after the view changed, which includes
                   rebuilding the grid's index (median, p95)
- index_peak_mb:   peak Python / numpy allocation while building the index
                   (tracemalloc; does not see the KD-tree's own C memory)
- index_kept_mb:   memory the index keeps: the grid's arrays, or the KD-tree's
                   nodes (``KD_NODE_BYTES`` each) plus its index array
"""

import argparse
import gc
import importlib.util
import inspect
import json
import math
import os
import sys
import time
import tracemalloc
from types import SimpleNamespace

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

THRESHOLD_PX = 30
TIE_PX = 2.0
REGION = (1600, 900)
VIEW_CHANGES = 12
# sizeof(KDTreeNode) in Blender's BLI_kdtree (two uint children, float[3],
# int index, uint axis); a fresh process grows by 29.5 bytes per point when
# filling a mathutils KDTree.  The nodes live in C memory, which neither
# tracemalloc nor the process size measured mid-run (freed memory is reused)
# reports reliably.
KD_NODE_BYTES = 28


# ---------------------------------------------------------------- loading

def load_impl(path):
    path = os.path.abspath(path)
    name = "bench_impl_" + str(abs(hash(path)))
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(path, "__init__.py"), submodule_search_locations=[path])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def impl_backends(impl):
    """Backends to run: all the package offers, or [None] for older versions."""
    backends = getattr(impl.utils, "SEARCH_BACKENDS", None)
    return list(backends) if backends else [None]


# ------------------------------------------------------------------- view

def perspective_view(eye, target, fov_deg=50.0, near=0.1, far=1000.0):
    width, height = REGION
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    aspect = width / height
    proj = Matrix((
        (f / aspect, 0.0, 0.0, 0.0),
        (0.0, f, 0.0, 0.0),
        (0.0, 0.0, (far + near) / (near - far), 2.0 * far * near / (near - far)),
        (0.0, 0.0, -1.0, 0.0),
    ))
    eye, target = Vector(eye), Vector(target)
    fwd = (target - eye).normalized()
    right = fwd.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(fwd)
    rot = Matrix((right, up, -fwd))
    view = rot.to_4x4()
    view.translation = -(rot @ eye)
    rv3d = SimpleNamespace(perspective_matrix=proj @ view, view_matrix=view,
                           is_perspective=True, view_perspective="PERSP",
                           view_distance=(target - eye).length)
    return SimpleNamespace(width=width, height=height), rv3d


def orbit_views(scale, count):
    """*count* views orbiting the middle of the cloud (the first one is the main view)."""
    target = Vector((5.0, 5.0, 5.0)) * scale
    views = []
    for k in range(count):
        angle = math.radians(-90.0 + 360.0 * k / count)
        eye = target + Vector((23.0 * math.cos(angle), 23.0 * math.sin(angle), 4.0 + 0.5 * k)) * scale
        views.append(perspective_view(eye, target, near=0.1 * scale, far=1000.0 * scale))
    return views


def project_all(coords, rv3d):
    pm = np.array(rv3d.perspective_matrix, dtype=np.float64)
    hom = coords @ pm[:3, :3].T + pm[:3, 3]
    w = coords @ pm[3, :3] + pm[3, 3]
    width, height = REGION
    front = w > 1e-9
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = width / 2.0 * (1.0 + hom[:, 0] / w)
        sy = height / 2.0 * (1.0 + hom[:, 1] / w)
    return np.stack([sx, sy], axis=1), front


# --------------------------------------------------------------- builders

def build(impl, coords, backend):
    det = impl.detector
    if hasattr(det, "build_from_points"):
        return det.build_from_points(coords, **({"backend": backend} if backend else {}))
    # 1.2.x: KD-tree + Python lists
    points = [Vector(c) for c in coords]
    tree = det.kdtree.KDTree(len(points))
    for i, co in enumerate(points):
        tree.insert(co, i)
    tree.balance()
    meta = [det._PointMeta(obj_name="Cloud", point_type="POINT") for _ in points]
    return det.BuildResult(
        tree=tree, point_meta=meta, point_count=len(points), points=points,
        axis_x=sorted((co.x, i) for i, co in enumerate(points)),
        axis_y=sorted((co.y, i) for i, co in enumerate(points)),
        axis_z=sorted((co.z, i) for i, co in enumerate(points)),
    )


def build_index(impl, result, backend, view):
    """Build what the backend searches with; returns nothing (timed by the caller)."""
    det = impl.detector
    if backend is None:
        return  # old versions build everything in build()
    if backend == impl.utils.SEARCH_KDTREE:
        det.prepare_search(result)
    else:
        region, rv3d = view
        det._screen_index(result, region, rv3d, float(THRESHOLD_PX))


def index_kept_bytes(impl, result, backend):
    if backend is None:
        return None
    if backend == impl.utils.SEARCH_KDTREE:
        cached = result._cache.get("kdtree")
        if cached is None:
            return None
        return KD_NODE_BYTES * len(cached["finite"]) + cached["finite"].nbytes + cached["box"].nbytes
    cached = result._cache.get("screen")
    if cached is None:
        return None
    return sum(v.nbytes for v in cached[1].values() if isinstance(v, np.ndarray))


def query_radius(impl, region, rv3d, co):
    px = impl.utils.pixel_world_size(region, rv3d, co)
    return px * max(region.width, region.height) * 0.5


def find(impl, result, co, region, rv3d, mouse, radius, backend, every=False):
    params = inspect.signature(impl.detector.find_candidates).parameters
    extra = {}
    if every and "max_results" in params:
        extra["max_results"] = 10 ** 9
    if backend is not None:
        extra["backend"] = backend
    return impl.detector.find_candidates(result, co, region, rv3d, mouse,
                                         THRESHOLD_PX, radius, **extra)


def candidate_key(cands):
    return [(tuple(c.location), c.type, c.target_name, c.screen_dist) for c in cands]


# ----------------------------------------------------------- ground truth

def ground_truth(coords, screen, front, co, mouse, radius):
    d_screen = np.hypot(screen[:, 0] - mouse[0], screen[:, 1] - mouse[1])
    d_world = np.linalg.norm(coords - np.asarray(co), axis=1)
    ok = front & (d_screen <= THRESHOLD_PX) & (d_world <= radius)
    idx = np.flatnonzero(ok)
    if idx.size == 0:
        return idx, None
    order = np.lexsort((d_world[idx], np.floor(d_screen[idx] / TIE_PX)))
    return idx, idx[order[0]]


# --------------------------------------------------------------- scenarios

def cloud(kind, n, scale, rng):
    if kind == "uniform":
        pts = rng.uniform(0.0, 10.0, size=(n, 3))
    else:  # dense: almost everything in a small blob near the middle
        pts = np.concatenate([
            rng.normal(5.0, 0.05, size=(n - n // 20, 3)),
            rng.uniform(0.0, 10.0, size=(n // 20, 3)),
        ])
    return pts * scale


def make_queries(impl, coords, views, count, scale, rng):
    """Query points near existing points, with their mouse position and radius per view."""
    picks = rng.choice(len(coords), size=count, replace=False)
    queries = []
    for i in picks:
        co = Vector(coords[i] + rng.normal(0.0, 0.02 * scale, size=3))
        per_view = []
        for region, rv3d in views:
            mouse = impl.utils.world_to_screen(region, rv3d, co)
            per_view.append(None if mouse is None else (mouse, query_radius(impl, region, rv3d, co)))
        queries.append((co, per_view))
    return queries


def percentile(values, q):
    return round(float(np.percentile(values, q)), 3) if len(values) else None


def run_backend(impl, backend, coords, views, queries, truth, checked):
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    result = build(impl, coords, backend)
    build_index(impl, result, backend, views[0])
    index_s = time.perf_counter() - t0
    _, index_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    kept = index_kept_bytes(impl, result, backend)

    region, rv3d = views[0]
    times, sizes, misses, lists = [], [], [], []
    agree = with_gt = 0
    for (co, per_view), (gt_idx, best) in zip(queries, truth):
        if per_view[0] is None:
            lists.append(None)
            continue
        mouse, radius = per_view[0]
        t0 = time.perf_counter()
        cands = find(impl, result, co, region, rv3d, mouse, radius, backend)
        times.append(time.perf_counter() - t0)
        sizes.append(len(cands))
        if best is None:
            lists.append(None)
            continue
        with_gt += 1
        if cands and np.linalg.norm(np.array(tuple(cands[0].location)) - coords[best]) < 1e-6 * max(
                1.0, float(np.abs(coords).max())):
            agree += 1
        if len(misses) >= checked:
            lists.append(None)
            continue
        # Every candidate (in crowded clouds that can be most of the points,
        # hence only for the first *checked* queries).
        every = find(impl, result, co, region, rv3d, mouse, radius, backend, every=True)
        lists.append(candidate_key(every))
        # Candidate locations are mathutils Vectors (float32): compare the
        # ground truth at the same precision, exactly.
        found = {tuple(np.float32(v) for v in c.location) for c in every}
        gt_locs = coords[gt_idx].astype(np.float32)
        misses.append(1.0 - sum(tuple(r) in found for r in gt_locs) / len(gt_locs))

    # The first query after each view change (the grid re-projects everything).
    changes = []
    for v in range(1, len(views)):
        region, rv3d = views[v]
        q = next((q for q in queries if q[1][v] is not None), None)
        if q is None:
            continue
        mouse, radius = q[1][v]
        t0 = time.perf_counter()
        find(impl, result, q[0], region, rv3d, mouse, radius, backend)
        changes.append(time.perf_counter() - t0)

    times_ms = np.array(times) * 1000.0
    changes_ms = np.array(changes) * 1000.0
    row = {
        "backend": backend or "default",
        "index_ms": round(index_s * 1000.0, 1),
        "index_peak_mb": round(index_peak / 2**20, 1),
        "index_kept_mb": round(kept / 2**20, 1) if kept is not None else None,
        "query_ms_median": percentile(times_ms, 50),
        "query_ms_p95": percentile(times_ms, 95),
        "view_change_ms_median": percentile(changes_ms, 50),
        "view_change_ms_p95": percentile(changes_ms, 95),
        "results_mean": round(float(np.mean(sizes)), 1) if sizes else None,
        "queries": len(times),
        "queries_with_candidates": with_gt,
        "miss_rate": round(float(np.mean(misses)), 4) if misses else None,
        "agreement": round(agree / with_gt, 3) if with_gt else None,
    }
    del result
    return row, lists


def run_scenario(impl, backends, kind, n, scale, queries_count, checked, rng):
    coords = cloud(kind, n, scale, rng)
    views = orbit_views(scale, VIEW_CHANGES + 1)
    queries = make_queries(impl, coords, views, queries_count, scale, rng)
    screen, front = project_all(coords, views[0][1])
    truth = []
    for co, per_view in queries:
        if per_view[0] is None:
            truth.append((None, None))
        else:
            mouse, radius = per_view[0]
            truth.append(ground_truth(coords, screen, front, co, mouse, radius))

    rows, reference = [], None
    for backend in backends:
        row, lists = run_backend(impl, backend, coords, views, queries, truth, checked)
        if reference is None:
            reference = lists
        pairs = [(a, b) for a, b in zip(reference, lists) if a is not None]
        row["identical"] = round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None
        rows.append({"kind": kind, "n": n, "scale": scale, **row})
        print(json.dumps(rows[-1]), flush=True)
    return rows


def scene_build(impl, backend, verts_per_side, budget):
    """Build from a real mesh in the scene (one grid object, Object Mode)."""
    import bmesh
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
    active = bpy.context.active_object
    mesh = bpy.data.meshes.new("BenchGrid")
    grid = bpy.data.objects.new("BenchGrid", mesh)
    bpy.context.scene.collection.objects.link(grid)
    grid.location = (12.0, 0.0, 0.0)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=verts_per_side - 1, y_segments=verts_per_side - 1, size=10.0)
    bm.to_mesh(mesh)
    bm.free()
    bpy.context.view_layer.objects.active = active
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    det = impl.detector
    original = det.get_addon_prefs
    prefs = SimpleNamespace(max_vertex_budget=budget)
    if backend is not None:
        prefs.search_backend = backend
    det.get_addon_prefs = lambda _ctx: prefs
    try:
        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        result = det.build_spatial_tree(bpy.context, active_obj=active)
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        det.get_addon_prefs = original
    return {"backend": backend or "default", "mesh_verts": len(mesh.vertices), "budget": budget,
            "points": result.point_count, "build_ms": round(elapsed * 1000.0, 1),
            "build_peak_mb": round(peak / 2**20, 1)}


def markdown(rows):
    head = ("| cloud | points | backend | index ms | query ms median / p95 | "
            "view change ms median / p95 | index MB (peak / kept) | miss rate | agreement | identical |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for r in rows:
        lines.append(
            f"| {r['kind']} x{r['scale']:g} | {r['n']:,} | {r['backend']} | {r['index_ms']} | "
            f"{r['query_ms_median']} / {r['query_ms_p95']} | "
            f"{r['view_change_ms_median']} / {r['view_change_ms_p95']} | "
            f"{r['index_peak_mb']} / {r['index_kept_mb']} | {r['miss_rate']} | {r['agreement']} | "
            f"{r['identical']} |")
    return "\n".join(lines)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl", default=os.path.join(ROOT_DIR, "smart_clipping"))
    parser.add_argument("--quick", action="store_true", help="skip the 500k-point cases")
    parser.add_argument("--sizes", default=None,
                        help="comma-separated point counts (default 10000,50000,100000,500000)")
    parser.add_argument("--queries", type=int, default=200, help="timed queries per case")
    parser.add_argument("--checked", type=int, default=40,
                        help="queries per case whose full candidate list is checked")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    impl = load_impl(args.impl)
    impl.register()
    backends = impl_backends(impl)
    rng = np.random.default_rng(1234)
    if args.sizes:
        sizes = [int(s) for s in args.sizes.split(",")]
    else:
        sizes = [10_000, 50_000, 100_000] + ([] if args.quick else [500_000])
    rows = []
    for kind in ("uniform", "dense"):
        for n in sizes:
            rows += run_scenario(impl, backends, kind, n, 1.0, args.queries, args.checked, rng)
    for scale in (0.001, 1000.0):
        rows += run_scenario(impl, backends, "uniform", 10_000, scale, args.queries, args.checked, rng)
    scene_rows = []
    for side, budget in ((1000, 50_000), (1000, 1_000_000)):
        for backend in backends:
            scene_rows.append(scene_build(impl, backend, side, budget))
            print(json.dumps(scene_rows[-1]), flush=True)
    print(markdown(rows), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"impl": args.impl, "blender": bpy.app.version_string,
                       "search": rows, "scene_build": scene_rows}, f, indent=1)


if __name__ == "__main__":
    main()
