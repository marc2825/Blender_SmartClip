"""Modal operator that drives the Smart Clipping move workflow.

Lifecycle
---------
invoke  -- gather what moves, collect the snap points, register draw handlers,
           show the keys in the status bar.
modal   -- process mouse / keyboard, search snap candidates, apply snap, redraw.
finish  -- remove draw handlers, clear the status bar, store the final offset
           for redo.
cancel  -- called by Blender when the modal is aborted externally
           (file load, window close): restore and clean up.
execute -- apply ``offset`` directly (redo panel / scripting).

Keys during a move: LMB / Enter confirm; RMB / Esc cancel; holding Ctrl moves
freely (Snap Exactly) or snaps exactly (Gradual Pull); X / Y / Z and
Shift+X / Y / Z constrain to an axis / plane; A cycles Align Only; S cycles
Snap To.  Settings changed with A and S are kept when the move is confirmed
and put back when it is cancelled, like Blender's own transform.
"""

import traceback
from collections import namedtuple

import bmesh
import bpy
from bpy.props import BoolVectorProperty, FloatVectorProperty, StringProperty
from mathutils import Vector

from . import detector, drawing, hud
from .i18n import rpt, tip
from .prefs import get_addon_prefs
from .utils import (
    DEFAULT_SNAP_BEHAVIOR,
    DEFAULT_SNAP_DISTANCE_PX,
    STATE_FREE,
    STATE_NONE,
    STATE_PROJECTED,
    STATE_PULLING,
    STATE_SNAPPED,
    apply_constraint,
    constraint_axes,
    next_align_axes,
    next_scope,
    pixel_world_size,
    pull_ratio,
    screen_to_world,
    snap_rule,
    world_to_location_matrix,
    world_to_screen,
)

# The 3D search radius covers half the viewport at the depth of the moving
# point, so it follows the view scale.  The screen-pixel filter
# (snap_distance_px) decides; the radius only keeps distant points that
# happen to line up on screen out (and bounds the depth the KD-tree search
# looks at).
QUERY_RADIUS_VIEWPORT_FRACTION = 0.5

# Gradual Pull strength at zero screen distance.
SOFT_PULL_POINT = 0.35
SOFT_PULL_ALIGN = 0.5

_CTRL_KEYS = {"LEFT_CTRL", "RIGHT_CTRL"}
_AXIS_KEYS = {"X", "Y", "Z"}

# Input that can navigate the viewport mid-move.  Such an event is handed to
# Blender only when the user's keymap binds it to a view operator (below), so
# e.g. Ctrl+Numpad+ (Select More) or Alt+Wheel (change frame) cannot fire.
_NAVIGATION_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM",
    "NDOF_MOTION",
    # numpad views, zoom and View Selected / View All
    "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
    "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
    "NUMPAD_PERIOD", "NUMPAD_PLUS", "NUMPAD_MINUS",
    "HOME",
}

# Operators that only change the view.
_VIEW_OPERATORS = {
    "view3d.rotate", "view3d.move", "view3d.zoom", "view3d.dolly",
    "view3d.view_axis", "view3d.view_orbit", "view3d.view_pan", "view3d.view_roll",
    "view3d.view_selected", "view3d.view_all", "view3d.view_center_cursor",
    "view3d.view_center_pick", "view3d.view_persportho", "view3d.view_camera",
    "view3d.ndof_orbit", "view3d.ndof_orbit_zoom", "view3d.ndof_pan", "view3d.ndof_all",
}

# Keymaps consulted, in the order the 3D Viewport handles them: the mode's
# own keymap first, then the shared ones.
_MODE_KEYMAPS = {"OBJECT": ("Object Mode",), "EDIT_MESH": ("Mesh",)}
_SHARED_KEYMAPS = ("Object Non-modal", "Frames", "3D View Generic", "3D View")


def _modifiers_match(kmi, event) -> bool:
    if getattr(kmi, "any", False):
        return True
    for mod in ("shift", "ctrl", "alt", "oskey", "hyper"):
        want = getattr(kmi, mod, 0)
        if want == -1:                       # "any state" for this modifier
            continue
        if bool(want) != bool(getattr(event, mod, False)):
            return False
    return True


# Keymaps bind wheel zoom to the "in" / "out" directions, which Blender maps
# to wheel up / down depending on the Invert Zoom preference.
_EVENT_TYPE_ALIASES = {
    "WHEELUPMOUSE": ("WHEELUPMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE"),
    "WHEELDOWNMOUSE": ("WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE"),
}


