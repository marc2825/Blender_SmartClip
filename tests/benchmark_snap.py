"""
Performance and accuracy benchmark for snap candidate search (not a pass/fail test).

Usage:
  blender --background --factory-startup --python tests/benchmark_snap.py
  blender --background --factory-startup --python tests/benchmark_snap.py -- --impl PATH/TO/smart_clipping
  blender --background --factory-startup --python tests/benchmark_snap.py -- --quick --json out.json

``--impl`` benchmarks another copy of the package (e.g. an older version
exported with ``git archive``) instead of the one in this repository.

Synthetic point clouds are searched through a mocked perspective view, and
every query is compared with a brute-force ground truth over all points:

- candidate:  within ``THRESHOLD_PX`` on screen of the moving point and
              within the world search radius, in front of the camera
- best:       smallest screen distance; points within ``TIE_PX`` of each
              other on screen are ordered by world distance
- recall:     mean share of the ground-truth candidates that the search
              returns when asked for all of them (missed candidates lower
              it; queries without any candidate are skipped)
- agreement:  share of queries whose top result is the ground-truth best
"""

import argparse
import importlib.util
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

def build(impl, coords):
    det = impl.detector
    if hasattr(det, "build_from_points"):
        return det.build_from_points(coords)
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


def query_radius(impl, region, rv3d, co):
    px = impl.utils.pixel_world_size(region, rv3d, co)
    return px * max(region.width, region.height) * 0.5


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


def find_all(impl, result, co, region, rv3d, mouse, radius):
    """Every candidate the implementation finds (no result-count cap)."""
    import inspect
    params = inspect.signature(impl.detector.find_candidates).parameters
    extra = {"max_results": 10 ** 9} if "max_results" in params else {}
    return impl.detector.find_candidates(result, co, region, rv3d, mouse,
                                         THRESHOLD_PX, radius, **extra)


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


def run_scenario(impl, kind, n, scale, queries, rng):
    coords = cloud(kind, n, scale, rng)
    region, rv3d = perspective_view(Vector((5.0, -18.0, 9.0)) * scale,
                                    Vector((5.0, 5.0, 5.0)) * scale,
                                    near=0.1 * scale, far=1000.0 * scale)
    screen, front = project_all(coords, rv3d)

    tracemalloc.start()
    t0 = time.perf_counter()
    result = build(impl, coords)
    build_s = time.perf_counter() - t0
    _, build_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # query near existing points so most queries have candidates
    picks = rng.choice(n, size=queries, replace=False)
    times, sizes, coverage = [], [], []
    agree = with_gt = 0
    for i in picks:
        co = Vector(coords[i] + rng.normal(0.0, 0.02 * scale, size=3))
        mouse = impl.utils.world_to_screen(region, rv3d, co)
        if mouse is None:
            continue
        radius = query_radius(impl, region, rv3d, co)
        t0 = time.perf_counter()
        cands = impl.detector.find_candidates(result, co, region, rv3d, mouse,
                                              THRESHOLD_PX, radius)
        times.append(time.perf_counter() - t0)
        sizes.append(len(cands))
        gt_idx, best = ground_truth(coords, screen, front, co, mouse, radius)
        if best is None:
            continue
        with_gt += 1
        tol = 1e-6 * max(1.0, scale)
        if cands and np.linalg.norm(np.array(tuple(cands[0].location)) - coords[best]) < tol:
            agree += 1
        found = find_all(impl, result, co, region, rv3d, mouse, radius)
        found_locs = np.round(np.array([tuple(c.location) for c in found]) / tol) if found else None
        gt_locs = np.round(coords[gt_idx] / tol)
        if found_locs is None:
            coverage.append(0.0)
        else:
            found_set = {tuple(r) for r in found_locs}
            coverage.append(sum(tuple(r) in found_set for r in gt_locs) / len(gt_locs))

    times_ms = np.array(times) * 1000.0
    return {
        "kind": kind, "n": n, "scale": scale, "queries": len(times),
        "build_ms": round(build_s * 1000.0, 1),
        "build_peak_mb": round(build_peak / 2**20, 1),
        "query_ms_mean": round(float(times_ms.mean()), 3) if len(times_ms) else None,
        "query_ms_p95": round(float(np.percentile(times_ms, 95)), 3) if len(times_ms) else None,
        "query_ms_max": round(float(times_ms.max()), 3) if len(times_ms) else None,
        "results_mean": round(float(np.mean(sizes)), 1) if sizes else None,
        "queries_with_candidates": with_gt,
        "recall": round(float(np.mean(coverage)), 3) if coverage else None,
        "agreement": round(agree / with_gt, 3) if with_gt else None,
    }


def scene_build(impl, verts_per_side, budget):
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
    det.get_addon_prefs = lambda _ctx: SimpleNamespace(max_vertex_budget=budget)
    try:
        tracemalloc.start()
        t0 = time.perf_counter()
        result = det.build_spatial_tree(bpy.context, active_obj=active)
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        det.get_addon_prefs = original
    return {"mesh_verts": len(mesh.vertices), "budget": budget,
            "points": result.point_count, "build_ms": round(elapsed * 1000.0, 1),
            "build_peak_mb": round(peak / 2**20, 1)}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl", default=os.path.join(ROOT_DIR, "smart_clipping"))
    parser.add_argument("--quick", action="store_true", help="skip the 1M-point cases")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    impl = load_impl(args.impl)
    impl.register()
    rng = np.random.default_rng(1234)
    sizes = [1_000, 10_000, 100_000] + ([] if args.quick else [1_000_000])
    rows = []
    for kind in ("uniform", "dense"):
        for n in sizes:
            queries = 200 if n <= 100_000 else 20
            rows.append(run_scenario(impl, kind, n, 1.0, queries, rng))
            print(json.dumps(rows[-1]), flush=True)
    for scale in (0.001, 1000.0):
        rows.append(run_scenario(impl, "uniform", 10_000, scale, 200, rng))
        print(json.dumps(rows[-1]), flush=True)
    scene_rows = []
    for side, budget in ((1000, 50_000), (1000, 1_000_000)):
        scene_rows.append(scene_build(impl, side, budget))
        print(json.dumps(scene_rows[-1]), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"impl": args.impl, "search": rows, "scene_build": scene_rows}, f, indent=1)


if __name__ == "__main__":
    main()
