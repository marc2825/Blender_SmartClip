"""Viewport overlay during a move.

3D (POST_VIEW): guide lines and the constraint axis.
2D (POST_PIXEL): the snap point marker, its label, the moving point's label,
the snap distance ring and, in the viewport the move runs in, the mode lines
in the lower left corner.

What tells the snap state apart is not colour alone: the marker is hollow
while the point is pulled or only guided and filled once it is snapped, and
the label next to it starts with the state.  The marker's shape tells what
the snap point is: a circle for a vertex, a square for a bounding box point,
a diamond for an aligned coordinate.  Sizes follow the interface scale, the
label colours follow the theme (tooltip colours).
"""

import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .utils import STATE_PULLING, STATE_SNAPPED

# Half-length of the "infinite-looking" constraint guide lines.
_CONSTRAINT_HALF_LEN = 50.0
_AXIS_VECTORS = {
    "X": Vector((1.0, 0.0, 0.0)),
    "Y": Vector((0.0, 1.0, 0.0)),
    "Z": Vector((0.0, 0.0, 1.0)),
}
_AXIS_FALLBACK = {
    "X": (1.0, 0.2, 0.32),
    "Y": (0.55, 0.86, 0.0),
    "Z": (0.16, 0.56, 1.0),
}
# Cap on dash segments per dashed line (long lines get longer dashes).
_MAX_DASHES = 200
_FONT_ID = 0


# ------------------------------------------------------------------
# Theme and scale
# ------------------------------------------------------------------

def _ui_scale() -> float:
    scale = bpy.context.preferences.system.ui_scale
    return scale if scale > 0.0 else 1.0


def _theme():
    """Colours from the active theme, with fallbacks."""
    colors = {
        "bg": (0.1, 0.1, 0.1, 0.9),
        "text": (0.85, 0.85, 0.85, 1.0),
        "warning": (1.0, 0.72, 0.25, 1.0),
        "axis": {k: (*v, 1.0) for k, v in _AXIS_FALLBACK.items()},
    }
    try:
        theme = bpy.context.preferences.themes[0]
        ui = theme.user_interface
        inner = tuple(ui.wcol_tooltip.inner)
        colors["bg"] = (inner[0], inner[1], inner[2], 0.9)
        colors["text"] = (*tuple(ui.wcol_tooltip.text)[:3], 1.0)
        colors["axis"] = {"X": (*ui.axis_x, 1.0), "Y": (*ui.axis_y, 1.0), "Z": (*ui.axis_z, 1.0)}
        warning = getattr(theme.info, "info_warning", None)
        if warning is not None:
            colors["warning"] = (*tuple(warning)[:3], 1.0)
    except (AttributeError, IndexError, TypeError):
        pass
    colors["muted"] = (*colors["text"][:3], 0.65)
    return colors


def _with_alpha(color, alpha):
    return (color[0], color[1], color[2], color[3] * alpha if len(color) > 3 else alpha)


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


def _ring(center, radius, segments=24, start=0.0):
    return [(center[0] + radius * math.cos(start + 2.0 * math.pi * i / segments),
             center[1] + radius * math.sin(start + 2.0 * math.pi * i / segments))
            for i in range(segments)]


def _shape_outline(center, shape, size):
    if shape == "square":
        return _ring(center, size * 1.15, 4, math.pi / 4.0)
    if shape == "diamond":
        return _ring(center, size * 1.3, 4, 0.0)
    return _ring(center, size, 20)


def _rounded_rect(x, y, w, h, r, segments=4):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    corners = ((x + w - r, y + h - r, 0.0), (x + r, y + h - r, 0.5 * math.pi),
               (x + r, y + r, math.pi), (x + w - r, y + r, 1.5 * math.pi))
    pts = []
    for cx, cy, a0 in corners:
        for i in range(segments + 1):
            a = a0 + 0.5 * math.pi * i / segments
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ------------------------------------------------------------------
# GPU primitives
# ------------------------------------------------------------------

def _as_3d(coords):
    return [(c[0], c[1], c[2] if len(c) > 2 else 0.0) for c in coords]


def _draw_lines(coords, color, width):
    if not coords:
        return
    # POLYLINE_* honours lineWidth on every GPU backend; gpu.state.line_width_set
    # is ignored for widths > 1 on Metal / Vulkan.
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": _as_3d(coords)})
    shader.bind()
    viewport = gpu.state.viewport_get()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _loop_segments(points):
    segments = []
    for i, p in enumerate(points):
        segments.extend([p, points[(i + 1) % len(points)]])
    return segments