def first_binding(keymaps, event):
    """Operator id of the first active item in *keymaps* that *event* triggers."""
    types = _EVENT_TYPE_ALIASES.get(event.type, (event.type,))
    for km in keymaps:
        if km is None:
            continue
        for kmi in km.keymap_items:
            if not kmi.active or kmi.type not in types:
                continue
            if kmi.value not in (event.value, "ANY"):
                continue
            if getattr(kmi, "key_modifier", "NONE") not in ("NONE", None):
                continue
            if _modifiers_match(kmi, event):
                return kmi.idname
    return None


def passes_to_navigation(context, event) -> bool:
    """True when *event* would only navigate the view (see _VIEW_OPERATORS)."""
    if event.type not in _NAVIGATION_EVENTS:
        return False
    keyconfig = context.window_manager.keyconfigs.user
    names = _MODE_KEYMAPS.get(context.mode, ()) + _SHARED_KEYMAPS
    keymaps = [keyconfig.keymaps.get(name) for name in names]
    return first_binding(keymaps, event) in _VIEW_OPERATORS

# Every draw handler currently installed by a running operator.  Kept at
# module level so unregister() can remove leftovers even if an operator
# instance died without cleaning up.
_live_draw_handles: list = []
# Movers of moves in progress, and the settings (scene, values) each move
# started with.  Unregistering the operator class drops its running modal
# handler without calling cancel(), so unregister() restores these itself.
_running_moves: list = []
_running_settings: dict = {}   # id(movers) -> (scene, settings at start)


def remove_all_draw_handlers():
    """Undo moves in progress, remove every draw handler and give the status
    bar back (used on unregister)."""
    if _running_moves:
        _clear_status(getattr(bpy.context, "workspace", None))
    for movers in list(_running_moves):
        for mover in movers:
            try:
                mover.restore()
            except Exception:
                traceback.print_exc()
    for scene, settings in list(_running_settings.values()):
        try:
            _write_settings(scene, settings)
        except (ReferenceError, AttributeError, TypeError):
            pass
    _running_moves.clear()
    _running_settings.clear()
    for handle in _live_draw_handles:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
    _live_draw_handles.clear()


def _add_handler(callback, op, draw_type):
    handle = bpy.types.SpaceView3D.draw_handler_add(callback, (op, None), "WINDOW", draw_type)
    _live_draw_handles.append(handle)
    return handle


def _remove_handler(handle):
    try:
        bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
    except (ValueError, RuntimeError):
        pass
    if handle in _live_draw_handles:
        _live_draw_handles.remove(handle)


# ----------------------------------------------------------------------
# Movers: what gets translated, and how to undo it
# ----------------------------------------------------------------------

class _ObjectMover:
    """Translates one object; `location` lives in its parent space."""

    __slots__ = ("obj", "init_loc", "to_loc", "lock")

    def __init__(self, obj):
        self.obj = obj
        self.init_loc = obj.location.copy()
        self.to_loc = world_to_location_matrix(obj)
        self.lock = tuple(obj.lock_location)

    def apply(self, delta_world: Vector):
        delta = self.to_loc @ delta_world
        for i, locked in enumerate(self.lock):
            if locked:
                delta[i] = 0.0
        self.obj.location = self.init_loc + delta

    def restore(self):
        self.obj.location = self.init_loc


class _EditMover:
    """Translates the selected vertices of one mesh in Edit Mode."""

    __slots__ = ("obj", "init_cos", "to_local")

    def __init__(self, obj, init_cos):
        self.obj = obj
        self.init_cos = init_cos  # {lookup-table index: local co}
        self.to_local = obj.matrix_world.inverted_safe().to_3x3()

    def _write(self, delta_local: Vector):
        bm = bmesh.from_edit_mesh(self.obj.data)
        bm.verts.ensure_lookup_table()
        for idx, orig in self.init_cos.items():
            bm.verts[idx].co = orig + delta_local
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)

    def apply(self, delta_world: Vector):
        self._write(self.to_local @ delta_world)

    def restore(self):
        self._write(Vector((0.0, 0.0, 0.0)))


def _edit_mode_objects(context):
    """Meshes in Edit Mode, active first, one per mesh datablock."""
    candidates = list(getattr(context, "objects_in_mode_unique_data", None) or [])
    active = context.active_object
    if active is not None and active.mode == "EDIT" and active.type == "MESH":
        candidates.insert(0, active)
    seen = set()
    result = []
    for obj in candidates:
        if obj.type != "MESH" or obj.mode != "EDIT":
            continue
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            result.append(obj)
    return result


