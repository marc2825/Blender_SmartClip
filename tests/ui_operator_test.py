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

import smart_clipping  # noqa: E402

STEP = 0.15  # seconds between simulated events

_results = []
_TEE = None


class SMARTCLIP_TEST_OT_probe(bpy.types.Operator):
    """Records that a key press reached the keymap item after Smart Clipping's."""
    bl_idname = "smartclip_test.probe"
    bl_label = "Smart Clipping Test Probe"
    calls = 0

    def invoke(self, _context, _event):
        SMARTCLIP_TEST_OT_probe.calls += 1
        return {"FINISHED"}


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
    scene.smartclip_target_scope = "SELF"  # Object Mode + SELF = no snap targets

    _parent, child, target = _setup_scene()
    bpy.context.view_layer.update()
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.ed.undo_push(message="Smart Clipping UI test scene")
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
    # The final offset is stored for the Adjust Last Operation (redo) panel.
    ops_done = bpy.context.window_manager.operators
    last = ops_done[-1] if len(ops_done) else None
    check("redo_offset_recorded",
          last is not None and last.bl_idname == "VIEW3D_OT_smartclip_move"
          and (Vector(last.properties.offset) - delta).length < 1e-4,
          f"{last.bl_idname if last else None}")

    # Editing Offset in Adjust Last Operation redoes the move with the new
    # value (what the panel does: undo, then execute with the new property;
    # undo reloads the data, so object references are fetched again)
    new_offset = Vector((0.3, -0.2, 0.15))
    last.properties.offset = new_offset
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.ed.undo_redo()
    yield STEP
    child = bpy.data.objects["UI_Child"]
    target = bpy.data.objects["UI_Target"]
    scene = bpy.context.scene
    moved = world() - start_world
    check("redo_applies_edited_offset", (moved - new_offset).length < 1e-4,
          f"moved {tuple(round(v, 4) for v in moved)}")
    child.location = start_loc
    bpy.context.view_layer.update()
    yield STEP

    # An internal error mid-move restores the selection and cleans up
    mark = len(_TEE.captured)
    original_find = smart_clipping.detector.find_candidates

    def failing_find(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    smart_clipping.detector.find_candidates = failing_find
    try:
        yield from start_modal("error")
        ev("MOUSEMOVE", "NOTHING", dx=40, dy=10)
        yield STEP
    finally:
        smart_clipping.detector.find_candidates = original_find
    injected = "".join(_TEE.captured[mark:])
    del _TEE.captured[mark:]
    check("error_reported", "injected failure" in injected)
    check("error_restores_position", (world() - start_world).length < 1e-6)
    check("error_removes_draw_handlers", not smart_clipping.ops._live_draw_handles,
          str(len(smart_clipping.ops._live_draw_handles)))
    # The error report pops up under the cursor and takes the next key press
    ev("MOUSEMOVE", "NOTHING", dx=200, dy=150)
    ev("ESC", "PRESS")
    ev("ESC", "RELEASE")
    ev("MOUSEMOVE", "NOTHING")
    yield STEP
    yield from start_modal("after_error")      # the operator still works
    ev("ESC", "PRESS")
    yield STEP

    # Scene setting off: the shared keymap item stays, poll() refuses, and the
    # key press continues to the next keymap item.  The probe item registered
    # in main() sits right after ours, in front of Blender's own Shift+G.
    order = [k.idname for k in bpy.context.window_manager.keyconfigs.user
             .keymaps["Object Mode"].keymap_items if k.type == "G" and k.shift and not k.ctrl]
    check("probe_follows_smart_clipping",
          order[:2] == ["view3d.smartclip_move", "smartclip_test.probe"], str(order))
    try:
        SMARTCLIP_TEST_OT_probe.calls = 0
        yield from start_modal("enabled_has_priority")
        ev("ESC", "PRESS")
        yield STEP
        check("enabled_takes_precedence", SMARTCLIP_TEST_OT_probe.calls == 0)

        scene.smartclip_enabled = False
        scene.smartclip_runtime_info = ""
        ev("G", "PRESS", shift=True)
        ev("G", "RELEASE", shift=True)
        yield STEP
        check("disabled_does_not_start", scene.smartclip_runtime_info == "")
        check("disabled_falls_through", SMARTCLIP_TEST_OT_probe.calls == 1,
              str(SMARTCLIP_TEST_OT_probe.calls))
        check("disabled_keeps_keymap_item",
              all(kmi.active for _km, kmi in smart_clipping._addon_keymaps))
    finally:
        scene.smartclip_enabled = True
    yield STEP

    # 3b. Every selected object moves by the same world delta
    target_start = target.matrix_world.translation.copy()
    target.select_set(True)
    yield from start_modal("multi_select")
    ev("MOUSEMOVE", "NOTHING", dx=70, dy=-20)
    yield STEP
    ev("LEFTMOUSE", "PRESS")
    ev("LEFTMOUSE", "RELEASE")
    yield STEP
    d_child = world() - start_world
    d_target = target.matrix_world.translation - target_start
    check("multi_select_moves_together",
          d_child.length > 0.01 and (d_child - d_target).length < 1e-4,
          f"child {tuple(round(v, 3) for v in d_child)} target {tuple(round(v, 3) for v in d_target)}")

    # Undo puts every moved object back; redo moves them again
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.ed.undo()
    yield STEP
    child = bpy.data.objects["UI_Child"]
    target = bpy.data.objects["UI_Target"]
    scene = bpy.context.scene
    check("undo_restores_all_moved",
          (world() - start_world).length < 1e-4
          and (target.matrix_world.translation - target_start).length < 1e-4)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.ed.redo()
    yield STEP
    child = bpy.data.objects["UI_Child"]
    target = bpy.data.objects["UI_Target"]
    scene = bpy.context.scene
    check("redo_moves_again", ((world() - start_world) - d_child).length < 1e-4
          and ((target.matrix_world.translation - target_start) - d_target).length < 1e-4)
    child.location = start_loc
    target.matrix_world.translation = target_start
    target.select_set(False)
    bpy.context.view_layer.update()
    yield STEP

    # 4. Hard snap (hold RMB) lands exactly on a target vertex
    scene.smartclip_target_scope = "VISIBLE"
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
    scene.smartclip_target_scope = "SELF"
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
    check("no_leftover_draw_handlers", not smart_clipping.ops._live_draw_handles)

    # Loading a file mid-move cancels the operator and removes its handlers
    yield from start_modal("file_load")
    ev("MOUSEMOVE", "NOTHING", dx=30)
    yield STEP
    with bpy.context.temp_override(window=win):
        bpy.ops.wm.read_homefile()
    yield 0.5
    check("file_load_removes_draw_handlers", not smart_clipping.ops._live_draw_handles,
          str(len(smart_clipping.ops._live_draw_handles)))

    # Disabling the add-on mid-move puts the selection back and cleans up
    # (Blender drops the modal handler without calling cancel()).  The file
    # load replaced the screen, so the window, area and region are fetched
    # again (event_simulate on the old ones crashes Blender).
    win, area, region, rv3d = _view3d()
    cx = region.x + region.width // 2
    cy = region.y + region.height // 2
    for dx in (5, 0):
        ev("MOUSEMOVE", "NOTHING", dx=dx)
        yield STEP
    cube = bpy.data.objects["Cube"]               # the startup file's cube
    cube_start = cube.matrix_world.translation.copy()
    scene = bpy.context.scene
    yield from start_modal("unregister")
    ev("MOUSEMOVE", "NOTHING", dx=90)
    yield STEP
    moved = (cube.matrix_world.translation - cube_start).length
    smart_clipping.unregister()
    yield STEP
    check("unregister_restores_selection",
          moved > 1e-3 and (cube.matrix_world.translation - cube_start).length < 1e-6,
          f"moved {moved:.3f}")
    check("unregister_removes_draw_handlers", not smart_clipping.ops._live_draw_handles)
    # The dropped handler can linger as a None entry until the next event.
    ev("MOUSEMOVE", "NOTHING", dx=20)
    ev("LEFTMOUSE", "PRESS")
    ev("LEFTMOUSE", "RELEASE")
    yield STEP
    leftover = [m for m in getattr(bpy.context.window, "modal_operators", [])
                if m is None or m.bl_idname == "VIEW3D_OT_smartclip_move"]
    check("unregister_ends_modal", not leftover, str(leftover))
    check("unregister_leaves_selection_alone",
          (cube.matrix_world.translation - cube_start).length < 1e-6)


def main():
    global _TEE
    tee = _TEE = _StderrTee(sys.stderr)
    sys.stderr = tee
    if not hasattr(bpy.types.Scene, "smartclip_target_scope"):
        smart_clipping.register()
    bpy.utils.register_class(SMARTCLIP_TEST_OT_probe)
    # Added in the same tick as the add-on's items so both are merged into the
    # user keymap together; head=True places it right after Smart Clipping's.
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="Object Mode", space_type="EMPTY", region_type="WINDOW")
    km.keymap_items.new("smartclip_test.probe", type="G", value="PRESS", shift=True, head=True)

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

    # persistent: the last step loads a file, which drops ordinary timers
    bpy.app.timers.register(tick, first_interval=1.0, persistent=True)


if __name__ == "__main__":
    main()
