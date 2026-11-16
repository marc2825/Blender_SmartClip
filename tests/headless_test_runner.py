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
from types import SimpleNamespace

import bmesh
import bpy
from mathutils import Matrix, Vector


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import smart_clipping  # noqa: E402
from smart_clipping import detector, ops, utils  # noqa: E402


def _ensure_addon_enabled():
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
def _temporary_budget(max_vertex_budget):
    # Always monkeypatch: the real preference clamps to >= 100, which would
    # silently change what the small-budget cases test.
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
    # 1.x names must be gone (renamed with a prefix in 2.0)
    assert not hasattr(bpy.types.Scene, "target_scope")
    assert not hasattr(bpy.types.Scene, "target_collection")
    assert hasattr(bpy.types.Scene, "smartclip_target_scope")
    assert hasattr(bpy.types.Scene, "smartclip_target_collection")
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
    scene.smartclip_target_scope = "SELF"

    with _temporary_budget(100000):
        # Object Mode: the whole active object moves -> nothing to snap to.
        obj_mode = detector.build_spatial_tree(bpy.context, active_obj=a)
        # Edit Mode: only the moving vertices are excluded.
        edit_mode = detector.build_spatial_tree(bpy.context, active_obj=a,
                                                moving_verts={a: {0, 1}})

    assert obj_mode.point_count == 0
    assert obj_mode.tree is None

    assert edit_mode.point_count == len(a.data.vertices)
    assert all(meta.obj_name == "Self_A" for meta in edit_mode.point_meta)
    assert edit_mode.exclude_indices == {0, 1}
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
    _add_cube("Budget_B", (3.0, 0.0, 0.0))
    _add_cube("Budget_C", (6.0, 0.0, 0.0))
    _select_only(active)

    scene = bpy.context.scene
    scene.smartclip_target_scope = "VISIBLE"

    # Cube has 8 vertices; budget 8 fits exactly the nearest target (B),
    # leaving nothing for C, which falls back to BOUNDS only.
    with _temporary_budget(8):
        result = detector.build_spatial_tree(bpy.context, active_obj=active)

    assert result.limit_exceeded
    assert result.bounds_objects == ["Budget_C"]
    assert result.partial_objects == []
    assert result.source_vertex_count == 8

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
          f"(tree points: {result.point_count})")


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

    # Cube fits (8); the grid crossing the limit is sampled into the remaining
    # 100 slots instead of collapsing to its box; the far cube gets bounds only.
    assert result.limit_exceeded
    assert result.partial_objects == ["Part_Grid"]
    assert result.bounds_objects == ["Part_Far"]
    assert result.source_vertex_count <= 108
    grid_points = [m for m in result.point_meta
                   if m.obj_name == "Part_Grid" and m.point_type == "POINT"]
    assert 50 <= len(grid_points) <= 100, len(grid_points)


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

    assert result.point_count == 9
    (excluded,) = result.exclude_indices
    expected = obj.matrix_world @ Vector((5.0, 0.0, 0.0))
    assert (result.points[excluded] - expected).length < 1e-5


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


def _build_from_points(coords, names=None, exclude=()):
    points = [Vector(c) for c in coords]
    names = names or [f"P{i}" for i in range(len(points))]
    tree = detector.kdtree.KDTree(len(points))
    for i, co in enumerate(points):
        tree.insert(co, i)
    tree.balance()
    return detector.BuildResult(
        tree=tree,
        point_meta=[detector._PointMeta(obj_name=n, point_type="POINT") for n in names],
        point_count=len(points),
        points=points,
        axis_x=sorted((co.x, i) for i, co in enumerate(points)),
        axis_y=sorted((co.y, i) for i, co in enumerate(points)),
        axis_z=sorted((co.z, i) for i, co in enumerate(points)),
        exclude_indices=set(exclude),
    )


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
        snap_distance_px=30, query_radius=10.0, max_hits=8,
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
    # (a) values written through the 1.x bpy.props definitions; Blender 5.x
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
    # (c) already-set 2.0 values must not be overwritten
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


CASES = {
    "scene_props": case_scene_properties_registered,
    "scope_self": case_scope_self,
    "scope_selected": case_scope_selected,
    "scope_visible_sort": case_scope_visible_distance_sort,
    "budget_fallback": case_budget_fallback_with_cubes,
    "scope_collection": case_scope_collection,
    "stress_100k": case_stress_100k_vertices,
    "budget_partial": case_budget_partial_fill,
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
    "execute_edit_multi_object": case_execute_edit_mode_multi_object,
    "legacy_prop_migration": case_legacy_scene_property_migration,
    "pixel_world_size": case_pixel_world_size,
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
    print("[smartclip:test] running cases:", ", ".join(selected))
    for name in selected:
        fn = CASES[name]
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")
            traceback.print_exc()

    print(f"[smartclip:test] summary: passed={len(selected) - failures} failed={failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
