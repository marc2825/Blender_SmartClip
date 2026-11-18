<p align="center">
  <img src="assets/logo.svg" alt="Smart Clipping" width="720">
</p>

# Smart Clipping

[![Release](https://img.shields.io/github/v/release/marc2825/Blender_SmartClip?label=version)](https://github.com/marc2825/Blender_SmartClip/releases/latest)
[![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?logo=blender&logoColor=white)](https://www.blender.org/)
[![License: MIT](https://img.shields.io/github/license/marc2825/Blender_SmartClip)](LICENSE)

[日本語](README.md) | [English](README.en.md)

オブジェクトや頂点を移動するときに、近くの頂点へのガイド線を表示し、位置合わせ（スナップ）を手伝う Blender アドオンです。PowerPoint の[スマートガイド](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3)を参考にしています。

![移動中のオブジェクトから近くの頂点へガイド線が伸び、スナップする様子](assets/teaser.gif)

> Blender 4.0 以降に対応しています。自動テストは Blender 4.0、4.2 LTS、5.2 LTS で実行しています。

## インストール

[Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest) から `smart_clipping-vX.Y.Z.zip` を入手し、Blender の **Preferences → Add-ons → Install from Disk**（4.1 以前は **Install**）で読み込みます。ZIP は展開しないでください。

1.1.x 以前から更新するときは、先に旧版（モジュール名 `src`）を無効にして削除してください。両方を有効にすると登録が衝突します。アドオンの設定は初期値に戻りますが、`.blend` に保存した Target Scope などの設定は引き継がれます。

## 使い方

1. 3D ビューで N キーを押し、**Tool** タブの **Smart Clipping** パネルを開きます。
2. **Target Scope** でスナップ先にするメッシュの範囲を選びます。初期値は表示中のすべてのメッシュです。
3. オブジェクトモードかメッシュの編集モードで `Shift+G` を押し、移動を始めます。
4. 候補の頂点に近づくと引き寄せられます。右ボタンを押している間は、候補にぴったり合わせます。
5. 左クリックか `Enter` で確定し、`Esc` で取り消します。確定後は **Adjust Last Operation** パネルで移動量を数値で直せます。

移動中は `X` `Y` `Z` で軸に、`Shift` を付けると面に拘束できます。パネルの **Axis Align** をオンにすると、頂点の位置ではなく座標値だけをそろえます。

操作キーの一覧、Target Scope の選び方、設定項目は[操作ガイド](docs/details.md)にあります。

## 注意

- スナップ先はメッシュの頂点だけです。移動を始めた時点の形状（モディファイア適用後）から作ります。
- 頂点数が **Max Vertex Budget**（初期値 50,000）を超えると、遠くのオブジェクトは頂点を間引くか、バウンディングボックスの角と原点だけを候補にします。
- **Enable Smart Clipping** をオフにすると、`Shift+G` は Blender 標準の Select Grouped / Select Similar に戻ります。

## 関連文書

- [操作ガイド](docs/details.md)（[English](docs/details.en.md)）
- [変更履歴](CHANGELOG.md)
- [開発者向け資料](docs/DEVELOPMENT.md)（英語）
- [サポート](SUPPORT.md)：質問は [Discussions](https://github.com/marc2825/Blender_SmartClip/discussions)、不具合は [Issues](https://github.com/marc2825/Blender_SmartClip/issues) へ

## 開発

Blender に同梱されたモジュールだけを使っています。テスト、CI、リリース手順は[開発者向け資料](docs/DEVELOPMENT.md)にあります。

```bash
blender --background --factory-startup --python tests/headless_test_runner.py  # テスト
python scripts/package_addon.py                                               # ZIP の作成
```

[Claude Code](https://claude.com/product/claude-code)（Anthropic）と [Codex](https://openai.com/codex)（OpenAI）を使って開発しました。

## ライセンス

[MIT License](LICENSE)。Copyright (c) 2026 marc2825
