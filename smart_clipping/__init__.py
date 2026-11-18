bl_info = {
    "name": "Smart Clipping",
    "author": "marc2825",
    "version": (1, 2, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Tool > Smart Clipping",
    "description": "Move with smart guides: KD-Tree snapping, axis align and constraints",
    "doc_url": "https://github.com/marc2825/Blender_SmartClip",
    "tracker_url": "https://github.com/marc2825/Blender_SmartClip/issues",
    "category": "3D View",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .ops import SMARTCLIP_OT_modal_move, remove_all_draw_handlers
from .prefs import SMARTCLIP_AddonPreferences, get_addon_prefs
from .utils import DEFAULT_VERTEX_BUDGET

_SCOPE_ITEMS = [
    ("SELF", "Self Only", "Snap only inside the active mesh"),
    ("SELECTED", "Selected", "Snap to other selected mesh objects"),
    ("VISIBLE", "All Visible", "Snap to all visible meshes (budget-controlled)"),
    ("COLLECTION", "Manual Collection", "Snap only to a specific collection (incl. child collections)"),
]


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
        col.prop(scene, "smartclip_target_scope", text="")
        if scene.smartclip_target_scope == "COLLECTION":
            col.separator()
            col.prop(scene, "smartclip_target_collection", text="Collection")

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
        budget = prefs.max_vertex_budget if prefs else DEFAULT_VERTEX_BUDGET
        box.label(text=f"Max Vertices: {budget}")
        info = getattr(scene, "smartclip_runtime_info", "")
        if info:
            box.label(text=info)

        layout.separator()
        layout.operator(SMARTCLIP_OT_modal_move.bl_idname, icon="SNAP_ON")


# ======================================================================
# Keymap management
# ======================================================================
# The addon's Shift+G items are added at the head of their keymaps, so they
# take precedence over the built-in Shift+G (Select Grouped / Select Similar).
# Whether they are active is the user's choice (Add Default / Clear Hotkeys,
# stored in the add-on preferences) and does not follow the per-scene
# "Enable Smart Clipping" setting: the keymap is shared by all scenes, so the
# operator's poll() checks the scene instead.  When it fails, the key press
# falls through to Blender's own Shift+G.

_addon_keymaps: list = []    # [(km, kmi), ...]
_hotkeys_fallback = {"enabled": True}  # used when preferences are unavailable


def _hotkeys_wanted() -> bool:
    prefs = get_addon_prefs(bpy.context)
    if prefs is not None:
        return bool(prefs.hotkeys_enabled)
    return _hotkeys_fallback["enabled"]


def _set_hotkeys_wanted(enabled: bool):
    _hotkeys_fallback["enabled"] = enabled
    prefs = get_addon_prefs(bpy.context)
    if prefs is not None:
        prefs.hotkeys_enabled = enabled
    for _km, kmi in _addon_keymaps:
        try:
            kmi.active = enabled
        except (ReferenceError, RuntimeError):
            pass


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
        kmi.active = _hotkeys_wanted()
        _addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


# ======================================================================
# Scene property migration (<= 1.1 -> 1.2)
# ======================================================================
# Up to 1.1 the addon registered `target_scope` / `target_collection` without a prefix.
# Their saved values stay in the file as orphan ID properties: in the
# custom-property storage up to Blender 4.x, in the system-property
# storage (bl_system_properties_get) from Blender 5.0.

_LEGACY_SCENE_PROPS = {
    "target_scope": "smartclip_target_scope",
    "target_collection": "smartclip_target_collection",
}


def _legacy_value(scene, name):
    getter = getattr(scene, "bl_system_properties_get", None)
    if getter is not None:
        group = getter()
        if group is not None and name in group:
            return group[name]
    if name in scene.keys():
        return scene[name]
    return None


def migrate_legacy_scene_properties():
    """Copy pre-1.2 scene settings into the prefixed properties (once)."""
    identifiers = [item[0] for item in _SCOPE_ITEMS]
    for scene in bpy.data.scenes:
        for old, new in _LEGACY_SCENE_PROPS.items():
            if scene.is_property_set(new):
                continue
            value = _legacy_value(scene, old)
            if value is None:
                continue
            try:
                if new == "smartclip_target_scope":
                    if isinstance(value, int) and 0 <= value < len(identifiers):
                        setattr(scene, new, identifiers[value])
                elif isinstance(value, bpy.types.Collection):
                    setattr(scene, new, value)
            except (TypeError, ValueError, AttributeError):
                pass


@persistent
def _on_load_post(_dummy):
    migrate_legacy_scene_properties()


def _deferred_init():
    # bpy.data is not accessible while add-ons register at startup.
    migrate_legacy_scene_properties()
    return None


# ======================================================================
# Hotkey helper operators (shown in addon preferences)
# ======================================================================

class SMARTCLIP_OT_add_default_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.add_default_hotkeys"
    bl_label = "Add Default Hotkeys"
    bl_description = "Set Shift+G for Object Mode and Mesh Edit Mode"

    def execute(self, _context):
        if not _addon_keymaps:
            _register_keymaps()
        for _km, kmi in _addon_keymaps:
            kmi.type = "G"
            kmi.value = "PRESS"
            kmi.shift = True
            kmi.ctrl = False
            kmi.alt = False
        _set_hotkeys_wanted(True)
        return {"FINISHED"}


class SMARTCLIP_OT_clear_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.clear_hotkeys"
    bl_label = "Clear Hotkeys"
    bl_description = "Deactivate the Smart Clipping hotkeys until Add Default Hotkeys is used"

    def execute(self, _context):
        _set_hotkeys_wanted(False)
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

_SCENE_PROPS = (
    "smartclip_enabled",
    "smartclip_target_scope",
    "smartclip_target_collection",
    "smartclip_runtime_info",
    "smartclip_align_x",
    "smartclip_align_y",
    "smartclip_align_z",
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.smartclip_enabled = BoolProperty(
        name="Enable Smart Clipping",
        description="Use Smart Clipping in this scene; when off, Shift+G does Blender's default",
        default=True,
    )
    bpy.types.Scene.smartclip_target_scope = EnumProperty(
        name="Target Scope",
        items=_SCOPE_ITEMS,
        default="VISIBLE",
    )
    bpy.types.Scene.smartclip_target_collection = PointerProperty(
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
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    bpy.app.timers.register(_deferred_init, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(_deferred_init):
        bpy.app.timers.unregister(_deferred_init)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    remove_all_draw_handlers()
    _unregister_keymaps()

    for p in reversed(_SCENE_PROPS):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
