"""Modal operator that drives the Smart Clipping move workflow.

Lifecycle
---------
invoke  -- gather what moves, build KD-Tree, register draw handlers.
modal   -- process mouse / keyboard, query tree, apply snap, redraw.
finish  -- remove draw handlers, store the final offset for redo.
cancel  -- called by Blender when the modal is aborted externally
           (file load, window close): restore and clean up.
execute -- apply ``offset`` directly (redo panel / scripting).
"""

import traceback

import bmesh
import bpy
from bpy.props import FloatVectorProperty
from mathutils import Vector

from . import detector, drawing
from .prefs import get_addon_prefs
from .utils import (
    DEFAULT_SNAP_DISTANCE_PX,
    apply_constraint,
    clamp01,
    constraint_axes,
    pixel_world_size,
    screen_to_world,
    world_to_location_matrix,
    world_to_screen,
)

# The KD-Tree search radius covers half the viewport at the depth of the
# moving point, so it follows the view scale.  The screen-pixel filter
# (snap_distance_px) is the real gatekeeper; the radius only pre-filters.
QUERY_RADIUS_VIEWPORT_FRACTION = 0.5

# Soft-snap pull strength at zero screen distance.
SOFT_PULL_POINT = 0.35
SOFT_PULL_ALIGN = 0.5

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
# Movers of moves in progress.  Unregistering the operator class drops its
# running modal handler without calling cancel(), so unregister() restores
# these itself.
_running_moves: list = []


def remove_all_draw_handlers():
    """Undo moves in progress and remove every draw handler (used on unregister)."""
    for movers in list(_running_moves):
        for mover in movers:
            try:
                mover.restore()
            except Exception:
                traceback.print_exc()
    _running_moves.clear()
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


