"""
Record the frames of the README demo (assets/teaser.gif) from the current UI.

Builds a small scene, drives two moves with simulated input (Shift+G, mouse
moves, A, clicks): snapping to a corner of one box and then another, and
Align Only X while sliding past, and saves a screenshot of the 3D View for
each frame.
Needs a display; real mouse and keyboard input is ignored while it runs.

  blender --factory-startup --enable-event-simulate --python-exit-code 1 \\
    --python tests/record_teaser.py -- FRAMES_DIR [--language ja_JP]

Then make the GIF (15 fps, 960 px wide, one palette for the whole clip):

  ffmpeg -framerate 15 -i FRAMES_DIR/frame_%04d.png -vf \\
    "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" \\
    -loop 0 assets/teaser.gif
"""

import math
import os
import sys
import traceback

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Euler, Vector

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import smart_clipping  # noqa: E402

FRAME_SECONDS = 0.12          # time given to Blender to redraw before a screenshot
UI_SCALE = 1.4                # larger labels, so they stay readable in the GIF


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("usage: ... --python tests/record_teaser.py -- FRAMES_DIR "
                         "[--language ja_JP]")
    out = os.path.abspath(argv[0])
    language = argv[argv.index("--language") + 1] if "--language" in argv else ""
    return out, language


def _box(name, size, location, color):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mat = bpy.data.materials.new(f"{name}_Material")
    mat.diffuse_color = color
    obj.data.materials.append(mat)
    return obj


def _scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    # Two boxes to line up with, and the one that moves (active)
    shelf = _box("Shelf", (1.2, 0.8, 2.4), (2.6, 1.4, 1.2), (0.55, 0.62, 0.72, 1.0))
    table = _box("Table", (2.4, 1.4, 0.8), (-1.6, 1.8, 0.4), (0.72, 0.6, 0.5, 1.0))
    crate = _box("Crate", (0.8, 0.8, 0.8), (0.4, -1.8, 0.4), (0.85, 0.55, 0.3, 1.0))
    bpy.ops.object.select_all(action="DESELECT")
    crate.select_set(True)
    bpy.context.view_layer.objects.active = crate
    bpy.context.view_layer.update()
    return shelf, table, crate


def _view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                return window, area, region, area.spaces.active.region_3d
    raise RuntimeError("no 3D View in the startup screen")


def _frames(out):
    win, area, region, rv3d = _view3d()
    space = area.spaces.active
    space.shading.type = "SOLID"
    space.shading.color_type = "MATERIAL"
    space.overlay.show_relationship_lines = False
    space.overlay.show_cursor = False
    space.show_region_ui = False          # the sidebar would cover the view
    bpy.context.preferences.view.ui_scale = UI_SCALE
    shelf, table, crate = _scene()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.smartclip_target_scope = "VISIBLE"
    for axis in "xyz":
        setattr(scene, f"smartclip_align_{axis}", False)

    rv3d.view_perspective = "PERSP"
    rv3d.view_location = (0.5, 0.3, 0.7)
    rv3d.view_distance = 9.0
    rv3d.view_rotation = Euler((math.radians(62), 0.0, math.radians(30))).to_quaternion()
    rv3d.update()
    yield 0.6

    count = [0]

    def shot():
        path = os.path.join(out, f"frame_{count[0]:04d}.png")
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screenshot_area(filepath=path)
        count[0] += 1

    cx = region.x + region.width // 2
    cy = region.y + region.height // 2
    mouse = [0.0, 0.0]          # offset of the simulated cursor from the view centre

    def ev(event_type, value, **mods):
        win.event_simulate(event_type, value, x=cx + round(mouse[0]), y=cy + round(mouse[1]),
                           **mods)

    def px(co):
        return location_3d_to_region_2d(region, rv3d, co)

    def hold(frames):
        for _ in range(frames):
            yield FRAME_SECONDS
            shot()

    def glide(to, frames):
        """Move the cursor to *to* with an ease in / out, one frame per step."""
        x0, y0 = mouse
        for i in range(1, frames + 1):
            t = i / frames
            t = t * t * (3 - 2 * t)
            mouse[0] = x0 + (to[0] - x0) * t
            mouse[1] = y0 + (to[1] - y0) * t
            ev("MOUSEMOVE", "NOTHING")
            yield FRAME_SECONDS
            shot()

    def press(key, **mods):
        ev(key, "PRESS", **mods)
        ev(key, "RELEASE", **mods)

    # Let the window take the simulated cursor; the first key event is dropped
    for dx in (4, 0, 4, 0):
        mouse[0] = dx
        ev("MOUSEMOVE", "NOTHING")
        yield FRAME_SECONDS
    mouse[0] = 0
    press("ESC")
    yield FRAME_SECONDS

    move = {}

    def begin():
        """Start a move; cursor offsets below are relative to where it starts."""
        move["mouse"] = tuple(mouse)
        move["origin_px"] = px(crate.matrix_world.translation.copy())
        press("G", shift=True)

    def cursor_for(co, nudge=(0, 0)):
        """Cursor position that brings the moving point (the origin) to *co*."""
        d = px(co) - move["origin_px"]
        return (move["mouse"][0] + d.x + nudge[0], move["mouse"][1] + d.y + nudge[1])

    def corner(obj, sx, sy, sz):
        """World position of a corner of *obj*'s box (+1 / -1 per axis)."""
        dims = obj.dimensions
        return obj.matrix_world.translation + Vector(
            (0.5 * sx * dims.x, 0.5 * sy * dims.y, 0.5 * sz * dims.z))

    yield from hold(5)
    # 1. Snap to a corner of the table, then to one of the shelf
    begin()
    yield from hold(3)
    table_corner = corner(table, 1, -1, 1)
    yield from glide(cursor_for(table_corner, (-45, -35)), 14)
    yield from glide(cursor_for(table_corner, (5, -4)), 7)
    yield from hold(12)
    shelf_corner = corner(shelf, -1, -1, -1)
    yield from glide(cursor_for(shelf_corner, (-50, -15)), 14)
    yield from glide(cursor_for(shelf_corner, (4, 3)), 7)
    yield from hold(12)
    press("LEFTMOUSE")
    yield from hold(5)

    # 2. Align Only X: slide towards the camera, staying in line with the shelf
    bpy.context.view_layer.update()
    begin()
    yield from hold(2)
    press("A")
    yield from hold(3)
    here = crate.matrix_world.translation.copy()
    yield from glide(cursor_for(here + Vector((0.05, -0.45, 0.0))), 9)
    yield from glide(cursor_for(here + Vector((0.05, -0.85, 0.0))), 9)
    yield from hold(14)
    press("LEFTMOUSE")
    yield from hold(8)


def main():
    out, language = _args()
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):
        if name.startswith("frame_") and name.endswith(".png"):
            os.remove(os.path.join(out, name))
    if not hasattr(bpy.types.Scene, "smartclip_target_scope"):
        smart_clipping.register()
    if language:
        view = bpy.context.preferences.view
        view.language = language
        view.use_translate_interface = True
        view.use_translate_tooltips = True
    steps = _frames(out)

    def tick():
        try:
            return next(steps)
        except StopIteration:
            print(f"[teaser] frames written to {out}", flush=True)
            os._exit(0)
        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)

    bpy.app.timers.register(tick, first_interval=1.0)


if __name__ == "__main__":
    main()
