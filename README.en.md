<p align="center">
  <img src="assets/logo.svg" alt="Smart Clipping" width="720">
</p>

# Smart Clipping

[![Release](https://img.shields.io/github/v/release/marc2825/Blender_SmartClip?label=version)](https://github.com/marc2825/Blender_SmartClip/releases/latest)
[![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?logo=blender&logoColor=white)](https://www.blender.org/)
[![License: MIT](https://img.shields.io/github/license/marc2825/Blender_SmartClip)](LICENSE)

[日本語](README.md) | [English](README.en.md)

A Blender add-on that shows guide lines to nearby vertices while you move objects or vertices, and helps you snap to them. It is inspired by [Smart Guides](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3) in PowerPoint.

![A moving object shows a guide line to a nearby vertex and snaps to it](assets/teaser.gif)

> Supports Blender 4.0 and later. Automated tests run on Blender 4.0, 4.2 LTS, and 5.2 LTS.

## Installation

Download `smart_clipping-vX.Y.Z.zip` from [Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest) and load it with **Preferences → Add-ons → Install from Disk** (**Install** on 4.1 and older). Do not unzip it.

When upgrading from 1.1.x or earlier, disable and remove the old version (module `src`) first; enabling both makes their registrations collide. Add-on preferences start from their defaults, while Snap To and other settings saved in `.blend` files carry over.

From 2.0, right click cancels a move, and a vertex within reach is snapped onto exactly without holding a button. To get the gradual pull of 1.x back, set **Snap Behavior** to **Gradual Pull** (sidebar panel > Limits and Display, or the add-on preferences).

## Usage

1. In the 3D Viewport, press N and open the **Smart Clipping** panel in the **Tool** tab.
2. Choose which meshes to snap to with **Snap To**. The default is every visible mesh (Visible Objects).
3. Press `Shift+G` in Object Mode or mesh Edit Mode to start moving. **Move with Guides** in the panel or in the Object / Mesh > Transform menu does the same.
4. When the moving point comes within reach of a vertex (the dashed ring), it snaps onto it. Hold `Ctrl` to move freely.
5. Confirm with left click or `Enter`; cancel with right click or `Esc`. After confirming, correct the move numerically in the **Adjust Last Operation** panel.

While moving, `X` `Y` `Z` constrain to an axis and `Shift` + the key to a plane. `A` switches **Align Only**, which lines up one coordinate with nearby vertices instead of snapping onto them, and `S` switches **Snap To**. The status bar lists these keys during a move.

The interface is in English and Japanese, following **Preferences → Interface → Translation**.

The full list of controls, what the viewport shows during a move, and the settings are in the [guide](docs/details.en.md).

## Notes

- Only mesh vertices are snap targets, taken from the geometry (with modifiers) at the moment the move starts.
- Snap points are limited to **Snap Point Limit** (default 50,000). Beyond it, distant objects are down-sampled or reduced to their bounding-box corners and origin, and the farthest are left out.
- With the checkbox in the panel header off, `Shift+G` goes back to Blender's Select Grouped / Select Similar in that scene.

## Documentation

- [Guide](docs/details.en.md) ([日本語](docs/details.md))
- [Changelog](CHANGELOG.md)
- [Developer guide](docs/DEVELOPMENT.md)
- [Support](SUPPORT.md): questions in [Discussions](https://github.com/marc2825/Blender_SmartClip/discussions), bugs in [Issues](https://github.com/marc2825/Blender_SmartClip/issues)

## Development

Only modules bundled with Blender are used. Tests, CI, and the release process are described in the [developer guide](docs/DEVELOPMENT.md).

```bash
blender --background --factory-startup --python tests/headless_test_runner.py  # tests
python scripts/package_addon.py                                               # build the ZIP
```

Developed with [Claude Code](https://claude.com/product/claude-code) (Anthropic) and [Codex](https://openai.com/codex) (OpenAI).

## License

[MIT License](LICENSE). Copyright (c) 2026 marc2825
