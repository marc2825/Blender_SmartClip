bl_info = {
    "name": "Smart Clipping",
    "author": "marc2825",
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Tool > Smart Clipping",
    "description": "Static KD-Tree based move snapping with vertex budget control",
    "category": "3D View",
}

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .ops import SMARTCLIP_OT_modal_move
from .prefs import SMARTCLIP_AddonPreferences, get_addon_prefs


# ======================================================================
# UI Panel
# ======================================================================

class SMARTCLIP_PT_panel(bpy.types.Panel):
    bl_label = "Smart Clipping"
    bl_idname = "SMARTCLIP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "smartclip_enabled", text="Enable Smart Clipping")
        layout.separator()

        col = layout.column(align=True)
        col.label(text="Target Scope:")
        col.prop(scene, "target_scope", text="")
        if scene.target_scope == "COLLECTION":
            col.separator()
            col.prop(scene, "target_collection", text="Collection")

        layout.separator()
        box = layout.box()
        box.label(text="Axis Align:")
        row = box.row(align=True)
        row.prop(scene, "smartclip_align_x", toggle=True)
        row.prop(scene, "smartclip_align_y", toggle=True)
        row.prop(scene, "smartclip_align_z", toggle=True)

        layout.separator()
        box = layout.box()
        box.label(text="Performance:")
        prefs = get_addon_prefs(context)
        budget = prefs.max_vertex_budget if prefs else 50000
        box.label(text=f"Max Vertices: {budget}")
        info = getattr(scene, "smartclip_runtime_info", "")
        if info:
            box.label(text=info)

        layout.separator()
        layout.operator(SMARTCLIP_OT_modal_move.bl_idname, icon="SNAP_ON")


# ======================================================================
# Keymap management
# ======================================================================

_addon_keymaps: list = []    # [(km, kmi), ...]
_overridden_kmis: list = []  # built-in Shift+G items we temporarily disabled


def _register_keymaps():
    """Create keymap entries for Object and Edit modes."""
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    kc = wm.keyconfigs.addon
    if not kc:
        return
    if _addon_keymaps:
        return  # already registered

    for km_name in ("Object Mode", "Mesh"):
        km = kc.keymaps.new(name=km_name, space_type="EMPTY", region_type="WINDOW")
        kmi = km.keymap_items.new(
            SMARTCLIP_OT_modal_move.bl_idname,
            type="G",
            value="PRESS",
            shift=True,
            head=True,
        )
        _addon_keymaps.append((km, kmi))

    _sync_keymap_state()


def _unregister_keymaps():
    _restore_builtin_shift_g()
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


# ------------------------------------------------------------------
# Built-in Shift+G override
# ------------------------------------------------------------------

def _override_builtin_shift_g():
    """Disable built-in Shift+G items so the addon takes priority."""
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return

    our_idname = SMARTCLIP_OT_modal_move.bl_idname
    seen = set()

    for kc in (wm.keyconfigs.active, wm.keyconfigs.default):
        if not kc:
            continue
        for km_name in ("Object Mode", "Mesh"):
            km = kc.keymaps.get(km_name)
            if not km:
                continue
            for kmi in km.keymap_items:
                if id(kmi) in seen:
                    continue
                seen.add(id(kmi))
                if (kmi.type == "G"
                        and kmi.value == "PRESS"
                        and kmi.shift
                        and not kmi.ctrl
                        and not kmi.alt
                        and kmi.idname != our_idname
                        and kmi.active):
                    _overridden_kmis.append(kmi)
                    kmi.active = False


def _restore_builtin_shift_g():
    """Re-enable built-in Shift+G items we previously disabled."""
    for kmi in _overridden_kmis:
        try:
            kmi.active = True
        except (ReferenceError, RuntimeError):
            pass
    _overridden_kmis.clear()


def _sync_keymap_state():
    """Enable/disable addon keymaps and manage built-in conflicts."""
    scene = getattr(bpy.context, "scene", None)
    enabled = getattr(scene, "smartclip_enabled", True) if scene else True

    for _km, kmi in _addon_keymaps:
        kmi.active = enabled

    # When ON:  disable conflicting built-in Shift+G
    # When OFF: restore built-in Shift+G
    _restore_builtin_shift_g()
    if enabled:
        _override_builtin_shift_g()


def _on_enabled_update(self, _context):
    """Called when smartclip_enabled changes."""
    _sync_keymap_state()


# ======================================================================
# Hotkey helper operators (shown in addon preferences)
# ======================================================================

class SMARTCLIP_OT_add_default_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.add_default_hotkeys"
    bl_label = "Add Default Hotkeys"
    bl_description = "Set Shift+G for Object Mode and Mesh Edit Mode"

    def execute(self, _context):
        for _km, kmi in _addon_keymaps:
            kmi.type = "G"
            kmi.value = "PRESS"
            kmi.shift = True
            kmi.ctrl = False
            kmi.alt = False
            kmi.active = True
        _sync_keymap_state()
        return {"FINISHED"}


class SMARTCLIP_OT_clear_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.clear_hotkeys"
    bl_label = "Clear Hotkeys"
    bl_description = "Deactivate Smart Clipping hotkeys"

    def execute(self, _context):
        for _km, kmi in _addon_keymaps:
            kmi.active = False
        _restore_builtin_shift_g()
        return {"FINISHED"}


# ======================================================================
# Registration
# ======================================================================

_classes = (
    SMARTCLIP_AddonPreferences,
    SMARTCLIP_OT_add_default_hotkeys,
    SMARTCLIP_OT_clear_hotkeys,
    SMARTCLIP_OT_modal_move,
    SMARTCLIP_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.smartclip_enabled = BoolProperty(
        name="Enable Smart Clipping",
        default=True,
        update=_on_enabled_update,
    )
    bpy.types.Scene.target_scope = EnumProperty(
        name="Target Scope",
        items=[
            ("SELF", "Self Only", "Snap only inside the active mesh"),
            ("SELECTED", "Selected", "Snap to other selected mesh objects"),
            ("VISIBLE", "All Visible", "Snap to all visible meshes (budget-controlled)"),
            ("COLLECTION", "Manual Collection", "Snap only to a specific collection"),
        ],
        default="VISIBLE",
    )
    bpy.types.Scene.target_collection = PointerProperty(
        name="Target Collection",
        type=bpy.types.Collection,
    )
    bpy.types.Scene.smartclip_runtime_info = StringProperty(
        name="Runtime Info",
        default="",
    )
    bpy.types.Scene.smartclip_align_x = BoolProperty(
        name="X",
        description="Axis-clipping: align to reference vertices' X coordinate",
        default=False,
    )
    bpy.types.Scene.smartclip_align_y = BoolProperty(
        name="Y",
        description="Axis-clipping: align to reference vertices' Y coordinate",
        default=False,
    )
    bpy.types.Scene.smartclip_align_z = BoolProperty(
        name="Z",
        description="Axis-clipping: align to reference vertices' Z coordinate",
        default=False,
    )

    _register_keymaps()


def unregister():
    _unregister_keymaps()

    props = (
        "smartclip_align_z", "smartclip_align_y", "smartclip_align_x",
        "smartclip_runtime_info", "target_collection", "target_scope", "smartclip_enabled",
    )
    for p in props:
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
