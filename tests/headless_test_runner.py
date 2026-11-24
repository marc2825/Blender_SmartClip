# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Smart Clipping headless test runner for Blender.

Usage:
  blender --background --factory-startup --python tests/headless_test_runner.py
  blender --background --factory-startup --python tests/headless_test_runner.py -- --case budget_fallback

With --module NAME the cases run against the add-on already enabled under
that name instead of the source folder, e.g. the installed extension
(``bl_ext.user_default.smart_clipping``, see tests/extension_install_test.py).
"""

import argparse
import importlib
import os
import sys
import time
import traceback
from contextlib import contextmanager
from types import SimpleNamespace

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _module_arg():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--module") + 1] if "--module" in argv[:-1] else None


INSTALLED = _module_arg()            # None: the source folder
PACKAGE = INSTALLED or "smart_clipping"


def _sub(name):
    return importlib.import_module(f"{PACKAGE}.{name}")


smart_clipping = importlib.import_module(PACKAGE)
detector, ops, utils = _sub("detector"), _sub("ops"), _sub("utils")


class Skip(Exception):
    """The case cannot run in this Blender; reported as skipped, not passed."""


def _ensure_addon_enabled():
    if INSTALLED:
        # Installed and enabled by Blender, with its preferences available.
        if INSTALLED not in bpy.context.preferences.addons:
            raise SystemExit(f"{INSTALLED} is not enabled in this Blender")
        return
    # Register by import path (the addon is not installed in this Blender).
    # Preferences stay unavailable, so code falls back to its defaults and
    # tests control the budget through _temporary_budget().
    if not hasattr(bpy.types.Scene, "smartclip_target_scope"):
        smart_clipping.register()


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


@contextmanager
def _temporary_budget(max_vertex_budget, search_backend=None):
    # Always monkeypatch: the real preference clamps to >= 100, which would
    # silently change what the small-budget cases test.  Without
    # *search_backend* the dummy has no such setting (the default applies).
    original_fn = detector.get_addon_prefs

    class _DummyPrefs:
        def __init__(self, value):
            self.max_vertex_budget = value
            if search_backend is not None:
                self.search_backend = search_backend

    detector.get_addon_prefs = lambda _ctx: _DummyPrefs(int(max_vertex_budget))
    try:
        yield
    finally:
        detector.get_addon_prefs = original_fn


def case_scene_properties_registered():
    assert hasattr(bpy.types.Scene, "smartclip_enabled")
    # Pre-1.2 names must be gone (renamed with a prefix in 1.2)
    assert not hasattr(bpy.types.Scene, "target_scope")
    assert not hasattr(bpy.types.Scene, "target_collection")
    assert hasattr(bpy.types.Scene, "smartclip_target_scope")
    assert hasattr(bpy.types.Scene, "smartclip_target_collection")
    # The last move's summary is kept in memory, not saved into files (2.0)
    assert not hasattr(bpy.types.Scene, "smartclip_runtime_info")
    assert hasattr(bpy.types.Scene, "smartclip_align_x")
    assert hasattr(bpy.types.Scene, "smartclip_align_y")
    assert hasattr(bpy.types.Scene, "smartclip_align_z")


def case_scope_self():
    _clear_scene()
    a = _add_cube("Self_A", (0.0, 0.0, 0.0))
    _add_cube("Self_B", (5.0, 0.0, 0.0))
    _select_only(a)
    scene = bpy.context.scene
    scene.smartclip_target_scope = "SELF"

    with _temporary_budget(100000):
        # Object Mode: the whole active object moves -> nothing to snap to.
        obj_mode = detector.build_spatial_tree(bpy.context, active_obj=a)
        # Edit Mode: only the moving vertices are excluded.
        edit_mode = detector.build_spatial_tree(bpy.context, active_obj=a,
                                                moving_verts={a: {0, 1}})

    assert obj_mode.point_count == 0

    assert edit_mode.point_count == len(a.data.vertices) - 2
    assert all(meta.obj_name == "Self_A" for meta in edit_mode.point_meta)
    moving_world = [a.matrix_world @ a.data.vertices[i].co for i in (0, 1)]
    assert all((co - m).length > 1e-6 for co in edit_mode.points for m in moving_world)
    assert not edit_mode.limit_exceeded


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
    scene.smartclip_target_scope = "SELECTED"

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
    scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    order = _ordered_unique_obj_names(result)
    # Active object is skipped in Object Mode (it would always be excluded).
    assert order == ["Vis_Near", "Vis_Far"]
    assert result.point_count == 16
    assert not result.limit_exceeded


def case_budget_fallback_with_cubes():
    _clear_scene()
    active = _add_cube("Budget_Active", (0.0, 0.0, 0.0))
    _add_cube("Budget_B", (3.0, 0.0, 0.0))                                  # 8 verts
    for i, name in enumerate(("Budget_C", "Budget_D", "Budget_E", "Budget_F")):
        _create_grid_object(name, (10.0 + 12.0 * i, 0.0, 0.0), 20, 20)     # 400 verts
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    # Budget 200 = B (8) + C: 9 stand-ins + 163 sampled vertices, keeping
    # 20 (3 later objects x 9, capped at a tenth of the budget) for D and E,
    # which get only their stand-ins.  2 points remain, so F is skipped.
    with _temporary_budget(200):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    assert result.limit_exceeded
    assert result.partial_objects == ["Budget_C"]
    assert result.bounds_objects == ["Budget_D", "Budget_E"]
    assert result.skipped_objects == ["Budget_F"]
    assert result.point_count == 8 + 9 + 163 + 9 + 9
    assert result.source_vertex_count == 8 + 163

    per_obj_types = {}
    for m in result.point_meta:
        per_obj_types.setdefault(m.obj_name, set()).add(m.point_type)
    assert per_obj_types["Budget_B"] == {"POINT"}
    assert per_obj_types["Budget_C"] == {"POINT", "BOUNDS"}
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
    scene.smartclip_target_scope = "COLLECTION"
    scene.smartclip_target_collection = col_a

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
    scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(50000):
        start = time.perf_counter()
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
        elapsed = time.perf_counter() - start

    assert len(heavy.data.vertices) >= 100000
    assert result.limit_exceeded
    # The heavy mesh is down-sampled to fill the budget (plus its 9 bounds points).
    assert result.partial_objects == ["Stress_Heavy"]
    assert result.bounds_objects == []
    assert 0 < result.source_vertex_count <= 50000
    assert result.point_count == result.source_vertex_count + 9
    types = {m.point_type for m in result.point_meta}
    assert types == {"POINT", "BOUNDS"}
    print(f"[smartclip:test] stress build elapsed: {elapsed:.4f}s "
          f"(snap points: {result.point_count})")


def case_budget_partial_fill():
    _clear_scene()
    active = _add_cube("Part_Active", (0.0, 0.0, 0.0))
    _add_cube("Part_Cube", (3.0, 0.0, 0.0))                        # 8 verts, nearest
    _create_grid_object("Part_Grid", (8.0, 0.0, 0.0), 20, 20)       # 400 verts
    _add_cube("Part_Far", (30.0, 0.0, 0.0))                         # 8 verts, farthest
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(108):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    # Cube fits (8); the grid crossing the limit gets its 9 stand-ins and a
    # sample of the remaining slots, minus 9 kept for the far cube, which
    # then fits with its own 8 vertices (cheaper than stand-ins).
    assert result.limit_exceeded
    assert result.partial_objects == ["Part_Grid"]
    assert result.bounds_objects == []
    assert result.point_count <= 108
    grid_points = [m for m in result.point_meta
                   if m.obj_name == "Part_Grid" and m.point_type == "POINT"]
    assert len(grid_points) == 108 - 8 - 9 - 9, len(grid_points)
    far = [m for m in result.point_meta if m.obj_name == "Part_Far"]
    assert len(far) == 8 and all(m.point_type == "POINT" for m in far)


def case_budget_exactly_used_up():
    # Issue #32: the first object fills the budget exactly, so the next one
    # is left out; that is the limit being reached.
    _clear_scene()
    active = _add_cube("Exact_Active", (0.0, 0.0, 0.0))
    _add_cube("Exact_Near", (3.0, 0.0, 0.0))                        # 8 verts
    _add_cube("Exact_Far", (9.0, 0.0, 0.0))                         # 8 verts
    empty_mesh = bpy.data.meshes.new("Exact_Empty_Mesh")
    empty = bpy.data.objects.new("Exact_Empty", empty_mesh)          # no vertices
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (20.0, 0.0, 0.0)
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(8):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
    assert result.point_count == 8, result.point_count
    assert result.limit_exceeded
    assert result.skipped_objects == ["Exact_Far"], result.skipped_objects
    summary = ops.build_summary(result)
    assert summary.limit_exceeded and summary.skipped == 1, summary

    # Everything fits exactly: no warning (the empty mesh loses nothing)
    bpy.data.objects.remove(bpy.data.objects["Exact_Far"])
    with _temporary_budget(8):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
    assert result.point_count == 8, result.point_count
    assert not result.limit_exceeded
    assert result.skipped_objects == [], result.skipped_objects

    # Exactly used up in Edit Mode, by the rest of the edited mesh
    _select_only(active)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bm = bmesh.from_edit_mesh(active.data)
        bm.verts.ensure_lookup_table()
        for i, v in enumerate(bm.verts):
            v.select_set(i == 0)
        bmesh.update_edit_mesh(active.data)
        bpy.context.scene.smartclip_target_scope = "VISIBLE"
        with _temporary_budget(7):
            result = detector.build_spatial_tree(
                bpy.context, active_obj=active, moving_verts={active: {0}})
        names = [m.obj_name for m in result.point_meta]
        assert names.count("Exact_Active") == 7, names
        assert result.limit_exceeded
        assert result.skipped_objects == ["Exact_Near"], result.skipped_objects
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def case_scope_collection_recursive():
    _clear_scene()
    active = _add_cube("Rec_Active", (0.0, 0.0, 0.0))
    top_obj = _add_cube("Rec_Top", (2.0, 0.0, 0.0))
    child_obj = _add_cube("Rec_Child", (4.0, 0.0, 0.0))
    _select_only(active)

    parent = _new_collection("SC_Rec_Parent")
    child = bpy.data.collections.new("SC_Rec_Child")
    parent.children.link(child)
    _link_to_collection(top_obj, parent)
    _link_to_collection(child_obj, child)

    scene = bpy.context.scene
    scene.smartclip_target_scope = "COLLECTION"
    scene.smartclip_target_collection = parent

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    assert {m.obj_name for m in result.point_meta} == {"Rec_Top", "Rec_Child"}


def case_edit_mode_sync():
    _clear_scene()
    obj = _add_cube("Edit_Sync", (1.0, 2.0, 3.0))
    _select_only(obj)
    bpy.context.scene.smartclip_target_scope = "SELF"

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.new((5.0, 0.0, 0.0))
        bm.verts.ensure_lookup_table()
        new_index = len(bm.verts) - 1
        bmesh.update_edit_mesh(obj.data)
        # obj.data.vertices is stale until the edit mesh is flushed
        assert len(obj.data.vertices) == 8

        with _temporary_budget(100000):
            result = detector.build_spatial_tree(
                bpy.context, active_obj=obj, moving_verts={obj: {new_index}},
            )
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    # The flushed mesh has 9 vertices; the new (moving) one is left out and
    # the 8 others are its correct, current positions.
    assert result.point_count == 8, result.point_count
    moving = obj.matrix_world @ Vector((5.0, 0.0, 0.0))
    assert all((co - moving).length > 1e-5 for co in result.points)
    corners = {tuple(round(v, 4) for v in obj.matrix_world @ Vector(c))
               for c in ((sx, sy, sz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1))}
    assert {tuple(round(v, 4) for v in co) for co in result.points} == corners


def case_parent_space_delta():
    _clear_scene()
    parent = _add_cube("PS_Parent", (5.0, -2.0, 1.0))
    parent.rotation_euler = (0.3, 0.0, 1.2)
    parent.scale = (2.0, 0.5, 1.5)
    child = _add_cube("PS_Child", (1.0, 1.0, 1.0))
    bpy.context.view_layer.update()
    # Parent like Ctrl+P (keep transform): sets matrix_parent_inverse.
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    # Transform the parent afterwards; until then the parent space is the
    # identity and `location` coincides with the world position.
    parent.location = (6.0, -1.0, 2.0)
    parent.rotation_euler = (0.3, 0.2, 2.0)
    parent.scale = (1.5, 0.8, 1.2)
    bpy.context.view_layer.update()

    start_loc = child.location.copy()
    start_world = child.matrix_world.translation.copy()
    to_loc = utils.world_to_location_matrix(child)

    # Zero movement must not move the object (the old code jumped here,
    # because it wrote the world position into the parent-space location).
    child.location = start_loc + to_loc @ Vector((0.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    assert (child.matrix_world.translation - start_world).length < 1e-5

    delta = Vector((0.7, -1.3, 2.1))
    child.location = start_loc + to_loc @ delta
    bpy.context.view_layer.update()
    moved = child.matrix_world.translation - start_world
    assert (moved - delta).length < 1e-4, (moved, delta)

    # Unparented: identity
    assert utils.world_to_location_matrix(parent) == Matrix.Identity(3)


def case_constraint_helpers():
    v = Vector((1.0, 2.0, 3.0))
    assert tuple(utils.apply_constraint(v, None)) == (1.0, 2.0, 3.0)
    assert tuple(utils.apply_constraint(v, "X")) == (1.0, 0.0, 0.0)
    assert tuple(utils.apply_constraint(v, "Z")) == (0.0, 0.0, 3.0)
    assert tuple(utils.apply_constraint(v, "YZ")) == (0.0, 2.0, 3.0)
    assert tuple(utils.apply_constraint(v, "XY")) == (1.0, 2.0, 0.0)
    assert utils.constraint_axes(None) == {"X", "Y", "Z"}
    assert utils.constraint_axes("XZ") == {"X", "Z"}


# --- Synthetic top-ortho view: 50 px per world unit, origin at (500, 500) ---

def _top_view():
    region = SimpleNamespace(width=1000, height=1000)
    rv3d = SimpleNamespace(
        perspective_matrix=Matrix.Diagonal((0.1, 0.1, -0.01, 1.0)),
        view_matrix=Matrix.Identity(4),  # looking down -Z
        is_perspective=False,
        view_perspective="ORTHO",
    )
    return region, rv3d


def _top_view_scaled(scale):
    """Top ortho view showing 50 px per (scale) world units."""
    region = SimpleNamespace(width=1000, height=1000)
    rv3d = SimpleNamespace(
        perspective_matrix=Matrix.Diagonal((0.1 / scale, 0.1 / scale, -0.01 / scale, 1.0)),
        view_matrix=Matrix.Identity(4),
        is_perspective=False,
        view_perspective="ORTHO",
    )
    return region, rv3d


def _perspective_view(eye, target, fov_deg=50.0, size=(1600, 900)):
    import math
    width, height = size
    near, far = 0.1, 1000.0
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    proj = Matrix((
        (f * height / width, 0.0, 0.0, 0.0),
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
    region = SimpleNamespace(width=width, height=height)
    rv3d = SimpleNamespace(perspective_matrix=proj @ view, view_matrix=view,
                           is_perspective=True, view_perspective="PERSP",
                           view_distance=(target - eye).length)
    return region, rv3d


def _build_from_points(coords, names=None, exclude=()):
    return detector.build_from_points(coords, names=names, exclude=exclude)


def case_axis_align_screen_gate():
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    build = _build_from_points([
        (0.2, 5.0, 0.0),    # x within 10 px  -> candidate
        (0.2, -1.0, 0.0),   # same x, closer reference -> preferred reference
        (10.0, 3.0, 0.0),   # x 500 px away   -> rejected by the pixel gate
        (0.0, 0.0, 4.0),    # z alignment     -> Z points into the screen
    ])

    cands = detector.find_axis_candidates(
        build, current, region, rv3d, mouse, snap_distance_px=30, axis_flags={"X"},
    )
    xs = sorted(round(c.location.x, 4) for c in cands)
    assert xs == [0.0, 0.2], xs
    best_02 = next(c for c in cands if abs(c.location.x - 0.2) < 1e-6)
    assert (best_02.reference_co - Vector((0.2, -1.0, 0.0))).length < 1e-6
    assert abs(best_02.screen_dist - 10.0) < 1e-3

    # Axis parallel to the view direction is skipped entirely.
    assert detector.find_axis_candidates(
        build, current, region, rv3d, mouse, snap_distance_px=30, axis_flags={"Z"},
    ) == []

    # A tighter gate rejects the 10 px candidate.
    cands = detector.find_axis_candidates(
        build, current, region, rv3d, mouse, snap_distance_px=5, axis_flags={"X"},
    )
    assert [round(c.location.x, 4) for c in cands] == [0.0]


def case_axis_align_nearest_in_dense_data():
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    # ~8k values in [-40, -1] used to fill the old fixed 5000-entry scan
    # window (which started at the low end) before 0.1 was reached.
    coords = [(-40.0 + i * 0.0049, 7.0, 0.0) for i in range(7960)]
    coords.append((0.1, 2.0, 0.0))
    build = _build_from_points(coords)

    cands = detector.find_axis_candidates(
        build, current, region, rv3d, mouse, snap_distance_px=30, axis_flags={"X"},
    )
    assert cands, "nearby alignment value not found"
    assert abs(cands[0].location.x - 0.1) < 1e-6


def case_find_candidates_hit_cap_skips_excluded():
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    near = [(0.001 * i, 0.0, 0.0) for i in range(200)]   # excluded (moving verts)
    coords = near + [(0.3, 0.0, 0.0), (0.0, 4.0, 0.0)]
    build = _build_from_points(coords, exclude=range(200))

    cands = detector.find_candidates(
        build, current, region, rv3d, mouse,
        snap_distance_px=30, query_radius=10.0, max_results=8,
    )
    assert len(cands) == 1  # (0,4,0) is 200 px away
    assert (cands[0].location - Vector((0.3, 0.0, 0.0))).length < 1e-6


def case_object_mode_excludes_movers_and_children():
    _clear_scene()
    a = _add_cube("Mv_A", (0.0, 0.0, 0.0))
    b = _add_cube("Mv_B", (3.0, 0.0, 0.0))
    child = _add_cube("Mv_BChild", (3.0, 3.0, 0.0))
    _add_cube("Mv_Target", (6.0, 0.0, 0.0))
    child.parent = b
    _select_only(a)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=a,
                                             exclude_objects=[a, b])

    # Moving objects and the child that moves with its parent are not targets.
    assert {m.obj_name for m in result.point_meta} == {"Mv_Target"}


def case_evaluated_mesh_targets():
    _clear_scene()
    active = _add_cube("Ev_Active", (0.0, 0.0, 0.0))
    arrayed = _add_cube("Ev_Array", (4.0, 0.0, 0.0))
    mod = arrayed.modifiers.new("Array", "ARRAY")
    mod.count = 3
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"

    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    # Snap targets follow what is displayed (modifiers applied).
    assert result.point_count == 24, result.point_count
    far_x = max(co.x for co in result.points)
    assert abs(far_x - (4.0 + 1.0 + 2 * 2.0)) < 1e-4, far_x


def _run_move(offset):
    bpy.ops.view3d.smartclip_move(offset=offset)


def case_execute_moves_all_selected():
    _clear_scene()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.smartclip_target_scope = "VISIBLE"
    parent = _add_cube("Ex_Parent", (0.0, 0.0, 0.0))
    parent.rotation_euler = (0.0, 0.0, 0.7)
    child = _add_cube("Ex_Child", (2.0, 0.0, 0.0))
    other = _add_cube("Ex_Other", (0.0, 4.0, 0.0))
    locked = _add_cube("Ex_Locked", (0.0, -4.0, 0.0))
    locked.lock_location = (False, True, False)
    bpy.context.view_layer.update()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    unselected = _add_cube("Ex_Unselected", (9.0, 9.0, 0.0))
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    for obj in (parent, child, other, locked):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = parent

    before = {o.name: o.matrix_world.translation.copy()
              for o in (parent, child, other, locked, unselected)}
    pivot, movers = ops.gather_movers(bpy.context)
    # The child moves with its parent, so it is not a mover itself.
    assert sorted(m.obj.name for m in movers) == ["Ex_Locked", "Ex_Other", "Ex_Parent"]
    assert (pivot - before["Ex_Parent"]).length < 1e-6

    delta = Vector((1.0, 2.0, 3.0))
    _run_move(delta)
    bpy.context.view_layer.update()

    for name in ("Ex_Parent", "Ex_Child", "Ex_Other"):
        moved = bpy.data.objects[name].matrix_world.translation - before[name]
        assert (moved - delta).length < 1e-4, (name, moved)
    moved = locked.matrix_world.translation - before["Ex_Locked"]
    assert (moved - Vector((1.0, 0.0, 3.0))).length < 1e-4, moved  # Y locked
    assert (unselected.matrix_world.translation - before["Ex_Unselected"]).length < 1e-9


def case_selected_scope_moves_active_only():
    _clear_scene()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.smartclip_target_scope = "SELECTED"
    active = _add_cube("SS_Active", (0.0, 0.0, 0.0))
    child = _add_cube("SS_ActiveChild", (0.0, 3.0, 0.0))
    child.parent = active
    target = _add_cube("SS_Target", (4.0, 0.0, 0.0))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in (active, child, target):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.context.view_layer.update()
    target_before = target.matrix_world.translation.copy()
    child_before = child.matrix_world.translation.copy()

    # Selected scope snaps the active object to the other selected objects:
    # only the active object (with its child) moves, the rest are targets.
    pivot, movers = ops.gather_movers(bpy.context)
    assert [m.obj.name for m in movers] == ["SS_Active"]
    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active,
                                             exclude_objects=[m.obj for m in movers])
    assert {m.obj_name for m in result.point_meta} == {"SS_Target"}

    delta = Vector((0.0, 0.0, 1.5))
    _run_move(delta)
    bpy.context.view_layer.update()
    assert (active.matrix_world.translation - delta).length < 1e-5
    assert (child.matrix_world.translation - child_before - delta).length < 1e-5
    assert (target.matrix_world.translation - target_before).length < 1e-9


def case_execute_edit_mode_multi_object():
    _clear_scene()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    a = _add_cube("EM_A", (0.0, 0.0, 0.0))
    b = _add_cube("EM_B", (5.0, 0.0, 0.0))
    b.scale = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for obj in (a, b):
            bm = bmesh.from_edit_mesh(obj.data)
            for v in bm.verts:
                v.select = False
            bm.verts.ensure_lookup_table()
            bm.verts[0].select = True
            bmesh.update_edit_mesh(obj.data)
        starts = {}
        for obj in (a, b):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            starts[obj.name] = (obj.matrix_world @ bm.verts[0].co,
                                obj.matrix_world @ bm.verts[1].co)

        pivot, movers = ops.gather_movers(bpy.context)
        assert sorted(m.obj.name for m in movers) == ["EM_A", "EM_B"]
        expected_pivot = (starts["EM_A"][0] + starts["EM_B"][0]) / 2
        assert (pivot - expected_pivot).length < 1e-5

        delta = Vector((0.5, -1.0, 2.0))
        _run_move(delta)

        for obj in (a, b):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            moved = obj.matrix_world @ bm.verts[0].co - starts[obj.name][0]
            still = obj.matrix_world @ bm.verts[1].co - starts[obj.name][1]
            assert (moved - delta).length < 1e-4, (obj.name, moved)
            assert still.length < 1e-6
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def case_legacy_scene_property_migration():
    from bpy.props import EnumProperty, PointerProperty

    coll = bpy.data.collections.new("SC_Legacy")
    # (a) values written through the pre-1.2 bpy.props definitions; Blender 5.x
    #     keeps them in the system-property storage
    legacy_a = bpy.data.scenes.new("SC_Legacy_A")
    bpy.types.Scene.target_scope = EnumProperty(items=[
        ("SELF", "", ""), ("SELECTED", "", ""), ("VISIBLE", "", ""), ("COLLECTION", "", ""),
    ], default="VISIBLE")
    bpy.types.Scene.target_collection = PointerProperty(type=bpy.types.Collection)
    try:
        legacy_a.target_scope = "COLLECTION"
        legacy_a.target_collection = coll
    finally:
        del bpy.types.Scene.target_scope
        del bpy.types.Scene.target_collection
    # (b) values stored as plain ID properties (Blender 4.x storage)
    legacy_b = bpy.data.scenes.new("SC_Legacy_B")
    legacy_b["target_scope"] = 1
    # (c) already-set prefixed values must not be overwritten
    legacy_c = bpy.data.scenes.new("SC_Legacy_C")
    legacy_c["target_scope"] = 0
    legacy_c.smartclip_target_scope = "VISIBLE"

    try:
        smart_clipping.migrate_legacy_scene_properties()
        assert legacy_a.smartclip_target_scope == "COLLECTION"
        assert legacy_a.smartclip_target_collection == coll
        assert legacy_b.smartclip_target_scope == "SELECTED"
        assert legacy_b.smartclip_target_collection is None
        assert legacy_c.smartclip_target_scope == "VISIBLE"
    finally:
        for sc in (legacy_a, legacy_b, legacy_c):
            bpy.data.scenes.remove(sc)
        bpy.data.collections.remove(coll)


def case_pixel_world_size():
    region, rv3d = _top_view()
    # 50 px per world unit in the synthetic top view
    size = utils.pixel_world_size(region, rv3d, Vector((1.0, 2.0, 0.0)))
    assert abs(size - 0.02) < 1e-5, size


# --- Keymap / scene enable (issue 3) -------------------------------------

def _addon_kmis():
    return [kmi for _km, kmi in smart_clipping._addon_keymaps]


def case_keymap_independent_of_scene_enable():
    scene = bpy.context.scene
    kmis = _addon_kmis()
    assert kmis, "addon keymap items were not registered"
    bpy.ops.smartclip.add_default_hotkeys()
    try:
        scene.smartclip_enabled = False
        # Disabling Smart Clipping in one scene must not switch the shared
        # keymap off (another scene may have it enabled); poll() blocks the
        # operator instead so Shift+G falls through to Blender's own item.
        assert all(kmi.active for kmi in kmis)
        assert not smart_clipping.SMARTCLIP_OT_modal_move.poll(bpy.context)
        scene.smartclip_enabled = True
        assert smart_clipping.SMARTCLIP_OT_modal_move.poll(bpy.context)
    finally:
        scene.smartclip_enabled = True


def case_clear_hotkeys_stays_cleared():
    scene = bpy.context.scene
    kmis = _addon_kmis()
    try:
        bpy.ops.smartclip.clear_hotkeys()
        assert not any(kmi.active for kmi in kmis)
        # Toggling the scene setting or loading a file must not bring a
        # removed assignment back.
        scene.smartclip_enabled = False
        scene.smartclip_enabled = True
        for handler in list(bpy.app.handlers.load_post):
            if getattr(handler, "__module__", "").startswith(PACKAGE):
                handler(None)
        assert not any(kmi.active for kmi in kmis), [kmi.active for kmi in kmis]
        bpy.ops.smartclip.add_default_hotkeys()
        assert all(kmi.active for kmi in kmis)
    finally:
        bpy.ops.smartclip.add_default_hotkeys()
        scene.smartclip_enabled = True


# --- Vertex budget (issues 1.1 / 1.3) ------------------------------------

def _usable_points(result):
    exclude = result.exclude_indices
    return [(co, m) for i, (co, m) in enumerate(zip(result.points, result.point_meta))
            if i not in exclude]


def case_moving_vertices_do_not_use_budget():
    _clear_scene()
    obj = _create_grid_object("MB_Grid", (0.0, 0.0, 0.0), 20, 20)   # 400 verts
    _select_only(obj)
    bpy.context.scene.smartclip_target_scope = "SELF"
    moving = set(range(300))
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        with _temporary_budget(150):
            result = detector.build_spatial_tree(bpy.context, active_obj=obj,
                                                 moving_verts={obj: moving})
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    usable = [m for _co, m in _usable_points(result) if m.point_type == "POINT"]
    # The 100 vertices that stay put fit in the budget of 150; the moving
    # ones are never candidates, so they must not take budget or be sampled.
    assert len(usable) == 100, len(usable)
    assert not result.limit_exceeded
    moving_world = {tuple(round(v, 5) for v in obj.matrix_world @ obj.data.vertices[i].co)
                    for i in moving}
    assert not any(tuple(round(v, 5) for v in co) in moving_world
                   for co, _m in _usable_points(result))


def case_shared_mesh_moving_vertices_excluded():
    _clear_scene()
    a = _add_cube("SM_A", (0.0, 0.0, 0.0))
    b = a.copy()                       # linked duplicate: same mesh datablock
    b.name = "SM_B"
    b.location = (5.0, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(b)
    bpy.context.view_layer.update()
    _select_only(a)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        with _temporary_budget(100000):
            result = detector.build_spatial_tree(bpy.context, active_obj=a,
                                                 moving_verts={a: {0}})
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    # Vertex 0 moves in the shared mesh, so it moves on SM_B as well and its
    # start position on SM_B is not a valid target.
    b_v0 = b.matrix_world @ b.data.vertices[0].co
    a_v0 = a.matrix_world @ a.data.vertices[0].co
    usable = [co for co, _m in _usable_points(result)]
    assert all((co - b_v0).length > 1e-5 for co in usable)
    assert all((co - a_v0).length > 1e-5 for co in usable)
    assert len(usable) == 14, len(usable)  # 7 + 7 remaining vertices


def case_budget_caps_total_points():
    _clear_scene()
    active = _add_cube("BC_Active", (-3.0, 0.0, 0.0))
    for i in range(150):
        _add_cube(f"BC_{i:03d}", (3.0 * i, 0.0, 0.0))
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    with _temporary_budget(100):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
    # Bounding-box stand-ins count against the budget too, so the number of
    # snap points stays bounded however many objects are in scope.
    assert result.point_count <= 100, result.point_count
    assert result.limit_exceeded


def case_budget_sampling_covers_mesh():
    _clear_scene()
    active = _add_cube("SC_Active", (0.0, 0.0, 20.0))
    grid = _create_grid_object("SC_Grid", (0.0, 0.0, 0.0), 320, 320)   # 102,400 verts
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    # 102,400 / 320 = 320: a stride sample would take every 320th vertex,
    # i.e. one column of the 320-wide grid.
    with _temporary_budget(320):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
    pts = [co for co, m in zip(result.points, result.point_meta)
           if m.obj_name == "SC_Grid" and m.point_type == "POINT"]
    assert len(pts) > 100, len(pts)
    xs = [co.x for co in pts]
    ys = [co.y for co in pts]
    # A stride equal to the grid row length used to pick a single column.
    assert max(xs) - min(xs) > 8.0 and max(ys) - min(ys) > 8.0, (min(xs), max(xs))


# --- Candidate ranking and recall (issues 1.2 / 1.4 / 1.5) ---------------

def case_ranking_independent_of_scene_scale():
    winners = []
    for scale in (0.001, 1.0, 1000.0):
        region, rv3d = _top_view_scaled(scale)
        current = Vector((0.0, 0.0, 0.0))
        mouse = utils.world_to_screen(region, rv3d, current)
        build = _build_from_points([
            (0.12 * scale, 0.0, -3.0 * scale),   # 6 px away on screen, deep
            (0.40 * scale, 0.0, 0.0),            # 20 px away, close in 3D
        ], names=["Near_On_Screen", "Near_In_3D"])
        cands = detector.find_candidates(build, current, region, rv3d, mouse,
                                         snap_distance_px=30, query_radius=1e9)
        winners.append(cands[0].target_name)
    # The candidate closest on screen wins at every scene scale.
    assert winners == ["Near_On_Screen"] * 3, winners


def case_ranking_ties_prefer_nearest_in_3d():
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    build = _build_from_points([(0.2, 0.0, -5.0), (0.2, 0.01, 1.0)],
                               names=["Behind", "Front"])
    cands = detector.find_candidates(build, current, region, rv3d, mouse,
                                     snap_distance_px=30, query_radius=1e9)
    assert cands[0].target_name == "Front", [c.target_name for c in cands]


def case_find_recall_with_crowded_neighbours():
    import math
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    # 2,000 points close in 3D but more than 30 px away on screen ...
    ring = [(1.1 * math.cos(t), 1.1 * math.sin(t), 0.0)
            for t in (2 * math.pi * k / 2000 for k in range(2000))]
    # ... and one point 20 px away on screen but farther in 3D.
    build = _build_from_points(ring + [(0.4, 0.0, 5.0)])
    cands = detector.find_candidates(build, current, region, rv3d, mouse,
                                     snap_distance_px=30, query_radius=10.0)
    assert cands, "the only on-screen candidate was not examined"
    assert (cands[0].location - Vector((0.4, 0.0, 5.0))).length < 1e-5


def _brute_force_best(coords, region, rv3d, current, mouse, thr, radius, exclude=()):
    best = None
    for i, c in enumerate(coords):
        if i in exclude:
            continue
        s = utils.world_to_screen(region, rv3d, Vector(c))
        if s is None:
            continue
        d = (s - mouse).length
        w = (Vector(c) - current).length
        if d <= thr and w <= radius:
            key = (int(d // 2.0), w)
            if best is None or key < best[0]:
                best = (key, i)
    return None if best is None else best[1]


def case_find_matches_brute_force_perspective():
    import random
    rnd = random.Random(7)
    region, rv3d = _perspective_view((5.0, -15.0, 8.0), (5.0, 5.0, 5.0))
    coords = [(rnd.uniform(0, 10), rnd.uniform(0, 10), rnd.uniform(0, 10)) for _ in range(3000)]
    build = _build_from_points(coords)
    checked = 0
    for k in range(60):
        current = Vector(coords[rnd.randrange(len(coords))]) + Vector(
            (rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3)))
        mouse = utils.world_to_screen(region, rv3d, current)
        expected = _brute_force_best(coords, region, rv3d, current, mouse, 30, 6.0)
        cands = detector.find_candidates(build, current, region, rv3d, mouse,
                                         snap_distance_px=30, query_radius=6.0)
        if expected is None:
            assert not cands
            continue
        checked += 1
        assert cands and (cands[0].location - Vector(coords[expected])).length < 1e-5, k
    assert checked > 30, checked


def case_axis_align_skips_excluded_run():
    region, rv3d = _top_view()
    current = Vector((0.0, 0.0, 0.0))
    mouse = utils.world_to_screen(region, rv3d, current)
    # 30,000 excluded points share the nearest x value; the scan must not
    # give up before reaching the valid one behind them.
    coords = [(0.05, 1.0 + i * 1e-4, 0.0) for i in range(30000)] + [(0.1, 3.0, 0.0)]
    build = _build_from_points(coords, exclude=range(30000))
    cands = detector.find_axis_candidates(build, current, region, rv3d, mouse,
                                          snap_distance_px=30, axis_flags={"X"})
    assert cands and abs(cands[0].location.x - 0.1) < 1e-6, [c.location.x for c in cands]


def case_axis_align_matches_brute_force_perspective():
    import random
    rnd = random.Random(11)
    region, rv3d = _perspective_view((-6.0, -14.0, 9.0), (4.0, 4.0, 3.0))
    coords = [(rnd.uniform(0, 8), rnd.uniform(0, 8), rnd.uniform(0, 6)) for _ in range(1500)]
    build = _build_from_points(coords)
    checked = 0
    for k in range(40):
        current = Vector((rnd.uniform(0, 8), rnd.uniform(0, 8), rnd.uniform(0, 6)))
        mouse = utils.world_to_screen(region, rv3d, current)
        for axis, idx in (("X", 0), ("Y", 1), ("Z", 2)):
            best = None
            for c in coords:
                align = current.copy()
                align[idx] = c[idx]
                s = utils.world_to_screen(region, rv3d, align)
                if s is None:
                    continue
                d = (s - mouse).length
                if d <= 30:
                    key = (int(d // 2.0), abs(c[idx] - current[idx]))
                    if best is None or key < best[0]:
                        best = (key, c[idx])
            cands = detector.find_axis_candidates(build, current, region, rv3d, mouse,
                                                  snap_distance_px=30, axis_flags={axis})
            if best is None:
                assert not cands
                continue
            checked += 1
            assert cands and abs(cands[0].location[idx] - best[1]) < 1e-6, (k, axis)
    assert checked > 60, checked


# --- Target Scope collection (#15) ----------------------------------------

def _edit_select_only_vertex(obj, index):
    bm = bmesh.from_edit_mesh(obj.data)
    for v in bm.verts:
        v.select = False
    bm.verts.ensure_lookup_table()
    bm.verts[index].select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def _points_by_object(result):
    counts = {}
    for m in result.point_meta:
        counts[m.obj_name] = counts.get(m.obj_name, 0) + 1
    return counts


def case_edit_selected_scope_includes_active_rest():
    _clear_scene()
    a = _add_cube("ES_A", (0.0, 0.0, 0.0))
    b = _add_cube("ES_B", (4.0, 0.0, 0.0))
    bpy.ops.object.select_all(action="DESELECT")
    b.select_set(True)
    a.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.context.scene.smartclip_target_scope = "SELECTED"
    bpy.ops.object.mode_set(mode="EDIT")       # both are meshes: both enter Edit Mode
    try:
        _edit_select_only_vertex(a, 0)
        _edit_select_only_vertex(b, 0)
        pivot, movers = ops.gather_movers(bpy.context)
        with _temporary_budget(100000):
            result = detector.build_spatial_tree(
                bpy.context, active_obj=a,
                moving_verts={m.obj: set(m.init_cos) for m in movers})
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    # In Edit Mode only the selected vertices move; the rest of every selected
    # mesh, the active one included, are targets.
    assert _points_by_object(result) == {"ES_A": 7, "ES_B": 7}, _points_by_object(result)


def case_edit_self_scope_covers_all_edited_meshes():
    _clear_scene()
    a = _add_cube("SE_A", (0.0, 0.0, 0.0))
    b = _add_cube("SE_B", (4.0, 0.0, 0.0))
    _add_cube("SE_Other", (8.0, 0.0, 0.0))
    bpy.ops.object.select_all(action="DESELECT")
    b.select_set(True)
    a.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.context.scene.smartclip_target_scope = "SELF"
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        _edit_select_only_vertex(a, 0)
        _edit_select_only_vertex(b, 0)
        pivot, movers = ops.gather_movers(bpy.context)
        with _temporary_budget(100000):
            result = detector.build_spatial_tree(
                bpy.context, active_obj=a,
                moving_verts={m.obj: set(m.init_cos) for m in movers})
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    # Self Only = the meshes being edited (all of them), not other objects.
    assert _points_by_object(result) == {"SE_A": 7, "SE_B": 7}, _points_by_object(result)


def case_collection_scope_skips_hidden():
    _clear_scene()
    active = _add_cube("CH_Active", (0.0, 0.0, 0.0))
    shown = _add_cube("CH_Shown", (3.0, 0.0, 0.0))
    hidden = _add_cube("CH_Hidden", (6.0, 0.0, 0.0))
    disabled = _add_cube("CH_Disabled", (9.0, 0.0, 0.0))
    coll = _new_collection("SC_Hidden_Test")
    for obj in (shown, hidden, disabled):
        _link_to_collection(obj, coll)
    hidden.hide_set(True)
    disabled.hide_viewport = True
    _select_only(active)
    scene = bpy.context.scene
    scene.smartclip_target_scope = "COLLECTION"
    scene.smartclip_target_collection = coll
    with _temporary_budget(100000):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)
    # Objects you cannot see are not snap targets (as with All Visible).
    assert _points_by_object(result) == {"CH_Shown": 8}, _points_by_object(result)


# --- Robustness (#17) -------------------------------------------------------

def case_non_finite_vertices_dropped():
    import math
    import warnings
    _clear_scene()
    active = _add_cube("NF_Active", (0.0, 0.0, 0.0))
    obj = _add_cube("NF_Bad", (3.0, 0.0, 0.0))
    # (assigning inf through .co clamps it to FLT_MAX; foreach_set keeps it)
    import numpy as np
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    co[0] = (math.nan, 0.0, 0.0)
    co[1] = (math.inf, 1.0, 1.0)
    obj.data.vertices.foreach_set("co", co.ravel())
    obj.data.update()
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    region, rv3d = _perspective_view((1.0, -12.0, 6.0), (2.0, 0.0, 0.0))
    with warnings.catch_warnings():
        warnings.simplefilter("error")             # numpy RuntimeWarning -> error
        with _temporary_budget(100000):
            result = detector.build_spatial_tree(bpy.context, active_obj=active)
        current = Vector((3.0, 0.0, 0.0))
        mouse = utils.world_to_screen(region, rv3d, current)
        detector.find_candidates(result, current, region, rv3d, mouse, 30, 50.0)
        detector.find_axis_candidates(result, current, region, rv3d, mouse, 30, {"X", "Y", "Z"})
    assert result.point_count == 6, result.point_count
    assert all(math.isfinite(v) for co in result.points for v in co)


def case_execute_skips_non_editable_objects():
    _clear_scene()
    lib_obj = _add_cube("NE_Linked", (2.0, 0.0, 0.0))
    # bpy.app.tempdir: some bundled Pythons (Windows 4.0.2) lack tempfile
    path = os.path.join(bpy.app.tempdir, "smartclip_lib.blend")
    bpy.data.libraries.write(path, {lib_obj})
    bpy.data.objects.remove(lib_obj)
    with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
        data_to.objects = ["NE_Linked"]
    linked = data_to.objects[0]
    bpy.context.scene.collection.objects.link(linked)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = linked
    bpy.context.scene.smartclip_enabled = True
    assert linked.library is not None
    before = linked.matrix_world.translation.copy()
    # A linked (non-editable) active object with nothing selected: nothing to
    # move, so the operator cancels instead of raising.
    result = bpy.ops.view3d.smartclip_move(offset=(1.0, 0.0, 0.0))
    assert result == {"CANCELLED"}, result
    assert (linked.matrix_world.translation - before).length < 1e-9


def case_navigation_binding_rules():
    def kmi(idname, key, value="PRESS", active=True, any=False, **mods):
        fields = {"shift": 0, "ctrl": 0, "alt": 0, "oskey": 0}
        fields.update(mods)
        return SimpleNamespace(idname=idname, type=key, value=value, active=active,
                               any=any, key_modifier="NONE", **fields)

    def event(key, value="PRESS", **mods):
        fields = {"shift": False, "ctrl": False, "alt": False, "oskey": False}
        fields.update(mods)
        return SimpleNamespace(type=key, value=value, **fields)

    mesh = SimpleNamespace(keymap_items=[
        kmi("mesh.select_more", "NUMPAD_PLUS", ctrl=1),
        kmi("mesh.unused", "NUMPAD_9", active=False),
    ])
    frames = SimpleNamespace(keymap_items=[kmi("screen.frame_offset", "WHEELUPMOUSE", alt=1)])
    view = SimpleNamespace(keymap_items=[
        kmi("view3d.zoom", "NUMPAD_PLUS"),
        kmi("view3d.view_axis", "NUMPAD_7", ctrl=-1),       # any Ctrl state
        kmi("view3d.object_as_camera", "NUMPAD_0", ctrl=1),
        kmi("view3d.view_camera", "NUMPAD_0"),
        kmi("view3d.zoom", "WHEELINMOUSE"),       # zoom is bound to wheel in / out
        kmi("view3d.rotate", "MIDDLEMOUSE", any=True),
        kmi("view3d.view_orbit", "NUMPAD_9", value="ANY"),
    ])
    keymaps = [mesh, None, frames, view]
    bind = lambda e: ops.first_binding(keymaps, e)

    # first matching keymap wins: Ctrl+Numpad+ is Select More, not zoom
    assert bind(event("NUMPAD_PLUS", ctrl=True)) == "mesh.select_more"
    assert bind(event("NUMPAD_PLUS")) == "view3d.zoom"
    assert bind(event("NUMPAD_7")) == "view3d.view_axis"
    assert bind(event("NUMPAD_7", ctrl=True)) == "view3d.view_axis"
    assert bind(event("NUMPAD_0", ctrl=True)) == "view3d.object_as_camera"
    assert bind(event("NUMPAD_0")) == "view3d.view_camera"
    assert bind(event("WHEELUPMOUSE", alt=True)) == "screen.frame_offset"
    assert bind(event("WHEELUPMOUSE")) == "view3d.zoom"
    assert bind(event("WHEELDOWNMOUSE")) == "view3d.zoom"
    assert bind(event("MIDDLEMOUSE", shift=True, ctrl=True)) == "view3d.rotate"
    assert bind(event("NUMPAD_9")) == "view3d.view_orbit"        # inactive item skipped
    assert bind(event("NUMPAD_7", value="RELEASE")) is None
    assert bind(event("NUMPAD_5", shift=True)) is None
    for name in ("mesh.select_more", "view3d.object_as_camera", "screen.frame_offset"):
        assert name not in ops._VIEW_OPERATORS
    for name in ("view3d.zoom", "view3d.view_axis", "view3d.rotate", "view3d.view_camera"):
        assert name in ops._VIEW_OPERATORS


# --- Search backends: screen-space grid vs. KD-tree (#19) -------------------

def _ortho_view(eye, target, half_height, size=(1600, 900)):
    """Orthographic view from *eye* towards *target*, 2 * half_height units tall."""
    width, height = size
    half_width = half_height * width / height
    near, far = 0.1, 1000.0
    proj = Matrix((
        (1.0 / half_width, 0.0, 0.0, 0.0),
        (0.0, 1.0 / half_height, 0.0, 0.0),
        (0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near)),
        (0.0, 0.0, 0.0, 1.0),
    ))
    eye, target = Vector(eye), Vector(target)
    fwd = (target - eye).normalized()
    right = fwd.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(fwd)
    rot = Matrix((right, up, -fwd))
    view = rot.to_4x4()
    view.translation = -(rot @ eye)
    region = SimpleNamespace(width=width, height=height)
    rv3d = SimpleNamespace(perspective_matrix=proj @ view, view_matrix=view,
                           is_perspective=False, view_perspective="ORTHO",
                           view_distance=(target - eye).length)
    return region, rv3d


def _candidate_keys(cands):
    return [(c.type, tuple(c.location), tuple(c.reference_co), c.screen_dist, c.score,
             c.target_name) for c in cands]


def _both_backends(build, current, region, rv3d, mouse, radius, thr=30):
    """Every candidate of each backend; fails unless they are identical."""
    found = [detector.find_candidates(build, current, region, rv3d, mouse,
                                      snap_distance_px=thr, query_radius=radius,
                                      max_results=10 ** 9, backend=backend)
             for backend in utils.SEARCH_BACKENDS]
    grid, kd = (_candidate_keys(f) for f in found)
    if grid != kd:
        first = next((i for i, (a, b) in enumerate(zip(grid, kd)) if a != b), min(len(grid), len(kd)))
        raise AssertionError(f"backends differ at #{first} (grid {len(grid)}, kd-tree {len(kd)}): "
                             f"{grid[first:first + 1]} vs {kd[first:first + 1]}")
    return found[0]


def case_backends_match_across_views():
    import random
    rnd = random.Random(19)
    spread = [(rnd.uniform(0, 10), rnd.uniform(0, 10), rnd.uniform(0, 10)) for _ in range(3000)]
    blob = [(5.0 + rnd.gauss(0, 0.03), 5.0 + rnd.gauss(0, 0.03), 5.0 + rnd.gauss(0, 0.03))
            for _ in range(1500)]
    coords = spread + blob + spread[:200]          # crowded blob and coincident points
    names = [f"Obj{i % 7}" for i in range(len(coords))]
    build = _build_from_points(coords, names=names)
    views = [
        _perspective_view((5.0, -15.0, 8.0), (5.0, 5.0, 5.0)),
        _perspective_view((-12.0, 3.0, 14.0), (5.0, 5.0, 5.0)),
        # inside the cloud: many points behind or beside the viewer
        _perspective_view((5.0, 5.0, 5.5), (5.0, 9.0, 4.0)),
        _ortho_view((20.0, -20.0, 15.0), (5.0, 5.0, 5.0), 8.0),
        _top_view(),
    ]
    noise = lambda s: Vector((rnd.uniform(-s, s), rnd.uniform(-s, s), rnd.uniform(-s, s)))
    with_candidates = brute_checked = 0
    # Views are revisited, so the grid rebuilds its screen index while the
    # KD-tree stays as it is.
    for rnd_pass in range(2):
        for v, (region, rv3d) in enumerate(views):
            for k in range(24):
                base = Vector((5.0, 5.0, 5.0)) if k % 3 == 0 else Vector(spread[rnd.randrange(3000)])
                current = base + noise(0.05 if k % 3 == 0 else 0.3)
                mouse = utils.world_to_screen(region, rv3d, current)
                if mouse is None:
                    continue
                for radius in (6.0, 0.05, None):
                    cands = _both_backends(build, current, region, rv3d, mouse, radius)
                    with_candidates += bool(cands)
                # a mouse position other than the moving point's projection
                shifted = mouse + Vector((rnd.uniform(-40, 40), rnd.uniform(-40, 40)))
                _both_backends(build, current, region, rv3d, shifted, 6.0)
                if rnd_pass == 0 and k % 6 == 1:
                    expected = _brute_force_best(coords, region, rv3d, current, mouse, 30, 6.0)
                    top = detector.find_candidates(build, current, region, rv3d, mouse, 30, 6.0,
                                                   backend=utils.SEARCH_KDTREE)
                    if expected is None:
                        assert not top, (v, k)
                    else:
                        brute_checked += 1
                        assert top and (top[0].location - Vector(coords[expected])).length < 1e-5, (v, k)
    assert with_candidates > 400, with_candidates
    assert brute_checked >= 15, brute_checked


def case_backends_match_edge_cases():
    import math
    region, rv3d = _perspective_view((0.0, -10.0, 3.0), (0.0, 0.0, 1.0))
    eye = Vector((0.0, -10.0, 3.0))
    ray = (Vector((0.0, 0.0, 1.0)) - eye).normalized()
    side = ray.cross(Vector((0.0, 0.0, 1.0))).normalized()
    # One line of sight: same spot on screen, different depths; one point
    # behind the viewer on the same line.
    line = [eye + ray * t for t in (3.0, 5.0, 8.0, 13.0)] + [eye - ray * 2.0]
    # Around the right border of the view (at depth 6 it is about 5 units
    # to the side): the last three are off screen.
    edge = [eye + ray * 6.0 + side * s for s in (4.6, 4.8, 5.0, 5.2, 5.6)]
    bad = [(math.nan, 0.0, 0.0), (0.0, math.inf, 1.0)]
    coords = [tuple(c) for c in line + edge] + bad + [tuple(line[1])]   # last: coincident
    names = ["L3", "L5", "L8", "L13", "Behind", "E1", "E2", "E3", "E4", "E5", "Nan", "Inf", "L5b"]
    build = _build_from_points(coords, names=names)

    current = eye + ray * 6.0 + side * 0.001
    mouse = utils.world_to_screen(region, rv3d, current)
    cands = _both_backends(build, current, region, rv3d, mouse, None)
    order = [c.target_name for c in cands]
    # nearest in 3D among the overlapping ones; the coincident copy right after it
    assert order[:2] == ["L5", "L5b"], order
    assert "Behind" not in order and "Nan" not in order and "Inf" not in order, order
    _both_backends(build, current, region, rv3d, mouse, 2.5)

    # Moving point near the border of the view, candidates partly off screen
    off_screen = 0
    for s in (4.7, 4.9, 5.1):
        cur = eye + ray * 6.0 + side * s
        m = utils.world_to_screen(region, rv3d, cur)
        cands = _both_backends(build, cur, region, rv3d, m, 10.0, thr=200)
        off_screen += sum(utils.world_to_screen(region, rv3d, c.location).x > region.width
                          for c in cands)
    assert off_screen >= 3, off_screen

    # A degenerate (singular) view matrix: the KD-tree cannot narrow by the
    # cone and checks every point, which still gives the same result.
    flat = SimpleNamespace(perspective_matrix=Matrix(((0.1, 0.0, 0.0, 0.0), (0.0, 0.1, 0.0, 0.0),
                                                      (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))),
                           view_matrix=Matrix.Identity(4))
    flat_region = SimpleNamespace(width=1000, height=1000)
    flat_mouse = utils.world_to_screen(flat_region, flat, current)
    assert len(_both_backends(build, current, flat_region, flat, flat_mouse, None, thr=200)) > 1

    # Excluded points (the moving geometry) are skipped by both
    build_ex = _build_from_points(coords, names=names, exclude={1, 12})
    cands = _both_backends(build_ex, current, region, rv3d, mouse, None)
    assert [c.target_name for c in cands][:1] == ["L8"], [c.target_name for c in cands]

    # A point exactly at the search radius counts, also far from the origin
    # where the KD-tree's float32 coordinates are coarse.  The coordinates are
    # float64 values that float32 cannot hold exactly.
    rng = np.random.default_rng(5)
    for offset, unit in (((0.0, 0.0, 0.0), 1.0),
                         ((1.0e4, -2.0e4, 3.0e3), 1.0),
                         ((0.0, 0.0, 0.0), 1.0e-3)):
        pts = np.array(offset) + rng.uniform(-1.0, 1.0, size=(400, 3)) * unit
        far_build = _build_from_points(pts)
        center = Vector(offset)
        views = (_perspective_view(center + Vector((0.0, -4.0, 1.5)) * unit, center),
                 _ortho_view(center + Vector((3.0, -4.0, 2.0)) * unit, center, 1.5 * unit))
        for view_region, view in views:
            for i in range(0, 400, 20):
                cur = Vector(pts[i] + np.array((0.01, -0.02, 0.015)) * unit)
                j = (i + 7) % 400
                # the radius exactly equal to the distance the search computes
                exact = float(detector._distances(far_build.coords[[j]], np.array(cur))[0])
                m = utils.world_to_screen(view_region, view, cur)
                cands = _both_backends(far_build, cur, view_region, view, m, exact, thr=2000)
                locs = {tuple(c.location) for c in cands}
                assert tuple(Vector(far_build.coords[j])) in locs, (offset, unit, i)


def case_kdtree_cone_rim():
    # Points on the rim of the snap disk (1e-6 px inside or outside) at depths
    # across the whole clip range: the KD-tree's chain of spheres around the
    # cone of sight must hold every point inside, as the grid finds them.
    rng = np.random.default_rng(23)
    thr = 30.0
    views = (_perspective_view((2.0, -9.0, 4.0), (0.0, 0.0, 0.5)),
             _perspective_view((300.0, -900.0, 400.0), (0.0, 0.0, 0.5), fov_deg=10.0),
             _ortho_view((6.0, -8.0, 5.0), (0.0, 0.0, 0.5), 3.0))
    rim_found = 0
    for region, rv3d in views:
        inv = np.linalg.inv(np.array(rv3d.perspective_matrix, dtype=np.float64))
        width, height = region.width, region.height
        for _ in range(4):
            mouse = Vector((rng.uniform(100, width - 100), rng.uniform(100, height - 100)))
            n = 3000
            angle = rng.uniform(0.0, 2.0 * np.pi, n)
            dist = thr * rng.choice([1.0 - 1e-6, 1.0 + 1e-6, 0.999, 0.5], n)
            sx = mouse.x + dist * np.cos(angle)
            sy = mouse.y + dist * np.sin(angle)
            ndc_z = rng.uniform(-1.0, 1.0, n)       # near to far clip
            hom = np.stack([2 * sx / width - 1, 2 * sy / height - 1, ndc_z, np.ones(n)], axis=1) @ inv.T
            pts = hom[:, :3] / hom[:, 3:4]
            build = _build_from_points(pts)
            # moving point somewhere in the cloud; the mouse is not its projection
            current = Vector(pts[rng.integers(n)])
            for radius in (None, float(np.linalg.norm(pts - np.array(current), axis=1).max()) / 3):
                cands = _both_backends(build, current, region, rv3d, mouse, radius, thr=thr)
                rim_found += sum(c.screen_dist > thr * 0.9999 for c in cands)
    assert rim_found > 1000, rim_found


def case_search_backend_setting():
    prop = smart_clipping.prefs.SMARTCLIP_AddonPreferences.bl_rna.properties["search_backend"]
    # Existing users keep the screen-space grid.
    assert prop.default == utils.SEARCH_GRID, prop.default
    assert [item.identifier for item in prop.enum_items] == list(utils.SEARCH_BACKENDS)
    for bad in (lambda: detector.build_from_points([(0, 0, 0)], backend="OCTREE"),
                lambda: detector.find_candidates(detector.build_from_points([(0, 0, 0)]),
                                                 Vector(), *_top_view(), (500, 500),
                                                 backend="OCTREE")):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("an unknown backend was accepted")

    _clear_scene()
    active = _add_cube("SB_Active", (0.0, 0.0, 0.0))
    _add_cube("SB_Cube", (3.0, 0.0, 0.0))
    for i, name in enumerate(("SB_GridA", "SB_GridB", "SB_GridC")):
        _create_grid_object(name, (8.0 + 12.0 * i, 0.0, 0.0), 30, 30)
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    builds = {}
    for backend in (None,) + utils.SEARCH_BACKENDS:
        with _temporary_budget(1000, backend):
            builds[backend] = detector.build_spatial_tree(bpy.context, active_obj=active)
    default, grid, kd = builds[None], builds[utils.SEARCH_GRID], builds[utils.SEARCH_KDTREE]
    assert default.backend == grid.backend == utils.SEARCH_GRID
    assert kd.backend == utils.SEARCH_KDTREE
    # Collection, exclusion and the budget are shared: the same snap points.
    assert kd.limit_exceeded and kd.partial_objects == grid.partial_objects
    assert np.array_equal(kd.coords, grid.coords) and np.array_equal(kd.is_bounds, grid.is_bounds)
    # The KD-tree is built while the move starts, not on the first mouse move.
    assert "kdtree" in kd._cache and "kdtree" not in grid._cache
    assert ops.build_summary(kd).backend == utils.SEARCH_KDTREE
    assert ops.build_summary(grid).backend == utils.SEARCH_GRID

    region, rv3d = _perspective_view((14.0, -25.0, 12.0), (14.0, 0.0, 0.0))
    import random
    rnd = random.Random(3)
    hits = 0
    for _ in range(40):
        current = Vector(kd.coords[rnd.randrange(kd.point_count)]) + Vector(
            (rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2)))
        mouse = utils.world_to_screen(region, rv3d, current)
        found = [detector.find_candidates(b, current, region, rv3d, mouse, 30, 15.0, max_results=10 ** 9)
                 for b in (grid, kd)]
        assert _candidate_keys(found[0]) == _candidate_keys(found[1])
        hits += bool(found[0])
    assert hits > 20, hits


def case_kdtree_edit_mode_excludes_moving():
    _clear_scene()
    obj = _create_grid_object("KE_Grid", (0.0, 0.0, 0.0), 12, 12)
    _select_only(obj)
    bpy.context.scene.smartclip_target_scope = "SELF"
    moving = {0, 1, 2, 13, 14}
    starts = [obj.matrix_world @ obj.data.vertices[i].co for i in sorted(moving)]
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        builds = []
        for backend in utils.SEARCH_BACKENDS:
            with _temporary_budget(100000, backend):
                builds.append(detector.build_spatial_tree(bpy.context, active_obj=obj,
                                                          moving_verts={obj: moving}))
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    grid, kd = builds
    assert kd.point_count == 144 - len(moving), kd.point_count
    region, rv3d = _perspective_view((0.0, -8.0, 6.0), (0.0, 0.0, 0.0))
    for start in starts:
        mouse = utils.world_to_screen(region, rv3d, start)
        # (grid spacing is about 85 px on screen here)
        found = [detector.find_candidates(b, start, region, rv3d, mouse, 200, 5.0, max_results=10 ** 9)
                 for b in (grid, kd)]
        assert _candidate_keys(found[0]) == _candidate_keys(found[1])
        assert found[1], "no other vertex found near a moving one"
        # A moving vertex never snaps to where it (or another moving one) started.
        assert all((c.location - s).length > 1e-6 for c in found[1] for s in starts)


# --- 2.0 interface: move decisions, words, translation, shortcut ---------

def case_move_decisions():
    # A: Off -> X -> Y -> Z -> Off; several axes from the panel go back to Off
    assert utils.next_align_axes(()) == ("X",)
    assert utils.next_align_axes(("X",)) == ("Y",)
    assert utils.next_align_axes({"Y"}) == ("Z",)
    assert utils.next_align_axes(frozenset({"Z"})) == ()
    assert utils.next_align_axes(("X", "Z")) == ()

    # S: the next Snap To that can have anything to snap to
    nxt = utils.next_scope
    # Object Mode: Same Mesh never; Selected Objects only with another
    # selected mesh; Collection only with a collection
    assert nxt("VISIBLE", False, False, False) == "VISIBLE"
    assert nxt("VISIBLE", False, True, False) == "COLLECTION"
    assert nxt("COLLECTION", False, True, False) == "VISIBLE"
    assert nxt("COLLECTION", False, True, True) == "SELECTED"
    assert nxt("SELECTED", False, False, True) == "VISIBLE"
    # Edit Mode: Same Mesh and Selected Objects always
    assert nxt("VISIBLE", True, False, False) == "SELF"
    assert nxt("SELF", True, False, False) == "SELECTED"
    assert nxt("SELECTED", True, False, False) == "VISIBLE"
    assert nxt("VISIBLE", True, True, False) == "COLLECTION"

    # Ctrl: off with Snap Exactly, exact with Gradual Pull -> (search, exact)
    assert utils.snap_rule(utils.SNAP_EXACT, False) == (True, True)
    assert utils.snap_rule(utils.SNAP_EXACT, True) == (False, True)
    assert utils.snap_rule(utils.SNAP_PULL, False) == (True, False)
    assert utils.snap_rule(utils.SNAP_PULL, True) == (True, True)

    assert abs(utils.pull_ratio(0.0, 30, 0.35) - 0.35) < 1e-9
    assert abs(utils.pull_ratio(15.0, 30, 0.5) - 0.25) < 1e-9
    assert utils.pull_ratio(30.0, 30, 0.35) == 0.0
    assert utils.pull_ratio(45.0, 30, 0.35) == 0.0

    prop = smart_clipping.prefs.SMARTCLIP_AddonPreferences.bl_rna.properties["snap_behavior"]
    assert prop.default == utils.SNAP_EXACT, prop.default


class _StubLayout:
    """Records label() calls of a status bar draw function."""

    def __init__(self, log):
        self.log = log

    def row(self, align=False):
        return self

    def label(self, text="", icon="NONE", translate=True):
        self.log.append((text, icon))

    def separator(self, factor=1.0):
        pass


def case_snap_reached_tolerance():
    # Issue #28: Snapped only when the moving point is on the snap point,
    # at any scene scale; Projected otherwise.
    for scale in (0.001, 1.0, 1000.0):
        target = Vector((1.0, 2.0, 3.0)) * scale
        pixel = 0.002 * scale          # world size of a screen pixel there
        assert ops.reached(target.copy(), target, pixel)
        rounded = Vector(tuple(float(np.float32(c * (1 + 3e-7))) for c in target))
        assert ops.reached(rounded, target, pixel), (scale, rounded - target)
        off = target + Vector((0.0, 0.0, 0.5 * pixel))
        assert not ops.reached(off, target, pixel), scale
        assert not ops.reached(target + Vector((0.0, 0.0, 0.01 * scale)), target, pixel)
    assert ops.reached(Vector((5.0, 0.0, 0.0)), Vector((5.0, 0.0, 1e-7)))
    assert not ops.reached(Vector((5.0, 0.0, 0.0)), Vector((5.0, 0.0, 1e-3)))


def case_pivot_objects():
    # The objects whose evaluated origins give the pivot after the move.
    _clear_scene()
    parent = _add_cube("Piv_Parent", (0.0, 0.0, 0.0))
    child = _add_cube("Piv_Child", (2.0, 0.0, 0.0))
    other = _add_cube("Piv_Other", (5.0, 0.0, 0.0))
    child.parent = parent
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    bpy.ops.object.select_all(action="DESELECT")
    for obj in (parent, child, other):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = child
    _pivot, movers = ops.gather_movers(bpy.context)
    assert {m.obj.name for m in movers} == {"Piv_Parent", "Piv_Other"}
    # The active child moves with its parent: its origin is the pivot
    assert [o.name for o in ops.pivot_objects(bpy.context, movers)] == ["Piv_Child"]
    child.select_set(False)
    bpy.context.view_layer.objects.active = None
    _pivot, movers = ops.gather_movers(bpy.context)
    assert sorted(o.name for o in ops.pivot_objects(bpy.context, movers)) == [
        "Piv_Other", "Piv_Parent"]
    assert ops.pivot_objects(bpy.context, []) == []


def case_overlay_insets():
    # Labels keep clear of the toolbar, the sidebar and the Adjust Last
    # Operation panel when they overlap the 3D View (#31).
    drawing = _sub("drawing")

    def reg(kind, x, y, w, h):
        return SimpleNamespace(type=kind, x=x, y=y, width=w, height=h)

    window = reg("WINDOW", 100, 50, 1000, 800)
    area = SimpleNamespace(regions=[
        window,
        reg("HEADER", 100, 850, 1000, 26),                 # above: not overlapping
        reg("TOOLS", 100, 50, 44, 790),
        reg("UI", 880, 50, 220, 790),
        reg("HUD", 150, 50, 260, 32),
    ])
    assert drawing._overlap_insets(area, window) == (44, 32, 220),         drawing._overlap_insets(area, window)
    # Hidden regions (1 px) and no overlap
    area.regions[2:] = [reg("UI", 880, 50, 1, 1), reg("HUD", 150, 50, 1, 1)]
    assert drawing._overlap_insets(area, window) == (0, 0, 0)
    assert drawing._overlap_insets(None, window) == (0, 0, 0)


def case_hud_words():
    hud = _sub("hud")

    scene = bpy.context.scene
    units = scene.unit_settings
    saved = (units.system, units.scale_length, units.use_separate)
    try:
        units.system = "NONE"
        assert hud.format_length(1.5, scene) == "1.500", hud.format_length(1.5, scene)
        units.system = "METRIC"
        units.scale_length = 1.0
        units.use_separate = False
        text = hud.format_length(1.25, scene)
        assert text.replace(" ", "") == "1.25m", text
        units.scale_length = 0.01          # 1 unit = 1 cm
        text = hud.format_length(1.25, scene)
        assert text.replace(" ", "") == "1.25cm", text
        units.system = "IMPERIAL"
        units.scale_length = 1.0
        text = hud.format_length(0.3048, scene)
        assert "'" in text or "ft" in text, text
    finally:
        units.system, units.scale_length, units.use_separate = saved

    def cand(kind, name="Cube"):
        return detector.SnapCandidate(kind, Vector(), Vector(), 3.0, 3.0, name)

    assert hud.candidate_runs(cand("POINT"), utils.STATE_SNAPPED) == [
        ("Snapped", "accent"), ("Cube vertex", "text")]
    assert hud.candidate_runs(cand("BOUNDS"), utils.STATE_PULLING, "0.1 m") == [
        ("Pulling", "accent"), ("Cube bounding box", "text"), ("0.1 m", "muted")]
    assert hud.candidate_runs(cand("ALIGN_Z"), utils.STATE_SNAPPED)[1] == (
        "Z coordinate of Cube", "text")
    assert hud.candidate_runs(cand("POINT"), utils.STATE_PROJECTED, "0.05 m") == [
        ("Projected", "accent"), ("Cube vertex", "text"), ("0.05 m", "muted")]
    assert hud.moved_text("1 m", None) == "Moved 1 m"
    assert hud.moved_text("1 m", "X") == "Moved 1 m along X"
    assert hud.moved_text("1 m", "YZ") == "Moved 1 m on YZ"

    plain = hud.mode_lines("VISIBLE", frozenset(), False, None, None, False)
    assert len(plain) == 1
    words = [text for text, _role in plain[0] if text]
    assert words == ["Snap To", "Visible Objects", "Align Only", "Off"], words
    noted = hud.mode_lines("SELF", frozenset({"X"}), True, "Y", None, True)
    assert len(noted) == 3 and "paused" in noted[1][0][0] and "limit" in noted[2][0][0]
    empty = hud.mode_lines("SELF", frozenset(), False, None,
                           hud.empty_reason("SELF", False, False), False)
    assert empty[1][0] == ("Nothing to snap to.", "warning") and "Edit Mode" in empty[1][1][0]
    assert "collection" in hud.empty_reason("COLLECTION", False, False)
    assert "Select" in hud.empty_reason("SELECTED", False, False)
    assert hud.limit_detail(3, 0) == "3 objects simplified"
    assert hud.limit_detail(3, 2) == "3 simplified, 2 left out"

    # Status bar: every icon exists in this Blender, Ctrl follows Snap Behavior
    valid = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys())
    for behavior, ctrl in ((utils.SNAP_EXACT, "Move Freely"), (utils.SNAP_PULL, "Snap Exactly")):
        items = hud.status_items(behavior)
        assert all(icon in valid for icons, _label in items for icon in icons)
        log = []
        ops.status_draw_fn(behavior)(SimpleNamespace(layout=_StubLayout(log)), bpy.context)
        assert ("Confirm", "MOUSE_LMB") in log and (ctrl, "EVENT_CTRL") in log, log
        assert ("Cancel", "EVENT_ESC") in log and ("", "MOUSE_RMB") in log, log
        assert all(icon != "NONE" for _text, icon in log), log
    line = hud.status_text(utils.SNAP_EXACT)
    assert "RMB/Esc Cancel" in line and "Shift+X/Y/Z Plane" in line, line


def case_build_summary():
    assert ops.build_summary(None) == (0, False, 0, 0, None)
    _clear_scene()
    active = _add_cube("BS_Active", (0.0, 0.0, 0.0))
    _add_cube("BS_Cube", (3.0, 0.0, 0.0))
    for i in range(6):
        _create_grid_object(f"BS_Grid{i}", (8.0 + 12.0 * i, 0.0, 0.0), 30, 30)
    _select_only(active)
    bpy.context.scene.smartclip_target_scope = "VISIBLE"
    with _temporary_budget(1000):
        build = detector.build_spatial_tree(bpy.context, active_obj=active)
    summary = ops.build_summary(build)
    assert summary.limit_exceeded and summary.points == build.point_count
    assert summary.simplified == len(set(build.partial_objects) | set(build.bounds_objects)) > 0
    assert summary.skipped == len(build.skipped_objects)


def case_translations():
    import string

    hud, i18n = _sub("hud"), _sub("i18n")

    view = bpy.context.preferences.view
    tr = bpy.app.translations
    switches = [name for name in ("language", "use_translate_interface",
                                  "use_translate_tooltips", "use_translate_reports")
                if hasattr(view, name)]          # Translate Reports is not in every version
    saved = {name: getattr(view, name) for name in switches}
    fields = string.Formatter()

    def placeholders(text):
        return {name for _lit, name, _spec, _conv in fields.parse(text) if name}

    try:
        for name in switches:
            setattr(view, name, "ja_JP" if name == "language" else True)
        if tr.locale != "ja_JP":
            raise Skip("this Blender cannot switch to Japanese")

        for msgid, msgstr in i18n.MESSAGES.items():
            assert placeholders(msgid) == placeholders(msgstr), msgid
            assert msgstr and msgstr != msgid, msgid

        # Registered messages apply to all of Blender: none may give one of
        # Blender's own messages a different translation.
        i18n.unregister()
        try:
            clashes = []
            for msgid, msgstr in i18n.MESSAGES.items():
                contexts = ("*", "Operator") if msgid in i18n.OPERATOR_MESSAGES else ("*",)
                for ctx in contexts:
                    builtin = tr.pgettext_iface(msgid, ctx)
                    if builtin not in (msgid, msgstr):
                        clashes.append((ctx, msgid, builtin))
            assert not clashes, clashes
        finally:
            i18n.register()

        # Every name and tooltip the add-on registers comes out in Japanese,
        # from these messages or from Blender's catalog.
        keep = {"Smart Clipping", "X", "Y", "Z"}
        missing = []

        def want(text, ctx="*"):
            if not text or text in keep:
                return
            if tr.pgettext_iface(text, ctx) == text and tr.pgettext_tip(text, ctx) == text:
                missing.append(text)

        # Blender's own (base class) properties are not the add-on's words
        inherited = {p.identifier for base in (bpy.types.Operator, bpy.types.AddonPreferences)
                     for p in base.bl_rna.properties}

        def props(rna_props):
            for prop in rna_props:
                if prop.identifier in inherited or prop.is_hidden:
                    continue
                want(prop.name)
                want(prop.description)
                for item in getattr(prop, "enum_items", ()):
                    want(item.name)
                    want(item.description)

        props(smart_clipping.prefs.SMARTCLIP_AddonPreferences.bl_rna.properties)
        props(bpy.types.Scene.bl_rna.properties[name] for name in smart_clipping._SCENE_PROPS)
        for cls in (smart_clipping.SMARTCLIP_OT_modal_move,
                    smart_clipping.SMARTCLIP_OT_add_default_hotkeys,
                    smart_clipping.SMARTCLIP_OT_clear_hotkeys):
            want(cls.bl_label, "Operator")
            want(cls.bl_description)
            props(cls.bl_rna.properties)
        for cls in (smart_clipping.SMARTCLIP_PT_panel, smart_clipping.SMARTCLIP_PT_limits):
            want(cls.bl_label)
        # Words left to Blender's catalog (status bar, mode lines, sections)
        for word in i18n.BLENDER_WORDS:
            want(word)
        assert not missing, missing

        # Words the add-on assembles itself
        assert hud.moved_text("1 m", "X") == "X 軸に沿って 1 m 移動", hud.moved_text("1 m", "X")
        assert hud.scope_name("SELF") == "同じメッシュ"
        assert hud.scope_name("VISIBLE") == tr.pgettext_iface("Visible Objects") != "Visible Objects"
        cand = detector.SnapCandidate("POINT", Vector(), Vector(), 1.0, 1.0, "Cube")
        assert hud.candidate_runs(cand, utils.STATE_SNAPPED) == [
            ("スナップ中", "accent"), ("Cube の頂点", "text")]
        assert i18n.rpt("Nothing selected to move") == "動かすものが選択されていません"
        # Confirm is Blender's own word, translated by Blender's catalog
        confirm = tr.pgettext_iface("Confirm")
        assert confirm != "Confirm" and confirm in hud.status_text(utils.SNAP_EXACT)
    finally:
        for name, value in saved.items():
            setattr(view, name, value)


def case_shortcut_reset():
    keymap = _sub("keymap")

    kmis = _addon_kmis()
    assert kmis
    try:
        for kmi in kmis:
            kmi.type = "H"
            kmi.shift = False
            kmi.ctrl = True
        keymap.set_hotkeys_wanted(False)
        assert not any(kmi.active for kmi in kmis)
        bpy.ops.smartclip.add_default_hotkeys()
        assert all(kmi.type == "G" and kmi.shift and not kmi.ctrl and kmi.active
                   for kmi in kmis), [(k.type, k.shift, k.ctrl, k.active) for k in kmis]
        # The user keymap shows the same items (drawn in the preferences).
        # Without a window Blender merges the keymaps only when asked to.
        bpy.context.window_manager.keyconfigs.update()
        labels = [label for label, _km, _kmi in keymap.user_items()]
        assert labels == ["Object Mode", "Edit Mode"], labels
    finally:
        bpy.ops.smartclip.add_default_hotkeys()


def case_shortcut_names_what_it_overrides():
    # Issue #29: the preferences say what the key takes over.  Without a
    # window Blender's own keymaps are empty, so a stand-in for Select Grouped
    # is added after the add-on's item (the UI test checks the real ones).
    keymap = _sub("keymap")

    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("Object Mode")
    ours = next(k for k in km.keymap_items if k.idname == keymap.MOVE_IDNAME)
    builtin = km.keymap_items.new("object.select_grouped", "G", "PRESS", shift=True)
    other_key = km.keymap_items.new("object.select_all", "G", "PRESS", ctrl=True)
    try:
        bpy.ops.smartclip.add_default_hotkeys()
        assert keymap.overridden_name(km, ours) == builtin.name, builtin.name
        builtin.active = False
        assert keymap.overridden_name(km, ours) is None
        builtin.active = True
        keymap.set_hotkeys_wanted(False)
        assert keymap.overridden_name(km, ours) is None      # off: takes over nothing
        keymap.set_hotkeys_wanted(True)
        ours.type = "H"                                       # a key nothing else uses
        assert keymap.overridden_name(km, ours) is None
    finally:
        km.keymap_items.remove(other_key)
        km.keymap_items.remove(builtin)
        bpy.ops.smartclip.add_default_hotkeys()


def case_redo_keeps_move_settings():
    # Adjust Last Operation undoes, then calls execute() with the recorded
    # properties; Repeat Last calls it again.  Both must do what the move did.
    _clear_scene()
    a = _add_cube("RD_A", (0.0, 0.0, 0.0))
    b = _add_cube("RD_B", (3.0, 0.0, 0.0))
    scene = bpy.context.scene
    for obj in (a, b):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = a
    scene.smartclip_target_scope = "VISIBLE"
    scene.smartclip_align_x = scene.smartclip_align_y = scene.smartclip_align_z = False

    # The move started with Selected Objects (only the active object moves)
    # and ended with Snap To = Visible Objects and Align Only = Y (A / S).
    bpy.ops.view3d.smartclip_move(offset=(1.0, 0.0, 0.0), start_scope="SELECTED",
                                  final_scope="VISIBLE", final_align=(False, True, False))
    bpy.context.view_layer.update()
    assert (a.matrix_world.translation - Vector((1.0, 0.0, 0.0))).length < 1e-6
    assert (b.matrix_world.translation - Vector((3.0, 0.0, 0.0))).length < 1e-6
    assert scene.smartclip_target_scope == "VISIBLE"
    assert (scene.smartclip_align_x, scene.smartclip_align_y, scene.smartclip_align_z) == (
        False, True, False)

    # From a script, with nothing recorded, the scene's settings decide.
    scene.smartclip_align_y = False
    bpy.ops.view3d.smartclip_move(offset=(0.0, 1.0, 0.0))
    bpy.context.view_layer.update()
    assert (b.matrix_world.translation - Vector((3.0, 1.0, 0.0))).length < 1e-6
    assert not scene.smartclip_align_y


def case_poll_without_active_object():
    _clear_scene()
    cube = _add_cube("PO_Cube", (0.0, 0.0, 0.0))
    bpy.context.view_layer.objects.active = None
    assert not smart_clipping.SMARTCLIP_OT_modal_move.poll(bpy.context)
    _select_only(cube)
    assert smart_clipping.SMARTCLIP_OT_modal_move.poll(bpy.context)


CASES = {
    "scene_props": case_scene_properties_registered,
    "scope_self": case_scope_self,
    "scope_selected": case_scope_selected,
    "scope_visible_sort": case_scope_visible_distance_sort,
    "budget_fallback": case_budget_fallback_with_cubes,
    "scope_collection": case_scope_collection,
    "stress_100k": case_stress_100k_vertices,
    "budget_partial": case_budget_partial_fill,
    "budget_exactly_used_up": case_budget_exactly_used_up,
    "scope_collection_recursive": case_scope_collection_recursive,
    "edit_mode_sync": case_edit_mode_sync,
    "parent_space_delta": case_parent_space_delta,
    "constraint_helpers": case_constraint_helpers,
    "axis_align_gate": case_axis_align_screen_gate,
    "axis_align_dense": case_axis_align_nearest_in_dense_data,
    "find_hit_cap": case_find_candidates_hit_cap_skips_excluded,
    "object_mode_excludes_movers": case_object_mode_excludes_movers_and_children,
    "evaluated_mesh_targets": case_evaluated_mesh_targets,
    "execute_moves_all_selected": case_execute_moves_all_selected,
    "selected_scope_moves_active_only": case_selected_scope_moves_active_only,
    "execute_edit_multi_object": case_execute_edit_mode_multi_object,
    "legacy_prop_migration": case_legacy_scene_property_migration,
    "pixel_world_size": case_pixel_world_size,
    "keymap_independent_of_scene": case_keymap_independent_of_scene_enable,
    "clear_hotkeys_stays_cleared": case_clear_hotkeys_stays_cleared,
    "moving_verts_no_budget": case_moving_vertices_do_not_use_budget,
    "shared_mesh_moving_excluded": case_shared_mesh_moving_vertices_excluded,
    "budget_caps_total_points": case_budget_caps_total_points,
    "budget_sampling_covers_mesh": case_budget_sampling_covers_mesh,
    "ranking_scale_independent": case_ranking_independent_of_scene_scale,
    "ranking_ties_nearest_3d": case_ranking_ties_prefer_nearest_in_3d,
    "find_recall_crowded": case_find_recall_with_crowded_neighbours,
    "find_brute_force_persp": case_find_matches_brute_force_perspective,
    "axis_skips_excluded_run": case_axis_align_skips_excluded_run,
    "axis_brute_force_persp": case_axis_align_matches_brute_force_perspective,
    "edit_selected_includes_active": case_edit_selected_scope_includes_active_rest,
    "edit_self_all_edited_meshes": case_edit_self_scope_covers_all_edited_meshes,
    "collection_skips_hidden": case_collection_scope_skips_hidden,
    "non_finite_vertices_dropped": case_non_finite_vertices_dropped,
    "execute_skips_non_editable": case_execute_skips_non_editable_objects,
    "navigation_binding_rules": case_navigation_binding_rules,
    "backends_match_views": case_backends_match_across_views,
    "backends_match_edge_cases": case_backends_match_edge_cases,
    "kdtree_cone_rim": case_kdtree_cone_rim,
    "search_backend_setting": case_search_backend_setting,
    "kdtree_edit_mode_excludes_moving": case_kdtree_edit_mode_excludes_moving,
    "move_decisions": case_move_decisions,
    "hud_words": case_hud_words,
    "overlay_insets": case_overlay_insets,
    "snap_reached_tolerance": case_snap_reached_tolerance,
    "pivot_objects": case_pivot_objects,
    "build_summary": case_build_summary,
    "translations": case_translations,
    "shortcut_reset": case_shortcut_reset,
    "shortcut_overrides": case_shortcut_names_what_it_overrides,
    "poll_without_active_object": case_poll_without_active_object,
    "redo_keeps_move_settings": case_redo_keeps_move_settings,
}


def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(CASES.keys()), default=None)
    parser.add_argument("--module", default=None,
                        help="run against the add-on enabled under this module name")
    return parser.parse_args(argv)


def main():
    _ensure_addon_enabled()
    args = _parse_args()
    selected = [args.case] if args.case else list(CASES.keys())

    failures = 0
    skipped = 0
    print(f"[smartclip:test] add-on: {smart_clipping.__name__} "
          f"({'installed' if INSTALLED else 'source folder'}), Blender {bpy.app.version_string}")
    print("[smartclip:test] running cases:", ", ".join(selected))
    for name in selected:
        fn = CASES[name]
        try:
            fn()
            print(f"[PASS] {name}")
        except Skip as exc:
            skipped += 1
            print(f"[SKIP] {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")
            traceback.print_exc()

    print(f"[smartclip:test] summary: passed={len(selected) - failures - skipped} "
          f"failed={failures} skipped={skipped}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
