import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty
from bpy.types import AddonPreferences

from . import keymap
from .i18n import iface
from .utils import (
    DEFAULT_SEARCH_BACKEND,
    DEFAULT_SNAP_BEHAVIOR,
    DEFAULT_SNAP_DISTANCE_PX,
    DEFAULT_VERTEX_BUDGET,
    SEARCH_GRID,
    SEARCH_KDTREE,
    SNAP_EXACT,
    SNAP_PULL,
)

_SEARCH_BACKEND_ITEMS = [
    (SEARCH_GRID, "Screen-space Grid",
     "Sort the snap points into a grid on screen, redone when the view changes (default)"),
    (SEARCH_KDTREE, "3D KD-tree (Experimental)",
     "Narrow the snap points down in 3D with a KD-tree built when the move starts, "
     "then check their distance on screen. Usually slower than the grid, and much slower "
     "when many snap points crowd around the moving point"),
]

_SNAP_BEHAVIOR_ITEMS = [
    (SNAP_EXACT, "Snap Exactly", "Jump onto the snap point. Hold Ctrl to move freely"),
    (SNAP_PULL, "Gradual Pull",
     "Pull towards the snap point, more strongly the closer it is. Hold Ctrl to snap exactly"),
]

ADDON_MODULE_NAME = __package__


def get_addon_prefs(context) -> "SMARTCLIP_AddonPreferences | None":
    addon = context.preferences.addons.get(ADDON_MODULE_NAME)
    if addon:
        return addon.preferences
    return None


def _on_hotkeys_enabled(self, _context):
    keymap.apply_active(self.hotkeys_enabled)


def _section(layout, idname, title):
    """A collapsible section (Blender 4.1+), or a titled box on Blender 4.0.

    Returns the layout to draw into, or None while the section is closed.
    """
    if hasattr(layout, "panel"):
        header, body = layout.panel(idname)
        header.label(text=title)
        return body
    box = layout.box()
    box.label(text=title)
    return box


class SMARTCLIP_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_MODULE_NAME

    snap_behavior: EnumProperty(
        name="Snap Behavior",
        description="What happens when a snap point comes within the snap distance",
        items=_SNAP_BEHAVIOR_ITEMS,
        default=DEFAULT_SNAP_BEHAVIOR,
    )

    snap_distance_px: IntProperty(
        name="Snap Distance",
        description="How close on screen the moving point must come to a snap point",
        default=DEFAULT_SNAP_DISTANCE_PX,
        min=1,
        max=1000,
        subtype="PIXEL",
    )

    max_vertex_budget: IntProperty(
        name="Snap Point Limit",
        description=(
            "Most snap points collected when a move starts, nearest objects first. Past the "
            "limit, objects get only their bounding box corners and origin, and the farthest "
            "are left out"
        ),
        default=DEFAULT_VERTEX_BUDGET,
        min=100,
        max=10_000_000,
    )

    search_backend: EnumProperty(
        name="Snap Search",
        description=(
            "How snap candidates are looked up during a move. Both methods find the same "
            "candidates; only the speed differs"
        ),
        items=_SEARCH_BACKEND_ITEMS,
        default=DEFAULT_SEARCH_BACKEND,
    )

    hotkeys_enabled: BoolProperty(
        name="Use Shortcut",
        description=(
            "Start Move with Guides with the shortcut below. When off, the key does what "
            "Blender assigns to it"
        ),
        default=True,
        update=_on_hotkeys_enabled,
    )

    color_guide: FloatVectorProperty(
        name="Guide Color",
        description="Color of the guide line and target marker before snapping",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.0, 1.0, 1.0),
    )

    color_snap: FloatVectorProperty(
        name="Snap Color",
        description="Color of the guide line and target marker while snapped",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 1.0, 1.0, 1.0),
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Snap To and Align Only are set per scene in the 3D Viewport: "
                          "Sidebar (N) > Tool > Smart Clipping", icon="INFO")
        layout.use_property_split = True
        layout.use_property_decorate = False

        body = _section(layout, "smartclip_prefs_snapping", "Snapping")
        if body:
            body.prop(self, "snap_behavior", expand=True)
            body.prop(self, "snap_distance_px")
            body.prop(self, "max_vertex_budget")

        body = _section(layout, "smartclip_prefs_display", "Display")
        if body:
            body.prop(self, "color_guide")
            body.prop(self, "color_snap")

        body = _section(layout, "smartclip_prefs_shortcut", "Shortcut")
        if body:
            body.prop(self, "hotkeys_enabled")
            # The keys are shown only while the shortcut is on: Blender records
            # a key change against the item's on/off state, so a change made
            # while it is off would not apply once it is on again.
            if self.hotkeys_enabled:
                col = body.column()
                for label, km, kmi in keymap.user_items():
                    col.prop(kmi, "type", text=label, full_event=True)
                    # Shift+G by default: say what it takes over, and how to keep it
                    taken = keymap.overridden_name(km, kmi)
                    if taken:
                        # Under the key field, past the label column
                        note = col.split(factor=0.4)
                        note.label(text="")
                        note.label(text=iface("Used instead of {name}").format(name=taken),
                                   icon="INFO", translate=False)
            row = body.row()
            row.operator("smartclip.add_default_hotkeys", icon="LOOP_BACK")

        body = _section(layout, "smartclip_prefs_advanced", "Advanced")
        if body:
            body.prop(self, "search_backend")
