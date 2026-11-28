# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Install the extension ZIP the way a user would (Blender 4.2+) and check that it
works as an extension and keeps its settings.

Usage (the user folders must point somewhere disposable; run both phases with
the same folders, the second one without --factory-startup so that it loads
the preferences the first one saved):

  BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts \\
  BLENDER_USER_CONFIG=/tmp/bl/config BLENDER_USER_EXTENSIONS=/tmp/bl/extensions \\
    blender --background --factory-startup --python tests/extension_install_test.py -- \\
      --phase install dist/snaxis-vX.Y.Z-extension.zip
  (same variables) blender --background --python tests/extension_install_test.py -- \\
      --phase reload dist/snaxis-vX.Y.Z-extension.zip

install: installs the extension into the "User Default" repository with
  Install from Disk's operator, checks that it registers under its bl_ext
  name (its keymap item in the 3D View keymap), changes every preference and
  the key, and saves the preferences.
reload: checks the extension came back enabled with the saved preferences and
  key, then switches it off (nothing left registered) and on, uninstalls it,
  and installs it again.  It ends with the extension enabled on default
  preferences and key, saved, for the headless suite and the UI test to run
  against (--module / SMARTCLIP_UI_MODULE).

Exit code 0 = every check passed.
"""

import os
import re
import sys
import traceback

import bpy

PKG_ID = "snaxis"                    # the extension's id
REPO = "user_default"
EXTENSION = f"bl_ext.{REPO}.{PKG_ID}"
MOVE = "view3d.smartclip_move"
SCENE_PROPS = ("smartclip_enabled", "smartclip_target_scope", "smartclip_target_collection",
               "smartclip_align_x", "smartclip_align_y", "smartclip_align_z")
# A value other than the default for every preference
CUSTOM_PREFS = {
    "snap_behavior": "PULL",
    "snap_distance_px": 23,
    "max_vertex_budget": 12345,
    "search_backend": "KDTREE",
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


# --- What is registered ----------------------------------------------------

def enabled():
    return EXTENSION in bpy.context.preferences.addons


def addon_items():
    """``[(keymap name, kmi), ...]``: the move's items in the add-on keyconfig."""
    kc = bpy.context.window_manager.keyconfigs.addon
    found = []
    for km in (kc.keymaps if kc else ()):
        found += [(km.name, k) for k in km.keymap_items if k.idname == MOVE]
    return found


def user_item():
    """The item as the user keymap has it (where a changed key lives)."""
    keyconfigs = bpy.context.window_manager.keyconfigs
    keyconfigs.update()
    km = keyconfigs.user.keymaps.get("3D View")
    for kmi in km.keymap_items if km else ():
        if kmi.idname == MOVE:
            return km, kmi
    return None, None


def operator_registered():
    try:
        return bpy.ops.view3d.smartclip_move.get_rna_type() is not None
    except (AttributeError, KeyError):
        return False


def translated():
    """Whether the add-on's own words come out in Japanese (its translations are on)."""
    view = bpy.context.preferences.view
    saved = (view.language, view.use_translate_interface)
    try:
        view.language = "ja_JP"
        view.use_translate_interface = True
        if bpy.app.translations.locale != "ja_JP":
            return None             # this Blender cannot switch language
        return bpy.app.translations.pgettext_iface("Snap Point Limit") != "Snap Point Limit"
    finally:
        view.language, view.use_translate_interface = saved


def registered_state():
    return {
        "operator": operator_registered(),
        "panels": [n for n in ("SMARTCLIP_PT_panel", "SMARTCLIP_PT_limits") if hasattr(bpy.types, n)],
        "scene_props": [p for p in SCENE_PROPS if p in bpy.types.Scene.bl_rna.properties],
        "keymap_items": [(name, k.type, k.shift, k.active) for name, k in addon_items()],
        "translated": translated(),
    }


def check_registered(prefix):
    state = registered_state()
    check(f"{prefix}_operator", state["operator"])
    check(f"{prefix}_panels", len(state["panels"]) == 2, str(state["panels"]))
    check(f"{prefix}_scene_properties", state["scene_props"] == list(SCENE_PROPS),
          str(state["scene_props"]))
    check(f"{prefix}_keymap_item", state["keymap_items"] == [("3D View", "F", True, True)],
          str(state["keymap_items"]))
    if state["translated"] is None:
        print(f"[SKIP] {prefix}_translations (this Blender cannot switch to Japanese)")
    else:
        check(f"{prefix}_translations", state["translated"])


def check_nothing_registered(prefix):
    state = registered_state()
    check(f"{prefix}_nothing_registered",
          not state["operator"] and not state["panels"] and not state["scene_props"]
          and not state["keymap_items"] and not state["translated"], str(state))


def prefs():
    addon = bpy.context.preferences.addons.get(EXTENSION)
    return addon.preferences if addon else None


def prefs_values(p):
    out = {}
    for name in CUSTOM_PREFS:
        value = getattr(p, name)
        out[name] = tuple(round(v, 4) for v in value) if hasattr(value, "__len__") \
            and not isinstance(value, str) else value
    return out


def expected_custom():
    return {k: tuple(round(v, 4) for v in val) if isinstance(val, tuple) else val
            for k, val in CUSTOM_PREFS.items()}


# --- Installing and removing -----------------------------------------------

def repo_index():
    for i, repo in enumerate(bpy.context.preferences.extensions.repos):
        if repo.module == REPO:
            return i
    raise RuntimeError(f"no extension repository {REPO!r}")


def install(zip_path):
    return bpy.ops.extensions.package_install_files(
        filepath=zip_path, repo=REPO, enable_on_install=True)


