"""
Smart Clipping headless test runner for Blender.

Usage:
  blender --background --factory-startup --python tests/headless_test_runner.py
  blender --background --factory-startup --python tests/headless_test_runner.py -- --case budget_fallback
"""

import argparse
import os
import sys
import time
import traceback
from contextlib import contextmanager

import bmesh
import bpy


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import src  # noqa: E402
from src import detector  # noqa: E402


def _ensure_addon_enabled():
    # Register by import path if needed.
    if not hasattr(bpy.types.Scene, "target_scope"):
        try:
            src.register()
        except ValueError:
            # Already registered in this process.
            pass

    # Try creating AddonPreferences entry to allow budget override through prefs.
    if "src" not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module="src")
        except Exception:
            # Not fatal; tests can still run via monkeypatch fallback.
            pass


def _clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False, confirm=False)

    # Purge unused datablocks created by previous tests.
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for coll in list(bpy.data.collections):
        if coll.users == 0:
            bpy.data.collections.remove(coll)


def _add_cube(name, location):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _select_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _new_collection(name):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def _link_to_collection(obj, coll):
    if obj.name not in coll.objects:
        coll.objects.link(obj)

    # Keep object only in desired collection for deterministic scope tests.
    for parent in list(obj.users_collection):
        if parent != coll:
            parent.objects.unlink(obj)


def _create_grid_object(name, location=(0.0, 0.0, 0.0), x_verts=320, y_verts=320):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location

    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm,
        x_segments=max(1, x_verts - 1),
        y_segments=max(1, y_verts - 1),
        size=5.0,
    )
    bm.to_mesh(mesh)
    bm.free()
    return obj


def _ordered_unique_obj_names(build_result):
    order = []
    seen = set()
    for item in build_result.point_meta:
        if item.obj_name not in seen:
            seen.add(item.obj_name)
            order.append(item.obj_name)
    return order


def _get_addon_prefs():
    addon = bpy.context.preferences.addons.get("src")
    return addon.preferences if addon else None


@contextmanager
def _temporary_budget(max_vertex_budget):
    prefs = _get_addon_prefs()
    if prefs is not None:
        old_value = prefs.max_vertex_budget
        prefs.max_vertex_budget = int(max_vertex_budget)
        try:
            yield
        finally:
            prefs.max_vertex_budget = old_value
        return

    original_fn = detector.get_addon_prefs

    class _DummyPrefs:
        def __init__(self, value):
            self.max_vertex_budget = value

    detector.get_addon_prefs = lambda _ctx: _DummyPrefs(int(max_vertex_budget))
    try:
        yield
    finally:
        detector.get_addon_prefs = original_fn


def case_scene_properties_registered():
    assert hasattr(bpy.types.Scene, "smartclip_enabled")
    assert hasattr(bpy.types.Scene, "target_scope")
    assert hasattr(bpy.types.Scene, "target_collection")
    assert hasattr(bpy.types.Scene, "smartclip_runtime_info")
    assert hasattr(bpy.types.Scene, "smartclip_align_x")
    assert hasattr(bpy.types.Scene, "smartclip_align_y")
    assert hasattr(bpy.types.Scene, "smartclip_align_z")


def case_scope_self():
    _clear_scene()
    a = _add_cube("Self_A", (0.0, 0.0, 0.0))
    _add_cube("Self_B", (5.0, 0.0, 0.0))
    _select_only(a)
    scene = bpy.context.scene
    scene.target_scope = "SELF"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=a)

    assert result.point_count == len(a.data.vertices)
    assert all(meta.obj_name == "Self_A" for meta in result.point_meta)
    assert not result.limit_exceeded


def case_scope_selected():
    _clear_scene()
    active = _add_cube("Sel_Active", (0.0, 0.0, 0.0))
    selected = _add_cube("Sel_Target", (3.0, 0.0, 0.0))
    _add_cube("Sel_Ignored", (6.0, 0.0, 0.0))

    bpy.ops.object.select_all(action="DESELECT")
    active.select_set(True)
    selected.select_set(True)
    bpy.context.view_layer.objects.active = active

    scene = bpy.context.scene
    scene.target_scope = "SELECTED"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    assert result.point_count == len(selected.data.vertices)
    assert all(meta.obj_name == "Sel_Target" for meta in result.point_meta)


