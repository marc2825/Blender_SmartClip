# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""The add-on's own keymap item: Move with Guides on Shift+F in the 3D View.

The item is added to the "3D View" keymap of the add-on keyconfig when the
add-on registers and removed again when it unregisters; nothing else in any
keymap is touched.  Shift+F is free in Blender's Object Mode, Edit Mode and
3D View keymaps.  Users change or turn off the key in the add-on preferences
(which show the item as the user keymap has it) or in Preferences > Keymap,
and Blender keeps the change with the preferences.

The per-scene "Enable Snaxis" setting does not touch the keymap: the
operator's poll() checks the scene, and when it fails the key press goes on
to whatever else is bound to it.
"""

import bpy

MOVE_IDNAME = "view3d.smartclip_move"
KEYMAP_NAME = "3D View"
KEYMAP_SPACE = "VIEW_3D"
DEFAULT_KEY = {"type": "F", "value": "PRESS", "shift": True}

_addon_keymaps: list = []              # [(km, kmi), ...] registered by this add-on


def register_keymaps():
    """Add the item to the add-on keyconfig (absent in background mode)."""
    wm = getattr(bpy.context, "window_manager", None)
    kc = wm.keyconfigs.addon if wm else None
    if not kc or _addon_keymaps:
        return
    km = kc.keymaps.new(name=KEYMAP_NAME, space_type=KEYMAP_SPACE)
    kmi = km.keymap_items.new(MOVE_IDNAME, **DEFAULT_KEY)
    _addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


def user_item():
    """``(km, kmi)``: the item as the user keymap has it (for the preferences), or None."""
    wm = getattr(bpy.context, "window_manager", None)
    kc = wm.keyconfigs.user if wm else None
    km = kc.keymaps.get(KEYMAP_NAME) if kc else None
    if km is None:
        return None
    for kmi in km.keymap_items:
        if kmi.idname == MOVE_IDNAME:
            return km, kmi
    return None