def _has_moving_ancestor(obj, moving_ptrs) -> bool:
    parent = obj.parent
    while parent is not None:
        if parent.as_pointer() in moving_ptrs:
            return True
        parent = parent.parent
    return False


def gather_movers(context, scope=None):
    """Return ``(pivot_world, movers)`` for the current selection.

    Object Mode: every selected editable object (falling back to the active
    one); children of a moving parent are left to the parent.  With Snap To
    set to Selected Objects only the active object moves, because the other
    selected objects are what it snaps to.  The pivot is the active object's
    origin when it moves, otherwise the median origin.  *scope* overrides
    the scene's Snap To for this decision (a redo uses the move's own).

    Edit Mode: the selected vertices of every mesh in Edit Mode; the pivot
    is their median point.  ``movers`` is empty when nothing would move.
    See pivot_objects() for where the pivot is once the movers moved.
    """
    # matrix_world can be stale (right after undo, or when a script changed
    # transforms); the parent-space conversion relies on it.
    context.view_layer.update()
    active = context.active_object

    if context.mode == "EDIT_MESH":
        movers = []
        world_sum = Vector((0.0, 0.0, 0.0))
        count = 0
        for obj in _edit_mode_objects(context):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            # Lookup-table positions (BMVert.index may be dirty after edits);
            # they match mesh.vertices order once the edit mesh is flushed.
            sel = {i: v.co.copy() for i, v in enumerate(bm.verts) if v.select}
            if not sel:
                continue
            mw = obj.matrix_world
            for co in sel.values():
                world_sum += mw @ co
            count += len(sel)
            movers.append(_EditMover(obj, sel))
        pivot = world_sum / count if count else Vector((0.0, 0.0, 0.0))
        return pivot, movers

    selected = list(context.selected_editable_objects)
    if not scope:
        scope = getattr(context.scene, "smartclip_target_scope", None)
    snaps_to_selection = scope == "SELECTED"
    active_editable = active is not None and active in list(context.editable_objects)
    if active_editable and (snaps_to_selection or not selected):
        selected = [active]
    elif snaps_to_selection:
        selected = []
    moving_ptrs = {obj.as_pointer() for obj in selected}
    roots = [obj for obj in selected if not _has_moving_ancestor(obj, moving_ptrs)]
    movers = [_ObjectMover(obj) for obj in roots]
    if not movers:
        return Vector((0.0, 0.0, 0.0)), movers

    active_moves = active is not None and (
        active.as_pointer() in moving_ptrs or _has_moving_ancestor(active, moving_ptrs)
    )
    if active_moves:
        pivot = active.matrix_world.translation.copy()
    else:
        pivot = sum((m.obj.matrix_world.translation for m in movers), Vector()) / len(movers)
    return pivot, movers


def pivot_objects(context, movers) -> list:
    """Objects whose evaluated origins give the pivot (Object Mode), or [].

    The active object when it moves (itself or with a moving parent), else
    every moving object (the median origin), as in gather_movers().
    """
    if context.mode == "EDIT_MESH" or not movers:
        return []
    active = context.active_object
    moving = {m.obj.as_pointer() for m in movers}
    if active is not None and (active.as_pointer() in moving
                               or _has_moving_ancestor(active, moving)):
        return [active]
    return [m.obj for m in movers]


def reached(position: Vector, target: Vector, pixel_size=None) -> bool:
    """Whether *position* is on *target*, allowing for float32 rounding.

    The tolerance is relative to the coordinates and, when the size of a
    pixel there is known, at most a twentieth of it, so a point visibly off
    the target never counts as on it, at any scene scale.
    """
    scale = max(1.0, max(abs(c) for c in target), max(abs(c) for c in position))
    tolerance = 1e-5 * scale
    if pixel_size:
        tolerance = min(tolerance, 0.05 * pixel_size)
    return (position - target).length <= tolerance


# ----------------------------------------------------------------------
# What the last move collected (sidebar) and the move's settings
# ----------------------------------------------------------------------

# Per scene, in memory only: nothing about a move is saved into the .blend.
BuildSummary = namedtuple("BuildSummary", "points limit_exceeded simplified skipped backend")
_last_builds: dict = {}


def build_summary(build) -> BuildSummary:
    if build is None:
        return BuildSummary(0, False, 0, 0, None)
    simplified = len(set(build.partial_objects) | set(build.bounds_objects))
    return BuildSummary(build.point_count, bool(build.limit_exceeded), simplified,
                        len(build.skipped_objects), build.backend)


def last_build(scene) -> "BuildSummary | None":
    """What the last move in *scene* collected, or None."""
    try:
        return _last_builds.get(scene.as_pointer())
    except ReferenceError:
        return None


