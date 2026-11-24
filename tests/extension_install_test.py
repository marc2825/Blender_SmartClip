# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Install the extension ZIP the way a user would (Blender 4.2+) and check that it
works as an extension, keeps its settings, and coexists safely with the legacy
add-on.

Usage (the user folders must point somewhere disposable; run both phases with
the same folders, the second one without --factory-startup so that it loads
the preferences the first one saved):

  BLENDER_USER_RESOURCES=/tmp/bl BLENDER_USER_SCRIPTS=/tmp/bl/scripts \\
  BLENDER_USER_CONFIG=/tmp/bl/config BLENDER_USER_EXTENSIONS=/tmp/bl/extensions \\
    blender --background --factory-startup --python tests/extension_install_test.py -- \\
      --phase install dist/snaxis-vX.Y.Z-extension.zip dist/snaxis-vX.Y.Z.zip
  (same variables) blender --background --python tests/extension_install_test.py -- \\
      --phase reload dist/snaxis-vX.Y.Z-extension.zip dist/snaxis-vX.Y.Z.zip

install: installs the extension into the "User Default" repository with
  Install from Disk's operator, checks that it registers under its bl_ext
  name, changes every preference and the key, saves the preferences.  Then
  installs the legacy ZIP and tries to enable it: it must refuse, and the
  extension must stay intact through the legacy copy being disabled and removed.
reload: checks the extension came back enabled with the saved preferences and
  key, then the other order: the legacy add-on on first, the extension refused,
  uninstalled, and installed again once the legacy add-on is gone.  It ends
  with the extension enabled on default preferences, saved, for the headless
  suite to run against (tests/headless_test_runner.py --module ...).

