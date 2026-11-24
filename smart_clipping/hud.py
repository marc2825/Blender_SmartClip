"""Words shown during a move: viewport labels, the mode lines and the status bar.

A label is a list of runs ``(text, role)``; drawing.py turns roles into
colours.  Roles: ``"text"``, ``"muted"``, ``"accent"`` (the snap colour),
``"warning"``, and ``GAP`` for extra space between groups.
"""

import bpy

from .i18n import iface
from .utils import SCOPE_NAMES, SNAP_PULL, STATE_PULLING, STATE_SNAPPED

GAP = (None, "gap")


def format_length(value: float, scene) -> str:
    """A length in the scene's unit system (Scene > Units), like Blender's header."""
    units = getattr(scene, "unit_settings", None)
    if units is None or units.system == "NONE":
        return f"{value:.3f}"
    scaled = value * units.scale_length
    try:
        return bpy.utils.units.to_string(units.system, "LENGTH", scaled, precision=4,
                                         split_unit=bool(units.use_separate))
    except (ValueError, TypeError, RuntimeError):
        return f"{scaled:.3f}"


def target_text(cand) -> str:
    name = cand.target_name or "?"
    if cand.type.startswith("ALIGN_"):
        return iface("{axis} coordinate of {object}").format(axis=cand.type[-1], object=name)
    if cand.type == "BOUNDS":
        return iface("{object} bounding box").format(object=name)
    return iface("{object} vertex").format(object=name)


def candidate_runs(cand, state, distance_text=None) -> list:
    """Label next to the snap point: state, what it is, and (pulling) how far."""
    runs = []
    if state == STATE_SNAPPED:
        runs.append((iface("Snapped"), "accent"))
    elif state == STATE_PULLING:
        runs.append((iface("Pulling"), "accent"))
    runs.append((target_text(cand), "text"))
    if distance_text:
        runs.append((distance_text, "muted"))
    return runs


def moved_text(distance_text: str, constraint) -> str:
    """Label next to the moving point: how far it moved and along what."""
    if not constraint:
        return iface("Moved {distance}").format(distance=distance_text)
    if len(constraint) == 1:
        return iface("Moved {distance} along {axis}").format(distance=distance_text,
                                                            axis=constraint)
    return iface("Moved {distance} on {plane}").format(distance=distance_text, plane=constraint)


def scope_name(scope) -> str:
    return iface(SCOPE_NAMES.get(scope, scope))


def axes_text(axes) -> str:
    return ", ".join(sorted(axes)) if axes else iface("Off")


def empty_reason(scope, is_edit, has_collection) -> str:
    """Why Snap To found nothing, and what to do about it."""
    if scope == "SELF" and not is_edit:
        return iface("Same Mesh works in Edit Mode. Press S to snap to other objects")
    if scope == "COLLECTION" and not has_collection:
        return iface("Choose a collection in the sidebar")
    if scope == "SELECTED":
        return iface("Select the objects to snap to before moving")
    return iface("No visible meshes found")


def mode_lines(scope, align_axes, align_blocked, constraint, empty, limit_exceeded) -> list:
    """Lines in the corner of the viewport: the settings S and A switch, and notes.

    *empty*: the reason from empty_reason() when there is nothing to snap to.
    """
    lines = [[
        (iface("Snap To"), "muted"), (scope_name(scope), "text"), GAP,
        (iface("Align Only"), "muted"), (axes_text(align_axes), "text"),
    ]]
    if empty:
        lines.append([(iface("Nothing to snap to."), "warning"), (empty, "text")])
    elif align_blocked:
        lines.append([(iface("Align Only {axes} is paused while the move is locked to "
                             "{constraint}").format(axes=axes_text(align_axes),
                                                    constraint=constraint), "warning")])
    if limit_exceeded:
        lines.append([(iface("Snap point limit reached: far objects use fewer points"),
                       "muted")])
    return lines


def status_items(behavior) -> list:
    """Status bar during a move: ``[(icons, label), ...]``.

    The labels are translated by the status bar itself; Confirm, Cancel, Axis,
    Plane and Snap To use Blender's own words.
    """
    ctrl = "Snap Exactly" if behavior == SNAP_PULL else "Move Freely"
    return [
        (("MOUSE_LMB",), "Confirm"),
        (("MOUSE_RMB", "EVENT_ESC"), "Cancel"),
        (("EVENT_CTRL",), ctrl),
        (("EVENT_X", "EVENT_Y", "EVENT_Z"), "Axis"),
        (("EVENT_SHIFT", "EVENT_X", "EVENT_Y", "EVENT_Z"), "Plane"),
        (("EVENT_A",), "Align Only"),
        (("EVENT_S",), "Snap To"),
    ]


_KEY_NAMES = {
    "MOUSE_LMB": "LMB", "MOUSE_RMB": "RMB", "EVENT_ESC": "Esc", "EVENT_CTRL": "Ctrl",
    "EVENT_SHIFT": "Shift", "EVENT_X": "X", "EVENT_Y": "Y", "EVENT_Z": "Z",
    "EVENT_A": "A", "EVENT_S": "S",
}


def status_text(behavior) -> str:
    """The status bar as one line of text (when it cannot be drawn with icons)."""
    parts = []
    for icons, label in status_items(behavior):
        names = [_KEY_NAMES.get(icon, icon) for icon in icons]
        if names[0] == "Shift":
            keys = "Shift+" + "/".join(names[1:])
        else:
            keys = "/".join(names)
        parts.append(f"{keys} {iface(label)}")
    return "    ".join(parts)


def limit_detail(simplified: int, skipped: int) -> str:
    """Second line of the sidebar's limit warning (short: the sidebar is narrow)."""
    if skipped:
        return iface("{simplified} simplified, {skipped} left out").format(
            simplified=simplified, skipped=skipped)
    return iface("{simplified} objects simplified").format(simplified=simplified)
