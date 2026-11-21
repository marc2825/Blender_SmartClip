import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty
from bpy.types import AddonPreferences

from .utils import (
    DEFAULT_SEARCH_BACKEND,
    DEFAULT_SNAP_DISTANCE_PX,
    DEFAULT_VERTEX_BUDGET,
    SEARCH_GRID,
    SEARCH_KDTREE,
)

_SEARCH_BACKEND_ITEMS = [
    (SEARCH_GRID, "Screen-space Grid",
     "Sort the snap points into a grid on screen, redone when the view changes (default)"),
    (SEARCH_KDTREE, "3D KD-tree (Experimental)",
     "Narrow the snap points down in 3D with a KD-tree built when the move starts, "
     "then check their distance on screen. Usually slower than the grid, and much slower "
     "when many snap points crowd around the moving point"),
]

ADDON_MODULE_NAME = __package__


def get_addon_prefs(context) -> "SMARTCLIP_AddonPreferences | None":
    addon = context.preferences.addons.get(ADDON_MODULE_NAME)
    if addon:
        return addon.preferences
    return None


class SMARTCLIP_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_MODULE_NAME

    snap_distance_px: IntProperty(
        name="Snap Threshold (px)",
        description="Screen-space distance in pixels for snap detection",
        default=DEFAULT_SNAP_DISTANCE_PX,
        min=1,
        max=1000,
    )

    max_vertex_budget: IntProperty(
        name="Max Vertex Budget",
        description=(
            "Maximum number of snap points (nearest objects first). The object crossing "
            "the limit is down-sampled; objects beyond it use bounding-box corners"
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
        name="Hotkeys Enabled",
        description="Whether the Shift+G assignment is active (set by Add Default / Clear Hotkeys)",
        default=True,
    )

    color_guide: FloatVectorProperty(
        name="Guide Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.0, 1.0, 1.0),
    )

    color_snap: FloatVectorProperty(
        name="Hard Snap Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 1.0, 1.0, 1.0),
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "snap_distance_px")
        col.prop(self, "max_vertex_budget")
        col.separator()
        col.prop(self, "color_guide")
        col.prop(self, "color_snap")

        layout.separator()
        box = layout.box()
        box.label(text="Advanced Settings")
        box.prop(self, "search_backend")

        layout.separator()
        box = layout.box()
        box.label(text="Hotkeys")
        row = box.row(align=True)
        row.operator("smartclip.add_default_hotkeys", icon="ADD")
        row.operator("smartclip.clear_hotkeys", icon="TRASH")
        state = "active" if self.hotkeys_enabled else "cleared"
        box.label(text=f"Shift+G (Object Mode / Mesh Edit Mode): {state}")

        layout.separator()
        box = layout.box()
        box.label(text="Modal Controls")
        col = box.column(align=True)
        col.label(text="Left Click / Enter: Confirm")
        col.label(text="ESC: Cancel")
        col.label(text="Right Click (hold): Hard Snap")
        col.label(text="X / Y / Z: Axis Constraint")
        col.label(text="Shift+X / Y / Z: Plane Constraint")
