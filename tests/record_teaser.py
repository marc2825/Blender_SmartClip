# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Record the frames of the README demo (assets/teaser.gif) from the current UI.

The 3D View is split into a perspective view (top) and a front orthographic
view (bottom), both with the Snaxis panel in the sidebar.  In Edit
Mode one vertex of a cube is moved with simulated input: it snaps onto a
vertex of another box, then Align Only X (A) and the X constraint (X) are
turned on and it slides along X, lining its X coordinate up with the boxes
on both sides and with its own mesh, and the move is confirmed.  Each frame
saves both views.  Needs a display; real mouse and keyboard input is ignored
while it runs.

  blender --factory-startup --enable-event-simulate --python-exit-code 1 \\
    --python tests/record_teaser.py -- FRAMES_DIR [--language ja_JP]

With --scene-only instead of FRAMES_DIR it only builds the scene and the
two views and leaves Blender to you, to try the demo's move by hand (no
simulated input, nothing recorded, the preferences left as they are):

  blender --factory-startup --python tests/record_teaser.py -- --scene-only

Then make the GIF (the two views stacked, 12.5 fps, 1384 px wide):

  ffmpeg -framerate 12.5 -i FRAMES_DIR/top_%04d.png -framerate 12.5 \\
    -i FRAMES_DIR/bottom_%04d.png -filter_complex \\
    "[0][1]vstack,scale=1384:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" \\
    -loop 0 assets/teaser.gif
"""

import math
import os
import sys
import traceback

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Euler, Vector

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import smart_clipping  # noqa: E402

FRAME_SECONDS = 0.12          # time given to Blender to redraw before a screenshot
UI_SCALE = 1.15               # a little larger, so labels stay readable in the GIF
# (location, distance, rotation): every box in view, clear of the sidebar
VIEW_TOP = ((0.2, 1.4, 0.6), 24.0, (math.radians(58), 0.0, math.radians(18)))
VIEW_BOTTOM = ((1.4, 0.0, 1.6), 12.5)


PREVIEW = False
SCENE_ONLY = False

TRY_IT = """
[teaser] The demo scene is ready: try the move yourself.
  1. Point the mouse at the lower (front) view and press Shift+G.
  2. Move to the lower-left corner of the box on the right: the vertex snaps
     onto it ("Snapped Near vertex").
  3. Press A (Align Only X), then X (constrain to X).
  4. Slide left and right: it stops where its X lines up with the boxes on
     both sides and with the cube's own left side ("Snapped X coordinate of ...").
  5. Left click to confirm (right click cancels; Ctrl+Z undoes).
"""


def _args():
    global PREVIEW, SCENE_ONLY
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    PREVIEW = "--preview" in argv             # one frame, to check the framing
    SCENE_ONLY = "--scene-only" in argv       # build the scene, then hand over
    language = argv[argv.index("--language") + 1] if "--language" in argv else ""
    if SCENE_ONLY:
        return None, language
    if not argv:
        raise SystemExit("usage: ... --python tests/record_teaser.py -- FRAMES_DIR "
                         "[--language ja_JP] (or --scene-only)")
    out = os.path.abspath(argv[0])
    return out, language


def _box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = obj.data.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def _scene():
    """Boxes standing on the ground; X values of their vertices: Cube -1 / 1,
    Near 3 / 5, Tall 1.5 / 2.5, Far -6 / -4, Small -3 / -2."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    _box("Near", (2, 2, 2), (4.0, 0.5, 1.0))
    _box("Tall", (1, 1, 3), (2.0, 3.0, 1.5))
    _box("Far", (2, 2, 2), (-5.0, 1.0, 1.0))
    _box("Small", (1, 1, 1), (-2.5, 3.0, 0.5))
    cube = _box("Cube", (2, 2, 2), (0.0, 0.0, 1.0))
    bpy.ops.object.select_all(action="DESELECT")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(cube.data)
    corner = Vector((1.0, -1.0, -1.0))           # front, right, bottom
    for v in bm.verts:
        v.select_set((v.co - corner).length < 1e-6)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(cube.data)
    return cube


def _view3d_areas(window):
    return [a for a in window.screen.areas if a.type == "VIEW_3D"]


def _region(area, kind="WINDOW"):
    return next(r for r in area.regions if r.type == kind)