_SETTING_PROPS = ("smartclip_target_scope", "smartclip_align_x", "smartclip_align_y",
                  "smartclip_align_z")


def _read_settings(scene) -> tuple:
    return tuple(getattr(scene, name) for name in _SETTING_PROPS)


def _write_settings(scene, values):
    for name, value in zip(_SETTING_PROPS, values):
        if getattr(scene, name) != value:
            setattr(scene, name, value)


def _align_axes(scene) -> frozenset:
    return frozenset(axis for axis in ("X", "Y", "Z")
                     if getattr(scene, f"smartclip_align_{axis.lower()}", False))


def _tag_redraw_view3d(context):
    """Redraw the 3D Views, sidebars included (settings changed mid-move)."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


# ----------------------------------------------------------------------
# Status bar: the keys that work during a move
# ----------------------------------------------------------------------

_icon_names = None


def _valid_icons() -> frozenset:
    global _icon_names
    if _icon_names is None:
        param = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
        _icon_names = frozenset(param.enum_items.keys())
    return _icon_names


def status_draw_fn(behavior):
    """Draw function for the status bar (``WorkSpace.status_text_set``)."""
    items = hud.status_items(behavior)

    def draw(header, _context):
        layout = header.layout
        try:
            icons_ok = _valid_icons()
            for icons, label in items:
                row = layout.row(align=True)
                for icon in icons[:-1]:
                    row.label(text="", icon=icon if icon in icons_ok else "NONE")
                last = icons[-1]
                row.label(text=label, icon=last if last in icons_ok else "NONE")
                layout.separator(factor=1.5)
        except Exception:
            layout.label(text=hud.status_text(behavior), translate=False)

    return draw


def _set_status(context, behavior):
    """Show the move's keys in the status bar; returns the workspace used."""
    workspace = getattr(context, "workspace", None)
    if workspace is None:
        return None
    try:
        workspace.status_text_set(status_draw_fn(behavior))
    except (TypeError, AttributeError, RuntimeError):
        try:
            workspace.status_text_set(hud.status_text(behavior))
        except (TypeError, AttributeError, RuntimeError):
            return None
    return workspace


def _clear_status(workspace):
    """Give the status bar back, even if *workspace* is gone."""
    for ws in (workspace, getattr(bpy.context, "workspace", None)):
        if ws is None:
            continue
        try:
            ws.status_text_set(None)
            return
        except (ReferenceError, AttributeError, RuntimeError, TypeError):
            continue
    try:
        from bl_ui.space_statusbar import STATUSBAR_HT_header
        original = getattr(STATUSBAR_HT_header, "_draw_orig", None)
        if original is not None:
            STATUSBAR_HT_header.draw = original
    except ImportError:
        pass


# ----------------------------------------------------------------------
# Operator
# ----------------------------------------------------------------------

def _poll_fail(cls, message) -> bool:
    try:
        cls.poll_message_set(tip(message))
    except (AttributeError, RuntimeError, TypeError):
        pass
    return False


