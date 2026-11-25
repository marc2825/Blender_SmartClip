# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Snaxis",
    "author": "marc2825",
    "version": (2, 2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Tool > Snaxis",
    "description": "Move with guide lines that snap to nearby vertices, line up coordinates "
                   "and follow axis constraints (formerly Smart Clipping)",
    "doc_url": "https://github.com/marc2825/Snaxis",
    "tracker_url": "https://github.com/marc2825/Snaxis/issues",
    "category": "3D View",
}

import sys as _sys

# Legacy add-on only (a top-level module; an extension is a sub-package of its
# repository).  After Install from Disk over an older version, switching the
# add-on off and on again re-runs only this file.  The submodules of the old
# version are still loaded, both in sys.modules and as attributes of this
# package (which `from . import x` would reuse), so drop them and import the
# new files.  Blender's extension manager unloads an extension's submodules
# itself when it updates one, so an extension leaves sys.modules alone.
if "." not in __name__:
    for _name in [n for n in _sys.modules if n.startswith(__name__ + ".")]:
        del _sys.modules[_name]
        globals().pop(_name[len(__name__) + 1:], None)

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, PointerProperty

from . import hud, i18n, keymap, ops
from .keymap import _addon_keymaps  # noqa: F401  (tests inspect the registered items)
from .ops import SMARTCLIP_OT_modal_move, remove_all_draw_handlers
from .prefs import SMARTCLIP_AddonPreferences, get_addon_prefs
from .utils import SCOPE_ITEMS

# Kept for scripts that read it; the items live in utils.
_SCOPE_ITEMS = SCOPE_ITEMS


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
    identifiers = [item[0] for item in SCOPE_ITEMS]
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
# Shortcut operators (add-on preferences, scripts)
# ======================================================================

class SMARTCLIP_OT_add_default_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.add_default_hotkeys"
    bl_label = "Reset Shortcut"
    bl_description = ("Set the shortcut back to Shift+G in Object Mode and mesh Edit Mode "
                      "and turn it on")

    def execute(self, _context):
        keymap.reset_to_default()
        return {"FINISHED"}


class SMARTCLIP_OT_clear_hotkeys(bpy.types.Operator):
    bl_idname = "smartclip.clear_hotkeys"
    bl_label = "Turn Off Shortcut"
    bl_description = "Turn off the shortcut so the key does what Blender assigns to it"

    def execute(self, _context):
        keymap.set_hotkeys_wanted(False)
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


# ======================================================================
# Another copy (the legacy add-on and the extension side by side)
# ======================================================================
# Both register the same operators, panels, Scene properties and Shift+G
# items.  The copy enabled second stops before registering anything, and as
# it then never counts as enabled, Blender does not call its unregister().

_registered = False


class AlreadyEnabledError(RuntimeError):
    pass


def other_copy() -> "str | None":
    """Module name of another copy of this add-on that is registered, if any."""
    panel = getattr(bpy.types, SMARTCLIP_PT_panel.bl_idname, None)
    owner = getattr(panel, "__module__", None)
    if owner is None or owner == __name__:
        return None
    return owner


def register():
    global _registered
    owner = other_copy()
    if owner is not None:
        raise AlreadyEnabledError(
            f"Snaxis is already enabled as \"{owner}\". Only one copy can be on: "
            f"turn that one off in Preferences > Add-ons (or Get Extensions) first, "
            f"then enable this one")

    i18n.register()
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.smartclip_enabled = BoolProperty(
        name="Enable Snaxis",
        description=("Use Snaxis in this scene. When off, its shortcut (Shift+G "
                     "unless changed) does what Blender assigns to the key"),
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
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    bpy.app.timers.register(_deferred_init, first_interval=0.0)
    _registered = True


def unregister():
    global _registered
    if not _registered:
        # register() stopped for another copy: what is registered is that
        # copy's, so leave it alone.
        return
    _registered = False
    if bpy.app.timers.is_registered(_deferred_init):
        bpy.app.timers.unregister(_deferred_init)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
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
