# Smart Clipping (Blender Addon) v2.0.0

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
- Object Mode（選択中の全オブジェクト）/ Edit Mode（編集中の全メッシュの選択頂点）の両対応
- スナップ先はモディファイア適用後の見た目どおりの形状
- 確定後に「最後の操作を調整」パネルで移動量（Offset）を数値修正可能

### インストール
1. [Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest) から `smart_clipping-vX.Y.Z.zip` をダウンロード
2. Blender > Preferences > Add-ons > Install from Disk（4.1 以前は Install）で ZIP を指定
3. アドオン「Smart Clipping」を有効化

#### 1.x からの更新
2.0.0 でアドオンのモジュール名が `src` から `smart_clipping` に変わりました。

1. Preferences > Add-ons で旧「Smart Clipping」（モジュール `src`）を無効化して削除してから、新しい ZIP をインストールしてください（両方を有効にすると登録が衝突します）
2. アドオン設定（Snap Threshold・Max Vertex Budget・色）は初期値に戻るので、必要なら設定し直してください
3. `.blend` に保存された Scene 設定（Target Scope / Collection）は、ファイルを開いたときに自動で引き継がれます

### 使い方
1. View3D > N-Panel > Tool > Smart Clipping を開く
2. `Enable Smart Clipping` を ON
3. `Target Scope` を選択（`COLLECTION` の場合は `Collection` を指定）
4. `Shift+G`（Object Mode / Edit Mode）または N-Panel の `Smart Clipping Move` ボタンで起動
5. 通常移動で Soft Snap（候補へ徐々に引き寄せ）、右クリック長押しで Hard Snap（候補へ完全固定）
6. 確定後、左下の「最後の操作を調整」パネルで `Offset` を数値で修正できます

`Enable Smart Clipping` を OFF にすると `Shift+G` は Blender 標準の動作（Select Grouped / Select Similar）に戻ります。

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
- `object_mode_excludes_movers`
- `evaluated_mesh_targets`
- `execute_moves_all_selected`
- `execute_edit_multi_object`
- `legacy_prop_migration`
- `pixel_world_size`

#### UI 自動テスト（ウィンドウが開きます）
モーダル操作をイベントシミュレーションで実行し、親付きオブジェクトの移動・ESC 復元・ビュー回転中の移動・拘束・Redo 用 Offset・複数オブジェクト移動・Hard Snap・Edit Mode を検証します。
```powershell
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

#### 手動（UI）
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml`
  - バージョン表記の整合チェック（`scripts/versioning.py`）と、Blender 4.0 / 4.2 LTS / 5.2 LTS でのヘッドレステスト
- Release: `.github/workflows/release-addon.yml`
  - タグ `v*.*.*` で `smart_clipping-vX.Y.Z.zip` と `sha256` を生成し、CHANGELOG の該当節を本文にして GitHub Release を公開（タグと `bl_info` のバージョンが一致しないと失敗）
  - 手動実行（workflow_dispatch）は Release を作らない試験実行で、ZIP とリリースノートを Artifact に保存します
- バージョンの正本は `smart_clipping/__init__.py` の `bl_info["version"]` です。上げるときは `CHANGELOG.md`・`CITATION.cff`・README のタイトルも合わせて更新してください
- Security Scan: `.github/workflows/codeql.yml`

### 詳細・注意
- 移動開始（`invoke`）時に対象をスナップショット化し、静的 KD-Tree で近傍候補を検索します。
- スナップ対象は `Target Scope`（`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`）で制御できます。
- 頂点は移動元に近いオブジェクトから順に `max_vertex_budget` まで登録します。予算をまたぐオブジェクトは残り予算ぶんに間引いて登録し、それ以降のオブジェクトはバウンディングボックス（`BOUNDS`）だけになります。
- Object Mode では移動中のオブジェクト（とその子）自身はスナップ対象にならないため、ツリーに登録せず予算も消費しません。親と子を両方選択しても子が二重に動くことはなく、`lock_location` でロックした軸は動きません。
- スナップ対象の形状はモディファイア適用後のものです（Edit Mode 中のオブジェクトは編集中のメッシュ）。
- 探索半径はビューの縮尺に追従するため、ミリ単位の小さなシーンでもキロ単位の大きなシーンでも同じ感覚で使えます。
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
- Object Mode (all selected objects) and Edit Mode (selected vertices of every mesh in Edit Mode)
- Snaps to the displayed geometry (modifiers applied)
- Fine-tune the final `Offset` in the Adjust Last Operation panel