def uninstall():
    return bpy.ops.extensions.package_uninstall(repo_index=repo_index(), pkg_id=PKG_ID)


# --- Phases ----------------------------------------------------------------

def phase_install(ext_zip):
    install(ext_zip)
    check("extension_enabled", enabled(),
          str([a.module for a in bpy.context.preferences.addons]))
    module = sys.modules.get(EXTENSION)
    check("extension_module_loaded", module is not None)
    if module is None:
        return
    check("no_top_level_module", "smart_clipping" not in sys.modules and PKG_ID not in sys.modules)
    installed_at = os.path.dirname(os.path.abspath(module.__file__))
    check("installed_in_user_repository",
          installed_at.startswith(os.path.abspath(bpy.utils.user_resource("EXTENSIONS"))),
          installed_at)
    check("license_installed", os.path.isfile(os.path.join(installed_at, "LICENSE")))
    check("manifest_installed", os.path.isfile(os.path.join(installed_at, "blender_manifest.toml")))
    check("submodules_in_own_namespace",
          all(name.startswith(EXTENSION) for name in sys.modules
              if name.rsplit(".", 1)[-1] in ("ops", "detector", "drawing", "hud", "i18n",
                                              "keymap", "prefs", "utils")
              and ("smart_clipping" in name or PKG_ID in name)),
          str(sorted(n for n in sys.modules if "smart_clipping" in n or PKG_ID in n)))
    check_registered("extension")
    p = prefs()
    check("extension_preferences", p is not None and p.max_vertex_budget > 0)
    check("preferences_module_name", module.prefs.ADDON_MODULE_NAME == EXTENSION,
          str(module.prefs.ADDON_MODULE_NAME))
    match = re.search(r"^snaxis-v(\d+\.\d+\.\d+)-extension\.zip$", os.path.basename(ext_zip))
    with open(os.path.join(installed_at, "blender_manifest.toml"), encoding="utf-8") as f:
        manifest_version = re.search(r'^version = "([^"]+)"', f.read(), re.M)
    check("version_matches_zip", match is not None and manifest_version is not None
          and match.group(1) == manifest_version.group(1),
          manifest_version.group(1) if manifest_version else "")

    # Every preference and the key changed (as a user does in the
    # preferences), then saved with the preferences
    for name, value in CUSTOM_PREFS.items():
        setattr(p, name, value)
    _km, kmi = user_item()
    if kmi is not None:
        kmi.type = "J"
        bpy.context.window_manager.keyconfigs.update()
    check("preferences_changed", prefs_values(p) == expected_custom(), str(prefs_values(p)))
    _km, kmi = user_item()
    check("key_changed", kmi is not None and kmi.type == "J", str(kmi.type if kmi else None))
    bpy.ops.wm.save_userpref()


def phase_reload(ext_zip):
    check("extension_enabled_after_restart", enabled())
    if sys.modules.get(EXTENSION) is None:
        return
    check_registered("after_restart")
    p = prefs()
    check("preferences_saved_and_loaded", prefs_values(p) == expected_custom(), str(prefs_values(p)))
    _km, kmi = user_item()
    check("key_saved_and_loaded", kmi is not None and kmi.type == "J",
          str(kmi.type if kmi else None))

    # Off and on again
    bpy.ops.preferences.addon_disable(module=EXTENSION)
    check_nothing_registered("disabled")
    bpy.ops.preferences.addon_enable(module=EXTENSION)
    check_registered("enabled_again")

    # Uninstalled, then installed again
    uninstall()
    ext_dir = os.path.join(bpy.utils.user_resource("EXTENSIONS"), REPO, PKG_ID)
    check("uninstalled", not os.path.exists(ext_dir), ext_dir)
    check_nothing_registered("uninstalled")
    install(ext_zip)
    check("reinstalled", enabled())
    check_registered("reinstalled")
    p = prefs()
    check("reinstalled_preferences_default",
          p is not None and not any(p.is_property_set(n) for n in CUSTOM_PREFS))

    # Back to the default key for the runs that follow (the test does this,
    # as a user would with the restore button; the add-on never does)
    km, kmi = user_item()
    if kmi is not None and kmi.is_user_modified:
        km.restore_item_to_default(kmi)
    _km, kmi = user_item()
    check("key_back_to_default", kmi is not None and kmi.type == "F" and kmi.shift,
          str(kmi.type if kmi else None))
    bpy.ops.wm.save_userpref()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 3 or argv[0] != "--phase" or argv[1] not in ("install", "reload"):
        print("usage: ... --python tests/extension_install_test.py -- "
              "--phase install|reload EXTENSION.zip")
        return 2
    phase, ext_zip = argv[1], os.path.abspath(argv[2])
    if not all(os.environ.get(v) for v in ("BLENDER_USER_RESOURCES", "BLENDER_USER_CONFIG",
                                           "BLENDER_USER_SCRIPTS", "BLENDER_USER_EXTENSIONS")):
        print("refusing to run: set BLENDER_USER_RESOURCES / _CONFIG / _SCRIPTS / _EXTENSIONS "
              "to a disposable folder so the real user folders are not touched")
        return 2
    if bpy.app.version < (4, 2, 0):
        print(f"extensions need Blender 4.2 or later, this is {bpy.app.version_string}")
        return 2

    (phase_install if phase == "install" else phase_reload)(ext_zip)
    print(f"[extension:test] {phase}: passed={len(_checked) - len(_failures)} "
          f"failed={len(_failures)}")
    return 1 if _failures or not _checked else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
