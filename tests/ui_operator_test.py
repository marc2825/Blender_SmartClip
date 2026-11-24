"""
End-to-end test of the modal operator in a real Blender UI using simulated
input events.  Needs a display (opens a Blender window for a few seconds);
real mouse / keyboard input is ignored while it runs.

Usage:
  blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py

Set SMARTCLIP_UI_SCREENSHOT_DIR to save screenshots of the overlays
(constraint.png, snap.png, align.png) for visual inspection,
SMARTCLIP_UI_STEP to wait longer between simulated events on slow (software)
OpenGL, SMARTCLIP_UI_BACKEND=KDTREE to run the checks with the experimental
KD-tree snap search instead of the default screen-space grid, and
SMARTCLIP_UI_LANGUAGE=ja_JP to run them with the interface in Japanese.

Exit code 0 = all checks passed, 1 = failures.
"""

import io
import os
import sys
import traceback
from types import SimpleNamespace

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Euler, Vector

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import smart_clipping  # noqa: E402

# Seconds between simulated events.  Software OpenGL on a virtual display
# redraws slowly, so CI sets SMARTCLIP_UI_STEP higher.
STEP = float(os.environ.get("SMARTCLIP_UI_STEP", "0.15"))
# Snap search backend (smart_clipping.utils.SEARCH_BACKENDS); empty = default.
BACKEND = os.environ.get("SMARTCLIP_UI_BACKEND", "").strip().upper()
# Interface language, e.g. ja_JP; empty = Blender's default (English).
LANGUAGE = os.environ.get("SMARTCLIP_UI_LANGUAGE", "").strip()

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


_skipped = []


def skip(name, reason):
    """A check that the environment made impossible (reported, not counted)."""
    _skipped.append(name)
    print(f"[SKIP] {name} {reason}", flush=True)


class _MoveSpy:
    """Keeps the running move operator, to read its state between events."""

    def __init__(self):
        self.op = None
        self._original = None

    def __enter__(self):
        cls = smart_clipping.ops.SMARTCLIP_OT_modal_move
        self._original = cls._handle_event
        original = self._original
        spy = self

        def recording(op, context, event):
            spy.op = op
            return original(op, context, event)

        cls._handle_event = recording
        return self

    def __exit__(self, *exc):
        smart_clipping.ops.SMARTCLIP_OT_modal_move._handle_event = self._original
        return False

    def state(self):
        try:
            return self.op.snap_state if self.op is not None else None
        except ReferenceError:
            return None


class _EventLog:
    """Records the Ctrl and mouse-move events the running move receives."""

    def __init__(self):
        self.events = []
        self._original = None

    def __enter__(self):
        cls = smart_clipping.ops.SMARTCLIP_OT_modal_move
        self._original = cls._handle_event
        log = self.events
        original = self._original

        def recording(op, context, event):
            if event.type in {"LEFT_CTRL", "RIGHT_CTRL", "MOUSEMOVE"}:
                log.append((event.type, event.value, bool(event.ctrl)))
            return original(op, context, event)

        cls._handle_event = recording
        return self

    def __exit__(self, *exc):
        smart_clipping.ops.SMARTCLIP_OT_modal_move._handle_event = self._original
        return False


def _view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next(r for r in area.regions if r.type == "WINDOW")
            return win, area, region, area.spaces.active.region_3d
    raise RuntimeError("no 3D View in the startup screen")


def _running():
    return bool(smart_clipping.ops._running_moves)


def _status_bar_taken():
    """Whether a move's keys replace the status bar (WorkSpace.status_text_set)."""
    from bl_ui.space_statusbar import STATUSBAR_HT_header
    original = getattr(STATUSBAR_HT_header, "_draw_orig", None)
    return original is not None and STATUSBAR_HT_header.draw is not original


