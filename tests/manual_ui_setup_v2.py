"""
Create a manual validation scene for Smart Clipping UI/operator tests.

Usage:
  blender --python tests/manual_ui_setup_v2.py
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
        prefs.snap_distance_px = 15

    active = add_cube("SC_Active", (0.0, 0.0, 0.0))
    add_cube("SC_Near_1", (3.0, 0.0, 0.0))
    add_cube("SC_Near_2", (0.0, 3.0, 0.0))
    add_cube("SC_Far_1", (12.0, 0.0, 0.0))
    heavy = add_heavy_grid("SC_Heavy_100k", (20.0, 0.0, 0.0), x_verts=320, y_verts=320)

    col = bpy.data.collections.new("SC_Manual_Refs")
    scene.collection.children.link(col)
    c1 = add_cube("SC_COL_A", (-6.0, 0.0, 0.0))
    c2 = add_cube("SC_COL_B", (-8.0, 2.0, 0.0))
    link_only_to_collection(c1, col)
    link_only_to_collection(c2, col)
    scene.target_collection = col

    bpy.ops.object.select_all(action="DESELECT")
    active.select_set(True)
    bpy.context.view_layer.objects.active = active

    print("")
    print("=== Smart Clipping (src) Manual Validation Scene Ready ===")
    print("1) Open N-Panel > Tool > Smart Clipping.")
    print("2) Check toggle: Enable Smart Clipping.")
    print("3) Scope=VISIBLE, press Smart Clipping Move button (or Shift+G).")
    print("4) Hold Ctrl during move to verify hard snap color (cyan).")
    print("5) Confirm runtime info shows Box Mode when heavy mesh is included.")
    print("6) Change Scope=COLLECTION and collection=SC_Manual_Refs, repeat move test.")
    print("7) Enter Edit Mode on SC_Active, select vertices, run move again.")
    print(f"Heavy object: {heavy.name}, verts={len(heavy.data.vertices)}")
    print("============================================================")


if __name__ == "__main__":
    main()
