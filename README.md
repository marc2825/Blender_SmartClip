# Smart Clipping (Blender Addon) v1.2.0

![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?logo=blender&logoColor=white)
[![Release](https://img.shields.io/github/v/release/marc2825/Blender_SmartClip?label=release)](https://github.com/marc2825/Blender_SmartClip/releases/latest)
[![License](https://img.shields.io/github/license/marc2825/Blender_SmartClip)](https://github.com/marc2825/Blender_SmartClip/blob/main/LICENSE)

[English](README.en.md)

![Demo](assets/teaser.gif)

## 概要

**Smart Clipping** は、Blender の移動操作を拡張するアドオンです。  
オブジェクトや頂点を移動するときに、周囲の要素を候補として検出し、3DガイドとHUDを表示しながら、近接要素へのスナップを補助します。  
近づいたときは Soft Snap（候補点へ徐々に引き寄せる補間）、右クリック長押しで Hard Snap（候補点へ完全に固定）を適用し、`Target Scope` で探索範囲を切り替えられます。

（このアドオンは、Microsoft PowerPoint の [Smart Guides](https://support.microsoft.com/en-us/office/guides-for-arranging-things-on-a-slide-33854dfa-e0d1-43ff-8971-667b19512de3) にインスパイアされて誕生しました。）

## 対応環境

Blender 4.0 以降で動きます。Blender 4.0、4.2 LTS、5.2 LTS で自動テストを実行しています。

## インストール

[Releases](https://github.com/marc2825/Blender_SmartClip/releases/latest) から `smart_clipping-vX.Y.Z.zip` をダウンロードし、Preferences > Add-ons の Install from Disk（Blender 4.1 以前は Install）で ZIP を選んで、Smart Clipping を有効にします。

1.1.x 以前から更新するときは、先に旧版を無効にして削除してください。1.2.0 でモジュール名が `src` から `smart_clipping` に変わったため、両方を有効にすると登録が衝突します。アドオンの設定は初期値に戻りますが、`.blend` に保存した Target Scope と Collection の設定は、ファイルを開いたときに引き継がれます。

## 使い方

3D ビューポートのサイドバー（N キー）の Tool タブに Smart Clipping パネルがあります。Enable Smart Clipping がオンのとき、オブジェクトモードかメッシュの編集モードで `Shift+G` を押すか、パネルの Smart Clipping Move を押すと移動が始まります。オブジェクトモードでは選択中のオブジェクトをすべて動かし、アクティブオブジェクトの原点をスナップさせます。編集モードでは編集中のメッシュの選択頂点を動かし、その中心をスナップさせます。

候補に近づくと、近いほど強く候補へ引き寄せられます（Soft Snap）。右ボタンを押している間は候補の位置にぴったり合わせます（Hard Snap）。向かっている候補のオブジェクト名と距離は、ガイド線と画面左下の表示で確かめられます。確定したあとは、最後の操作を調整パネルで移動量（Offset）を数値で直せます。

Enable Smart Clipping をオフにすると、`Shift+G` は Blender 標準の Select Grouped / Select Similar に戻ります。

| 操作 | 動作 |
|---|---|
| 左クリック / `Enter` | 確定 |
| `Esc` | キャンセルして元の位置に戻す |
| 右ボタンを押し続ける | Hard Snap |
| `X` / `Y` / `Z` | その軸に沿ってだけ動かす（もう一度押すと解除） |
| `Shift+X` / `Shift+Y` / `Shift+Z` | その軸を除いた面の上でだけ動かす（もう一度押すと解除） |
| 中ボタン / ホイール | 移動を続けたままビューを回転・パン・ズーム |

軸と面の拘束はワールド座標の軸に対して働きます。拘束中は軸の線が X は赤、Y は緑、Z は青で表示され、スナップした位置も拘束した軸や面の上に合わせます。

### スナップ先の範囲

Target Scope で、スナップ先にするメッシュを選びます。

- Self Only: 編集中のメッシュ自身。編集モードで、同じメッシュの別の頂点に合わせるときに使います。
- Selected: アクティブ以外の選択中のメッシュ
- All Visible: 表示中のすべてのメッシュ（初期値）
- Manual Collection: 指定したコレクションと、その子コレクションに入っているメッシュ

### Axis Align

パネルの Axis Align で X、Y、Z のどれかをオンにすると、頂点の位置ではなく、その軸の座標値にそろえます。たとえば Z をオンにしたとき、z 座標が 1 の頂点があれば、XY の位置はそのままで z = 1 にそろえる候補になります。複数の軸をオンにしても、そろえるのは一度に 1 軸だけです。そろえた後の位置が画面上で Snap Threshold 以内に入る値だけが候補になり、トップビューの Z のように視線とほぼ平行な軸は対象外です。そろえる元の頂点までは点線で表示されます。

## 設定

Preferences > Add-ons > Smart Clipping で次の項目を変えられます。

- Snap Threshold (px): 候補にする画面上の距離。初期値は 30 です。
- Max Vertex Budget: スナップ先として登録する頂点数の上限。初期値は 50,000 で、超えたときの扱いは[動作の詳細](docs/details.md#スナップ先の作り方)にあります。
- Guide Color / Hard Snap Color: ガイド線と表示の色

同じ画面の Add Default Hotkeys と Clear Hotkeys で、`Shift+G` の割り当てを戻したり外したりできます。

## 詳しい情報

- [動作の詳細と困ったとき](docs/details.md)
- [変更履歴](CHANGELOG.md)
- [開発者向け資料（英語）](docs/DEVELOPMENT.md)
- 使い方の質問は [Discussions](https://github.com/marc2825/Blender_SmartClip/discussions)、不具合の報告は [Issues](https://github.com/marc2825/Blender_SmartClip/issues) へお願いします（[SUPPORT.md](SUPPORT.md)）。

## ライセンス

[MIT License](LICENSE)

## 開発について

このアドオンは [Claude Code](https://claude.com/product/claude-code)（Anthropic）と [Codex](https://openai.com/codex)（OpenAI）を使って開発しました。
