"""Modal operator that drives the Smart Clipping move workflow.

Lifecycle
---------
invoke  -- build KD-Tree, snapshot initial state, register draw handlers.
modal   -- process mouse / keyboard, query tree, apply snap, redraw.
finish  -- remove draw handlers, optionally restore initial state.
"""

import bmesh
import bpy
from mathutils import Vector

from . import detector, drawing
from .prefs import get_addon_prefs
from .utils import clamp01, screen_to_world, world_delta_to_local, world_to_screen


class SMARTCLIP_OT_modal_move(bpy.types.Operator):
    bl_idname = "view3d.smartclip_move"
    bl_label = "Smart Clipping Move"
    bl_description = "Move with smart-clipping guides and snapping"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    # ------------------------------------------------------------------ poll
    @classmethod
    def poll(cls, context):
        if not (context.area and context.area.type == "VIEW_3D"):
            return False
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

    # -------------------------------------------------------------- invoke
    def invoke(self, context, event):
        self._init_state()

        scene = context.scene
        if not scene.smartclip_enabled:
            return {"FINISHED"}

        self._active_obj = context.active_object
        if self._active_obj is None:
            return {"FINISHED"}

        self._is_edit = context.mode == "EDIT_MESH" and self._active_obj.type == "MESH"
        if context.mode not in {"OBJECT", "EDIT_MESH"}:
            return {"FINISHED"}

        # Colours from preferences
        prefs = get_addon_prefs(context)
        if prefs:
            self.color_guide = tuple(prefs.color_guide)
            self.color_snap = tuple(prefs.color_snap)

        # Resolve the 3-D view region we'll use for projections
        self._region, self._rv3d = _resolve_region(context)
        if not self._region or not self._rv3d:
            self.report({"WARNING"}, "Could not resolve 3D View region")
            return {"CANCELLED"}

        # Mouse start
        self._start_mouse = _event_to_region(event, self._region)
        self._last_mouse = self._start_mouse.copy()

        # Snapshot the geometry that will be moved
        if self._is_edit:
            if not self._snapshot_edit_mode():
                self.report({"WARNING"}, "Select at least one vertex")
                return {"CANCELLED"}
        else:
            self._init_obj_loc = self._active_obj.location.copy()
            self._start_world = self._init_obj_loc.copy()

        # Depth reference for mouse unprojection
        self._start_mouse_world = screen_to_world(
            self._region, self._rv3d, self._start_mouse, self._start_world,
        )

        # Build spatial index (heavy work happens here, once)
        # In Edit Mode, pass the selected vertex indices so only those are
        # excluded from snap candidates (non-selected verts remain as targets).
        moving_verts = set(self._init_vert_cos.keys()) if self._is_edit else None
        self._build = detector.build_spatial_tree(
            context, active_obj=self._active_obj,
            moving_vert_indices=moving_verts,
        )
        if self._build.limit_exceeded:
            scene.smartclip_runtime_info = "Limit exceeded: Switched to Box Mode"
        else:
            scene.smartclip_runtime_info = f"Vertices in tree: {self._build.source_vertex_count}"

        # Register GPU draw handlers
        self._add_draw_handlers()

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # --------------------------------------------------------------- modal
    def modal(self, context, event):
        # Cancel (ESC only — right-click is used for hard snap)
        if event.type == "ESC" and event.value == "PRESS":
            self._restore()
            self._finish(context)
            return {"CANCELLED"}

        # Confirm
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self._finish(context)
            return {"FINISHED"}

        # Pass through viewport navigation (orbit / pan / zoom)
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
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

        # Consume Ctrl / Shift / Alt / any other modifier to prevent Blender
        # defaults (Ctrl+Z, Ctrl+S, Shift+G …) from firing during modal.
        if event.type in {"LEFT_CTRL", "RIGHT_CTRL",
                          "LEFT_SHIFT", "RIGHT_SHIFT",
                          "LEFT_ALT", "RIGHT_ALT",
                          "OSKEY"}:
            return {"RUNNING_MODAL"}

        # All remaining events are consumed (BLOCKING modal).
        return {"RUNNING_MODAL"}

    # ------------------------------------------------- internal helpers
    def _init_state(self):
        self._active_obj = None
        self._is_edit = False
        self._build = None
        self._region = None
        self._rv3d = None

        self._start_mouse = Vector((0.0, 0.0))
        self._last_mouse = Vector((0.0, 0.0))
        self._start_world = Vector((0.0, 0.0, 0.0))
        self._start_mouse_world = Vector((0.0, 0.0, 0.0))

        self._init_obj_loc = None
        self._init_vert_cos = {}  # {vert_index: Vector}

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

    def _snapshot_edit_mode(self) -> bool:
        bm = bmesh.from_edit_mesh(self._active_obj.data)
        bm.verts.ensure_lookup_table()
        sel = [v for v in bm.verts if v.select]
        if not sel:
            return False
        center_local = sum((v.co for v in sel), Vector()) / len(sel)
        self._start_world = self._active_obj.matrix_world @ center_local
        self._init_vert_cos = {v.index: v.co.copy() for v in sel}
        return True

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

    def _apply_constraint(self, movement: Vector) -> Vector:
        """Zero-out movement components blocked by the active constraint."""
        if not self.constraint_mode:
            return movement
        m = movement.copy()
        if self.constraint_mode == "X":
            m.y = 0.0; m.z = 0.0
        elif self.constraint_mode == "Y":
            m.x = 0.0; m.z = 0.0
        elif self.constraint_mode == "Z":
            m.x = 0.0; m.y = 0.0
        elif self.constraint_mode == "XY":
            m.z = 0.0
        elif self.constraint_mode == "XZ":
            m.y = 0.0
        elif self.constraint_mode == "YZ":
            m.x = 0.0
        return m

    # --------------------------------------------------------- snap core
    def _do_snap(self, context):
        prefs = get_addon_prefs(context)
        threshold_px = prefs.snap_distance_px if prefs else 15
        # World-space search radius for the KD-Tree.  The screen-pixel filter
        # (snap_distance_px) is the real gatekeeper, so this can be generous.
        query_radius = max(5.0, threshold_px * 0.5)

        mouse_world = screen_to_world(
            self._region, self._rv3d, self._last_mouse, self._start_world,
        )
        movement = mouse_world - self._start_mouse_world
        movement = self._apply_constraint(movement)
        self.free_world = self._start_world + movement

        # Use the projected vertex/object position for screen-space filtering,
        # NOT the raw mouse cursor (which may be offset from the actual geometry).
        free_screen = world_to_screen(self._region, self._rv3d, self.free_world)
        if free_screen is None:
            free_screen = self._last_mouse  # fallback if behind camera

        # Axis-clipping mode: use axis search instead of regular search
        scene = context.scene
        axis_flags = set()
        if getattr(scene, "smartclip_align_x", False):
            axis_flags.add("X")
        if getattr(scene, "smartclip_align_y", False):
            axis_flags.add("Y")
        if getattr(scene, "smartclip_align_z", False):
            axis_flags.add("Z")

        if axis_flags:
            candidates = detector.find_axis_candidates(
                self._build,
                current_co=self.free_world,
                region=self._region,
                rv3d=self._rv3d,
                mouse_xy=free_screen,
                snap_distance_px=threshold_px,
                axis_flags=axis_flags,
                query_radius=query_radius,
            )
        else:
            candidates = detector.find_candidates(
                self._build,
                current_co=self.free_world,
                region=self._region,
                rv3d=self._rv3d,
                mouse_xy=free_screen,
                snap_distance_px=threshold_px,
                query_radius=query_radius,
            )

        self.current_candidate = candidates[0] if candidates else None
        self.hard_snap = bool(self._rmb_held and self.current_candidate)

        if self.current_candidate:
            cand = self.current_candidate
            if self.hard_snap:
                self.applied_world = cand.location.copy()
            elif cand.type.startswith("ALIGN_"):
                # Axis-clipping soft snap: use world-space axis distance
                axis_idx = {"ALIGN_X": 0, "ALIGN_Y": 1, "ALIGN_Z": 2}[cand.type]
                axis_dist = abs(self.free_world[axis_idx] - cand.location[axis_idx])
                ratio = 1.0 - min(axis_dist / max(0.01, query_radius * 10), 1.0)
                soft = clamp01(ratio) * 0.5
                self.applied_world = self.free_world.lerp(cand.location, soft)
            else:
                # Regular soft snap: use screen distance
                ratio = 1.0 - (cand.screen_dist / max(1.0, threshold_px))
                soft = clamp01(ratio) * 0.35
                self.applied_world = self.free_world.lerp(cand.location, soft)
        else:
            self.applied_world = self.free_world.copy()

        self._apply_position(self.applied_world)
        self._update_hud()

        if context.area:
            context.area.tag_redraw()

    def _apply_position(self, world_co: Vector):
        if self._is_edit:
            delta_w = world_co - self._start_world
            delta_l = world_delta_to_local(self._active_obj, delta_w)
            bm = bmesh.from_edit_mesh(self._active_obj.data)
            bm.verts.ensure_lookup_table()
            for idx, orig in self._init_vert_cos.items():
                bm.verts[idx].co = orig + delta_l
            bmesh.update_edit_mesh(self._active_obj.data, loop_triangles=False, destructive=False)
        else:
            self._active_obj.location = world_co

    def _restore(self):
        if self._is_edit:
            bm = bmesh.from_edit_mesh(self._active_obj.data)
            bm.verts.ensure_lookup_table()
            for idx, orig in self._init_vert_cos.items():
                bm.verts[idx].co = orig
            bmesh.update_edit_mesh(self._active_obj.data, loop_triangles=False, destructive=False)
        elif self._init_obj_loc is not None:
            self._active_obj.location = self._init_obj_loc

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
            self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
                drawing.draw_3d, (self, None), "WINDOW", "POST_VIEW",
            )
        if self._handle_2d is None:
            self._handle_2d = bpy.types.SpaceView3D.draw_handler_add(
                drawing.draw_2d, (self, None), "WINDOW", "POST_PIXEL",
            )
        self.draw_enabled = True

    def _remove_draw_handlers(self):
        self.draw_enabled = False
        if self._handle_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")
            self._handle_3d = None
        if self._handle_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d, "WINDOW")
            self._handle_2d = None

    def _finish(self, context):
        self._remove_draw_handlers()
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