def _show_sidebar(area):
    """Open the sidebar with the add-on's panels drawn for the whole test.

    The sidebar opens on its Item tab, which scripts cannot switch, so the
    panels are registered again in that tab, with the sub-panel open.
    """
    panel, limits = smart_clipping.SMARTCLIP_PT_panel, smart_clipping.SMARTCLIP_PT_limits
    bpy.utils.unregister_class(limits)
    bpy.utils.unregister_class(panel)
    panel.bl_category = limits.bl_category = "Item"
    limits.bl_options = set()
    bpy.utils.register_class(panel)
    bpy.utils.register_class(limits)
    area.spaces.active.show_region_ui = True


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
    print(f"[ui:test] Blender {bpy.app.version_string}, window {win.width}x{win.height}, "
          f"3D view region {region.width}x{region.height} at ({region.x}, {region.y}), "
          f"step {STEP}s, search {BACKEND or 'default'}, language {LANGUAGE or 'default'}",
          flush=True)
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
    rv3d.update()
    _show_sidebar(area)
    yield 0.5

    cx = region.x + region.width // 2
    cy = region.y + region.height // 2

    def ev(event_type, value, dx=0, dy=0, **mods):
        win.event_simulate(event_type, value, x=cx + dx, y=cy + dy, **mods)

    def px(co):
        return location_3d_to_region_2d(region, rv3d, co)

    def start_modal(label):
        ev("G", "PRESS", shift=True)
        ev("G", "RELEASE", shift=True)
        yield STEP
        check(f"{label}:modal_started", _running())

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
    check("status_bar_shows_keys", _status_bar_taken())
    ev("ESC", "PRESS")
    yield STEP
    check("esc_restores_location", (child.location - start_loc).length < 1e-6)
    check("status_bar_given_back", not _status_bar_taken())

    # RMB cancels too, as in Blender's own transform
    yield from start_modal("rmb_cancel")
    ev("MOUSEMOVE", "NOTHING", dx=90, dy=30)
    yield STEP
    moved_away = (world() - start_world).length
    ev("RIGHTMOUSE", "PRESS")
    ev("RIGHTMOUSE", "RELEASE")
    yield STEP
    check("rmb_cancels", moved_away > 1e-3 and not _running()
          and (child.location - start_loc).length < 1e-6, f"moved {moved_away:.3f}")

    # 2. Orbiting mid-move must not make the object jump
    yield from start_modal("orbit")
    ev("MOUSEMOVE", "NOTHING", dx=60)
    yield STEP
    before = world()
    rv3d.view_rotation = rv3d.view_rotation @ Euler((0.0, 0.0, 0.5)).to_quaternion()
    rv3d.update()
    area.tag_redraw()
    yield STEP
    ev("MOUSEMOVE", "NOTHING", dx=60)
    yield STEP
    check("view_change_no_jump", (world() - before).length < 1e-3,
          f"jumped {(world() - before).length:.4f}")
    ev("ESC", "PRESS")
    yield STEP
    rv3d.view_rotation = Euler((1.1, 0.0, 0.6)).to_quaternion()
    rv3d.update()
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
    # (snap_rule runs on every mouse move, whether or not there is anything
    # to snap to)
    mark = len(_TEE.captured)
    original_rule = smart_clipping.ops.snap_rule

    def failing_rule(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    smart_clipping.ops.snap_rule = failing_rule
    try:
        yield from start_modal("error")
        ev("MOUSEMOVE", "NOTHING", dx=40, dy=10)
        yield STEP
    finally:
        smart_clipping.ops.snap_rule = original_rule
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
        ev("G", "PRESS", shift=True)
        ev("G", "RELEASE", shift=True)
        yield STEP
        check("disabled_does_not_start", not _running())
        check("disabled_falls_through", SMARTCLIP_TEST_OT_probe.calls == 1,
              str(SMARTCLIP_TEST_OT_probe.calls))
        check("disabled_keeps_keymap_item",
              all(kmi.active for _km, kmi in smart_clipping._addon_keymaps))
    finally:
        scene.smartclip_enabled = True
    yield STEP

    # 3b. Every selected object moves by the same world delta
    target_start = target.matrix_world.translation.copy()
    target_start_loc = target.location.copy()
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
    target.location = target_start_loc
    target.select_set(False)
    bpy.context.view_layer.update()
    yield STEP

    check("target_put_back", (target.matrix_world.translation - target_start).length < 1e-6)

    # Confirming before any mouse move registers no operation (no undo step)
    registered = len(bpy.context.window_manager.operators)
    yield from start_modal("confirm_unmoved")
    ev("LEFTMOUSE", "PRESS")
    ev("LEFTMOUSE", "RELEASE")
    yield STEP
    check("unmoved_confirm_not_registered",
          len(bpy.context.window_manager.operators) == registered
          and (world() - start_world).length < 1e-9)

    # Numpad views work mid-move and the selection does not jump
    yield from start_modal("numpad")
    ev("MOUSEMOVE", "NOTHING", dx=40)
    yield STEP
    before_view = rv3d.view_rotation.copy()
    before = world()
    ev("NUMPAD_7", "PRESS")
    ev("NUMPAD_7", "RELEASE")
    yield STEP
    rv3d.update()
    ev("MOUSEMOVE", "NOTHING", dx=40)
    yield STEP
    check("numpad_view_changed", before_view.rotation_difference(rv3d.view_rotation).angle > 0.1)
    check("numpad_no_jump", (world() - before).length < 1e-3,
          f"jumped {(world() - before).length:.4f}")
    ev("ESC", "PRESS")
    yield STEP
    check("numpad_esc_restores", (child.location - start_loc).length < 1e-6)

    # Keys with modifiers pass through only when bound to view navigation:
    # Ctrl+Numpad7 (bottom view) works, while Ctrl+Numpad0 (Set Active Object
    # as Camera) and Alt+Wheel (change frame) must not run mid-move.
    registered = len(bpy.context.window_manager.operators)
    camera_before = scene.camera
    frame_before = scene.frame_current
    yield from start_modal("modified_keys")
    ev("MOUSEMOVE", "NOTHING", dx=30)
    yield STEP
    view_before = rv3d.view_rotation.copy()
    ev("NUMPAD_7", "PRESS", ctrl=True)
    ev("NUMPAD_7", "RELEASE", ctrl=True)
    yield STEP
    rv3d.update()
    check("ctrl_numpad_view_passes",
          view_before.rotation_difference(rv3d.view_rotation).angle > 0.1)
    distance_before = rv3d.view_distance
    ev("WHEELUPMOUSE", "PRESS")                    # plain wheel: zoom passes
    yield STEP
    check("wheel_zoom_passes", abs(rv3d.view_distance - distance_before) > 1e-4,
          f"{distance_before:.3f} -> {rv3d.view_distance:.3f}")
    rotation_before = rv3d.view_rotation.copy()
    ev("MIDDLEMOUSE", "PRESS", dx=30)              # middle-drag: orbit passes
    ev("MOUSEMOVE", "NOTHING", dx=110, dy=40)
    yield STEP
    ev("MIDDLEMOUSE", "RELEASE", dx=110, dy=40)
    yield STEP
    rv3d.update()
    check("middle_drag_orbit_passes",
          rotation_before.rotation_difference(rv3d.view_rotation).angle > 0.01)
    ev("MOUSEMOVE", "NOTHING", dx=30)
    yield STEP
    ev("NUMPAD_0", "PRESS", ctrl=True)
    ev("NUMPAD_0", "RELEASE", ctrl=True)
    ev("WHEELUPMOUSE", "PRESS", alt=True)
    yield STEP
    check("ctrl_numpad0_blocked", scene.camera == camera_before,
          str(scene.camera.name if scene.camera else None))
    check("alt_wheel_blocked", scene.frame_current == frame_before,
          f"{frame_before} -> {scene.frame_current}")
    ev("ESC", "PRESS")
    yield STEP
    check("modified_keys_register_nothing",
          len(bpy.context.window_manager.operators) == registered)
    scene.camera = camera_before
    scene.frame_current = frame_before
    rv3d.view_distance = 12.0
    rv3d.view_rotation = Euler((1.1, 0.0, 0.6)).to_quaternion()
    rv3d.view_perspective = "PERSP"
    rv3d.update()
    yield STEP

    # 4. Snap Exactly: a few pixels off a vertex lands exactly on it, no
    #    button needed; holding Ctrl moves freely; RMB cancels
    scene.smartclip_target_scope = "VISIBLE"
    vertex = target.matrix_world @ target.data.vertices[0].co
    to_vertex = px(vertex) - px(start_world)
    yield from start_modal("snap")
    build = smart_clipping.ops.last_build(scene)
    check("snap:search_backend",
          build is not None and build.backend == (BACKEND or smart_clipping.utils.SEARCH_GRID),
          repr(build))
    near = dict(dx=round(to_vertex.x) + 3, dy=round(to_vertex.y) - 2)
    ev("MOUSEMOVE", "NOTHING", **near)
    yield STEP
    check("snaps_exactly_on_vertex", (world() - vertex).length < 1e-4,
          f"off by {(world() - vertex).length:.4f}")
    screenshot("snap.png")
    with _EventLog() as log:
        ev("LEFT_CTRL", "PRESS", ctrl=True, **near)
        ev("MOUSEMOVE", "NOTHING", ctrl=True, **near)
        yield STEP
    moved_freely = (world() - vertex).length > 1e-3
    # Only Ctrl presses and moves with Ctrl held were sent.  If the move saw
    # Ctrl released anyway, the display synced the modifier from the real
    # keyboard (seen on some X11 virtual displays): the add-on followed what it
    # was told, so the check cannot say anything there.
    dropped = [e for e in log.events
               if (e[0] != "MOUSEMOVE" and e[1] == "RELEASE") or (e[0] == "MOUSEMOVE" and not e[2])]
    if not moved_freely and dropped:
        skip("ctrl_moves_freely", f"the display reported Ctrl as released: {log.events}")
    else:
        check("ctrl_moves_freely", moved_freely,
              f"off by {(world() - vertex).length:.4f}; events {log.events}")
    ev("LEFT_CTRL", "RELEASE", **near)
    ev("MOUSEMOVE", "NOTHING", **near)
    yield STEP
    check("ctrl_release_snaps_again", (world() - vertex).length < 1e-4)
    ev("RIGHTMOUSE", "PRESS")
    ev("RIGHTMOUSE", "RELEASE")
    yield STEP
    check("rmb_after_snap_restores", not _running()
          and (child.location - start_loc).length < 1e-6)

    # Reachable: Snapped (the vertex of 4. again, watched through the spy)
    with _MoveSpy() as spy:
        yield from start_modal("snapped_state")
        ev("MOUSEMOVE", "NOTHING", **near)
        yield STEP
        check("reachable_vertex_snapped",
              spy.state() == smart_clipping.utils.STATE_SNAPPED
              and (world() - vertex).length < 1e-4, f"state {spy.state()}")
        ev("ESC", "PRESS")
        yield STEP

    # 4b. Exact snaps the move cannot reach (#28), seen from the top
    #     (orthographic, so mouse offsets are world X / Y offsets).
    #     Single-vertex targets on the -X side, away from the other objects.
    saved_view = (rv3d.view_perspective, rv3d.view_rotation.copy(),
                  rv3d.view_location.copy(), rv3d.view_distance)
    rv3d.view_perspective = "ORTHO"
    rv3d.view_rotation = Euler((0.0, 0.0, 0.0)).to_quaternion()
    rv3d.view_location = start_world
    rv3d.view_distance = 6.0
    rv3d.update()
    yield STEP

    def point_object(name, co):
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        mesh.from_pydata([tuple(co)], [], [])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return obj

    def to_px(co):
        d = px(co) - px(start_world)
        return dict(dx=round(d.x), dy=round(d.y))

    off_axis = start_world + Vector((-1.2, 0.06, 0.0))
    point_object("UI_OffAxis", off_axis)
    bpy.context.view_layer.update()
    with _MoveSpy() as spy:
        yield from start_modal("projected_axis")
        ev("MOUSEMOVE", "NOTHING", **to_px(start_world + Vector((-1.2, 0.0, 0.0))))
        yield STEP
        unconstrained = spy.state()
        ev("X", "PRESS")
        ev("X", "RELEASE")
        yield STEP
        pos = world()
        check("x_constraint_projects_vertex",
              spy.state() == smart_clipping.utils.STATE_PROJECTED
              and abs(pos.x - off_axis.x) < 1e-4
              and abs(pos.y - start_world.y) < 1e-5 and abs(pos.z - start_world.z) < 1e-5,
              f"state {unconstrained} -> {spy.state()}, at {tuple(round(v, 4) for v in pos)}")
        check("off_axis_vertex_snapped_before_constraint",
              unconstrained == smart_clipping.utils.STATE_SNAPPED, str(unconstrained))
        screenshot("projected.png")
        ev("RIGHTMOUSE", "PRESS")
        ev("RIGHTMOUSE", "RELEASE")
        yield STEP
        check("projected_rmb_restores", not _running()
              and (child.location - start_loc).length < 1e-6)
    bpy.data.objects.remove(bpy.data.objects["UI_OffAxis"])

    # Location Lock Z (the parent rotates about Z only, so this is world Z)
    above = start_world + Vector((-0.9, 0.3, 0.45))
    point_object("UI_Above", above)
    child.lock_location[2] = True
    bpy.context.view_layer.update()
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.ed.undo_push(message="Smart Clipping UI test: Location Lock")
    yield STEP
    with _MoveSpy() as spy:
        yield from start_modal("projected_lock")
        ev("MOUSEMOVE", "NOTHING", **to_px(above))
        yield STEP
        pos = world()
        state = spy.state()
        ev("LEFTMOUSE", "PRESS")
        ev("LEFTMOUSE", "RELEASE")
        yield STEP
    locked_pos = world()
    check("location_lock_projected",
          state == smart_clipping.utils.STATE_PROJECTED
          and abs(pos.z - start_world.z) < 1e-5
          and abs(pos.x - above.x) < 1e-4 and abs(pos.y - above.y) < 1e-4,
          f"state {state}, at {tuple(round(v, 4) for v in pos)}")
    check("location_lock_confirm_keeps_position", (locked_pos - pos).length < 1e-5)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.ed.undo()
    yield STEP
    child = bpy.data.objects["UI_Child"]
    target = bpy.data.objects["UI_Target"]
    scene = bpy.context.scene
    check("location_lock_undo", (world() - start_world).length < 1e-5)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.ed.redo()
    yield STEP
    child = bpy.data.objects["UI_Child"]
    target = bpy.data.objects["UI_Target"]
    scene = bpy.context.scene
    check("location_lock_redo", (world() - locked_pos).length < 1e-5,
          f"{tuple(round(v, 4) for v in world())}")
    child.location = start_loc
    child.lock_location[2] = False
    bpy.data.objects.remove(bpy.data.objects["UI_Above"])
    bpy.context.view_layer.update()

    # An object constraint (Limit Location, world space) stops it short
    beyond = start_world + Vector((-1.2, 0.25, 0.0))
    point_object("UI_Beyond", beyond)
    limit = child.constraints.new("LIMIT_LOCATION")
    limit.use_min_x = True
    limit.min_x = start_world.x - 0.5
    bpy.context.view_layer.update()
    with _MoveSpy() as spy:
        yield from start_modal("projected_limit")
        ev("MOUSEMOVE", "NOTHING", **to_px(beyond))
        yield STEP
        pos = world()
        check("limit_location_projected",
              spy.state() == smart_clipping.utils.STATE_PROJECTED
              and abs(pos.x - limit.min_x) < 1e-4,
              f"state {spy.state()}, at {tuple(round(v, 4) for v in pos)}")
        ev("ESC", "PRESS")
        yield STEP
    child.constraints.remove(limit)
    bpy.data.objects.remove(bpy.data.objects["UI_Beyond"])
    bpy.context.view_layer.update()
    check("limit_location_esc_restores", not _running()
          and (world() - start_world).length < 1e-5)

    rv3d.view_perspective, rv3d.view_rotation, rv3d.view_location, rv3d.view_distance =         saved_view
    rv3d.update()
    yield STEP

    # A cycles Align Only (Off -> X -> Y); Esc puts it back, LMB keeps it
    yield from start_modal("align_key")
    for _ in range(2):
        ev("A", "PRESS")
        ev("A", "RELEASE")
    ev("MOUSEMOVE", "NOTHING", dx=40, dy=25)
    yield STEP
    check("a_cycles_align_only",
          (scene.smartclip_align_x, scene.smartclip_align_y, scene.smartclip_align_z)
          == (False, True, False))
    screenshot("align.png")
    ev("ESC", "PRESS")
    yield STEP
    check("esc_restores_align_only",
          not (scene.smartclip_align_x or scene.smartclip_align_y or scene.smartclip_align_z))
    yield from start_modal("align_key_confirm")
    ev("A", "PRESS")
    ev("A", "RELEASE")
    ev("MOUSEMOVE", "NOTHING", dx=40, dy=25)
    yield STEP
    ev("LEFTMOUSE", "PRESS")
    ev("LEFTMOUSE", "RELEASE")
    yield STEP
    check("confirm_keeps_align_only", scene.smartclip_align_x and not scene.smartclip_align_y)
    scene.smartclip_align_x = False
    child.location = start_loc
    bpy.context.view_layer.update()
    yield STEP

    # S cycles Snap To and collects the snap points again
    coll = bpy.data.collections.new("UI_Snap_Collection")
    scene.collection.children.link(coll)
    coll.objects.link(target)
    scene.smartclip_target_collection = coll
    yield from start_modal("snap_to_key")
    ev("S", "PRESS")
    ev("S", "RELEASE")
    ev("MOUSEMOVE", "NOTHING", dx=20)
    yield STEP
    build = smart_clipping.ops.last_build(scene)
    check("s_cycles_snap_to", scene.smartclip_target_scope == "COLLECTION"
          and build is not None and build.points == len(target.data.vertices), repr(build))
    ev("ESC", "PRESS")
    yield STEP
    check("esc_restores_snap_to", scene.smartclip_target_scope == "VISIBLE")
    scene.smartclip_target_collection = None
    bpy.data.collections.remove(coll)
    bpy.context.view_layer.update()
    yield STEP

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

    # Ctrl+Numpad+ / - are Select More / Less in Edit Mode: not mid-move
    selected_before = sum(v.select for v in bm.verts)
    registered = len(bpy.context.window_manager.operators)
    yield from start_modal("edit_modified_keys")
    ev("MOUSEMOVE", "NOTHING", dx=20)
    yield STEP
    for key in ("NUMPAD_PLUS", "NUMPAD_MINUS", "NUMPAD_PLUS"):
        ev(key, "PRESS", ctrl=True)
        ev(key, "RELEASE", ctrl=True)
    yield STEP
    ev("ESC", "PRESS")
    yield STEP
    bm = bmesh.from_edit_mesh(child.data)
    bm.verts.ensure_lookup_table()
    check("ctrl_numpad_select_blocked", sum(v.select for v in bm.verts) == selected_before,
          f"{selected_before} -> {sum(v.select for v in bm.verts)}")
    check("edit_modified_keys_register_nothing",
          len(bpy.context.window_manager.operators) == registered)
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
    rv3d.update()
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
    if LANGUAGE:
        view = bpy.context.preferences.view
        view.language = LANGUAGE
        view.use_translate_interface = True
        view.use_translate_tooltips = True
    if BACKEND:
        # Registered by path, the add-on has no stored preferences: hand the
        # snap point collection the requested backend directly.
        if BACKEND not in smart_clipping.utils.SEARCH_BACKENDS:
            raise SystemExit(f"SMARTCLIP_UI_BACKEND must be one of "
                             f"{smart_clipping.utils.SEARCH_BACKENDS}, not {BACKEND!r}")
        prefs = SimpleNamespace(max_vertex_budget=smart_clipping.utils.DEFAULT_VERTEX_BUDGET,
                                search_backend=BACKEND)
        smart_clipping.detector.get_addon_prefs = lambda _ctx: prefs
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
        print(f"[ui:test] summary: passed={len(_results) - len(failed)} failed={len(failed)}"
              f"{f' skipped={len(_skipped)}' if _skipped else ''}",
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
