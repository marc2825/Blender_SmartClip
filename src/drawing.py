"""GPU overlay drawing for guide lines, snap points, and the HUD."""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


# Half-length of the "infinite-looking" constraint guide lines.
_CONSTRAINT_HALF_LEN = 50.0
_AXIS_COLORS = {
    "X": (1.0, 0.2, 0.2, 0.45),
    "Y": (0.2, 1.0, 0.2, 0.45),
    "Z": (0.3, 0.3, 1.0, 0.45),
}
_AXIS_VECTORS = {
    "X": Vector((1.0, 0.0, 0.0)),
    "Y": Vector((0.0, 1.0, 0.0)),
    "Z": Vector((0.0, 0.0, 1.0)),
}
# Cap on dash segments per dashed line (long lines get longer dashes).
_MAX_DASHES = 200


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def _dashed_line_points(start, end, dash=0.06, gap=0.04):
    """Generate vertex pairs for drawing a dashed line as LINES segments."""
    d = end - start
    length = d.length
    if length < 1e-6:
        return []
    scale = max(1.0, length / ((dash + gap) * _MAX_DASHES))
    dash *= scale
    gap *= scale
    n = d / length
    pts = []
    t = 0.0
    while t < length:
        p0 = start + n * t
        t1 = min(t + dash, length)
        p1 = start + n * t1
        pts.extend([p0, p1])
        t = t1 + gap
    return pts


def _constraint_guides(constraint, origin):
    """Return [(axis, [p0, p1]), ...] guide lines for an axis / plane constraint."""
    if not constraint or origin is None:
        return []
    guides = []
    for axis in constraint:  # "X" -> one line, "YZ" -> two lines
        vec = _AXIS_VECTORS.get(axis)
        if vec is None:
            continue
        offset = vec * _CONSTRAINT_HALF_LEN
        guides.append((axis, [origin - offset, origin + offset]))
    return guides


def _draw_lines(coords, color, width):
    if not coords:
        return
    # POLYLINE_* honours lineWidth on every GPU backend; gpu.state.line_width_set
    # is ignored for widths > 1 on Metal / Vulkan.
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    shader.bind()
    viewport = gpu.state.viewport_get()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_points(coords, color, size):
    if not coords:
        return
    shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.point_size_set(size)
    batch.draw(shader)
    gpu.state.point_size_set(1.0)


# ------------------------------------------------------------------
# 3-D overlay (POST_VIEW)
# ------------------------------------------------------------------

def draw_3d(op, _context):
    """Draw guide lines and snap point markers in world space."""
    try:
        if not op.draw_enabled:
            return
        _draw_3d(op)
    except ReferenceError:
        # Operator already freed (e.g. aborted without cleanup): draw nothing.
        return


def _draw_3d(op):
    color = op.color_snap if op.hard_snap else op.color_guide

    lines = []
    dashes = []
    pts = []

    free = op.free_world
    applied = op.applied_world
    cand = op.current_candidate

    if cand:
        if cand.type.startswith("ALIGN_"):
            # Axis-clipping mode: solid line from current to alignment point,
            # dashed line from alignment point to the reference vertex
            pts.append(cand.location)
            pts.append(cand.reference_co)
            if applied:
                lines.extend([applied, cand.location])
            dashes.extend(_dashed_line_points(cand.location, cand.reference_co))
        else:
            # Regular snap: line from free to applied + line from applied to candidate
            if free and applied:
                lines.extend([free, applied])
            pts.append(cand.location)
            if applied:
                lines.extend([applied, cand.location])
    else:
        # No candidate: show free→applied line only when there's a difference
        if free and applied:
            lines.extend([free, applied])

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    try:
        # Constraint axis lines (subtle, behind other overlays)
        for axis, coords in _constraint_guides(op.constraint_mode, applied):
            _draw_lines(coords, _AXIS_COLORS[axis], 1.5)

        _draw_lines(lines, color, 2.0)
        _draw_lines(dashes, (*color[:3], color[3] * 0.7), 1.5)
        _draw_points(pts, color, 8.0)
    finally:
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


# ------------------------------------------------------------------
# 2-D HUD (POST_PIXEL)
# ------------------------------------------------------------------

def draw_2d(op, _context):
    """Draw the lower-left HUD text."""
    try:
        if not op.draw_enabled:
            return
        text = op.hud_text
        color = op.color_snap if op.hard_snap else op.color_guide
    except ReferenceError:
        return
    if not text:
        return

    scale = bpy.context.preferences.system.ui_scale
    font_id = 0
    blf.position(font_id, 20 * scale, 20 * scale, 0)
    blf.size(font_id, 14.0 * scale)
    blf.color(font_id, color[0], color[1], color[2], color[3])
    blf.draw(font_id, text)
