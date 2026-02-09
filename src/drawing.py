import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


def _axis_line(candidate, size=0.45):
    origin = candidate.location
    if candidate.type == "AXIS_X":
        axis = Vector((1.0, 0.0, 0.0))
    elif candidate.type == "AXIS_Y":
        axis = Vector((0.0, 1.0, 0.0))
    elif candidate.type == "AXIS_Z":
        axis = Vector((0.0, 0.0, 1.0))
    else:
        return None
    return origin - axis * size, origin + axis * size


def draw_3d(operator, _context):
    if not getattr(operator, "draw_enabled", False):
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    color = operator.color_snap if operator.hard_snap else operator.color_guide

    line_points = []
    point_points = []

    free_co = getattr(operator, "free_world", None)
    applied_co = getattr(operator, "applied_world", None)
    candidate = getattr(operator, "current_candidate", None)

    if free_co and applied_co:
        line_points.extend([free_co, applied_co])

    if candidate:
        point_points.append(candidate.location)
        axis_line = _axis_line(candidate)
        if axis_line:
            line_points.extend(axis_line)
        elif applied_co:
            line_points.extend([applied_co, candidate.location])

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")

    if line_points:
        batch = batch_for_shader(shader, "LINES", {"pos": line_points})
        shader.bind()
        shader.uniform_float("color", color)
        gpu.state.line_width_set(2.0)
        batch.draw(shader)

    if point_points:
        batch = batch_for_shader(shader, "POINTS", {"pos": point_points})
        shader.bind()
        shader.uniform_float("color", color)
        gpu.state.point_size_set(8.0)
        batch.draw(shader)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("NONE")


def draw_2d(operator, _context):
    if not getattr(operator, "draw_enabled", False):
        return

    hud_text = getattr(operator, "hud_text", "")
    if not hud_text:
        return

    color = operator.color_snap if operator.hard_snap else operator.color_guide
    font_id = 0
    x = 20
    y = 20

    blf.position(font_id, x, y, 0)
    blf.size(font_id, 13.0)
    blf.color(font_id, color[0], color[1], color[2], color[3])
    blf.draw(font_id, hud_text)
