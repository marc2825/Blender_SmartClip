"""
Create a manual validation scene for Smart Clipping UI/operator tests.

Usage:
  blender --python tests/manual_ui_setup.py
"""

import os
import sys

import bmesh
import bpy

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import src  # noqa: E402


def ensure_addon_enabled():
    if not hasattr(bpy.types.Scene, "target_scope"):
        try:
            src.register()
        except ValueError:
            pass

    if "src" not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module="src")
        except Exception:
            pass


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False, confirm=False)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for coll in list(bpy.data.collections):
        if coll.users == 0:
            bpy.data.collections.remove(coll)


def add_cube(name, location):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_heavy_grid(name, location, x_verts=320, y_verts=320):
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


def link_only_to_collection(obj, coll):
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    for parent in list(obj.users_collection):
        if parent != coll:
            parent.objects.unlink(obj)


def main():
    ensure_addon_enabled()
    clear_scene()

    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.target_scope = "VISIBLE"

    prefs = bpy.context.preferences.addons.get("src")
    if prefs:
        prefs = prefs.preferences
        prefs.max_vertex_budget = 50000
        prefs.snap_distance_px = 30

    # Active object (origin)
    active = add_cube("SC_Active", (0.0, 0.0, 0.0))

    # Near targets for regular snap / Axis Align validation
    add_cube("SC_Near_X",  (4.0,  0.0, 0.0))   # aligned on X axis
    add_cube("SC_Near_Y",  (0.0,  4.0, 0.0))   # aligned on Y axis
    add_cube("SC_Near_Z",  (0.0,  0.0, 4.0))   # aligned on Z axis
    add_cube("SC_Diag",    (4.0,  4.0, 0.0))   # diagonal — tests free snap

    # Far object for distance-sort / budget validation
    heavy = add_heavy_grid("SC_Heavy_100k", (25.0, 0.0, 0.0), x_verts=320, y_verts=320)

    # Collection scope targets
    col = bpy.data.collections.new("SC_Manual_Refs")
    scene.collection.children.link(col)
    c1 = add_cube("SC_COL_A", (-5.0, 0.0, 0.0))
    c2 = add_cube("SC_COL_B", (-5.0, 3.0, 2.0))
    link_only_to_collection(c1, col)
    link_only_to_collection(c2, col)
    scene.target_collection = col

    bpy.ops.object.select_all(action="DESELECT")
    active.select_set(True)
    bpy.context.view_layer.objects.active = active

    print("\n=== Smart Clipping Manual Validation Scene ===")
    print("  SC_Active (origin) | SC_Near_X/Y/Z | SC_Diag | SC_COL_A/B | SC_Heavy_100k")
    print("  Scope=VISIBLE, budget=50000, snap_px=30  |  See tests/TESTS_OVERVIEW.txt")
    print("")
    print("[ Soft/Hard Snap ]  Shift+G → move near SC_Near_* → soft pull (purple).")
    print("                    Hold RMB near candidate → hard snap (cyan). LMB/Enter=confirm, ESC=cancel.")
    print("[ Axis Align ]      N-Panel Axis Align Z ON → move freely → z=4.0 suggested (SC_Near_Z).")
    print("                    Switch to X → x=4.0 suggested (SC_Near_X / SC_Diag).")
    print("[ Constraint ]      During modal: X/Y/Z = axis lock, Shift+X/Y/Z = plane lock (toggle).")
    print("[ Bounds ]          N-Panel runtime info should show 'Box Mode' (SC_Heavy_100k).")
    print("[ Collection ]      Scope=COLLECTION, col=SC_Manual_Refs → only SC_COL_A/B as targets.")
    print("[ Edit Mode ]       Tab → select verts → Shift+G → selected move, unselected snap.")
    print(f"\n  Heavy: {heavy.name}, verts={len(heavy.data.vertices)}")
    print("================================================")


if __name__ == "__main__":
    main()