def _frames(out):
    win = bpy.context.window_manager.windows[0]
    area = _view3d_areas(win)[0]
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.5)
    yield 0.4
    top, bottom = sorted(_view3d_areas(win), key=lambda a: -a.y)
    if not SCENE_ONLY:
        bpy.context.preferences.view.ui_scale = UI_SCALE
    for a in (top, bottom):
        space = a.spaces.active
        space.shading.type = "SOLID"
        space.overlay.show_cursor = False
        space.overlay.show_relationship_lines = False
        space.show_region_ui = True
    yield 0.4
    for a in (top, bottom):
        _region(a, "UI").active_panel_category = "Tool"

    cube = _scene()
    scene = bpy.context.scene
    scene.smartclip_enabled = True
    scene.smartclip_target_scope = "VISIBLE"
    for axis in "xyz":
        setattr(scene, f"smartclip_align_{axis}", False)

    rv_top = top.spaces.active.region_3d
    rv_top.view_perspective = "PERSP"
    rv_top.view_location = VIEW_TOP[0]
    rv_top.view_distance = VIEW_TOP[1]
    rv_top.view_rotation = Euler(VIEW_TOP[2]).to_quaternion()
    rv_bottom = bottom.spaces.active.region_3d
    with bpy.context.temp_override(window=win, area=bottom, region=_region(bottom)):
        bpy.ops.view3d.view_axis(type="FRONT")          # "Front Orthographic"
    yield 0.6
    rv_bottom.view_location = VIEW_BOTTOM[0]
    rv_bottom.view_distance = VIEW_BOTTOM[1]
    rv_top.update()
    rv_bottom.update()
    yield 0.8
    if SCENE_ONLY:
        print(TRY_IT, flush=True)
        return

    # The move runs in the front view: there the cursor's offset is the world
    # X / Z offset, so it can be steered to exact coordinates.
    region = _region(bottom)
    count = [0]

    def shot():
        for name, a in (("top", top), ("bottom", bottom)):
            path = os.path.join(out, f"{name}_{count[0]:04d}.png")
            with bpy.context.temp_override(window=win, area=a):
                bpy.ops.screen.screenshot_area(filepath=path)
        count[0] += 1

    def px(co):
        return location_3d_to_region_2d(region, rv_bottom, Vector(co))

    vertex = cube.matrix_world @ Vector((1.0, -1.0, -1.0))
    start = px(vertex)
    mouse = [start.x, start.y]

    def ev(event_type, value, **mods):
        win.event_simulate(event_type, value, x=region.x + round(mouse[0]),
                           y=region.y + round(mouse[1]), **mods)

    def hold(frames):
        for _ in range(frames):
            yield FRAME_SECONDS
            shot()

    def glide(x, z, frames):
        """Bring the moving vertex towards world (x, z) with an ease in / out."""
        to = px((x, vertex.y, z))
        x0, y0 = mouse
        for i in range(1, frames + 1):
            t = i / frames
            t = t * t * (3 - 2 * t)
            mouse[0] = x0 + (to.x - x0) * t
            mouse[1] = y0 + (to.y - y0) * t
            ev("MOUSEMOVE", "NOTHING")
            yield FRAME_SECONDS
            shot()

    def press(key, **mods):
        ev(key, "PRESS", **mods)
        ev(key, "RELEASE", **mods)

    # Let the window take the simulated cursor; the first key event is dropped
    for dx in (4, 0, 4, 0):
        mouse[0] = start.x + dx
        ev("MOUSEMOVE", "NOTHING")
        yield FRAME_SECONDS
    press("ESC")                                 # also closes the splash screen
    yield FRAME_SECONDS
    if PREVIEW:
        yield from hold(1)
        return

    yield from hold(6)
    press("G", shift=True)                       # Move with Guides
    yield from hold(3)
    # Onto the near-left bottom corner of the box on the right (x 3, z 0)
    yield from glide(2.3, 0.5, 12)
    yield from glide(3.08, 0.06, 6)
    yield from hold(10)
    # Align Only X and the X constraint: slide along X
    press("A")
    yield from hold(3)
    press("X")
    yield from hold(6)
    for x_far, x_near, frames in ((4.6, 4.92, 12),      # Near, x 5
                                  (2.0, 1.58, 14),      # Tall, x 1.5
                                  (-0.6, -0.93, 10),    # its own mesh, x -1
                                  (-3.6, -3.93, 12),    # Far, x -4
                                  (-5.5, -5.92, 8),     # Far, x -6
                                  (2.4, 2.96, 18)):     # Near, x 3
        yield from glide(x_far, 0.0, frames)
        yield from glide(x_near, 0.0, 5)
        yield from hold(9)
    press("LEFTMOUSE")                           # confirm
    yield from hold(14)


def main():
    out, language = _args()
    if out is not None:
        os.makedirs(out, exist_ok=True)
        for name in os.listdir(out):
            if name.endswith(".png") and name.startswith(("top_", "bottom_", "frame_")):
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
            if SCENE_ONLY:
                return None                   # Blender stays open
            print(f"[teaser] frames written to {out}", flush=True)
            os._exit(0)
        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)

    bpy.app.timers.register(tick, first_interval=1.0)


if __name__ == "__main__":
    main()
