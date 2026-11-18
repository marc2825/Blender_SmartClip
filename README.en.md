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

When upgrading from 1.1.x or earlier, disable and remove the old version (module `src`) first; enabling both makes their registrations collide. Add-on preferences start from their defaults, while Target Scope and other settings saved in `.blend` files carry over.

## Usage

1. In the 3D Viewport, press N and open the **Smart Clipping** panel in the **Tool** tab.
2. Choose which meshes to snap to with **Target Scope**. The default is every visible mesh.
3. Press `Shift+G` in Object Mode or mesh Edit Mode to start moving.
4. Close to a candidate vertex, the selection is pulled toward it. While the right mouse button is held, it sits exactly on the candidate.
5. Confirm with left click or `Enter`, cancel with `Esc`. After confirming, correct the move numerically in the **Adjust Last Operation** panel.

While moving, `X` `Y` `Z` constrain to an axis and `Shift` + the key to a plane. With **Axis Align** on in the panel, only coordinate values are aligned instead of vertex positions.

The full list of controls, how to choose Target Scope, and the preferences are in the [guide](docs/details.en.md).

## Notes

- Only mesh vertices are snap targets, taken from the geometry (with modifiers) at the moment the move starts.
- Beyond **Max Vertex Budget** (default 50,000) vertices, distant objects are down-sampled or reduced to their bounding-box corners and origin.
- With **Enable Smart Clipping** off, `Shift+G` goes back to Blender's Select Grouped / Select Similar.

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