Exit code 0 = every check passed.
"""

import os
import re
import sys
import traceback

import bpy

LEGACY = "smart_clipping"            # the legacy add-on's module (its name as Smart Clipping)
PKG_ID = "snaxis"                    # the extension's id
REPO = "user_default"
EXTENSION = f"bl_ext.{REPO}.{PKG_ID}"
COPIES = (LEGACY, PKG_ID)            # last part of a copy's module name
MOVE = "view3d.smartclip_move"
SCENE_PROPS = ("smartclip_enabled", "smartclip_target_scope", "smartclip_target_collection",
               "smartclip_align_x", "smartclip_align_y", "smartclip_align_z")
# A value other than the default for every preference
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


# --- What is registered, and by whom -------------------------------------

def owner():
    panel = getattr(bpy.types, "SMARTCLIP_PT_panel", None)
    return getattr(panel, "__module__", None)


def enabled_copies():
    return sorted(a.module for a in bpy.context.preferences.addons
                  if a.module.rsplit(".", 1)[-1] in COPIES)


def addon_items():
    kc = bpy.context.window_manager.keyconfigs.addon
    found = []
    for name in ("Object Mode", "Mesh"):
        km = kc.keymaps.get(name) if kc else None
        found += [k for k in km.keymap_items if k.idname == MOVE] if km else []
    return found


def user_item():
    """The Object Mode item as the user keymap has it (where a changed key lives)."""
    keyconfigs = bpy.context.window_manager.keyconfigs
    keyconfigs.update()
    km = keyconfigs.user.keymaps.get("Object Mode")
    for kmi in km.keymap_items if km else ():
        if kmi.idname == MOVE:
            return kmi
    return None


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
    """Everything one copy registers, to compare before and after."""
    return {
        "owner": owner(),
        "operator": operator_registered(),
        "panels": [n for n in ("SMARTCLIP_PT_panel", "SMARTCLIP_PT_limits") if hasattr(bpy.types, n)],
        "scene_props": [p for p in SCENE_PROPS if p in bpy.types.Scene.bl_rna.properties],
        "keymap_items": [(k.type, k.shift, k.active) for k in addon_items()],
        "translated": translated(),
    }


def check_registered_by(prefix, module):
    state = registered_state()
    check(f"{prefix}_owner", state["owner"] == module, str(state["owner"]))
    check(f"{prefix}_operator", state["operator"])
    check(f"{prefix}_panels", len(state["panels"]) == 2, str(state["panels"]))
    check(f"{prefix}_scene_properties", state["scene_props"] == list(SCENE_PROPS),
          str(state["scene_props"]))
    check(f"{prefix}_keymap_items", len(state["keymap_items"]) == 2, str(state["keymap_items"]))
    if state["translated"] is None:
        print(f"[SKIP] {prefix}_translations (this Blender cannot switch to Japanese)")
    else:
        check(f"{prefix}_translations", state["translated"])
    return state


def check_nothing_registered(prefix):
    state = registered_state()
    check(f"{prefix}_nothing_registered",
          state["owner"] is None and not state["operator"] and not state["panels"]
          and not state["scene_props"] and not state["keymap_items"]
          and not state["translated"], str(state))


def prefs_of(module):
    addon = bpy.context.preferences.addons.get(module)
    return addon.preferences if addon else None


def prefs_values(prefs):
    out = {}
    for name in CUSTOM_PREFS:
        value = getattr(prefs, name)
        out[name] = tuple(round(v, 4) for v in value) if hasattr(value, "__len__") \
            and not isinstance(value, str) else value
    return out


def expected_custom():
    return {k: tuple(round(v, 4) for v in val) if isinstance(val, tuple) else val
            for k, val in CUSTOM_PREFS.items()}


# --- Installing, enabling, removing --------------------------------------

def repo_index():
    for i, repo in enumerate(bpy.context.preferences.extensions.repos):
        if repo.module == REPO:
            return i
    raise RuntimeError(f"no extension repository {REPO!r}")


def install_extension(zip_path):
    return bpy.ops.extensions.package_install_files(
        filepath=zip_path, repo=REPO, enable_on_install=True)


def uninstall_extension():
    return bpy.ops.extensions.package_uninstall(repo_index=repo_index(), pkg_id=PKG_ID)


def install_legacy(zip_path):
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)


def remove_legacy():
    try:
        bpy.ops.preferences.addon_remove(module=LEGACY)
    except RuntimeError as exc:
        # Blender's operator redraws the Preferences area after deleting the
        # files; there is no area in background mode.
        if "tag_redraw" not in str(exc):
            raise


def try_enable(module):
    """Enable like the checkbox does; returns the error message, or None."""
    try:
        bpy.ops.preferences.addon_enable(module=module)
    except RuntimeError as exc:
        return str(exc)
    return None


def save_preferences():
    bpy.ops.wm.save_userpref()


def legacy_dir():
    return os.path.join(bpy.utils.user_resource("SCRIPTS", path="addons"), LEGACY)


# --- Phases ----------------------------------------------------------------

def phase_install(ext_zip, legacy_zip):
    # Installed and enabled as an extension, under its bl_ext name
    install_extension(ext_zip)
    check("extension_enabled", enabled_copies() == [EXTENSION], str(enabled_copies()))
    module = sys.modules.get(EXTENSION)
    check("extension_module_loaded", module is not None)
    if module is None:
        return
    check("no_top_level_module", LEGACY not in sys.modules)
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
              and (LEGACY in name or PKG_ID in name)),
          str(sorted(n for n in sys.modules if LEGACY in n or PKG_ID in n)))
    check_registered_by("extension", EXTENSION)
    prefs = prefs_of(EXTENSION)
    check("extension_preferences", prefs is not None and prefs.max_vertex_budget > 0)
    check("preferences_module_name", module.prefs.ADDON_MODULE_NAME == EXTENSION,
          str(module.prefs.ADDON_MODULE_NAME))
    match = re.search(r"^snaxis-v(\d+\.\d+\.\d+)-extension\.zip$", os.path.basename(ext_zip))
    with open(os.path.join(installed_at, "blender_manifest.toml"), encoding="utf-8") as f:
        manifest_version = re.search(r'^version = "([^"]+)"', f.read(), re.M)
    check("version_matches_zip", match is not None and manifest_version is not None
          and match.group(1) == manifest_version.group(1),
          manifest_version.group(1) if manifest_version else "")

    # Every preference and the key changed, then saved with the preferences
    for name, value in CUSTOM_PREFS.items():
        setattr(prefs, name, value)
    kmi = user_item()
    if kmi is not None:
        kmi.type = "F"
        bpy.context.window_manager.keyconfigs.update()
    check("preferences_changed", prefs_values(prefs) == expected_custom(), str(prefs_values(prefs)))
    kmi = user_item()
    check("key_changed", kmi is not None and kmi.type == "F", str(kmi.type if kmi else None))

    # The legacy add-on next to it: enabling it must refuse and leave the
    # extension as it was
    before = registered_state()
    install_legacy(legacy_zip)
    error = try_enable(LEGACY)
    check("legacy_refused_while_extension_on",
          error is not None and "already enabled" in error and EXTENSION in error, str(error))
    check("legacy_not_enabled", enabled_copies() == [EXTENSION], str(enabled_copies()))
    check("extension_untouched_by_refused_legacy", registered_state() == before,
          f"{registered_state()} != {before}")
    check("extension_preferences_untouched", prefs_values(prefs_of(EXTENSION)) == expected_custom())
    bpy.ops.preferences.addon_disable(module=LEGACY)
    check("extension_untouched_by_disabling_legacy", registered_state() == before)
    remove_legacy()
    check("legacy_removed", not os.path.exists(legacy_dir()), legacy_dir())
    check("extension_untouched_by_removing_legacy", registered_state() == before)

    save_preferences()


def phase_reload(ext_zip, legacy_zip):
    # Enabled again at start-up, with the saved preferences and key
    check("extension_enabled_after_restart", enabled_copies() == [EXTENSION], str(enabled_copies()))
    module = sys.modules.get(EXTENSION)
    if module is None:
        return
    check_registered_by("after_restart", EXTENSION)
    prefs = prefs_of(EXTENSION)
    check("preferences_saved_and_loaded", prefs_values(prefs) == expected_custom(),
          str(prefs_values(prefs)))
    kmi = user_item()
    check("key_saved_and_loaded", kmi is not None and kmi.type == "F",
          str(kmi.type if kmi else None))
    check("use_shortcut_saved_and_loaded",
          all(not active for _t, _s, active in registered_state()["keymap_items"]))

    # Scene settings live in the .blend file and carry over to the other copy
    scene = bpy.context.scene
    scene.smartclip_target_scope = "SELECTED"
    scene.smartclip_align_x = True

    # Switching to the legacy add-on: the extension off first
    bpy.ops.preferences.addon_disable(module=EXTENSION)
    check_nothing_registered("extension_disabled")
    install_legacy(legacy_zip)
    error = try_enable(LEGACY)
    check("legacy_enabled_after_extension_off", error is None and enabled_copies() == [LEGACY],
          f"{error} {enabled_copies()}")
    before = check_registered_by("legacy", LEGACY)
    check("scene_settings_carry_over",
          scene.smartclip_target_scope == "SELECTED" and scene.smartclip_align_x,
          f"{scene.smartclip_target_scope} {scene.smartclip_align_x}")
    legacy_prefs = prefs_of(LEGACY)
    defaults = {name: legacy_prefs.bl_rna.properties[name] for name in CUSTOM_PREFS}
    check("legacy_preferences_start_from_defaults",
          all(not legacy_prefs.is_property_set(name) for name in defaults),
          str([name for name in defaults if legacy_prefs.is_property_set(name)]))
    # A changed key belongs to the copy it was set in: the other copy starts
    # from Shift+G (the docs ask users to set it again after switching)
    kmi = user_item()
    check("key_starts_from_default_in_other_copy", kmi is not None and kmi.type == "G",
          str(kmi.type if kmi else None))

    # The extension refused while the legacy add-on is on
    error = try_enable(EXTENSION)
    check("extension_refused_while_legacy_on",
          error is not None and "already enabled" in error and LEGACY in error, str(error))
    check("extension_not_enabled", enabled_copies() == [LEGACY], str(enabled_copies()))
    check("legacy_untouched_by_refused_extension", registered_state() == before,
          f"{registered_state()} != {before}")
    uninstall_extension()
    ext_dir = os.path.join(bpy.utils.user_resource("EXTENSIONS"), REPO, PKG_ID)
    check("extension_uninstalled", not os.path.exists(ext_dir), ext_dir)
    check("legacy_untouched_by_uninstalling_extension", registered_state() == before)

    # Back to the extension once the legacy add-on is gone
    bpy.ops.preferences.addon_disable(module=LEGACY)
    check_nothing_registered("legacy_disabled")
    remove_legacy()
    install_extension(ext_zip)
    check("extension_reinstalled", enabled_copies() == [EXTENSION], str(enabled_copies()))
    check_registered_by("reinstalled", EXTENSION)
    prefs = prefs_of(EXTENSION)
    check("reinstalled_preferences_default",
          prefs is not None and not any(prefs.is_property_set(n) for n in CUSTOM_PREFS))
    bpy.ops.smartclip.add_default_hotkeys()
    kmi = user_item()
    check("reinstalled_shortcut_default", kmi is not None and kmi.type == "G" and kmi.active,
          str(kmi.type if kmi else None))
    save_preferences()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 4 or argv[0] != "--phase" or argv[1] not in ("install", "reload"):
        print("usage: ... --python tests/extension_install_test.py -- "
              "--phase install|reload EXTENSION.zip LEGACY.zip")
        return 2
    phase, ext_zip, legacy_zip = argv[1], os.path.abspath(argv[2]), os.path.abspath(argv[3])
    if not all(os.environ.get(v) for v in ("BLENDER_USER_RESOURCES", "BLENDER_USER_CONFIG",
                                           "BLENDER_USER_SCRIPTS", "BLENDER_USER_EXTENSIONS")):
        print("refusing to run: set BLENDER_USER_RESOURCES / _CONFIG / _SCRIPTS / _EXTENSIONS "
              "to a disposable folder so the real user folders are not touched")
        return 2
    if bpy.app.version < (4, 2, 0):
        print(f"extensions need Blender 4.2 or later, this is {bpy.app.version_string}")
        return 2

    (phase_install if phase == "install" else phase_reload)(ext_zip, legacy_zip)
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