def case_scope_visible_distance_sort():
    _clear_scene()
    active = _add_cube("Vis_Active", (0.0, 0.0, 0.0))
    _add_cube("Vis_Near", (3.0, 0.0, 0.0))
    _add_cube("Vis_Far", (12.0, 0.0, 0.0))
    _select_only(active)

    scene = bpy.context.scene
    scene.target_scope = "VISIBLE"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    order = _ordered_unique_obj_names(result)
    assert order[:3] == ["Vis_Active", "Vis_Near", "Vis_Far"]
    assert result.point_count == 24
    assert not result.limit_exceeded


def case_budget_fallback_with_cubes():
    _clear_scene()
    active = _add_cube("Budget_Active", (0.0, 0.0, 0.0))
    _add_cube("Budget_B", (3.0, 0.0, 0.0))
    _add_cube("Budget_C", (6.0, 0.0, 0.0))
    _select_only(active)

    scene = bpy.context.scene
    scene.target_scope = "VISIBLE"

    # Cube has 8 vertices; budget 8 forces all but first processed object to BOUNDS mode.
    with _temporary_budget(8):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    assert result.limit_exceeded
    assert len(result.bounds_objects) >= 1
    assert "Budget_B" in result.bounds_objects or "Budget_C" in result.bounds_objects

    per_obj_types = {}
    for m in result.point_meta:
        per_obj_types.setdefault(m.obj_name, set()).add(m.point_type)
    for obj_name in result.bounds_objects:
        assert per_obj_types[obj_name] == {"BOUNDS"}


def case_scope_collection():
    _clear_scene()
    active = _add_cube("Col_Active", (0.0, 0.0, 0.0))
    a1 = _add_cube("Col_A1", (2.0, 0.0, 0.0))
    a2 = _add_cube("Col_A2", (4.0, 0.0, 0.0))
    b1 = _add_cube("Col_B1", (6.0, 0.0, 0.0))
    _select_only(active)

    col_a = _new_collection("SC_Test_A")
    col_b = _new_collection("SC_Test_B")

    _link_to_collection(a1, col_a)
    _link_to_collection(a2, col_a)
    _link_to_collection(b1, col_b)
    _link_to_collection(active, bpy.context.scene.collection)

    scene = bpy.context.scene
    scene.target_scope = "COLLECTION"
    scene.target_collection = col_a

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    target_names = {m.obj_name for m in result.point_meta}
    assert target_names == {"Col_A1", "Col_A2"}
    assert result.point_count == 16


def case_stress_100k_vertices():
    _clear_scene()
    active = _add_cube("Stress_Active", (0.0, 0.0, 0.0))
    heavy = _create_grid_object("Stress_Heavy", location=(20.0, 0.0, 0.0), x_verts=320, y_verts=320)
    _select_only(active)

    scene = bpy.context.scene
    scene.target_scope = "VISIBLE"

    with _temporary_budget(50000):
        start = time.perf_counter()
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
        elapsed = time.perf_counter() - start

    assert len(heavy.data.vertices) >= 100000
    assert result.limit_exceeded
    assert "Stress_Heavy" in result.bounds_objects
    assert result.point_count < 1000
    print(f"[src:test] stress build elapsed: {elapsed:.4f}s")


CASES = {
    "scene_props": case_scene_properties_registered,
    "scope_self": case_scope_self,
    "scope_selected": case_scope_selected,
    "scope_visible_sort": case_scope_visible_distance_sort,
    "budget_fallback": case_budget_fallback_with_cubes,
    "scope_collection": case_scope_collection,
    "stress_100k": case_stress_100k_vertices,
}


def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(CASES.keys()), default=None)
    return parser.parse_args(argv)


def main():
    _ensure_addon_enabled()
    args = _parse_args()
    selected = [args.case] if args.case else list(CASES.keys())

    failures = 0
    print("[src:test] running cases:", ", ".join(selected))
    for name in selected:
        fn = CASES[name]
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")
            traceback.print_exc()

    print(f"[src:test] summary: passed={len(selected) - failures} failed={failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
