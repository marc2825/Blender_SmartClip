"""GPU overlay drawing for guide lines, snap points, and the HUD."""

import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def _dashed_line_points(start, end, dash=0.06, gap=0.04):
    """Generate vertex pairs for drawing a dashed line as LINES segments."""
    d = end - start
    length = d.length
    if length < 1e-6:
        return []
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


# ------------------------------------------------------------------
# 3-D overlay (POST_VIEW)
# ------------------------------------------------------------------

def draw_3d(op, _context):
    """Draw guide lines and snap point markers in world space."""
    if not getattr(op, "draw_enabled", False):
        return

    color = op.color_snap if op.hard_snap else op.color_guide
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    lines = []
    dashes = []
    pts = []

    free = getattr(op, "free_world", None)
    applied = getattr(op, "applied_world", None)
    cand = getattr(op, "current_candidate", None)

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

    # Axis / plane constraint indicator line through the current position
    constraint = getattr(op, "constraint_mode", None)
    constraint_lines = []
    if constraint and applied:
        _CLEN = 50.0  # half-length of the infinite-looking constraint line
        if constraint == "X":
            constraint_lines = [applied - Vector((_CLEN, 0, 0)), applied + Vector((_CLEN, 0, 0))]
        elif constraint == "Y":
            constraint_lines = [applied - Vector((0, _CLEN, 0)), applied + Vector((0, _CLEN, 0))]
        elif constraint == "Z":
            constraint_lines = [applied - Vector((0, 0, _CLEN)), applied + Vector((0, 0, _CLEN))]

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")

    # Constraint axis line (subtle, behind other overlays)
    if constraint_lines:
        _axis_colors = {
            "X": (1.0, 0.2, 0.2, 0.45),
            "Y": (0.2, 1.0, 0.2, 0.45),
            "Z": (0.3, 0.3, 1.0, 0.45),
        }
        c_color = _axis_colors.get(constraint, (*color[:3], 0.35))
        batch = batch_for_shader(shader, "LINES", {"pos": constraint_lines})
        shader.bind()
        shader.uniform_float("color", c_color)
        gpu.state.line_width_set(1.5)
        batch.draw(shader)

    # Solid lines
    if lines:
        batch = batch_for_shader(shader, "LINES", {"pos": lines})
        shader.bind()
        shader.uniform_float("color", color)
        gpu.state.line_width_set(2.0)
        batch.draw(shader)

    # Dashed lines (thinner)
    if dashes:
        batch = batch_for_shader(shader, "LINES", {"pos": dashes})
        shader.bind()
        shader.uniform_float("color", (*color[:3], color[3] * 0.7))
        gpu.state.line_width_set(1.5)
        batch.draw(shader)

    # Points: snap target + reference vertex
    if pts:
        batch = batch_for_shader(shader, "POINTS", {"pos": pts})
        shader.bind()
        shader.uniform_float("color", color)
        gpu.state.point_size_set(8.0)
        batch.draw(shader)

    # Restore defaults
    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("NONE")


# ------------------------------------------------------------------
# 2-D HUD (POST_PIXEL)
# ------------------------------------------------------------------

def draw_2d(op, _context):
    """Draw the lower-left HUD text."""
    if not getattr(op, "draw_enabled", False):
        return

    text = getattr(op, "hud_text", "")
    if not text:
        return

    color = op.color_snap if op.hard_snap else op.color_guide
    font_id = 0

    blf.position(font_id, 20, 20, 0)
    blf.size(font_id, 14.0)
    blf.color(font_id, color[0], color[1], color[2], color[3])
    blf.draw(font_id, text)
