# Smart Clipping (Blender Addon) v1.0.0

## 日本語 (JA)

### 概要
`src` は、Blender の移動操作を拡張するアドオンです。  
`invoke` 時点で静的な KD-Tree を構築し、近傍要素へのガイド表示とスナップを行います。  
大規模シーン向けに、`Vertex Budget` と `Target Scope` で負荷を制御します。

### 対応環境
- Blender: 4.0 LTS 以降
- Python: 3.10+
- 主要依存: `bpy`, `gpu`, `mathutils`, `bmesh`, `bpy_extras`

### 主な機能
- 静的 KD-Tree による高速近傍検索
- `Target Scope`（`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`）
- `max_vertex_budget` 超過時の `BOUNDS` フォールバック
- Soft Snap（接近時）/ Hard Snap（`Ctrl` 押下時）
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
4. `Shift + Alt + G` で起動
5. 通常移動で Soft Snap、`Ctrl` 押下で Hard Snap

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

#### 手動（UI）
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml`
  - Blender を取得してヘッドレステストを実行
- Release: `.github/workflows/release-addon.yml`
  - タグ `v*.*.*` で `src-vX.Y.Z.zip` と `sha256` を生成・公開
- Security Scan: `.github/workflows/codeql.yml`

### 公開運用ファイル
- `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- `SECURITY.md`, `SUPPORT.md`, `RELEASE_CHECKLIST.md`
- `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`
- `.github/dependabot.yml`, `.github/release.yml`, `.github/CODEOWNERS`
- `docs/PUBLISHING_CHECKLIST.md`, `docs/GITHUB_SETUP.md`, `docs/TESTING.md`
- `docs/TROUBLESHOOTING.md`, `docs/ROADMAP.md`
- `scripts/package_addon.py`

### リポジトリ構成
```text
src/
  __init__.py
  ops.py
  detector.py
  drawing.py
  utils.py
  prefs.py

tests/
  headless_test_runner.py
  manual_ui_setup.py

scripts/
  package_addon.py

docs/
  PUBLISHING_CHECKLIST.md
  GITHUB_SETUP.md
  TESTING.md
  TROUBLESHOOTING.md
  ROADMAP.md
```

### 注意
- `find_candidates` は 3D View の `region/rv3d` に依存します。
- ヘッドレスでは対話操作を完全再現できないため、UI挙動は手動検証も実施してください。
- 以下はプレースホルダなので公開前に更新してください:
  - `.github/CODEOWNERS`
  - `.github/ISSUE_TEMPLATE/config.yml`
  - `CITATION.cff`

---

## English (EN)

### Overview
`src` is a Blender addon that extends move behavior.  
It builds a static KD-Tree snapshot at `invoke` time and provides guide/snap behavior to nearby elements.  
For large scenes, it controls load using `Vertex Budget` and `Target Scope`.

### Requirements
- Blender: 4.0 LTS+
- Python: 3.10+
- Core dependencies: `bpy`, `gpu`, `mathutils`, `bmesh`, `bpy_extras`

### Key Features
- Fast nearest lookup with static KD-Tree
- `Target Scope` (`SELF` / `SELECTED` / `VISIBLE` / `COLLECTION`)
- `BOUNDS` fallback when `max_vertex_budget` is exceeded
- Soft Snap near candidates / Hard Snap while holding `Ctrl`
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
4. Start with `Shift + Alt + G`
5. Move for soft snap, hold `Ctrl` for hard snap

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

#### Manual (Interactive UI)
```powershell
blender --python tests/manual_ui_setup.py
```

### CI/CD
- CI: `.github/workflows/blender-ci.yml`
- Release: `.github/workflows/release-addon.yml`
- Security scan: `.github/workflows/codeql.yml`

### Publishing Assets
- `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- `SECURITY.md`, `SUPPORT.md`, `RELEASE_CHECKLIST.md`
- `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`
- `.github/dependabot.yml`, `.github/release.yml`, `.github/CODEOWNERS`
- `docs/PUBLISHING_CHECKLIST.md`, `docs/GITHUB_SETUP.md`, `docs/TESTING.md`
- `docs/TROUBLESHOOTING.md`, `docs/ROADMAP.md`
- `scripts/package_addon.py`

### Notes
- `find_candidates` depends on actual 3D View `region/rv3d` context.
- Headless tests cannot fully reproduce interactive viewport behavior; run manual checks as well.
- Update placeholders before publishing:
  - `.github/CODEOWNERS`
  - `.github/ISSUE_TEMPLATE/config.yml`
  - `CITATION.cff`
