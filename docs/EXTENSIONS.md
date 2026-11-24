# Blender Extensions submission

What goes to [extensions.blender.org](https://extensions.blender.org/) for Snaxis (formerly Smart Clipping), checked against the platform's rules, and how to submit it. Work tracked in [#38](https://github.com/marc2825/Snaxis/issues/38).

**Status: not submitted yet.** Do not describe Snaxis as available on the platform until the listing is approved.

## Package

Upload `snaxis-vX.Y.Z-extension.zip` from the GitHub release (the same file `python scripts/package_addon.py` builds; check it against the `.sha256` next to it). The site reads these from its `blender_manifest.toml`; to change them, change the manifest and upload a new version:

| Field | Value |
|---|---|
| Name | Snaxis |
| Id | `snaxis` (permanent once listed) |
| Tagline | Smart guides that snap moves to nearby vertices |
| Type | Add-on |
| Tags | 3D View, Modeling, Mesh |
| Blender | 4.2.0 and later (4.0 / 4.1: the legacy ZIP on GitHub) |
| License | GPL-3.0-or-later |
| Copyright | 2026 marc2825 |
| Website | https://github.com/marc2825/Snaxis |
| Permissions | None (no files, network, clipboard, camera or microphone) |

## Listing text

Paste into the description field (Markdown). It describes only what the current version does.

```markdown
Snaxis (formerly Smart Clipping) shows guide lines to nearby vertices while you move objects or vertices in the 3D Viewport, and snaps exactly onto them — like the smart guides in PowerPoint, for lining things up by eye without typing coordinates.

### Features

- **Snap to vertices**: when the moving point comes within reach of a vertex, a guide line appears and the point lands exactly on it.
- **Line up one coordinate**: match only X, Y or Z to a nearby vertex (`A` while moving switches off → X → Y → Z).
- **Axis and plane constraints**: `X` / `Y` / `Z` (with `Shift` for a plane), as in Blender's own move. A snap point the constrained move cannot reach is labeled "Projected" with the remaining distance.
- **Object Mode and Edit Mode**: moves the selected objects (the active object's origin snaps) or the selected vertices (their median snaps).
- **Choose what to snap to**: the same mesh, selected objects, everything visible, or a collection (`S` while moving).
- **Snap Behavior**: Snap Exactly (default) or Gradual Pull.
- Interface in English and Japanese.

### Quick start

1. Select an object or vertices and press `Shift+G` (or Object / Mesh menu > Transform > Move with Guides).
2. Move the mouse: guide lines appear near vertices, and the point snaps onto them.
3. Left click or `Enter` confirms, right click or `Esc` cancels. Hold `Ctrl` to move without snapping.

Settings: Sidebar (`N`) > Tool > Snaxis, and the add-on preferences.

### Good to know

- `Shift+G` is used instead of Select Grouped (Object Mode) and Select Similar (Edit Mode); both stay in the Select menu. The add-on preferences show what the key takes over, and the key can be changed or turned off there.
- Snap points are mesh vertices, with modifiers. In very large scenes their number is capped (Snap Point Limit, 50,000 by default): distant objects are thinned out and the panel says so.
- Do not enable it together with the legacy add-on version from GitHub (also when it is still named Smart Clipping): the second one refuses to start and says which one is on.

Documentation, source code and issue tracker: https://github.com/marc2825/Snaxis
```

**Version notes** (if the upload form asks for them), for 2.1.1:

```markdown
First release on the platform. Formerly called Smart Clipping, with the same features as its legacy add-on on GitHub; enabling the extension and the legacy add-on together is refused with a message.
```

## Media

In [assets/listing/](../assets/listing/), made from the actual interface of Blender 5.3.0 with this version (`tests/record_teaser.py`; the images are not part of the extension package):

| File | Size | Use |
|---|---|---|
| `icon.png` (source `icon.svg`) | 256 × 256 | Icon |
| `featured.png` | 1920 × 1080 | Featured image / thumbnail |
| `screenshot-1-snap-to-vertex.png` | 1920 × 1080 | Preview: a vertex snapped onto a corner of another box |
| `screenshot-2-align-x-with-other-box.png` | 1920 × 1080 | Preview: Align Only X with the X constraint, lined up with the tall box |
| `screenshot-3-align-x-with-own-mesh.png` | 1920 × 1080 | Preview: the same, lined up with a vertex of its own mesh |
| `demo.mp4` | 1920 × 1080, 17 s, 0.8 MB | Preview video, if the form takes one |

The platform's upload form (behind Blender ID sign-in) was not available when these were made, so its exact requirements are not known here. Published listings show 16:9 preview images (1920 × 1080 with 640 × 360 thumbnails), which these follow. If the form asks for other sizes, re-export from the same sources. The moderation guidelines discourage heavy GIFs in the description, so `assets/teaser.gif` is not used there.

None of the images shows the Blender logo (terms 2.2). The Blender interface itself appears in the screenshots, as in other listings.

## Check against the platform's rules

Sources: [terms of service](https://extensions.blender.org/terms-of-service/) (last updated 10 August 2026), [manifest schema 1.0.0](https://developer.blender.org/docs/features/extensions/schema/1.0.0/), [moderation guidelines](https://developer.blender.org/docs/features/extensions/moderation/guidelines/), [Getting started](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html), [Licenses](https://docs.blender.org/manual/en/latest/advanced/extensions/licenses.html). "Required" are rules the pages state as must / not allowed; "guideline" are what they recommend or what moderators check.

| Rule | Kind | Status |
|---|---|---|
| GPL v3 or later for the whole add-on (terms 1.1) | Required | Met: `LICENSE` is GPL v3, every source has `SPDX-License-Identifier: GPL-3.0-or-later`, the manifest says `SPDX:GPL-3.0-or-later` |
| Bundled assets (images, SVG, fonts) CC0 (1.2) | Required | Met: the package holds only Python files, the manifest and `LICENSE` |
| Copyright holders of bundled code credited in the manifest (1.3) | Required | Met: one author, `copyright = ["2026 marc2825"]`; no third-party code ([#20](https://github.com/marc2825/Snaxis/issues/20)) |
| No "Blender" in the name (2.1); no Blender logo in icon, thumbnails, previews (2.2); no false impression of endorsement (2.3) | Required | Met. The description mentions PowerPoint only as a comparison, with no logo |
| Description that says everything it does (3.1) | Required | Met: the listing text above, checked against the current version |
| Fully functional, documented, maintained (3.3) | Required | Met: guide, issue tracker, CI |
| No obfuscated code or byte code; Python only, no pre-compiled packages (3.5, 3.6) | Required | Met |
| No negative impact on Blender's performance or stability (3.7) | Required | Met as far as tested: the add-on does work only during a move, and the snap point limit bounds it on large scenes |
| Does not tamper with other extensions, the OS or user data (3.9) | Required | Met: it never disables or edits another add-on. When the legacy copy is on, the extension stops its own registration and leaves the other copy alone |
| No extra requirements, paid content or registration (3.10); no ads, donation or purchase links in the UI (6.1–6.3) | Required | Met: the UI has no links of that kind (`bl_info` keeps a documentation and tracker link for the legacy add-on, which Blender ignores in an extension) |
| Network permission and `bpy.app.online_access` (4.x); self-contained, no remote code (5.1–5.3) | Required | Met: no network access, no downloads, no dependency on other extensions |
| Manifest: required fields, no empty values, tagline ≤ 64 characters without end punctuation, `blender_version_min` ≥ 4.2.0, valid tags | Required | Met: `blender --command extension validate` passes on 4.2.23, 5.2.4 and 5.3.0, and `tests/package_test.py` checks the rest |
| No optional manifest fields left at their defaults; permissions only when used | Guideline | Met: only fields with content; no `permissions` |
| No auto-updater; no pip installs at run time | Guideline (required) | Met |
| `keyconfigs.addon` may be None in background mode | Guideline (required) | Met: `keymap.register_keymaps()` returns when it is None |
| Preferences by `__package__`, not `__name__`; no literal `bl_ext` / repository names | Guideline (required) | Met: `prefs.ADDON_MODULE_NAME = __package__`; translations registered under `__package__` |
| `sys` read-only; no module loading tricks | Guideline (required) | Met for the extension: the legacy add-on's clean-up of its own old submodules (`__init__.py`, [#23](https://github.com/marc2825/Snaxis/issues/23)) runs only as a top-level module, never in an extension |
| No writing into the add-on's folder; `extension_path_user` for files | Guideline (required) | Met: it writes no files |
| `bl_info` | Guideline (the manual's conversion steps remove it) | Kept for the legacy add-on (Blender 4.0 / 4.1). Blender ignores it in an extension and only mentions it with `--debug-python` |
| Keymap conflicts | Not covered by the rules | `Shift+G` replaces Select Grouped / Select Similar; the preferences say so under the key, the key can be changed or turned off, and the listing and README say it. No change needed for review |

**Outside the rules, still open** ([#21](https://github.com/marc2825/Snaxis/issues/21), a technical screening, not a formal freedom-to-operate opinion): US11204679B1 (Adobe, US only, active) comes close in one configuration and should be checked by a professional before distributing with a US focus. The rename to Snaxis (2.1.1) moves away from the US trademark SMARTCLIP (registration 7700431) that #21 noted; "Snaxis" itself has not been searched in the trademark registers (USPTO, J-PlatPat): a web search found no product of that name, only the company name Synaxis in unrelated fields. Neither blocks the submission under the platform's rules.

## Submitting (the owner)

1. Push the `v2.1.1` tag (or have it pushed) so the release workflow publishes both ZIPs; it runs the UI tests on the source and on the installed extension first.
2. Download `snaxis-v2.1.1-extension.zip` and its `.sha256` from the release and check the checksum (`sha256sum -c snaxis-v2.1.1-extension.sha256`, or `Get-FileHash` on Windows).
3. Optionally drag the ZIP into Blender 4.2 or later and try a move once.
4. Sign in at https://extensions.blender.org/ with your Blender ID (create one at https://id.blender.org/ if needed). The account should be the one that will maintain the listing (guideline: the uploader is the owner / maintainer).
5. Open https://extensions.blender.org/submit/ and upload the ZIP. The site reads the name, tagline, version, tags, license and website from the manifest.
6. On the draft page, paste the [listing text](#listing-text), add the [media](#media) (icon, featured image, screenshots, optionally the video), and set the support / issue link to https://github.com/marc2825/Snaxis/issues if asked.
7. Submit for review. The extension shows as "Awaiting Review" in the [approval queue](https://extensions.blender.org/approval-queue/); moderators comment there.
8. If they ask for changes ("Awaiting Changes"): fix them here, release a new patch version (2.1.1) the same way, and upload that ZIP as a new version of the same extension.
9. After approval: update the README's installation steps to point to the platform (Get Extensions), then announce it.
