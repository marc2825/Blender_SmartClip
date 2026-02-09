import bpy
from bpy.props import FloatVectorProperty, IntProperty
from bpy.types import AddonPreferences


def addon_name() -> str:
    return __package__.split(".")[0]


def get_addon_prefs(context):
    addon = context.preferences.addons.get(addon_name())
    if addon:
        return addon.preferences
    return None


class SMARTCLIPPING_AddonPreferences(AddonPreferences):
    bl_idname = addon_name()

    snap_distance_px: IntProperty(
        name="Snap Threshold (px)",
        default=15,
        min=1,
        max=1000,
    )
    max_vertex_budget: IntProperty(
        name="Max Vertex Budget",
        description="Switches overflowing objects to bounds snap mode",
        default=50000,
        min=100,
        max=10_000_000,
    )
    color_guide: FloatVectorProperty(
        name="Guide Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.0, 1.0, 1.0),  # Magenta
    )
    color_snap: FloatVectorProperty(
        name="Hard Snap Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 1.0, 1.0, 1.0),  # Cyan
    )

    def draw(self, _context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "snap_distance_px")
        col.prop(self, "max_vertex_budget")
        col.separator()
        col.prop(self, "color_guide")
        col.prop(self, "color_snap")
