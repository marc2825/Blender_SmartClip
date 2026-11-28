# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""Japanese translation of the add-on's interface.

Blender translates labels, property names, tooltips and enum items through
the messages registered here when the interface language is Japanese.  Text
the add-on assembles itself (viewport labels, format strings) goes through
``iface`` / ``tip`` / ``rpt`` explicitly.

Words Blender already translates (BLENDER_WORDS) are deliberately left out:
messages registered here apply to the whole of Blender, so registering a
common word would change it in Blender's own interface too.  A word that only
newer versions translate is registered with the same translation, which
changes nothing where Blender has it.  tests/headless_test_runner.py checks
that no message below collides with Blender's catalog and that every word in
BLENDER_WORDS is translated by it.
"""

import bpy

# Words the add-on shows and leaves to Blender's own catalog (identical in
# Blender 4.0 to 5.3).
BLENDER_WORDS = (
    "Snap To", "Selected Objects", "Visible Objects", "Collection", "Snapping",
    "Object Mode", "Edit Mode", "Confirm", "Cancel", "Axis", "Plane", "Off", "Display",
    "Advanced", "Offset",
)

# English message -> Japanese, default translation context ("*").
MESSAGES = {
    # Translated by Blender from 5.x only (same words there)
    "Snap Distance": "スナップ距離",

    # Operator
    "Move with Guides": "ガイド付きで移動",
    "Move the selection with guide lines that snap to nearby vertices":
        "近くの頂点にスナップするガイド線を使って、選択したものを移動します",
    "Distance moved, in world space": "移動した距離（ワールド座標）",
    "Snaxis is turned off for this scene": "このシーンでは Snaxis がオフになっています",
    "Needs an active object": "アクティブオブジェクトが必要です",
    "Works in Object Mode and mesh Edit Mode": "オブジェクトモードとメッシュの編集モードで使えます",
    "Nothing selected to move": "動かすものが選択されていません",
    "Select at least one vertex": "頂点を 1 つ以上選択してください",
    "Move with Guides needs a 3D Viewport": "3D ビューポートの中で使ってください",
    "Move with Guides stopped because of an internal error (see the system console)":
        "内部エラーのため移動を中止しました（詳細はシステムコンソールにあります）",

    # Sidebar panel and scene settings
    "Limits and Display": "上限と表示",
    "Enable Snaxis": "Snaxis を使う",
    "Use Snaxis in this scene. When off, Move with Guides does not start here":
        "このシーンで Snaxis を使います。オフのときは、このシーンでは「ガイド付きで移動」が始まりません",
    "Which meshes the move snaps to. Press S while moving to switch":
        "移動中にスナップする先のメッシュです。移動中は S キーで切り替えられます",
    "Same Mesh": "同じメッシュ",
    "Snap to other vertices of the meshes being edited (Edit Mode)":
        "編集中のメッシュのほかの頂点にスナップします（編集モード）",
    "Snap to the other selected meshes. In Object Mode only the active object moves":
        "ほかの選択中のメッシュにスナップします。オブジェクトモードでは、アクティブオブジェクトだけが動きます",
    "Snap to every visible mesh, nearest first, up to the snap point limit":
        "表示中のすべてのメッシュに、近いものから順にスナップ点の上限までスナップします",
    "Snap to the visible meshes in a collection and its child collections":
        "指定したコレクションと、その子コレクションにある表示中のメッシュにスナップします",
    "Collection to snap to, including its child collections":
        "スナップ先にするコレクション（子コレクションを含む）",
    # Short enough for the label column of the sidebar at its default width
    "Align Only": "座標合わせ",
    "Line up the X coordinate with nearby vertices instead of snapping onto them. "
    "Press A while moving to switch":
        "頂点に重ねる代わりに、近くの頂点と X 座標だけをそろえます。移動中は A キーで切り替えられます",
    "Line up the Y coordinate with nearby vertices instead of snapping onto them. "
    "Press A while moving to switch":
        "頂点に重ねる代わりに、近くの頂点と Y 座標だけをそろえます。移動中は A キーで切り替えられます",
    "Line up the Z coordinate with nearby vertices instead of snapping onto them. "
    "Press A while moving to switch":
        "頂点に重ねる代わりに、近くの頂点と Z 座標だけをそろえます。移動中は A キーで切り替えられます",
    "Snap point limit reached": "スナップ点が上限に達しました",
    "{simplified} objects simplified": "{simplified} 個を簡略化",
    "{simplified} simplified, {skipped} left out": "簡略化 {simplified} 個、対象外 {skipped} 個",
    "Add-on preferences are unavailable": "アドオンの設定を読み込めません",

    # Add-on preferences
    "Snap Behavior": "スナップのしかた",
    "What happens when a snap point comes within the snap distance":
        "スナップ距離の内側にスナップ点が入ったときの動きです",
    "Snap Exactly": "ぴったり合わせる",
    "Jump onto the snap point. Hold Ctrl to move freely":
        "スナップ点にぴったり合わせます。Ctrl を押している間はスナップしません",
    "Gradual Pull": "徐々に引き寄せる",
    "Pull towards the snap point, more strongly the closer it is. Hold Ctrl to snap exactly":
        "近いほど強くスナップ点へ引き寄せます。Ctrl を押している間はぴったり合わせます",
    "How close on screen the moving point must come to a snap point, "
    "at interface scale 1 (it grows with the scale). PageUp / PageDown "
    "or Alt+Wheel change it while moving":
        "スナップするまでの、動かしている点とスナップ点の画面上の距離です。インターフェイスの拡大率 1 "
        "のときの値で、拡大率に合わせて大きくなります。移動中は PageUp / PageDown か Alt＋ホイールで変えられます",
    "Snap Point Limit": "スナップ点の上限",
    "Most snap points collected when a move starts, nearest objects first. Past the limit, "
    "objects get only their bounding box corners and origin, and the farthest are left out":
        "移動を始めるときに集めるスナップ点の上限です。近いオブジェクトから集め、上限を超えると"
        "バウンディングボックスの角と原点だけにし、さらに遠いものは対象外にします",
    "Snap Search": "候補の探し方",
    "How snap candidates are looked up during a move. Both methods find the same "
    "candidates; only the speed differs":
        "移動中にスナップ候補を探す方法です。どちらも見つかる候補は同じで、違うのは速さだけです",
    "Screen-space Grid": "画面上の格子",
    "Sort the snap points into a grid on screen, redone when the view changes (default)":
        "スナップ点を画面上の格子に振り分けます。視点を変えると振り分け直します（初期値）",
    "3D KD-tree (Experimental)": "3D KD-tree（実験的）",
    "Narrow the snap points down in 3D with a KD-tree built when the move starts, then "
    "check their distance on screen. Usually slower than the grid, and much slower when "
    "many snap points crowd around the moving point":
        "移動を始めるときに作る KD-tree で 3D 空間の候補を絞り、画面上の距離を調べます。"
        "通常は格子より遅く、動かしている点の周りに点が密集していると大幅に遅くなります",
    "Shortcut": "ショートカット",
    "The shortcut is not available (no keymap in this session)":
        "ショートカットを表示できません（このセッションにはキーマップがありません）",
    "Guide Color": "ガイドの色",
    "Color of the guide line and target marker before snapping":
        "スナップする前のガイド線と目標マーカーの色です",
    "Snap Color": "スナップ時の色",
    "Color of the guide line and target marker while snapped":
        "スナップしている間のガイド線と目標マーカーの色です",
    "Snap To and Align Only are set per scene in the 3D Viewport: Sidebar (N) > Tool > "
    "Snaxis":
        "スナップ先と座標合わせは、シーンごとに 3D ビューポートのサイドバー（N）> "
        "ツール > Snaxis で設定します",

    # Status bar during a move
    "Move Freely": "スナップしない",

    # Viewport labels during a move
    "Snapped": "スナップ中",
    "Projected": "投影",
    "Pulling": "引き寄せ中",
    "{object} vertex": "{object} の頂点",
    "{object} bounding box": "{object} のバウンディングボックス",
    "{axis} coordinate of {object}": "{object} の {axis} 座標",
    "Moved {distance}": "{distance} 移動",
    "Moved {distance} along {axis}": "{axis} 軸に沿って {distance} 移動",
    "Moved {distance} on {plane}": "{plane} 平面上で {distance} 移動",
    "Nothing to snap to.": "スナップ先がありません。",
    "Same Mesh works in Edit Mode. Press S to snap to other objects":
        "「同じメッシュ」は編集モードで使います。S キーでほかのオブジェクトにスナップできます",
    "Choose a collection in the sidebar": "サイドバーでコレクションを指定してください",
    "Select the objects to snap to before moving":
        "スナップ先のオブジェクトを選択してから移動を始めてください",
    "No visible meshes found": "表示中のメッシュが見つかりません",
    "Align Only {axes} is paused while the move is locked to {constraint}":
        "{constraint} に拘束している間は、{axes} 座標をそろえません",
    "Snap point limit reached: far objects use fewer points":
        "スナップ点の上限に達したため、遠くのオブジェクトは点を減らしています",
}

# Operator names are looked up in the "Operator" context as well.
OPERATOR_MESSAGES = ("Move with Guides",)

LOCALES = ("ja_JP",)


def translations() -> dict:
    table = {("*", msgid): msgstr for msgid, msgstr in MESSAGES.items()}
    for msgid in OPERATOR_MESSAGES:
        table[("Operator", msgid)] = MESSAGES[msgid]
    return {locale: table for locale in LOCALES}


def register():
    unregister()
    bpy.app.translations.register(__package__, translations())


def unregister():
    try:
        bpy.app.translations.unregister(__package__)
    except (ValueError, RuntimeError):
        pass


def iface(msgid: str) -> str:
    """Interface text in the current language (when Translate Interface is on)."""
    return bpy.app.translations.pgettext_iface(msgid)


def tip(msgid: str) -> str:
    """Tooltip text in the current language (when Translate Tooltips is on)."""
    return bpy.app.translations.pgettext_tip(msgid)


def rpt(msgid: str) -> str:
    """Report text in the current language (when Translate Reports is on)."""
    fn = getattr(bpy.app.translations, "pgettext_rpt", None) or bpy.app.translations.pgettext_iface
    return fn(msgid)
