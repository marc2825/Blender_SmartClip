# Smart Clipping (Blender Addon)

![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?logo=blender&logoColor=white)
[![Release](https://img.shields.io/github/v/release/marc2825/Blender_SmartClip?label=release)](https://github.com/marc2825/Blender_SmartClip/releases/latest)
[![License](https://img.shields.io/github/license/marc2825/Blender_SmartClip)](https://github.com/marc2825/Blender_SmartClip/blob/main/LICENSE)

[日本語](README.md)

![Demo](assets/teaser.gif)

## Overview

Smart Clipping is a Blender add-on that extends the move operation. While you move objects or vertices, it finds nearby elements as snap candidates and shows 3D guides and a HUD. Near a candidate the selection is pulled toward it (soft snap); holding the right mouse button locks it onto the candidate (hard snap). Target Scope controls which meshes are searched.

The add-on is inspired by [Smart Guides](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3) in Microsoft PowerPoint.

## Requirements

Blender 4.0 or later. Automated tests run on Blender 4.0, 4.2 LTS, and 5.2 LTS.

## Installation

Download `smart_clipping-vX.Y.Z.zip` from [Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest), choose it with Install from Disk in Preferences > Add-ons (Install on Blender 4.1 and older), and enable Smart Clipping.

When upgrading from 1.1.x or earlier, disable and remove the old version first. Version 1.2.0 renamed the module from `src` to `smart_clipping`, so enabling both makes their registrations collide. Add-on preferences start from their defaults again; the Target Scope and Collection settings saved in `.blend` files carry over when the file is opened.

## Usage

The Smart Clipping panel is in the Tool tab of the 3D Viewport sidebar (N). With Enable Smart Clipping on, press `Shift+G` in Object Mode or mesh Edit Mode, or click Smart Clipping Move in the panel, to start a move. In Object Mode all selected objects move and the active object's origin is what snaps. In Edit Mode the selected vertices of the meshes being edited move and their center is what snaps.

Close to a candidate, the selection is pulled toward it, more strongly the closer it gets (soft snap). While the right mouse button is held, it sits exactly on the candidate (hard snap). The guide lines and the lower-left HUD show which object you are heading for and the distance. After confirming, you can correct the move numerically as Offset in the Adjust Last Operation panel.

With Enable Smart Clipping off, `Shift+G` goes back to Blender's Select Grouped / Select Similar.

| Input | Action |
|---|---|
| Left click / `Enter` | Confirm |
| `Esc` | Cancel and restore the original position |
| Hold right mouse button | Hard snap |
| `X` / `Y` / `Z` | Move along that axis only (press again to release) |
| `Shift+X` / `Shift+Y` / `Shift+Z` | Move in the plane excluding that axis (press again to release) |
| Middle mouse / wheel | Orbit, pan, or zoom without ending the move |

Axis and plane constraints use the global axes. A constrained axis is drawn in red (X), green (Y), or blue (Z), and snapped positions are kept on the constrained axis or plane.

### Snap targets

Target Scope selects which meshes can be snapped to.

- Self Only: the mesh being edited. Use it in Edit Mode to snap to other vertices of the same mesh.
- Selected: selected meshes other than the active one
- All Visible: every visible mesh (default)
- Manual Collection: meshes in the chosen collection and its child collections

### Axis Align

Turning on X, Y, or Z under Axis Align in the panel aligns to that axis's coordinate values instead of vertex positions. With Z on, for example, a vertex at z = 1 offers z = 1 as a candidate while X and Y stay where they are. With several axes on, only one axis is aligned at a time. A value becomes a candidate only if the aligned position is within Snap Threshold on screen, and an axis nearly parallel to the view direction (such as Z in top view) is skipped. A dashed line leads to the vertex the value comes from.

## Preferences

Preferences > Add-ons > Smart Clipping has these settings.

- Snap Threshold (px): screen distance within which candidates are found. Default 30.
- Max Vertex Budget: maximum number of vertices registered as snap targets. Default 50,000; what happens beyond it is described in [How it works](docs/details.en.md#how-snap-targets-are-built).
- Guide Color / Hard Snap Color: colors of the guides and HUD

Add Default Hotkeys and Clear Hotkeys on the same page restore or remove the `Shift+G` assignment.

## More information

- [How it works and troubleshooting](docs/details.en.md)
- [Changelog](CHANGELOG.md)
- [Developer guide](docs/DEVELOPMENT.md)
- Ask usage questions in [Discussions](https://github.com/marc2825/Blender_SmartClip/discussions) and report bugs in [Issues](https://github.com/marc2825/Blender_SmartClip/issues) ([SUPPORT.md](SUPPORT.md)).

## License

[MIT License](LICENSE)

## Development

This add-on was developed with [Claude Code](https://claude.com/product/claude-code) (Anthropic) and [Codex](https://openai.com/codex) (OpenAI).
