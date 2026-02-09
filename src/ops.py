import bmesh
import bpy
from mathutils import Vector

from . import detector, drawing, utils
from .prefs import get_addon_prefs


class SMARTCLIPPING_OT_modal_move(bpy.types.Operator):
    bl_idname = "view3d.src_move"
    bl_label = "Smart Clipping Move"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    @classmethod
    def poll(cls, context):
        return (
            context.area
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def __init__(self):
        self.active_obj = None
        self.is_edit_mode = False

        self.build_result = None
        self.current_candidate = None
        self.draw_enabled = False

        self.start_mouse = Vector((0.0, 0.0))
        self.last_mouse = Vector((0.0, 0.0))
        self.start_world = Vector((0.0, 0.0, 0.0))
        self.start_mouse_world = Vector((0.0, 0.0, 0.0))
        self.view_region = None
        self.view_rv3d = None

        self.initial_obj_location = None
        self.initial_vert_positions = {}

        self.free_world = None
        self.applied_world = None
        self.hard_snap = False
        self.hud_text = ""

        self.color_guide = (1.0, 0.0, 1.0, 1.0)
        self.color_snap = (0.0, 1.0, 1.0, 1.0)

        self._draw_handle_3d = None
        self._draw_handle_2d = None

    def invoke(self, context, event):
        scene = context.scene
        if not scene.src_enabled:
            self.report({"WARNING"}, "Enable Smart Clipping in panel first")
            return {"CANCELLED"}

        self.active_obj = context.active_object
        if not self.active_obj:
            self.report({"WARNING"}, "No active object")
            return {"CANCELLED"}

        self.is_edit_mode = context.mode == "EDIT_MESH" and self.active_obj.type == "MESH"
        if context.mode not in {"OBJECT", "EDIT_MESH"}:
            self.report({"WARNING"}, "Smart Clipping supports Object/Edit Mesh mode")
            return {"CANCELLED"}

        prefs = get_addon_prefs(context)
        if prefs:
            self.color_guide = tuple(prefs.color_guide)
            self.color_snap = tuple(prefs.color_snap)

        self.view_region, self.view_rv3d = self._resolve_view_context(context)
        if not self.view_region or not self.view_rv3d:
            self.report({"WARNING"}, "Unable to resolve 3D view region")
            return {"CANCELLED"}

        self.start_mouse = self._event_to_view_coords(event)
        self.last_mouse = self.start_mouse.copy()

        if self.is_edit_mode:
            if not self._setup_edit_mode_snapshot():
                self.report({"WARNING"}, "Select at least one vertex in Edit Mode")
                return {"CANCELLED"}
        else:
            self.initial_obj_location = self.active_obj.location.copy()
            self.start_world = self.initial_obj_location.copy()

        self.start_mouse_world = utils.mouse_to_world(
            self.view_region,
            self.view_rv3d,
            self.start_mouse,
            self.start_world,
        )

        self.build_result = detector.build_spatial_tree(context, active_obj=self.active_obj)
        if self.build_result.limit_exceeded:
            scene.src_runtime_info = "Limit exceeded: Switched to Box Mode"
        else:
            scene.src_runtime_info = f"Vertices in tree: {self.build_result.source_vertex_count}"

        self._add_draw_handlers()
        context.window_manager.modal_handler_add(self)

        print(
            "[src] Invoke:",
            f"points={self.build_result.point_count}",
            f"limit_exceeded={self.build_result.limit_exceeded}",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._restore_initial_state()
            self._finish(context)
            return {"CANCELLED"}

        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self._finish(context)
            return {"FINISHED"}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self.last_mouse = self._event_to_view_coords(event)
            self._update_snap(context, ctrl_pressed=event.ctrl)
            return {"RUNNING_MODAL"}

        if event.type in {"LEFT_CTRL", "RIGHT_CTRL"}:
            self._update_snap(context, ctrl_pressed=event.ctrl)
            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def _setup_edit_mode_snapshot(self):
        bm = bmesh.from_edit_mesh(self.active_obj.data)
        bm.verts.ensure_lookup_table()
        selected = [v for v in bm.verts if v.select]
        if not selected:
            return False

        center_local = sum((v.co for v in selected), Vector()) / float(len(selected))
        self.start_world = self.active_obj.matrix_world @ center_local
        self.initial_vert_positions = {v.index: v.co.copy() for v in selected}
        return True

    def _update_snap(self, context, ctrl_pressed):
        prefs = get_addon_prefs(context)
        snap_threshold = prefs.snap_distance_px if prefs else 15
        query_radius = max(0.1, snap_threshold * 0.025)

        mouse_world = utils.mouse_to_world(
            self.view_region,
            self.view_rv3d,
            self.last_mouse,
            self.start_world,
        )
        movement = mouse_world - self.start_mouse_world
        self.free_world = self.start_world + movement

        candidates = detector.find_candidates(
            self.build_result,
            current_co=self.free_world,
            region=self.view_region,
            rv3d=self.view_rv3d,
            mouse_xy=self.last_mouse,
            snap_distance_px=snap_threshold,
            epsilon=0.01,
            query_radius=query_radius,
        )

        self.current_candidate = candidates[0] if candidates else None
        self.hard_snap = bool(ctrl_pressed and self.current_candidate)

        if self.current_candidate:
            if self.hard_snap:
                self.applied_world = self.current_candidate.location.copy()
            else:
                ratio = 1.0 - (self.current_candidate.screen_dist / max(1.0, snap_threshold))
                soft_factor = utils.clamp01(ratio) * 0.35
                self.applied_world = self.free_world.lerp(self.current_candidate.location, soft_factor)
        else:
            self.applied_world = self.free_world.copy()

        self._apply_world_transform(self.applied_world)
        self._update_hud()
        context.area.tag_redraw()

        if self.current_candidate:
            print(
                "[src] Hit",
                f"obj={self.current_candidate.target_name}",
                f"type={self.current_candidate.type}",
                f"screen={self.current_candidate.screen_dist:.2f}px",
            )

    def _apply_world_transform(self, world_co):
        if self.is_edit_mode:
            world_delta = world_co - self.start_world
            local_delta = utils.world_delta_to_local(self.active_obj, world_delta)

            bm = bmesh.from_edit_mesh(self.active_obj.data)
            bm.verts.ensure_lookup_table()
            for idx, initial_co in self.initial_vert_positions.items():
                bm.verts[idx].co = initial_co + local_delta
            bmesh.update_edit_mesh(self.active_obj.data, loop_triangles=False, destructive=False)
        else:
            self.active_obj.location = world_co

    def _restore_initial_state(self):
        if self.is_edit_mode:
            bm = bmesh.from_edit_mesh(self.active_obj.data)
            bm.verts.ensure_lookup_table()
            for idx, initial_co in self.initial_vert_positions.items():
                bm.verts[idx].co = initial_co
            bmesh.update_edit_mesh(self.active_obj.data, loop_triangles=False, destructive=False)
        else:
            if self.initial_obj_location is not None:
                self.active_obj.location = self.initial_obj_location

    def _update_hud(self):
        if not self.current_candidate:
            self.hud_text = "Target: None"
            return

        source_type = "Vertex"
        if self.current_candidate.type == "BOUNDS":
            source_type = "Bounds"

        world_dist = (self.current_candidate.location - self.applied_world).length
        self.hud_text = (
            f"Target: {self.current_candidate.target_name} ({source_type}) | Dist: {world_dist:.3f}m"
        )

    def _add_draw_handlers(self):
        if self._draw_handle_3d is None:
            self._draw_handle_3d = bpy.types.SpaceView3D.draw_handler_add(
                drawing.draw_3d,
                (self, None),
                "WINDOW",
                "POST_VIEW",
            )
        if self._draw_handle_2d is None:
            self._draw_handle_2d = bpy.types.SpaceView3D.draw_handler_add(
                drawing.draw_2d,
                (self, None),
                "WINDOW",
                "POST_PIXEL",
            )
        self.draw_enabled = True

    def _remove_draw_handlers(self):
        self.draw_enabled = False
        if self._draw_handle_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle_3d, "WINDOW")
            self._draw_handle_3d = None
        if self._draw_handle_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle_2d, "WINDOW")
            self._draw_handle_2d = None

    def _finish(self, context):
        self._remove_draw_handlers()
        if context.area:
            context.area.tag_redraw()

    def _resolve_view_context(self, context):
        if context.region and context.region.type == "WINDOW" and context.region_data:
            return context.region, context.region_data

        if context.area and context.area.type == "VIEW_3D":
            window_region = None
            for region in context.area.regions:
                if region.type == "WINDOW":
                    window_region = region
                    break
            if window_region and context.space_data and context.space_data.type == "VIEW_3D":
                return window_region, context.space_data.region_3d
        return None, None

    def _event_to_view_coords(self, event):
        if not self.view_region:
            return Vector((event.mouse_region_x, event.mouse_region_y))
        return Vector(
            (
                float(event.mouse_x - self.view_region.x),
                float(event.mouse_y - self.view_region.y),
            )
        )