def _fill_polygon(points, color):
    """Fill a convex polygon (2D, pixel space)."""
    if len(points) < 3:
        return
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    coords = [(cx, cy)] + list(points)
    indices = [(0, i + 1, (i + 1) % len(points) + 1) for i in range(len(points))]
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": _as_3d(coords)}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_marker(center, shape, filled, color, outline, scale):
    points = _shape_outline(center, shape, 5.0 * scale)
    if filled:
        _fill_polygon(points, color)
        _draw_lines(_loop_segments(points), outline, 1.0 * scale)
    else:
        _draw_lines(_loop_segments(points), outline, 4.0 * scale)
        _draw_lines(_loop_segments(points), color, 2.0 * scale)


def _draw_cross(center, size, color, width):
    x, y = center
    _draw_lines([(x - size, y), (x + size, y), (x, y - size), (x, y + size)], color, width)


def _draw_dashed_ring(center, radius, color, halo, width):
    """Dashes about 6 px long, light on a dark halo so they read on any surface."""
    segments = max(16, min(160, int(2.0 * math.pi * radius / 6.0)))
    if segments % 2:
        segments += 1
    pts = _ring(center, radius, segments)
    dashes = [p for i in range(0, segments, 2) for p in (pts[i], pts[i + 1])]
    _draw_lines(dashes, halo, width + 2.0)
    _draw_lines(dashes, color, width)


# ------------------------------------------------------------------
# Text labels
# ------------------------------------------------------------------

def _run_widths(runs, size, scale):
    blf.size(_FONT_ID, size)
    widths = []
    for text, role in runs:
        if role == "gap":
            widths.append(14.0 * scale)
        else:
            widths.append(blf.dimensions(_FONT_ID, text)[0])
    return widths


def _label_size(runs, scale):
    size = 12.0 * scale
    widths = _run_widths(runs, size, scale)
    space = 5.0 * scale
    words = [w for w, (_t, role) in zip(widths, runs) if role != "gap"]
    gaps = sum(w for w, (_t, role) in zip(widths, runs) if role == "gap")
    text_w = sum(words) + gaps + space * max(0, len(words) - 1)
    pad_x, pad_y = 7.0 * scale, 4.0 * scale
    return text_w + 2.0 * pad_x, size + 2.0 * pad_y, size, widths, space, pad_x, pad_y


def _draw_label(x, y, runs, colors, scale):
    """Draw *runs* on a rounded box whose lower left corner is (x, y)."""
    if not runs:
        return 0.0, 0.0
    w, h, size, widths, space, pad_x, pad_y = _label_size(runs, scale)
    _fill_polygon(_rounded_rect(x, y, w, h, 4.0 * scale), colors["bg"])
    blf.size(_FONT_ID, size)
    cx = x + pad_x
    baseline = y + pad_y + size * 0.22
    first = True
    for (text, role), width in zip(runs, widths):
        if role == "gap":
            cx += width
            continue
        if not first:
            cx += space
        first = False
        color = colors.get(role, colors["text"])
        blf.color(_FONT_ID, color[0], color[1], color[2], color[3])
        blf.position(_FONT_ID, cx, baseline, 0)
        blf.draw(_FONT_ID, text)
        cx += width
    return w, h


def _overlap_insets(area, region):
    """Pixels of *region* covered by overlapping regions at its left and bottom
    (the toolbar with Region Overlap on)."""
    left = bottom = 0.0
    if area is None or region is None:
        return left, bottom
    for other in area.regions:
        if other.type == "WINDOW" or other.width <= 1 or other.height <= 1:
            continue
        overlaps_x = other.x < region.x + region.width and other.x + other.width > region.x
        overlaps_y = other.y < region.y + region.height and other.y + other.height > region.y
        if not (overlaps_x and overlaps_y):
            continue
        if other.x <= region.x + 1 and other.height > region.height * 0.5:
            left = max(left, other.x + other.width - region.x)
        elif other.y <= region.y + 1 and other.width > region.width * 0.5:
            bottom = max(bottom, other.y + other.height - region.y)
    return left, bottom


# ------------------------------------------------------------------
# 3-D overlay (POST_VIEW)
# ------------------------------------------------------------------

def draw_3d(op, _context):
    """Draw guide lines in world space."""
    try:
        if not op.draw_enabled:
            return
        _draw_3d(op)
    except ReferenceError:
        # Operator already freed (e.g. aborted without cleanup): draw nothing.
        return


