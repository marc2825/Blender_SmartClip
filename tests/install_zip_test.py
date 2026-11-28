# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Install the legacy release ZIP the way a user would and check that the add-on works.

Usage (the user folders must point somewhere disposable):
  BLENDER_USER_SCRIPTS=/tmp/bl/scripts BLENDER_USER_CONFIG=/tmp/bl/config \\
  BLENDER_USER_RESOURCES=/tmp/bl \\
    blender --background --factory-startup --python tests/install_zip_test.py -- \\
      dist/snaxis-vX.Y.Z.zip

Updating over an older version is checked across a restart, as users are
told to do, by tests/upgrade_settings_test.py.

Exit code 0 = installed, enabled, registered, disabled and removed cleanly.
"""

import os
import re
import sys
import traceback

import bpy

MODULE = "smart_clipping"
MOVE = "view3d.smartclip_move"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 1:
        print("usage: ... --python tests/install_zip_test.py -- PATH/TO/snaxis-vX.Y.Z.zip")
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
    check("no_manifest", not os.path.exists(os.path.join(installed_at, "blender_manifest.toml")))

    match = re.search(r"-v(\d+\.\d+\.\d+)\.zip$", zip_path)
    version = ".".join(str(v) for v in module.bl_info["version"])
    check("version_matches_zip", match is not None and match.group(1) == version, version)

    check("preferences", addon.preferences.max_vertex_budget > 0)
    check("scene_properties", hasattr(bpy.types.Scene, "smartclip_target_scope"))
    check("operator", hasattr(bpy.ops.view3d, "smartclip_move"))

    # The add-on's own keymap item: Shift+F in the 3D View keymap, nothing else
    def addon_items():
        found = []
        for km in bpy.context.window_manager.keyconfigs.addon.keymaps:
            found += [(km.name, k) for k in km.keymap_items if k.idname == MOVE]
        return found

    items = addon_items()
    check("hotkey", len(items) == 1 and items[0][0] == "3D View" and items[0][1].type == "F"
          and items[0][1].shift and not items[0][1].ctrl and not items[0][1].alt,
          str([(name, k.type, k.shift) for name, k in items]))

    # A key changed in the user keymap (as the preferences' key field does it)
    # is Blender's to keep: it survives switching the add-on off and on.
    keyconfigs = bpy.context.window_manager.keyconfigs

    def user_item():
        keyconfigs.update()     # what the event loop does after an edit in the window
        found = module.keymap.user_item()
        return found[1] if found else None

    kmi = user_item()
    if kmi is not None:
        kmi.type = "J"
        keyconfigs.update()
    bpy.ops.preferences.addon_disable(module=MODULE)
    check("disabled_cleanly", not hasattr(bpy.types.Scene, "smartclip_target_scope")
          and not addon_items())
    bpy.ops.preferences.addon_enable(module=MODULE)
    module = sys.modules[MODULE]
    kmi = user_item()
    check("reenable_keeps_custom_key", kmi is not None and kmi.active and kmi.type == "J",
          f"{kmi.type if kmi else None}")

    bpy.ops.preferences.addon_disable(module=MODULE)
    check("disabled_again", not hasattr(bpy.types.Scene, "smartclip_target_scope"))

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
