# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Measure collecting the snap points (the start of a move, and S switching
Snap To) on large evaluated meshes: time, peak memory, and what was kept.

One scenario per run, so each starts from a fresh Blender:

  blender --background --factory-startup --python-exit-code 1 \\
    --python tests/benchmark_build.py -- --verts 4000000 --objects 1 --budget 50000 \\
    [--output results.jsonl]

- ``--verts``: evaluated vertices in total, split over ``--objects`` meshes.
  Each mesh is a grid with a Subdivision Surface modifier (level 2), so the
  snap points come from the evaluated mesh, as in a real scene.
- ``--budget``: Snap Point Limit.
- Peak memory is measured on Linux only (``/proc/self/clear_refs`` resets the
  peak, ``VmHWM`` reads it): the growth of the resident set during the first
  collection, over what the scene already used.  Elsewhere it is left out.
- The scenario is skipped (not run) when the memory it would need, estimated
  generously, is more than half of what the system has available, so the
  benchmark cannot push the machine into swapping.

Prints one line ``[bench] {json}`` and appends it to ``--output`` if given.
"""

import argparse
import gc
import json
import math
import os
import sys
import time
import traceback

import bmesh
import bpy

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import smart_clipping  # noqa: E402
from smart_clipping import detector  # noqa: E402

SUBDIV_LEVELS = 2
# Estimate of the memory one evaluated vertex costs while the scene exists and
# its snap points are collected (base mesh, evaluated mesh, the copy
# to_mesh() makes, coordinate arrays): about twice the ~150 bytes measured on
# Blender 5.2 with 4M vertices.
BYTES_PER_VERTEX = 300


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--verts", type=int, required=True)
    parser.add_argument("--objects", type=int, default=1)
    parser.add_argument("--budget", type=int, default=50_000)
    parser.add_argument("--output", default=None)
    return parser.parse_args(argv)


def _status(field) -> "int | None":
    """A field of /proc/self/status in bytes (Linux), or None."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _reset_peak() -> bool:
    try:
        with open("/proc/self/clear_refs", "w", encoding="ascii") as f:
            f.write("5")
        return True
    except OSError:
        return False


def _available_bytes() -> "int | None":
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _grid_object(name, base_verts_per_side, location):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=base_verts_per_side - 1,
                          y_segments=base_verts_per_side - 1, size=5.0)
    bm.to_mesh(mesh)
    bm.free()
    mod = obj.modifiers.new("Subdivision", "SUBSURF")
    mod.levels = SUBDIV_LEVELS
    mod.render_levels = SUBDIV_LEVELS
    return obj


def main() -> int:
    args = _args()
    result = {"blender": bpy.app.version_string, "verts_target": args.verts,
              "objects": args.objects, "budget": args.budget}

    available = _available_bytes()
    need = args.verts * BYTES_PER_VERTEX
    if available is not None and need > available / 2:
        result.update(skipped=f"needs about {need / 2**30:.1f} GiB, "
                              f"{available / 2**30:.1f} GiB available")
        return _report(result, args.output)

    smart_clipping.register()
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)

    # Grids whose subdivided vertex count adds up to --verts
    per_object = args.verts / args.objects
    side = math.sqrt(per_object)
    base_side = max(2, round((side - 1) / 2 ** SUBDIV_LEVELS) + 1)
    t0 = time.perf_counter()
    active = bpy.data.objects.new("Bench_Active", bpy.data.meshes.new("Bench_Active_Mesh"))
    bpy.context.scene.collection.objects.link(active)
    for i in range(args.objects):
        _grid_object(f"Bench_{i:02d}", base_side, (12.0 * (i + 1), 0.0, 0.0))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = sum(len(o.evaluated_get(depsgraph).data.vertices)
                    for o in bpy.data.objects if o.name.startswith("Bench_") and o is not active)
    result["setup_s"] = round(time.perf_counter() - t0, 2)
    result["verts_evaluated"] = evaluated

    bpy.context.view_layer.objects.active = active
    active.select_set(True)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    class _Prefs:
        max_vertex_budget = args.budget

    detector.get_addon_prefs = lambda _ctx: _Prefs()

    gc.collect()
    rss_before = _status("VmRSS")
    measured = _reset_peak()
    t0 = time.perf_counter()
    build = detector.build_spatial_tree(bpy.context, active_obj=active)
    result["first_build_s"] = round(time.perf_counter() - t0, 3)
    peak = _status("VmHWM") if measured else None
    if rss_before is not None and peak is not None:
        result["rss_before_mib"] = round(rss_before / 2**20)
        result["peak_growth_mib"] = round((peak - rss_before) / 2**20)
    result["points"] = build.point_count
    result["limit_exceeded"] = bool(build.limit_exceeded)
    result["simplified"] = len(set(build.partial_objects) | set(build.bounds_objects))
    result["skipped_objects"] = len(build.skipped_objects)
    del build

    # S switching Snap To collects them again
    gc.collect()
    t0 = time.perf_counter()
    detector.build_spatial_tree(bpy.context, active_obj=active)
    result["rebuild_s"] = round(time.perf_counter() - t0, 3)
    return _report(result, args.output)


def _report(result, output) -> int:
    line = json.dumps(result)
    print(f"[bench] {line}", flush=True)
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
