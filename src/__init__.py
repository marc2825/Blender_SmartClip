bl_info = {
    "name": "Smart Clipping",
    "author": "marc2825",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Tool > Smart Clipping",
    "description": "Static KD-Tree based move snapping with vertex budget control",
    "category": "3D View",
}

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .ops import SMARTCLIPPING_OT_modal_move
from .prefs import SMARTCLIPPING_AddonPreferences, get_addon_prefs


class SMARTCLIPPING_PT_panel(bpy.types.Panel):
    bl_label = "Smart Clipping"
    bl_idname = "SMARTCLIPPING_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "src_enabled", text="Enable Smart Clipping")
        layout.separator()

        col = layout.column(align=True)
        col.label(text="Target Scope:")
        col.prop(scene, "target_scope", text="")
        if scene.target_scope == "COLLECTION":
            col.separator()
            col.prop(scene, "target_collection", text="Collection")

        layout.separator()
        box = layout.box()
        box.label(text="Performance:")
        prefs = get_addon_prefs(context)
        max_verts = prefs.max_vertex_budget if prefs else 50000
        box.label(text=f"Max Vertices: {max_verts}")
        if scene.src_runtime_info:
            box.label(text=scene.src_runtime_info)

        layout.separator()
        layout.operator(SMARTCLIPPING_OT_modal_move.bl_idname, icon="SNAP_ON")


classes = (
    SMARTCLIPPING_AddonPreferences,
    SMARTCLIPPING_OT_modal_move,
    SMARTCLIPPING_PT_panel,
)

addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km.keymap_items.new(
        SMARTCLIPPING_OT_modal_move.bl_idname,
        type="G",
        value="PRESS",
        shift=True,
        alt=True,
    )
    addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.src_enabled = BoolProperty(
        name="Enable Smart Clipping",
        default=True,
    )
    bpy.types.Scene.target_scope = EnumProperty(
        name="Target Scope",
        items=[
            ("SELF", "Self Only", "Snap only inside active mesh"),
            ("SELECTED", "Selected", "Use other selected mesh objects"),
            ("VISIBLE", "All Visible", "Use all visible mesh objects with budget control"),
            ("COLLECTION", "Manual Collection", "Use only the selected collection"),
        ],
        default="VISIBLE",
    )
    bpy.types.Scene.target_collection = PointerProperty(type=bpy.types.Collection)
    bpy.types.Scene.src_runtime_info = StringProperty(
        name="Smart Clipping Runtime Info",
        default="",
    )

    register_keymaps()


def unregister():
    unregister_keymaps()

    del bpy.types.Scene.src_runtime_info
    del bpy.types.Scene.target_collection
    del bpy.types.Scene.target_scope
    del bpy.types.Scene.src_enabled

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
