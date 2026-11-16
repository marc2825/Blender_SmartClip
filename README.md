# Smart Clipping (Blender Addon) v1.1.0

![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?logo=blender&logoColor=white)
[![Release](https://img.shields.io/github/v/release/marc2825/Blender_SmartClip?label=release)](https://github.com/marc2825/Blender_SmartClip/releases/latest)
[![License](https://img.shields.io/github/license/marc2825/Blender_SmartClip)](https://github.com/marc2825/Blender_SmartClip/blob/main/LICENSE)

👉 [English README](#english-en)

![Demo](assets/teaser.gif)

## 日本語 (JA)

### 概要
**Smart Clipping** は、Blender の移動操作を拡張するアドオンです。  
オブジェクトや頂点を移動するときに、周囲の要素を候補として検出し、3DガイドとHUDを表示しながら、近接要素へのスナップを補助します。  
近づいたときは Soft Snap（候補点へ徐々に引き寄せる補間）、右クリック長押しで Hard Snap（候補点へ完全に固定）を適用し、`Target Scope` で探索範囲を切り替えられます。

（このアドオンは、Microsoft PowerPoint の [Smart Guides](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3) にインスパイアされて誕生しました。）

### 対応環境
- Blender: 4.0 LTS 以降
- Python: 3.11+
- 主要依存: `bpy`, `gpu`, `mathutils`, `bmesh`, `bpy_extras`

### 主な機能
- 静的 KD-Tree による高速近傍検索
- `Target Scope`（`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`）
- `max_vertex_budget` 超過時の間引き挿入と `BOUNDS` フォールバック
- Soft Snap（接近時に候補へ徐々に補間）/ Hard Snap（右クリック長押しで候補へ完全固定）
- **Axis Align モード**（X / Y / Z 軸トグル）
- **軸 / 面拘束**（モーダル中に `X` / `Y` / `Z` / `Shift+X` / `Shift+Y` / `Shift+Z`）
- 3D ガイド線表示と左下 HUD 表示
- Object Mode / Edit Mode の両対応

### インストール
1. `src/` フォルダを ZIP 化（またはアドオンディレクトリに配置）
2. Blender > Preferences > Add-ons > Install で ZIP を指定
3. アドオンを有効化

### 使い方
1. View3D > N-Panel > Tool > Smart Clipping を開く
2. `Enable Smart Clipping` を ON
3. `Target Scope` を選択（`COLLECTION` の場合は `Collection` を指定）
4. N-Panel の `Smart Clipping Move` ボタンで起動（必要なら Preferences でホットキーを追加）
5. 通常移動で Soft Snap（候補へ徐々に引き寄せ）、右クリック長押しで Hard Snap（候補へ完全固定）

#### モーダル操作キー

| キー | 動作 |
|------|------|
| 左クリック / `Enter` | 確定 |
| `ESC` | キャンセル（元の位置に戻る） |
| 右クリック（長押し） | Hard Snap（候補へ完全固定） |
| `X` / `Y` / `Z` | 軸拘束（トグル） |
| `Shift+X` / `Shift+Y` / `Shift+Z` | 面拘束（トグル） |

#### Axis Align モード
N-Panel の **Axis Align** セクションで X / Y / Z トグルを ON にすると、頂点の位置そのものではなく、その軸上での座標値にスナップするモードに切り替わります。

- **全軸 OFF（デフォルト）**: 通常の頂点スナップ。マウスカーソル付近の頂点（3D空間上の位置）に直接スナップします。
- **1軸 ON**（例: Z のみ）: 参照頂点に z=1 のものがあれば、XY によらず z=1 にスナップを提案。X を ON なら同様に x 座標へのアライメント。
- **複数軸同時 ON**（例: X と Z）: 各軸が独立に候補を生成し、最もスコアの良い **1軸だけ** が採用されます（2軸同時にアラインするわけではありません）。
- 候補になるのは、アライメント後の位置が画面上で `Snap Threshold (px)` 以内に収まる値だけです。視線方向とほぼ平行な軸（例: トップビューでの Z）はマウスで動かせないため対象外になります。

アライメント中は、参照元の頂点からスナップ先への **点線** が表示され、どの頂点の座標値にアラインしているかを視覚的に確認できます。
HUD には `Align Z: 1.000 (Cube.001) | Dist: 0.003m` のように軸・座標値・参照オブジェクト名が表示されます。

#### 軸 / 面拘束（モーダル中）
Smart Clipping モーダル操作中に、Blender 標準の `G` → `X`/`Y`/`Z` と同様の軸・面拘束が使えます。

| キー | 動作 |
|------|------|
| `X` | X 軸上のみ移動 |
| `Y` | Y 軸上のみ移動 |
| `Z` | Z 軸上のみ移動 |
| `Shift+X` | YZ 平面上のみ移動（X を除外） |
| `Shift+Y` | XZ 平面上のみ移動（Y を除外） |
| `Shift+Z` | XY 平面上のみ移動（Z を除外） |

- 同じキーをもう一度押すとフリー移動に戻ります（トグル）
- 拘束中は対応する軸のカラーライン（赤=X / 緑=Y / 青=Z）がビューポートに表示されます
- 面拘束中は面を構成する 2 軸のラインが表示されます
- HUD に現在の拘束状態（例: `Axis: X` / `Plane: YZ`）が表示されます
- Smart Clipping のスナップ機能（Soft Snap / Hard Snap / Axis Align）と併用可能です。スナップ結果も拘束軸・面上に射影されるため、拘束が外れることはありません

### テスト
#### 自動（ヘッドレス）
```powershell
blender --background --factory-startup --python tests/headless_test_runner.py
```

単体ケース実行:
```powershell
blender --background --factory-startup --python tests/headless_test_runner.py -- --case stress_100k
```

実装済みケース:
- `scene_props`
- `scope_self`
- `scope_selected`
- `scope_visible_sort`
- `budget_fallback`
- `scope_collection`
- `stress_100k`
- `budget_partial`
- `scope_collection_recursive`
- `edit_mode_sync`
- `parent_space_delta`
- `constraint_helpers`
- `axis_align_gate`
- `axis_align_dense`
- `find_hit_cap`

#### UI 自動テスト（ウィンドウが開きます）
モーダル操作をイベントシミュレーションで実行し、親付きオブジェクトの移動・ESC 復元・ビュー回転中の移動・拘束・Hard Snap・Edit Mode を検証します。
```powershell
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

#### 手動（UI）
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml`
  - バージョン表記の整合チェック（`scripts/versioning.py`）と、Blender を取得してのヘッドレステスト
- Release: `.github/workflows/release-addon.yml`
  - タグ `v*.*.*` で `src-vX.Y.Z.zip` と `sha256` を生成・公開（タグと `bl_info` のバージョンが一致しないと失敗）
- バージョンの正本は `src/__init__.py` の `bl_info["version"]` です。上げるときは `CHANGELOG.md`・`CITATION.cff`・README のタイトルも合わせて更新してください
- Security Scan: `.github/workflows/codeql.yml`

### 詳細・注意
- 移動開始（`invoke`）時に対象をスナップショット化し、静的 KD-Tree で近傍候補を検索します。
- スナップ対象は `Target Scope`（`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`）で制御できます。
- 頂点は移動元に近いオブジェクトから順に `max_vertex_budget` まで登録します。予算をまたぐオブジェクトは残り予算ぶんに間引いて登録し、それ以降のオブジェクトはバウンディングボックス（`BOUNDS`）だけになります。
- Object Mode では移動中のオブジェクト自身はスナップ対象にならないため、ツリーに登録せず予算も消費しません。
- スナップ候補のスクリーン距離フィルタは、マウスカーソルではなく移動中の頂点/オブジェクトの投影位置を基準にします。
- 移動中にビューを回転・パン・ズームしても、移動中の位置は飛びません。
- ヘッドレステストは対話的なマウス操作を完全再現できないため、UI 自動テストと手動検証を併用してください。

### 開発について
本アドオンは **[Claude Code](https://claude.com/product/claude-code)（Anthropic）** と **[Codex](https://openai.com/codex)（OpenAI）** との協調開発により作成されました。

---

## English (EN)

### Overview
**Smart Clipping** is a Blender addon that enhances move operations.  
While moving objects or vertices, it detects nearby candidates and assists snapping with a 3D guide and HUD feedback.  
It applies soft snap when close (gradual interpolation toward a candidate), hard snap while holding right-click (fully locks to the candidate), and lets you control search range via `Target Scope`.

(This addon is inspired by [Smart Guides](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3) in Microsoft PowerPoint.)

### Requirements
- Blender: 4.0 LTS+
- Python: 3.11+
- Core dependencies: `bpy`, `gpu`, `mathutils`, `bmesh`, `bpy_extras`

### Key Features
- Fast nearest lookup with static KD-Tree
- `Target Scope` (`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`)
- Down-sampling and `BOUNDS` fallback when `max_vertex_budget` is exceeded
- Soft Snap near candidates (gradual interpolation) / Hard Snap while holding right-click (full lock to candidate)
- **Axis Align mode** (X / Y / Z toggles)
- **Axis / plane constraint** (press `X`/`Y`/`Z` or `Shift+X`/`Shift+Y`/`Shift+Z` during modal)
- 3D guide rendering and lower-left HUD text
- Works in both Object Mode and Edit Mode

### Installation
1. Zip `src/` (or place it directly in your addons directory)
2. Blender > Preferences > Add-ons > Install
3. Enable the addon

### Usage
1. Open View3D > N-Panel > Tool > Smart Clipping
2. Enable `Enable Smart Clipping`
3. Choose `Target Scope` (`Collection` is required for `COLLECTION`)
4. Start from the `Smart Clipping Move` button (or assign a hotkey in Preferences)
5. Move for soft snap (gradual pull toward candidate), hold right-click for hard snap (full lock to candidate)

#### Modal Controls

| Key | Action |
|-----|--------|
| Left Click / `Enter` | Confirm |
| `ESC` | Cancel (restore original position) |
| Right Click (hold) | Hard Snap (lock to candidate) |
| `X` / `Y` / `Z` | Axis constraint (toggle) |
| `Shift+X` / `Shift+Y` / `Shift+Z` | Plane constraint (toggle) |

#### Axis Align Mode
Enable one or more axis toggles (X / Y / Z) in the **Axis Align** section of the N-Panel. When active, snapping targets axis coordinate values from reference vertices instead of exact vertex positions.

- **All off (default)**: Regular vertex snapping. Snaps directly to nearby vertex positions in 3D space near the current object/vertex position.
- **1 axis on** (e.g. Z only): If a reference vertex has z=1, the addon suggests snapping to z=1 regardless of XY position. X on similarly suggests alignment to X coordinates.
- **Multiple axes on** (e.g. X and Z): Each axis generates independent candidates; the best-scoring **single axis** wins (does not align to two axes simultaneously).
- A value is only suggested when the aligned position lies within `Snap Threshold (px)` on screen. An axis nearly parallel to the view direction (e.g. Z in top view) cannot be steered with the mouse and is skipped.

A **dashed line** connects the snap target to the reference vertex, showing which vertex provides the axis value.
The HUD displays: `Align Z: 1.000 (Cube.001) | Dist: 0.003m`.

#### Axis / Plane Constraint (During Modal)
While in Smart Clipping modal mode, you can constrain movement to a single axis or a plane, just like Blender's native `G` then `X`/`Y`/`Z`.

| Key | Action |
|-----|--------|
| `X` | Move along X axis only |
| `Y` | Move along Y axis only |
| `Z` | Move along Z axis only |
| `Shift+X` | Move on YZ plane (exclude X) |
| `Shift+Y` | Move on XZ plane (exclude Y) |
| `Shift+Z` | Move on XY plane (exclude Z) |

- Press the same key again to return to free movement (toggle)
- A colored axis line is shown in the viewport while constrained (red=X / green=Y / blue=Z)
- A plane constraint shows the lines of both of its axes
- The HUD shows the current constraint (e.g. `Axis: X` / `Plane: YZ`)
- Works together with Smart Clipping snap features (Soft Snap / Hard Snap / Axis Align); snap results are projected onto the constraint axis / plane, so snapping never breaks the constraint

### Testing
#### Automated (Headless)
```powershell
blender --background --factory-startup --python tests/headless_test_runner.py
```

Single case:
```powershell
blender --background --factory-startup --python tests/headless_test_runner.py -- --case stress_100k
```

Cases:
- `scene_props`
- `scope_self`
- `scope_selected`
- `scope_visible_sort`
- `budget_fallback`
- `scope_collection`
- `stress_100k`
- `budget_partial`
- `scope_collection_recursive`
- `edit_mode_sync`
- `parent_space_delta`
- `constraint_helpers`
- `axis_align_gate`
- `axis_align_dense`
- `find_hit_cap`

#### Automated UI (opens a window)
Drives the modal operator with simulated events: parented objects, ESC restore, navigating mid-move, constraints, hard snap, and Edit Mode.
```powershell
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

#### Manual (Interactive UI)
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml` (version consistency check via `scripts/versioning.py` + headless tests)
- Release: `.github/workflows/release-addon.yml` (fails if the tag does not match `bl_info`)
- Security scan: `.github/workflows/codeql.yml`
- The single source of truth for the version is `bl_info["version"]` in `src/__init__.py`; bump `CHANGELOG.md`, `CITATION.cff`, and the README title together with it.

### Notes
- At move start (`invoke`), target geometry is snapshotted and queried through a static KD-Tree.
- Snap target range is controlled by `Target Scope` (`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`).
- Vertices are inserted nearest object first up to `max_vertex_budget`. The object crossing the limit is down-sampled into the remaining budget; objects after it contribute only their bounding box (`BOUNDS`).
- In Object Mode the moving object itself is never a snap target, so it is not inserted and does not consume budget.
- Screen-space candidate filtering uses the projected position of the moving vertex/object, not the raw mouse cursor.
- Orbiting, panning, or zooming during a move does not make the selection jump.
- Headless tests cannot fully reproduce interactive viewport behavior, so also run the automated UI test and manual checks.

### Development
This addon was developed in collaboration with **[Claude Code](https://claude.com/product/claude-code) (Anthropic)** and **[Codex](https://openai.com/codex) (OpenAI)**.