def gather_movers(context):
    """Return ``(pivot_world, movers)`` for the current selection.

    Object Mode: every selected editable object (falling back to the active
    one); children of a moving parent are left to the parent.  With Target
    Scope set to Selected only the active object moves, because the other
    selected objects are what it snaps to.  The pivot is the active object's
    origin when it moves, otherwise the median origin.

    Edit Mode: the selected vertices of every mesh in Edit Mode; the pivot
    is their median point.  ``movers`` is empty when nothing would move.
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
    snaps_to_selection = getattr(context.scene, "smartclip_target_scope", None) == "SELECTED"
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


class SMARTCLIP_OT_modal_move(bpy.types.Operator):
    bl_idname = "view3d.smartclip_move"
    bl_label = "Smart Clipping Move"
    bl_description = "Move with smart-clipping guides and snapping"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    offset: FloatVectorProperty(
        name="Offset",
        description="World-space translation applied to the selection",
        subtype="TRANSLATION",
        size=3,
        options={"SKIP_SAVE"},
    )

    # ------------------------------------------------------------------ poll
    @classmethod
    def poll(cls, context):
        scene = context.scene
        if not getattr(scene, "smartclip_enabled", False):
            return False
        obj = context.active_object
        if obj is None:
            return False
        if context.mode == "OBJECT":
            return True
        if context.mode == "EDIT_MESH" and obj.type == "MESH":
            return True
        return False

    # ------------------------------------------------------------- execute
    def execute(self, context):
        _pivot, movers = gather_movers(context)
        if not movers:
            self.report({"WARNING"}, "Nothing selected to move")
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

        # Colours from preferences
        prefs = get_addon_prefs(context)
        if prefs:
            self.color_guide = tuple(prefs.color_guide)
            self.color_snap = tuple(prefs.color_snap)

        # Resolve the 3-D view region we'll use for projections
        self._region, self._rv3d = _resolve_region(context)
        if not self._region or not self._rv3d:
            self.report({"WARNING"}, "Smart Clipping Move needs a 3D Viewport")
            return {"CANCELLED"}
        # The view matrices are refreshed when the region redraws; make sure
        # they match the current view (e.g. after a script changed it).
        self._rv3d.update()

        self._start_world, self._movers = gather_movers(context)
        if not self._movers:
            self.report({"WARNING"}, "Select at least one vertex" if self._is_edit
                        else "Nothing selected to move")
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

        # Build spatial index (heavy work happens here, once).  Moving
        # geometry is excluded so it can never snap to itself.
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
        scene.smartclip_runtime_info = _runtime_info(self._build)

        # Register GPU draw handlers
        self._add_draw_handlers()

        context.window_manager.modal_handler_add(self)
        _running_moves.append(self._movers)
        return {"RUNNING_MODAL"}

    # --------------------------------------------------------------- modal
    def modal(self, context, event):
        try:
            return self._handle_event(context, event)
        except Exception:
            # Never leave a half-moved selection or orphaned draw handlers.
            traceback.print_exc()
            self.report({"ERROR"}, "Smart Clipping aborted by an internal error (see console)")
            self._safe_restore()
            self._finish(context)
            return {"CANCELLED"}

    def cancel(self, context):
        self._safe_restore()
        self._finish(context)

    def _handle_event(self, context, event):
        # Cancel (ESC only — right-click is used for hard snap)
        if event.type == "ESC" and event.value == "PRESS":
            self._restore()
            self._finish(context)
            return {"CANCELLED"}

        # Confirm
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            moved = (self.applied_world is not None
                     and (self.applied_world - self._start_world).length > 0.0)
            if moved:
                self.offset = self.applied_world - self._start_world
            self._finish(context)
            # Nothing moved: no undo step and no redo panel entry
            return {"FINISHED"} if moved else {"CANCELLED"}

        # Pass through viewport navigation (orbit / pan / zoom / numpad views)
        if passes_to_navigation(context, event):
            return {"PASS_THROUGH"}

        # Right-click hold = hard snap
        if event.type == "RIGHTMOUSE":
            self._rmb_held = event.value == "PRESS"
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        # Mouse movement -> recalculate snap
        if event.type == "MOUSEMOVE":
            self._last_mouse = _event_to_region(event, self._region)
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        # Axis / plane constraint toggle (like G then X / Shift+X)
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self._toggle_constraint(event.type, plane=event.shift)
            self._do_snap(context)
            return {"RUNNING_MODAL"}

        # All remaining events (incl. Ctrl / Shift / Alt and navigation keys
        # bound to something else) are consumed so Blender defaults (Ctrl+Z,
        # Ctrl+S, Select More …) cannot fire mid-move.
        return {"RUNNING_MODAL"}

    # ------------------------------------------------- internal helpers
    def _init_state(self):
        self._active_obj = None
        self._is_edit = False
        self._build = None
        self._region = None
        self._rv3d = None
        self._movers = []

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

        # Right-mouse-button held → hard snap
        self._rmb_held = False

        # Exposed to drawing callbacks
        self.free_world = None
        self.applied_world = None
        self.current_candidate = None
        self.hard_snap = False
        self.hud_text = ""
        self.draw_enabled = False
        self.color_guide = (1.0, 0.0, 1.0, 1.0)
        self.color_snap = (0.0, 1.0, 1.0, 1.0)

        self._handle_3d = None
        self._handle_2d = None

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
        prefs = get_addon_prefs(context)
        threshold_px = prefs.snap_distance_px if prefs else DEFAULT_SNAP_DISTANCE_PX

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

        # Axis-clipping mode: only axes the constraint lets us move along
        scene = context.scene
        axis_flags = {
            axis for axis in ("X", "Y", "Z")
            if getattr(scene, f"smartclip_align_{axis.lower()}", False)
        } & constraint_axes(self.constraint_mode)

        if axis_flags:
            candidates = detector.find_axis_candidates(
                self._build,
                current_co=self.free_world,
                region=self._region,
                rv3d=self._rv3d,
                mouse_xy=free_screen,
                snap_distance_px=threshold_px,
                axis_flags=axis_flags,
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

        self.current_candidate = candidates[0] if candidates else None
        self.hard_snap = bool(self._rmb_held and self.current_candidate)

        if self.current_candidate:
            cand = self.current_candidate
            if self.hard_snap:
                target = cand.location.copy()
            else:
                pull = SOFT_PULL_ALIGN if cand.type.startswith("ALIGN_") else SOFT_PULL_POINT
                ratio = 1.0 - (cand.screen_dist / max(1.0, threshold_px))
                target = self.free_world.lerp(cand.location, clamp01(ratio) * pull)
            # Snapping must not break an active axis / plane constraint.
            self.applied_world = self._constrain_to_start(target)
        else:
            self.applied_world = self.free_world.copy()

        delta = self.applied_world - self._start_world
        for mover in self._movers:
            mover.apply(delta)
        self._update_hud()

        if context.area:
            context.area.tag_redraw()

    def _restore(self):
        for mover in self._movers:
            mover.restore()

    def _safe_restore(self):
        for mover in self._movers:
            try:
                mover.restore()
            except Exception:
                traceback.print_exc()

    def _update_hud(self):
        parts = []

        # Constraint indicator
        cm = self.constraint_mode
        if cm:
            if len(cm) == 1:
                parts.append(f"Axis: {cm}")
            else:
                parts.append(f"Plane: {cm}")

        cand = self.current_candidate
        if not cand:
            parts.append("Target: None")
            self.hud_text = " | ".join(parts)
            return

        if cand.type.startswith("ALIGN_"):
            axis_label = cand.type[-1]  # 'X', 'Y', 'Z'
            axis_idx = {"X": 0, "Y": 1, "Z": 2}[axis_label]
            val = cand.location[axis_idx]
            dist = (cand.location - self.applied_world).length
            parts.append(
                f"Align {axis_label}: {val:.3f} "
                f"({cand.target_name}) | Dist: {dist:.3f}m"
            )
        else:
            kind = "Bounds" if cand.type == "BOUNDS" else "Vertex"
            dist = (cand.location - self.applied_world).length
            parts.append(f"Target: {cand.target_name} ({kind}) | Dist: {dist:.3f}m")

        self.hud_text = " | ".join(parts)

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
        if any(m is self._movers for m in _running_moves):
            _running_moves[:] = [m for m in _running_moves if m is not self._movers]
        if context.area:
            context.area.tag_redraw()


# ------------------------------------------------------------------
# Helpers (module-level)
# ------------------------------------------------------------------

def _runtime_info(build) -> str:
    if build is None:
        return ""
    if not build.limit_exceeded:
        return f"Vertices in tree: {build.source_vertex_count}"
    info = (
        f"Budget exceeded: {build.point_count} points "
        f"(sampled: {len(build.partial_objects)}, box only: {len(build.bounds_objects)}"
    )
    if build.skipped_objects:
        info += f", skipped: {len(build.skipped_objects)}"
    return info + ")"


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
