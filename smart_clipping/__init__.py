# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Snaxis",
    "author": "marc2825",
    "version": (2, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Tool > Snaxis",
    "description": "Move with guide lines that snap to nearby vertices, line up coordinates "
                   "and follow axis constraints (formerly Smart Clipping)",
    "doc_url": "https://github.com/marc2825/Snaxis",
    "tracker_url": "https://github.com/marc2825/Snaxis/issues",
    "category": "3D View",
}

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty

from . import hud, i18n, keymap, ops
from .keymap import _addon_keymaps  # noqa: F401  (tests inspect the registered items)
from .ops import SMARTCLIP_OT_modal_move, remove_all_draw_handlers
from .prefs import SMARTCLIP_AddonPreferences, get_addon_prefs
from .utils import SCOPE_ITEMS


# ======================================================================
# Sidebar panel
# ======================================================================

class _SidebarPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"


class SMARTCLIP_PT_panel(_SidebarPanel, bpy.types.Panel):
    bl_label = "Snaxis"
    bl_idname = "SMARTCLIP_PT_panel"

    def draw_header(self, context):
        self.layout.prop(context.scene, "smartclip_enabled", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.active = scene.smartclip_enabled

        row = layout.row()
        row.scale_y = 1.4
        row.operator(SMARTCLIP_OT_modal_move.bl_idname, icon="SNAP_ON")

        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column()
        col.prop(scene, "smartclip_target_scope")
        if scene.smartclip_target_scope == "COLLECTION":
            col.prop(scene, "smartclip_target_collection")
        row = col.row(align=True, heading="Align Only")
        row.prop(scene, "smartclip_align_x", toggle=True)
        row.prop(scene, "smartclip_align_y", toggle=True)
        row.prop(scene, "smartclip_align_z", toggle=True)
        prefs = get_addon_prefs(context)
        if prefs is not None:
            col.prop(prefs, "snap_distance_px")

        info = ops.last_build(scene)
        if info is not None and info.limit_exceeded:
            col = layout.column(align=True)
            col.use_property_split = False
            col.label(text="Snap point limit reached", icon="ERROR")
            col.label(text=hud.limit_detail(info.simplified, info.skipped), icon="BLANK1",
                      translate=False)


class SMARTCLIP_PT_limits(_SidebarPanel, bpy.types.Panel):
    bl_label = "Limits and Display"
    bl_idname = "SMARTCLIP_PT_limits"
    bl_parent_id = "SMARTCLIP_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        # Labels above the fields: a sub-panel's label column is too narrow
        # for these names, in Japanese especially.
        layout = self.layout
        layout.active = context.scene.smartclip_enabled
        prefs = get_addon_prefs(context)
        if prefs is None:
            layout.label(text="Add-on preferences are unavailable", icon="INFO")
            return
        col = layout.column()
        col.label(text="Snap Behavior")
        col.row().prop(prefs, "snap_behavior", expand=True)
        col.separator()
        col.prop(prefs, "max_vertex_budget")
        col.separator()
        row = col.row()
        for prop in ("color_guide", "color_snap"):
            sub = row.column(align=True)
            sub.label(text=prefs.bl_rna.properties[prop].name)
            sub.prop(prefs, prop, text="")


def _menu_entry(self, _context):
    self.layout.separator()
    self.layout.operator(SMARTCLIP_OT_modal_move.bl_idname, icon="SNAP_ON")


_MENUS = ("VIEW3D_MT_transform_object", "VIEW3D_MT_transform")


# ======================================================================
# Registration
# ======================================================================

_classes = (
    SMARTCLIP_AddonPreferences,
    SMARTCLIP_OT_modal_move,
    SMARTCLIP_PT_panel,
    SMARTCLIP_PT_limits,
)

_SCENE_PROPS = (
    "smartclip_enabled",
    "smartclip_target_scope",
    "smartclip_target_collection",
    "smartclip_align_x",
    "smartclip_align_y",
    "smartclip_align_z",
)


def _align_description(axis):
    return (f"Line up the {axis} coordinate with nearby vertices instead of snapping onto "
            f"them. Press A while moving to switch")


def register():
    i18n.register()
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.smartclip_enabled = BoolProperty(
        name="Enable Snaxis",
        description="Use Snaxis in this scene. When off, Move with Guides does not start here",
        default=True,
    )
    bpy.types.Scene.smartclip_target_scope = EnumProperty(
        name="Snap To",
        description="Which meshes the move snaps to. Press S while moving to switch",
        items=SCOPE_ITEMS,
        default="VISIBLE",
    )
    bpy.types.Scene.smartclip_target_collection = PointerProperty(
        name="Collection",
        description="Collection to snap to, including its child collections",
        type=bpy.types.Collection,
    )
    bpy.types.Scene.smartclip_align_x = BoolProperty(
        name="X", description=_align_description("X"), default=False)
    bpy.types.Scene.smartclip_align_y = BoolProperty(
        name="Y", description=_align_description("Y"), default=False)
    bpy.types.Scene.smartclip_align_z = BoolProperty(
        name="Z", description=_align_description("Z"), default=False)

    for name in _MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_menu_entry)

    keymap.register_keymaps()


def unregister():
    remove_all_draw_handlers()
    keymap.unregister_keymaps()

    for name in _MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            try:
                menu.remove(_menu_entry)
            except (ValueError, RuntimeError):
                pass

    for p in reversed(_SCENE_PROPS):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    i18n.unregister()