### Installation
1. Download `smart_clipping-vX.Y.Z.zip` from [Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest)
2. Blender > Preferences > Add-ons > Install from Disk (Install on 4.1 and older)
3. Enable "Smart Clipping"

#### Upgrading from 1.x
In 2.0.0 the add-on module was renamed from `src` to `smart_clipping`.

1. Disable and remove the old "Smart Clipping" (module `src`) in Preferences > Add-ons before installing the new ZIP (enabling both makes their registrations collide)
2. Add-on preferences (snap threshold, vertex budget, colors) start from their defaults again
3. Scene settings saved in `.blend` files (Target Scope / Collection) are migrated automatically when the file is opened

### Usage
1. Open View3D > N-Panel > Tool > Smart Clipping
2. Enable `Enable Smart Clipping`
3. Choose `Target Scope` (`Collection` is required for `COLLECTION`)
4. Press `Shift+G` (Object Mode / Edit Mode) or use the `Smart Clipping Move` button
5. Move for soft snap (gradual pull toward candidate), hold right-click for hard snap (full lock to candidate)
6. After confirming, adjust `Offset` numerically in the Adjust Last Operation panel

Turning `Enable Smart Clipping` off gives `Shift+G` back to Blender (Select Grouped / Select Similar).

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
- `object_mode_excludes_movers`
- `evaluated_mesh_targets`
- `execute_moves_all_selected`
- `execute_edit_multi_object`
- `legacy_prop_migration`
- `pixel_world_size`

#### Automated UI (opens a window)
Drives the modal operator with simulated events: parented objects, ESC restore, navigating mid-move, constraints, the redo offset, multi-object moves, hard snap, and Edit Mode.
```powershell
blender --factory-startup --enable-event-simulate --python tests/ui_operator_test.py
```

#### Manual (Interactive UI)
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml` (version consistency check via `scripts/versioning.py` + headless tests on Blender 4.0 / 4.2 LTS / 5.2 LTS)
- Release: `.github/workflows/release-addon.yml` — a `v*.*.*` tag builds `smart_clipping-vX.Y.Z.zip` + `sha256` and publishes a GitHub Release whose body is the CHANGELOG section (fails if the tag does not match `bl_info`). A manual run (workflow_dispatch) is a dry run that only uploads the ZIP and notes as an artifact.
- Security scan: `.github/workflows/codeql.yml`
- The single source of truth for the version is `bl_info["version"]` in `smart_clipping/__init__.py`; bump `CHANGELOG.md`, `CITATION.cff`, and the README title together with it.

### Notes
- At move start (`invoke`), target geometry is snapshotted and queried through a static KD-Tree.
- Snap target range is controlled by `Target Scope` (`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`).
- Vertices are inserted nearest object first up to `max_vertex_budget`. The object crossing the limit is down-sampled into the remaining budget; objects after it contribute only their bounding box (`BOUNDS`).
- In Object Mode the moving objects (and their children) are never snap targets, so they are not inserted and do not consume budget. Selecting a parent and its child does not move the child twice, and axes locked with `lock_location` stay put.
- Snap targets use the evaluated geometry (modifiers applied); objects in Edit Mode use their edit mesh.
- The search radius follows the view scale, so tiny (mm) and huge (km) scenes behave the same.
- Screen-space candidate filtering uses the projected position of the moving vertex/object, not the raw mouse cursor.
- Orbiting, panning, or zooming during a move does not make the selection jump.
- Headless tests cannot fully reproduce interactive viewport behavior, so also run the automated UI test and manual checks.

### Development
This addon was developed in collaboration with **[Claude Code](https://claude.com/product/claude-code) (Anthropic)** and **[Codex](https://openai.com/codex) (OpenAI)**.