class SMARTCLIP_OT_modal_move(bpy.types.Operator):
    bl_idname = "view3d.smartclip_move"
    bl_label = "Move with Guides"
    bl_description = "Move the selection with guide lines that snap to nearby vertices"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    offset: FloatVectorProperty(
        name="Offset",
        description="Distance moved, in world space",
        subtype="TRANSLATION",
        size=3,
        options={"SKIP_SAVE"},
    )

    # Recorded when a move is confirmed, so Adjust Last Operation (which
    # undoes first) and Repeat Last do what the move did: Snap To at the
    # start decides what moves, and the A / S settings the move ended with
    # are kept.  Empty when the operator is called from a script.
    start_scope: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    final_scope: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    final_align: BoolVectorProperty(size=3, options={"HIDDEN", "SKIP_SAVE"})

    # ------------------------------------------------------------------ poll
    @classmethod
    def poll(cls, context):
        scene = context.scene
        if not getattr(scene, "smartclip_enabled", False):
            return _poll_fail(cls, "Smart Clipping is turned off for this scene")
        obj = context.active_object
        if obj is None:
            return _poll_fail(cls, "Needs an active object")
        if context.mode == "OBJECT":
            return True
        if context.mode == "EDIT_MESH" and obj.type == "MESH":
            return True
        return _poll_fail(cls, "Works in Object Mode and mesh Edit Mode")

    # ------------------------------------------------------------- execute
    def execute(self, context):
        if self.final_scope:
            try:
                _write_settings(context.scene, (self.final_scope, *self.final_align))
            except (TypeError, ValueError, AttributeError):
                pass
        _pivot, movers = gather_movers(context, scope=self.start_scope or None)
        if not movers:
            self.report({"WARNING"}, rpt("Nothing selected to move"))
            return {"CANCELLED"}
        delta = Vector(self.offset)
        for mover in movers:
            mover.apply(delta)
        return {"FINISHED"}

    # -------------------------------------------------------------- invoke
    def invoke(self, context, event):
        self._init_state()

        scene = context.scene
        self._active_obj = context.active_object
        self._is_edit = context.mode == "EDIT_MESH"

        prefs = get_addon_prefs(context)
        if prefs:
            self.color_guide = tuple(prefs.color_guide)
            self.color_snap = tuple(prefs.color_snap)
            self.threshold_px = prefs.snap_distance_px
            self._behavior = prefs.snap_behavior
        self._ctrl_held = bool(event.ctrl)

        # Resolve the 3-D view region we'll use for projections
        self._region, self._rv3d = _resolve_region(context)
        if not self._region or not self._rv3d:
            self.report({"WARNING"}, rpt("Move with Guides needs a 3D Viewport"))
            return {"CANCELLED"}
        self.region_pointer = self._region.as_pointer()
        # The view matrices are refreshed when the region redraws; make sure
        # they match the current view (e.g. after a script changed it).
        self._rv3d.update()

        self._start_world, self._movers = gather_movers(context)
        self._pivot_objects = pivot_objects(context, self._movers)
        if not self._movers:
            self.report({"WARNING"}, rpt("Select at least one vertex") if self._is_edit
                        else rpt("Nothing selected to move"))
            return {"CANCELLED"}

        # Mouse start
        self._start_mouse = _event_to_region(event, self._region)
        self._last_mouse = self._start_mouse.copy()
        self._solved_mouse = self._start_mouse.copy()

        # Depth reference for mouse unprojection
        self._start_mouse_world = screen_to_world(
            self._region, self._rv3d, self._start_mouse, self._start_world,
        )
        self._view_matrix = self._rv3d.perspective_matrix.copy()

        # Collect the snap points (heavy work happens here, once per Snap To).
        # Moving geometry is excluded so it can never snap to itself.
        self._settings_at_start = _read_settings(scene)
        self.align_axes = _align_axes(scene)
        self._rebuild(context)
        self._update_labels(context)

        self._add_draw_handlers()
        context.window_manager.modal_handler_add(self)
        _running_moves.append(self._movers)
        _running_settings[id(self._movers)] = (scene, self._settings_at_start)
        self._workspace = _set_status(context, self._behavior)
        return {"RUNNING_MODAL"}

    # --------------------------------------------------------------- modal
    def modal(self, context, event):
        try:
            return self._handle_event(context, event)
        except Exception:
            # Never leave a half-moved selection or orphaned draw handlers.
            traceback.print_exc()
            self.report({"ERROR"}, rpt("Move with Guides stopped because of an internal error "
                                       "(see the system console)"))
            self._safe_restore()
            self._restore_settings(context)
            self._finish(context)
            return {"CANCELLED"}

    def cancel(self, context):
        self._safe_restore()
        self._restore_settings(context)
        self._finish(context)

    def _handle_event(self, context, event):
        # Cancel with Esc or RMB, as in Blender's own transform
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._restore()
            self._restore_settings(context)
            self._finish(context)
            return {"CANCELLED"}

        # Confirm
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            moved = (self.applied_world is not None
                     and (self.applied_world - self._start_world).length > 0.0)
            if moved:
                self.offset = self.applied_world - self._start_world
                scene = context.scene
                self.start_scope = self._settings_at_start[0]
                self.final_scope = scene.smartclip_target_scope
                self.final_align = tuple(getattr(scene, f"smartclip_align_{a}")
                                         for a in ("x", "y", "z"))
            self._finish(context)
            # Nothing moved: no undo step and no redo panel entry
            return {"FINISHED"} if moved else {"CANCELLED"}

        # Pass through viewport navigation (orbit / pan / zoom / numpad views)
        if passes_to_navigation(context, event):
            return {"PASS_THROUGH"}

        # Holding Ctrl switches snapping (see snap_rule)
        if event.type in _CTRL_KEYS:
            held = event.value != "RELEASE"
            if held != self._ctrl_held:
                self._ctrl_held = held
                self._do_snap(context)
            return {"RUNNING_MODAL"}

        # Mouse movement -> recalculate snap
        if event.type == "MOUSEMOVE":
            self._last_mouse = _event_to_region(event, self._region)
            self._ctrl_held = bool(event.ctrl)
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        pressed = event.value == "PRESS" and not getattr(event, "is_repeat", False)

        # Axis / plane constraint toggle (like G then X / Shift+X)
        if pressed and event.type in _AXIS_KEYS:
            self._toggle_constraint(event.type, plane=event.shift)
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        # A: Align Only, S: Snap To
        if pressed and event.type in {"A", "S"} and not (event.shift or event.alt
                                                         or event.oskey):
            if event.type == "A":
                self._cycle_align(context)
            else:
                self._cycle_scope(context)
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        # All remaining events (incl. navigation keys bound to something
        # else) are consumed so Blender defaults (Ctrl+Z, Ctrl+S, Select
        # More ...) cannot fire mid-move.
        return {"RUNNING_MODAL"}

    # ------------------------------------------------- internal helpers
    def _init_state(self):
        self._active_obj = None
        self._is_edit = False
        self._build = None
        self._region = None
        self._rv3d = None
        self._movers = []
        self._pivot_objects = []
        self._workspace = None

        self._start_mouse = Vector((0.0, 0.0))
        self._last_mouse = Vector((0.0, 0.0))
        self._solved_mouse = Vector((0.0, 0.0))  # mouse used by the last solve
        self._start_world = Vector((0.0, 0.0, 0.0))
        self._start_mouse_world = Vector((0.0, 0.0, 0.0))
        self._raw_movement = Vector((0.0, 0.0, 0.0))  # before constraints
        self._view_matrix = None

        # Axis / plane movement constraint (like G then X/Y/Z / Shift+X/Y/Z)
        # None = free, "X"/"Y"/"Z" = single axis, "YZ"/"XZ"/"XY" = plane
        self.constraint_mode = None

        self._behavior = DEFAULT_SNAP_BEHAVIOR
        self._ctrl_held = False
        self._settings_at_start = None
        self._empty_reason = None

        # Exposed to drawing callbacks
        self.region_pointer = 0
        self.threshold_px = DEFAULT_SNAP_DISTANCE_PX
        self.free_world = None
        self.applied_world = None   # where the move puts the pivot (constraint applied)
        self.pivot_world = None     # where the pivot is (Location Lock, object constraints)
        self.current_candidate = None
        self.snap_state = STATE_NONE
        self.snapping_on = True
        self.align_axes = frozenset()
        self.align_blocked = False
        self.limit_exceeded = False
        self.candidate_runs = []
        self.moved_label = ""
        self.mode_runs = []
        self.draw_enabled = False
        self.color_guide = (1.0, 0.0, 1.0, 1.0)
        self.color_snap = (0.0, 1.0, 1.0, 1.0)

        self._handle_3d = None
        self._handle_2d = None

    def _rebuild(self, context):
        """Collect the snap points for the current Snap To."""
        scene = context.scene
        if self._is_edit:
            self._build = detector.build_spatial_tree(
                context, active_obj=self._active_obj,
                moving_verts={m.obj: set(m.init_cos) for m in self._movers},
                view=(self._region, self._rv3d),
            )
        else:
            self._build = detector.build_spatial_tree(
                context, active_obj=self._active_obj,
                exclude_objects=[m.obj for m in self._movers],
                view=(self._region, self._rv3d),
            )
        summary = build_summary(self._build)
        _last_builds[scene.as_pointer()] = summary
        self.limit_exceeded = summary.limit_exceeded
        if summary.points:
            self._empty_reason = None
        else:
            self._empty_reason = hud.empty_reason(
                scene.smartclip_target_scope, self._is_edit,
                scene.smartclip_target_collection is not None)

    def _restore_settings(self, context):
        if self._settings_at_start is None:
            return
        try:
            _write_settings(context.scene, self._settings_at_start)
        except (ReferenceError, AttributeError, TypeError):
            pass

    # ------------------------------------------------ constraint toggle
    def _toggle_constraint(self, axis_key: str, plane: bool):
        """Toggle axis or plane constraint, Blender-style.

        X         -> constrain to X axis  (press again -> off)
        Shift+X   -> constrain to YZ plane (press again -> off)
        """
        if plane:
            # Shift+X -> YZ plane, Shift+Y -> XZ plane, Shift+Z -> XY plane
            plane_map = {"X": "YZ", "Y": "XZ", "Z": "XY"}
            target = plane_map[axis_key]
        else:
            target = axis_key  # "X", "Y", or "Z"

        # Toggle: same constraint again -> free
        if self.constraint_mode == target:
            self.constraint_mode = None
        else:
            self.constraint_mode = target

    def _constrain_to_start(self, world_co: Vector) -> Vector:
        """Project *world_co* onto the active constraint through the start point."""
        return self._start_world + apply_constraint(world_co - self._start_world,
                                                    self.constraint_mode)

    # ------------------------------------------- settings switched mid-move
    def _cycle_align(self, context):
        scene = context.scene
        axes = next_align_axes(_align_axes(scene))
        for axis in ("X", "Y", "Z"):
            prop = f"smartclip_align_{axis.lower()}"
            if getattr(scene, prop) != (axis in axes):
                setattr(scene, prop, axis in axes)
        _tag_redraw_view3d(context)

    def _cycle_scope(self, context):
        scene = context.scene
        has_other_selected = self._is_edit
        if not self._is_edit:
            # Children of a moving object move with it and are no targets
            moving = {m.obj.as_pointer() for m in self._movers}
            has_other_selected = any(
                obj.type == "MESH" and obj.as_pointer() not in moving
                and not _has_moving_ancestor(obj, moving)
                for obj in context.selected_objects)
        scope = next_scope(scene.smartclip_target_scope, self._is_edit,
                           scene.smartclip_target_collection is not None, has_other_selected)
        if scope != scene.smartclip_target_scope:
            scene.smartclip_target_scope = scope
            self._rebuild(context)
        _tag_redraw_view3d(context)

    # ----------------------------------------------------- view changes
    def _sync_view(self):
        """Re-anchor mouse tracking after the user navigated the viewport.

        Movement is measured on a view-aligned plane, so after orbit / pan /
        zoom the old anchor no longer matches and the selection would jump.
        Rebase the anchor so the free position stays continuous.
        """
        current = self._rv3d.perspective_matrix
        if self._view_matrix is not None and current == self._view_matrix:
            return
        self._view_matrix = current.copy()
        mouse_world = screen_to_world(
            self._region, self._rv3d, self._solved_mouse, self._start_world,
        )
        self._start_mouse_world = mouse_world - self._raw_movement

    def _query_radius(self) -> float:
        px = pixel_world_size(self._region, self._rv3d, self.free_world)
        if not px:
            return max(getattr(self._rv3d, "view_distance", 10.0), 1e-3)
        extent = max(self._region.width, self._region.height)
        return max(px * extent * QUERY_RADIUS_VIEWPORT_FRACTION, 1e-6)

    # --------------------------------------------------------- snap core
    def _do_snap(self, context):
        threshold_px = self.threshold_px

        self._sync_view()
        mouse_world = screen_to_world(
            self._region, self._rv3d, self._last_mouse, self._start_world,
        )
        self._solved_mouse = self._last_mouse.copy()
        self._raw_movement = mouse_world - self._start_mouse_world
        movement = apply_constraint(self._raw_movement, self.constraint_mode)
        self.free_world = self._start_world + movement

        # Use the projected vertex/object position for screen-space filtering,
        # NOT the raw mouse cursor (which may be offset from the actual geometry).
        free_screen = world_to_screen(self._region, self._rv3d, self.free_world)
        if free_screen is None:
            free_screen = self._last_mouse  # fallback if behind camera

        # Align Only works on the axes the constraint lets the point move
        # along; on none of them (X on with a Y constraint) it pauses rather
        # than snapping to vertices instead.
        scene = context.scene
        search, exact = snap_rule(self._behavior, self._ctrl_held)
        self.align_axes = _align_axes(scene)
        usable_axes = self.align_axes & constraint_axes(self.constraint_mode)
        self.align_blocked = bool(self.align_axes) and not usable_axes
        has_points = self._build is not None and self._build.point_count > 0
        self.snapping_on = search and not self.align_blocked and has_points

        candidates = []
        if self.snapping_on:
            if usable_axes:
                candidates = detector.find_axis_candidates(
                    self._build,
                    current_co=self.free_world,
                    region=self._region,
                    rv3d=self._rv3d,
                    mouse_xy=free_screen,
                    snap_distance_px=threshold_px,
                    axis_flags=usable_axes,
                )
            else:
                candidates = detector.find_candidates(
                    self._build,
                    current_co=self.free_world,
                    region=self._region,
                    rv3d=self._rv3d,
                    mouse_xy=free_screen,
                    snap_distance_px=threshold_px,
                    query_radius=self._query_radius(),
                )

        cand = candidates[0] if candidates else None
        self.current_candidate = cand
        if cand is not None:
            if exact:
                target = cand.location.copy()
            else:
                strength = SOFT_PULL_ALIGN if cand.type.startswith("ALIGN_") else SOFT_PULL_POINT
                target = self.free_world.lerp(
                    cand.location, pull_ratio(cand.screen_dist, threshold_px, strength))
            # Snapping must not break an active axis / plane constraint.
            self.applied_world = self._constrain_to_start(target)
        else:
            self.applied_world = self.free_world.copy()

        delta = self.applied_world - self._start_world
        for mover in self._movers:
            mover.apply(delta)
        self.pivot_world = self._pivot_now(context)

        if cand is None:
            self.snap_state = STATE_NONE if search else STATE_FREE
        elif not exact:
            self.snap_state = STATE_PULLING
        elif reached(self.pivot_world, cand.location,
                     pixel_world_size(self._region, self._rv3d, cand.location)):
            self.snap_state = STATE_SNAPPED
        else:
            self.snap_state = STATE_PROJECTED
        self._update_labels(context)

        if context.area:
            context.area.tag_redraw()

    def _pivot_now(self, context) -> Vector:
        """Where the pivot is after the movers moved.

        In Object Mode Location Lock, object constraints and drivers can keep
        an object from where the move puts it, so the evaluated origins are
        read (the viewport would evaluate them for the next redraw anyway).
        Edit Mode vertices are where they were written.
        """
        if not self._pivot_objects:
            return self.applied_world.copy()
        context.view_layer.update()
        try:
            total = Vector((0.0, 0.0, 0.0))
            for obj in self._pivot_objects:
                total += obj.matrix_world.translation
            return total / len(self._pivot_objects)
        except ReferenceError:
            return self.applied_world.copy()

    def _restore(self):
        for mover in self._movers:
            mover.restore()

    def _safe_restore(self):
        for mover in self._movers:
            try:
                mover.restore()
            except Exception:
                traceback.print_exc()

    def _update_labels(self, context):
        scene = context.scene
        cand = self.current_candidate
        pivot = self.pivot_world if self.pivot_world is not None else self.applied_world
        if cand is not None:
            distance = None
            if self.snap_state in (STATE_PULLING, STATE_PROJECTED) and pivot is not None:
                distance = hud.format_length((cand.location - pivot).length, scene)
            self.candidate_runs = hud.candidate_runs(cand, self.snap_state, distance)
        else:
            self.candidate_runs = []
        if pivot is not None:
            moved = (pivot - self._start_world).length
            self.moved_label = hud.moved_text(hud.format_length(moved, scene),
                                              self.constraint_mode)
        else:
            self.moved_label = ""
        self.mode_runs = hud.mode_lines(scene.smartclip_target_scope, self.align_axes,
                                        self.align_blocked, self.constraint_mode,
                                        self._empty_reason, self.limit_exceeded)

    # ----------------------------------------------- draw handler mgmt
    def _add_draw_handlers(self):
        if self._handle_3d is None:
            self._handle_3d = _add_handler(drawing.draw_3d, self, "POST_VIEW")
        if self._handle_2d is None:
            self._handle_2d = _add_handler(drawing.draw_2d, self, "POST_PIXEL")
        self.draw_enabled = True

    def _remove_draw_handlers(self):
        self.draw_enabled = False
        if self._handle_3d is not None:
            _remove_handler(self._handle_3d)
            self._handle_3d = None
        if self._handle_2d is not None:
            _remove_handler(self._handle_2d)
            self._handle_2d = None

    def _finish(self, context):
        self._remove_draw_handlers()
        _clear_status(self._workspace)
        self._workspace = None
        if any(m is self._movers for m in _running_moves):
            _running_moves[:] = [m for m in _running_moves if m is not self._movers]
        _running_settings.pop(id(self._movers), None)
        _tag_redraw_view3d(context)
        if context.area:
            context.area.tag_redraw()


# ------------------------------------------------------------------
# Helpers (module-level)
# ------------------------------------------------------------------

def _resolve_region(context):
    """Return (region, rv3d) for the active 3-D viewport."""
    if context.region and context.region.type == "WINDOW" and context.region_data:
        return context.region, context.region_data

    area = context.area
    if area and area.type == "VIEW_3D":
        for r in area.regions:
            if r.type == "WINDOW":
                sd = context.space_data
                if sd and sd.type == "VIEW_3D":
                    return r, sd.region_3d
    return None, None


def _event_to_region(event, region) -> Vector:
    """Convert an absolute mouse event to region-local coordinates."""
    if region:
        return Vector((float(event.mouse_x - region.x),
                        float(event.mouse_y - region.y)))
    return Vector((float(event.mouse_region_x),
                    float(event.mouse_region_y)))