def _draw_3d(op):
    scale = _ui_scale()
    colors = _theme()
    color = op.color_snap if op.snap_state == STATE_SNAPPED else op.color_guide

    lines = []
    dashes = []
    free = op.free_world
    applied = op.applied_world
    cand = op.current_candidate

    if cand:
        if cand.type.startswith("ALIGN_"):
            # Align Only: solid line from the moving point to the aligned
            # position, dashed line on to the vertex it lines up with
            if applied:
                lines.extend([applied, cand.location])
            dashes.extend(_dashed_line_points(cand.location, cand.reference_co))
        else:
            # Where the mouse would put it -> where it is -> the snap point
            if free and applied and (free - applied).length > 1e-9:
                lines.extend([free, applied])
            if applied and (applied - cand.location).length > 1e-9:
                lines.extend([applied, cand.location])
    elif free and applied and (free - applied).length > 1e-9:
        lines.extend([free, applied])

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    try:
        # Constraint axis lines (subtle, behind other overlays)
        for axis, coords in _constraint_guides(op.constraint_mode, applied):
            _draw_lines(coords, _with_alpha(colors["axis"][axis], 0.55), 1.5 * scale)

        _draw_lines(lines, color, 2.0 * scale)
        _draw_lines(dashes, _with_alpha(color, 0.7), 1.5 * scale)
    finally:
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


# ------------------------------------------------------------------
# 2-D overlay (POST_PIXEL)
# ------------------------------------------------------------------

def draw_2d(op, _context):
    """Draw markers, labels and the mode lines in pixel space."""
    try:
        if not op.draw_enabled:
            return
        _draw_2d(op)
    except ReferenceError:
        return


def _draw_2d(op):
    context = bpy.context
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return
    scale = _ui_scale()
    colors = _theme()
    accent = tuple(op.color_snap if op.snap_state == STATE_SNAPPED else op.color_guide)
    colors["accent"] = (*accent[:3], 1.0)

    def project(co):
        return location_3d_to_region_2d(region, rv3d, co) if co is not None else None

    gpu.state.blend_set("ALPHA")
    try:
        free_px = project(op.free_world)
        applied_px = project(op.applied_world)
        cand = op.current_candidate

        # Snap distance: snap points inside this ring are within reach
        if op.snapping_on and free_px is not None:
            _draw_dashed_ring(free_px, float(op.threshold_px), _with_alpha(colors["text"], 0.8),
                              _with_alpha(colors["bg"], 0.6), 1.25 * scale)

        if cand is not None:
            cand_px = project(cand.location)
            if cand.type.startswith("ALIGN_"):
                shape = "diamond"
                ref_px = project(cand.reference_co)
                if ref_px is not None:
                    _draw_marker(ref_px, "circle", False, _with_alpha(colors["accent"], 0.7),
                                 colors["bg"], 0.7 * scale)
            else:
                shape = "square" if cand.type == "BOUNDS" else "circle"
            if (free_px is not None and op.snap_state in (STATE_SNAPPED, STATE_PULLING)
                    and applied_px is not None and (free_px - applied_px).length > 3.0):
                _draw_cross(free_px, 5.0 * scale, colors["muted"], 1.5 * scale)
            if cand_px is not None:
                _draw_marker(cand_px, shape, op.snap_state == STATE_SNAPPED, colors["accent"],
                             colors["bg"], scale)
                w, _h, *_rest = _label_size(op.candidate_runs, scale)
                x = cand_px.x + 12.0 * scale
                if x + w > region.width - 8.0 * scale:
                    x = cand_px.x - 12.0 * scale - w
                _draw_label(x, cand_px.y + 6.0 * scale, op.candidate_runs, colors, scale)

        if applied_px is not None and op.moved_label:
            runs = [(op.moved_label, "text")]
            w, h, *_rest = _label_size(runs, scale)
            _draw_label(applied_px.x - w / 2.0, applied_px.y - h - 14.0 * scale, runs, colors,
                        scale)

        if op.mode_runs and region.as_pointer() == op.region_pointer:
            left, bottom = _overlap_insets(context.area, region)
            x = left + 12.0 * scale
            y = bottom + 12.0 * scale
            for runs in reversed(op.mode_runs):
                _w, h = _draw_label(x, y, runs, colors, scale)
                y += h + 4.0 * scale
    finally:
        gpu.state.blend_set("NONE")
