# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Shift+G keymap items and whether they are on.

The items are added at the head of their keymaps, so they take precedence
over the built-in Shift+G (Select Grouped / Select Similar).  Whether they are
active is the user's choice (Use Shortcut in the add-on preferences) and does
not follow the per-scene "Enable Smart Clipping" setting: the keymap is shared
by all scenes, so the operator's poll() checks the scene instead.  When it
fails, the key press falls through to Blender's own Shift+G.

A different key is set on the user keymap items (the add-on preferences draw
them, as does Preferences > Keymap), which Blender saves with the preferences.
The preferences also say which of Blender's own functions the key takes over
(overridden_name), so the trade-off of the default is visible where it is set.
"""

import bpy

MOVE_IDNAME = "view3d.smartclip_move"
# (keymap name, label in the preferences)
KEYMAPS = (("Object Mode", "Object Mode"), ("Mesh", "Edit Mode"))
DEFAULT_KEY = {"type": "G", "value": "PRESS", "shift": True, "ctrl": False, "alt": False,
               "oskey": False}

_addon_keymaps: list = []              # [(km, kmi), ...]
_fallback = {"enabled": True}          # used when preferences are unavailable


def _prefs():
    from .prefs import get_addon_prefs
    return get_addon_prefs(bpy.context)


def hotkeys_wanted() -> bool:
    prefs = _prefs()
    if prefs is not None:
        return bool(prefs.hotkeys_enabled)
    return _fallback["enabled"]


def apply_active(enabled: bool):
    for _km, kmi in _addon_keymaps:
        try:
            kmi.active = enabled
        except (ReferenceError, RuntimeError):
            pass


def set_hotkeys_wanted(enabled: bool):
    _fallback["enabled"] = enabled
    prefs = _prefs()
    if prefs is not None:
        prefs.hotkeys_enabled = enabled   # its update callback applies it as well
    apply_active(enabled)


def register_keymaps():
    """Create keymap entries for Object and Edit modes."""
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    kc = wm.keyconfigs.addon
    if not kc:
        return
    if _addon_keymaps:
        return  # already registered

    enabled = hotkeys_wanted()
    for km_name, _label in KEYMAPS:
        km = kc.keymaps.new(name=km_name, space_type="EMPTY", region_type="WINDOW")
        kmi = km.keymap_items.new(MOVE_IDNAME, head=True, **DEFAULT_KEY)
        kmi.active = enabled
        _addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


def user_items() -> list:
    """``[(label, km, kmi), ...]``: the items as the user keymap has them."""
    wm = getattr(bpy.context, "window_manager", None)
    kc = wm.keyconfigs.user if wm else None
    if kc is None:
        return []
    found = []
    for km_name, label in KEYMAPS:
        km = kc.keymaps.get(km_name)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname == MOVE_IDNAME:
                found.append((label, km, kmi))
                break
    return found


_KEY_FIELDS = ("type", "value", "any", "shift", "ctrl", "alt", "oskey", "key_modifier")


def overridden_name(km, kmi) -> "str | None":
    """Name of the active item in *km* (a user keymap) that *kmi* takes over.

    The first other active item with the same key and modifiers, which the
    key would run without Smart Clipping (Select Grouped / Select Similar
    for Shift+G); None when there is none or *kmi* is off.
    """
    try:
        if not kmi.active:
            return None
        key = tuple(getattr(kmi, f, None) for f in _KEY_FIELDS)
        for other in km.keymap_items:
            if other.idname == kmi.idname or not other.active:
                continue
            if tuple(getattr(other, f, None) for f in _KEY_FIELDS) == key:
                return other.name or other.idname
    except (ReferenceError, RuntimeError, AttributeError):
        pass
    return None


def reset_to_default():
    """Shift+G again in both modes, user changes undone, and turned on.

    A key change in the user keymap is recorded against the item's on/off
    state and only shows as a change while that state holds (one made in
    Preferences > Keymap while the shortcut was off, for example), so the
    changes are undone in both states, ending with the shortcut on.
    """
    if not _addon_keymaps:
        register_keymaps()
    for _km, kmi in _addon_keymaps:
        for key, value in DEFAULT_KEY.items():
            setattr(kmi, key, value)
    wm = getattr(bpy.context, "window_manager", None)
    for enabled in (False, True):
        set_hotkeys_wanted(enabled)
        if wm is not None:
            wm.keyconfigs.update()
        for _label, km, kmi in user_items():
            if getattr(kmi, "is_user_modified", False):
                try:
                    km.restore_item_to_default(kmi)
                except (ReferenceError, RuntimeError, TypeError):
                    pass
