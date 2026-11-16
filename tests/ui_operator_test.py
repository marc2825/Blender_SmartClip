"""
End-to-end test of the modal operator in a real Blender UI using simulated
input events.  Needs a display (opens a Blender window for a few seconds);
real mouse / keyboard input is ignored while it runs.

Usage:
  blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py

Set SMARTCLIP_UI_SCREENSHOT_DIR to save screenshots of the overlays
(constraint.png, hard_snap.png) for visual inspection.

Exit code 0 = all checks passed, 1 = failures.
"""

import io
import os
import sys
import traceback

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Euler, Vector

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import src  # noqa: E402

STEP = 0.15  # seconds between simulated events

_results = []


class _StderrTee(io.TextIOBase):
    """Record everything written to stderr (draw-handler tracebacks land here)."""

    def __init__(self, inner):
        self.inner = inner
        self.captured = []

    def write(self, text):
        self.captured.append(text)
        return self.inner.write(text)

    def flush(self):
        self.inner.flush()


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip(), flush=True)


def _view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next(r for r in area.regions if r.type == "WINDOW")
            return win, area, region, area.spaces.active.region_3d
    raise RuntimeError("no 3D View in the startup screen")


def _setup_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4.0, -2.0, 0.5))
    parent = bpy.context.active_object
    parent.name = "UI_Parent"
    parent.rotation_euler = (0.0, 0.0, 0.9)
    parent.scale = (2.0, 0.5, 1.0)

    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0.0, 0.0, 0.0))
    child = bpy.context.active_object
    child.name = "UI_Child"
    bpy.context.view_layer.update()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    # Transform the parent after parenting so `location` is no longer the
    # world position (right after Ctrl+P the parent space is the identity).
    parent.rotation_euler = (0.0, 0.0, 1.6)
    parent.scale = (1.5, 0.7, 1.0)

    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(1.5, 0.0, 0.0))
    target = bpy.context.active_object
    target.name = "UI_Target"

    bpy.ops.object.select_all(action="DESELECT")
    child.select_set(True)
    bpy.context.view_layer.objects.active = child
    bpy.context.view_layer.update()
    return parent, child, target


