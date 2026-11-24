# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Install a release ZIP the way a user would and check that the add-on works.

Usage (the user folders must point somewhere disposable):
  BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \\
  BLENDER_USER_RESOURCES=/tmp/bl \\
    blender --background --factory-startup --python tests/install_zip_test.py -- \\
      [--upgrade-from OLD.zip] dist/snaxis-vX.Y.Z.zip

With --upgrade-from, OLD.zip is installed and enabled first, then the new ZIP
is installed over it and the add-on is disabled and enabled again in the
same session (no restart), as a user updating from the Preferences would.

Exit code 0 = installed, enabled, registered, disabled and removed cleanly.
"""

import os
import re
import sys
import traceback

import bpy

MODULE = "smart_clipping"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    old_zip = None
    if len(argv) == 3 and argv[0] == "--upgrade-from":
        old_zip, argv = os.path.abspath(argv[1]), argv[2:]
    if len(argv) != 1:
        print("usage: ... --python tests/install_zip_test.py -- "
              "[--upgrade-from OLD.zip] PATH/TO/snaxis-vX.Y.Z.zip")
        return 2
    zip_path = os.path.abspath(argv[0])
    if not (os.environ.get("BLENDER_USER_SCRIPTS") or os.environ.get("BLENDER_USER_RESOURCES")):
        print("refusing to run: set BLENDER_USER_SCRIPTS / BLENDER_USER_RESOURCES to a "
              "disposable folder so the real user add-on folder is not touched")
        return 2

    failures = []
    checked = []

    def check(name, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip(), flush=True)
        checked.append(name)
        if not cond:
            failures.append(name)

    if old_zip:
        bpy.ops.preferences.addon_install(filepath=old_zip)
        bpy.ops.preferences.addon_enable(module=MODULE)
        old = sys.modules.get(MODULE)
        check("old_version_enabled", old is not None,
              ".".join(str(v) for v in old.bl_info["version"]) if old else "")
        old_modules = {name: id(mod) for name, mod in sys.modules.items()
                       if name.startswith(MODULE + ".")}
        # Install over it and switch the add-on off and on without restarting
        bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
        bpy.ops.preferences.addon_disable(module=MODULE)
        try:
            bpy.ops.preferences.addon_enable(module=MODULE)
        except Exception as exc:       # the failure reported in issue #23
            check("upgrade_reenable", False, f"{type(exc).__name__}: {exc}")
        else:
            check("upgrade_reenable", bpy.context.preferences.addons.get(MODULE) is not None)
        stale = [name for name, ident in old_modules.items()
                 if name in sys.modules and id(sys.modules[name]) == ident]
        check("upgrade_reloads_every_module", not stale, ", ".join(stale))
    else:
        bpy.ops.preferences.addon_install(filepath=zip_path)
        bpy.ops.preferences.addon_enable(module=MODULE)
    addon = bpy.context.preferences.addons.get(MODULE)
    module = sys.modules.get(MODULE)
    check("enabled", addon is not None and module is not None)
    if module is None:
        return 1

    installed_at = os.path.dirname(os.path.abspath(module.__file__))
    user_root = os.path.abspath(os.environ.get("BLENDER_USER_SCRIPTS")
                                or os.environ["BLENDER_USER_RESOURCES"])
    check("installed_in_user_folder", installed_at.startswith(user_root), installed_at)
    check("license_included", os.path.isfile(os.path.join(installed_at, "LICENSE")))

    match = re.search(r"-v(\d+\.\d+\.\d+)\.zip$", zip_path)
    version = ".".join(str(v) for v in module.bl_info["version"])
    check("version_matches_zip", match is not None and match.group(1) == version, version)

    check("preferences", addon.preferences.max_vertex_budget > 0)
    check("scene_properties", hasattr(bpy.types.Scene, "smartclip_target_scope"))
    check("operator", hasattr(bpy.ops.view3d, "smartclip_move"))
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("Object Mode")
    items = [k for k in km.keymap_items if k.idname == "view3d.smartclip_move"] if km else []
    check("hotkey", len(items) == 1 and items[0].type == "G" and items[0].shift)

    # A cleared hotkey is remembered in the preferences and stays off when
    # the add-on registers again (as on the next start of Blender).
    def addon_items():
        km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("Object Mode")
        return [k for k in km.keymap_items if k.idname == "view3d.smartclip_move"] if km else []

    bpy.ops.smartclip.clear_hotkeys()
    module.unregister()
    module.register()
    prefs = bpy.context.preferences.addons[MODULE].preferences
    check("cleared_hotkey_stays_off",
          not prefs.hotkeys_enabled and addon_items() and not any(k.active for k in addon_items()))
    bpy.ops.smartclip.add_default_hotkeys()
    check("default_hotkey_restored", prefs.hotkeys_enabled and all(k.active for k in addon_items()))

    # Use Shortcut (the preference) and a key changed in the user keymap, as
    # the preferences' key field does it.  Without a window Blender merges
    # the keymaps only when asked to.
    keyconfigs = bpy.context.window_manager.keyconfigs

    def user_object_mode_item():
        keyconfigs.update()
        items = module.keymap.user_items()
        return items[0][2] if items else None

    kmi = user_object_mode_item()
    if kmi is not None:
        kmi.type = "F"
        keyconfigs.update()     # what the event loop does after an edit in the window
    prefs.hotkeys_enabled = False
    kmi = user_object_mode_item()
    check("use_shortcut_off", kmi is not None and not kmi.active
          and not any(k.active for k in addon_items()))
    prefs.hotkeys_enabled = True
    kmi = user_object_mode_item()
    check("use_shortcut_on_keeps_custom_key", kmi is not None and kmi.active and kmi.type == "F",
          f"{kmi.type if kmi else None}")

    # Switching the add-on off and on (or updating it) keeps the changed key
    bpy.ops.preferences.addon_disable(module=MODULE)
    bpy.ops.preferences.addon_enable(module=MODULE)
    module = sys.modules[MODULE]
    prefs = bpy.context.preferences.addons[MODULE].preferences
    kmi = user_object_mode_item()
    check("reenable_keeps_custom_key", kmi is not None and kmi.active and kmi.type == "F",
          f"{kmi.type if kmi else None}")
    bpy.ops.smartclip.add_default_hotkeys()
    kmi = user_object_mode_item()
    check("reset_shortcut_restores_shift_g", kmi is not None and kmi.active and kmi.type == "G"
          and kmi.shift and not kmi.is_user_modified)

    bpy.ops.preferences.addon_disable(module=MODULE)
    check("disabled_cleanly", not hasattr(bpy.types.Scene, "smartclip_target_scope"))

    try:
        bpy.ops.preferences.addon_remove(module=MODULE)
    except RuntimeError as exc:
        # Blender's operator redraws the Preferences area after deleting the
        # files; there is no area in background mode.
        if "tag_redraw" not in str(exc):
            raise
    check("removed", not os.path.exists(installed_at), installed_at)

    print(f"[install:test] summary: passed={len(checked) - len(failures)} failed={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
