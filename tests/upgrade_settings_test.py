# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Install a new legacy ZIP over an older one the way a user updates, and check
that the user's settings survive the update and a restart of Blender.

The legacy add-on keeps its module name (``smart_clipping``) across versions,
including the rename from Smart Clipping to Snaxis, and Blender keeps
add-on preferences and a changed key under that name.

Usage (disposable user folders; run both phases with the same folders, the
second one without --factory-startup so that it loads what the first saved):

  BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts \\
  BLENDER_USER_CONFIG=/tmp/bl/config \\
    blender --background --factory-startup --python tests/upgrade_settings_test.py -- \\
      --phase before OLD.zip NEW.zip
  (same variables) blender --background --python tests/upgrade_settings_test.py -- \\
      --phase after OLD.zip NEW.zip

before: installs and enables OLD.zip, changes every preference and the key,
  saves, installs NEW.zip over it (as Install from Disk does), saves again.
after: the add-on is enabled at start-up as the new version, with the
  preferences and the key as they were changed.

Exit code 0 = every check passed.
"""

import os
import sys
import traceback

import bpy

MODULE = "smart_clipping"
MOVE = "view3d.smartclip_move"
# A value other than the default for every preference the old version has
CUSTOM_PREFS = {
    "snap_behavior": "PULL",
    "snap_distance_px": 23,
    "max_vertex_budget": 12345,
    "search_backend": "KDTREE",
    "hotkeys_enabled": False,
    "color_guide": (0.1, 0.2, 0.3, 0.4),
    "color_snap": (0.5, 0.6, 0.7, 0.8),
}

_checked = []
_failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip(), flush=True)
    _checked.append(name)
    if not cond:
        _failures.append(name)


def prefs():
    addon = bpy.context.preferences.addons.get(MODULE)
    return addon.preferences if addon else None


def values(p):
    out = {}
    for name in CUSTOM_PREFS:
        value = getattr(p, name)
        out[name] = (tuple(round(v, 4) for v in value)
                     if hasattr(value, "__len__") and not isinstance(value, str) else value)
    return out


def expected():
    return {k: tuple(round(v, 4) for v in val) if isinstance(val, tuple) else val
            for k, val in CUSTOM_PREFS.items()}


def user_item():
    keyconfigs = bpy.context.window_manager.keyconfigs
    keyconfigs.update()
    km = keyconfigs.user.keymaps.get("Object Mode")
    for kmi in km.keymap_items if km else ():
        if kmi.idname == MOVE:
            return kmi
    return None


def bl_info():
    module = sys.modules.get(MODULE)
    return getattr(module, "bl_info", {}) if module else {}


def phase_before(old_zip, new_zip):
    bpy.ops.preferences.addon_install(filepath=old_zip)
    bpy.ops.preferences.addon_enable(module=MODULE)
    p = prefs()
    check("old_version_enabled", p is not None, str(bl_info().get("name")))
    if p is None:
        return
    old_version = bl_info().get("version")
    for name, value in CUSTOM_PREFS.items():
        setattr(p, name, value)
    kmi = user_item()
    if kmi is not None:
        kmi.type = "F"
        bpy.context.window_manager.keyconfigs.update()
    check("old_settings_changed", values(p) == expected(), str(values(p)))
    kmi = user_item()
    check("old_key_changed", kmi is not None and kmi.type == "F", str(kmi.type if kmi else None))
    bpy.ops.wm.save_userpref()

    # Update in place, as Install from Disk over the old version does
    bpy.ops.preferences.addon_install(filepath=new_zip, overwrite=True)
    check("still_enabled_after_install", prefs() is not None)
    bpy.ops.wm.save_userpref()
    print(f"[upgrade:test] installed over {old_version}", flush=True)


def phase_after(_old_zip, new_zip):
    p = prefs()
    check("enabled_after_restart", p is not None)
    if p is None:
        return
    info = bl_info()
    import re
    match = re.search(r"-v(\d+\.\d+\.\d+)\.zip$", new_zip)
    version = ".".join(str(v) for v in info.get("version", ()))
    check("new_version_loaded", match is not None and match.group(1) == version,
          f"{info.get('name')} {version}")
    check("preferences_kept", values(p) == expected(), str(values(p)))
    kmi = user_item()
    check("key_kept", kmi is not None and kmi.type == "F", str(kmi.type if kmi else None))
    check("use_shortcut_kept", kmi is not None and not kmi.active)
    check("registered", hasattr(bpy.types, "SMARTCLIP_PT_panel")
          and "smartclip_enabled" in bpy.types.Scene.bl_rna.properties)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 4 or argv[0] != "--phase" or argv[1] not in ("before", "after"):
        print("usage: ... --python tests/upgrade_settings_test.py -- "
              "--phase before|after OLD.zip NEW.zip")
        return 2
    if not all(os.environ.get(v) for v in ("BLENDER_USER_RESOURCES", "BLENDER_USER_CONFIG",
                                           "BLENDER_USER_SCRIPTS")):
        print("refusing to run: set BLENDER_USER_RESOURCES / _CONFIG / _SCRIPTS to a "
              "disposable folder so the real user folders are not touched")
        return 2
    phase, old_zip, new_zip = argv[1], os.path.abspath(argv[2]), os.path.abspath(argv[3])
    (phase_before if phase == "before" else phase_after)(old_zip, new_zip)
    print(f"[upgrade:test] {phase}: passed={len(_checked) - len(_failures)} "
          f"failed={len(_failures)}", flush=True)
    return 1 if _failures or not _checked else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