def _steps():
    win, area, region, rv3d = _view3d()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.target_scope = "SELF"  # Object Mode + SELF = no snap targets

    _parent, child, target = _setup_scene()
    rv3d.view_perspective = "PERSP"
    rv3d.view_location = (0.5, 0.0, 0.0)
    rv3d.view_distance = 12.0
    rv3d.view_rotation = Euler((1.1, 0.0, 0.6)).to_quaternion()
    yield 0.5

    cx = region.x + region.width // 2
    cy = region.y + region.height // 2

    def ev(event_type, value, dx=0, dy=0, **mods):
        win.event_simulate(event_type, value, x=cx + dx, y=cy + dy, **mods)

    def px(co):
        return location_3d_to_region_2d(region, rv3d, co)

    def start_modal(label):
        scene.smartclip_runtime_info = ""
        ev("G", "PRESS", shift=True)
        ev("G", "RELEASE", shift=True)
        yield STEP
        check(f"{label}:modal_started", scene.smartclip_runtime_info != "",
              repr(scene.smartclip_runtime_info))

    def world():
        return child.matrix_world.translation.copy()

    shot_dir = os.environ.get("SMARTCLIP_UI_SCREENSHOT_DIR")

    def screenshot(name):
        if shot_dir:
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.screen.screenshot_area(filepath=os.path.join(shot_dir, name))

    # Warm up: let the window activate the 3D View under the cursor.  The
    # first simulated key event after startup is dropped, so spend it on a
    # harmless ESC.
    for dx in (5, 0, 5, 0):
        ev("MOUSEMOVE", "NOTHING", dx=dx)
        yield STEP
    ev("ESC", "PRESS")
    ev("ESC", "RELEASE")
    yield STEP
    start_loc = child.location.copy()
    start_world = world()
    start_px = px(start_world)

    # 1. Parented object: no jump on start, follows the mouse, ESC restores
    yield from start_modal("parented")
    ev("MOUSEMOVE", "NOTHING")
    yield STEP
    check("parented_no_jump_on_start", (world() - start_world).length < 1e-4,
          f"moved {(world() - start_world).length:.4f}")
    ev("MOUSEMOVE", "NOTHING", dx=120)
    yield STEP
    offset = px(world()) - start_px
    check("parented_follows_mouse", (offset - Vector((120.0, 0.0))).length < 3.0,
          f"screen offset {tuple(round(v, 1) for v in offset)}")
    ev("ESC", "PRESS")
    yield STEP
    check("esc_restores_location", (child.location - start_loc).length < 1e-6)

    # 2. Orbiting mid-move must not make the object jump
    yield from start_modal("orbit")
    ev("MOUSEMOVE", "NOTHING", dx=60)
    yield STEP
    before = world()
    rv3d.view_rotation = rv3d.view_rotation @ Euler((0.0, 0.0, 0.5)).to_quaternion()
    area.tag_redraw()
    yield STEP
    ev("MOUSEMOVE", "NOTHING", dx=60)
    yield STEP
    check("view_change_no_jump", (world() - before).length < 1e-3,
          f"jumped {(world() - before).length:.4f}")
    ev("ESC", "PRESS")
    yield STEP
    rv3d.view_rotation = Euler((1.1, 0.0, 0.6)).to_quaternion()
    yield STEP

    # 3. Axis constraint holds in world space; LMB confirms
    yield from start_modal("constraint")
    ev("X", "PRESS")
    ev("X", "RELEASE")
    ev("MOUSEMOVE", "NOTHING", dx=80, dy=60)
    yield STEP
    screenshot("constraint.png")
    ev("LEFTMOUSE", "PRESS")
    ev("LEFTMOUSE", "RELEASE")
    yield STEP
    delta = world() - start_world
    check("x_constraint_world_space",
          abs(delta.y) < 1e-4 and abs(delta.z) < 1e-4 and abs(delta.x) > 0.01,
          f"delta {tuple(round(v, 4) for v in delta)}")
    child.location = start_loc
    bpy.context.view_layer.update()
    yield STEP

    # 4. Hard snap (hold RMB) lands exactly on a target vertex
    scene.target_scope = "VISIBLE"
    vertex = target.matrix_world @ target.data.vertices[0].co
    to_vertex = px(vertex) - px(start_world)
    yield from start_modal("hard_snap")
    ev("MOUSEMOVE", "NOTHING", dx=round(to_vertex.x), dy=round(to_vertex.y))
    yield STEP
    ev("RIGHTMOUSE", "PRESS")
    yield STEP
    check("hard_snap_on_vertex", (world() - vertex).length < 1e-4,
          f"off by {(world() - vertex).length:.4f}")
    screenshot("hard_snap.png")
    ev("RIGHTMOUSE", "RELEASE")
    ev("ESC", "PRESS")
    yield STEP
    check("esc_after_snap_restores", (child.location - start_loc).length < 1e-6)

    # 5. Edit Mode: move one vertex, ESC restores it
    scene.target_scope = "SELF"
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(child.data)
    bm.verts.ensure_lookup_table()
    bm.verts[0].select = True
    bmesh.update_edit_mesh(child.data)
    orig = bm.verts[0].co.copy()
    yield STEP
    yield from start_modal("edit_mode")
    ev("MOUSEMOVE", "NOTHING", dx=50, dy=-30)
    yield STEP
    bm = bmesh.from_edit_mesh(child.data)
    bm.verts.ensure_lookup_table()
    check("edit_mode_vertex_moves", (bm.verts[0].co - orig).length > 1e-3)
    ev("ESC", "PRESS")
    yield STEP
    bm = bmesh.from_edit_mesh(child.data)
    bm.verts.ensure_lookup_table()
    check("edit_mode_esc_restores", (bm.verts[0].co - orig).length < 1e-6)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode="OBJECT")
    yield STEP


def main():
    tee = _StderrTee(sys.stderr)
    sys.stderr = tee
    if not hasattr(bpy.types.Scene, "target_scope"):
        src.register()

    steps = _steps()

    def finish(crashed=False):
        sys.stderr = tee.inner
        errors = "".join(tee.captured)
        check("no_python_errors", not crashed and "Traceback" not in errors)
        failed = [name for name, ok in _results if not ok]
        print(f"[ui:test] summary: passed={len(_results) - len(failed)} failed={len(failed)}",
              flush=True)
        os._exit(1 if failed else 0)

    def tick():
        try:
            return next(steps)
        except StopIteration:
            finish()
        except Exception:
            traceback.print_exc()
            finish(crashed=True)
        return None

    bpy.app.timers.register(tick, first_interval=1.0)


if __name__ == "__main__":
    main()
