# -*- coding: utf-8 -*-
"""v1.5.6 — the customer requests: the Export menu, a third first-run button, environment
icons, buttons that look like buttons.

The **sixth patch ON the released 1.5**, and four changes asked for by the people who run the
shipped line. The topical file of the release; the mechanism lives in `DOCUMENTATION.md` and
the history in `CHANGELOG.md` (v1.5.6).

  §1 the EXPORT MENU: a top-level container BETWEEN "Edit" and "Profile" that takes every
     export of the application, with the SAME actions, ids and `file.*` keys (a `hotkeys`
     value of `config.json` is keyed by the ACTION ID, so a rename would drop a user's
     binding), while File keeps the project's life;
  §2 the THIRD DOOR of the first screen: "open an existing map" between the primary action
     and the demo, wired to the window's ORDINARY project-open path;
  §3 the ENVIRONMENT moves from the 5 px left strip into the card's own ICON (the primary
     tag's tone) in both card modes — a card without tags keeps its neutral tone;
  §4 the badge chip is CENTRED ON THE ALIAS ROW (the alias owns the left side, the marks and
     the chevron the right) and still elides or hides when the room is short;
  §5 the two collapse "◇" become BUTTONS: a frame from the ONE QSS registry entry, the map
     button bigger and still inside the view;
  §6 the release state (the version, the two keys in every language, the unchanged contract).

Run: python tests/test_ui_requests.py   (from the project root) or python tests/run_all.py
"""
import os
import re

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, EXPECTED_APP_VERSION,
                     EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

app = QApplication.instance() or QApplication([])

from models.server import ServerData  # noqa: E402
from graphics.server_node import ServerNode, env_tag  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.main_window_project_io as PIO  # noqa: E402
import ui.theme_qss as theme_qss  # noqa: E402
from i18n import t as _t  # noqa: E402
from ui import theme  # noqa: E402
from ui.hotkey_registry import action_family, action_ids  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402

from _fakes import QuestionStub  # noqa: E402

# No modal box may block an offscreen run: a stray question is answered "No" (there is
# nothing to save in this file) and the save dialog is refused, so a load never blocks.
_questions = QuestionStub(QMessageBox.No).install(MW)
_orig_save_dialog = PIO.QFileDialog.getSaveFileName
PIO.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))

_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — the "it lives in ONE place" audits."""
    key = parts
    if key not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[key] = f.read()
    return _SRC[key]


def make_main():
    """An offscreen MainWindow with the timers stopped and NO status checker (hermetic)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def menu_map(win) -> dict:
    """{menu title: QMenu} of the window's menubar (the order is the bar's own)."""
    return {a.text(): a.menu() for a in win.menuBar().actions() if a.menu() is not None}


#: the eight exports of the application — the three groups of the new menu, in order.
_IMAGE_IDS = ("file.export_png", "file.export_drawio", "file.export_pdf", "file.export_svg")
_IMAGE_PAIR = ("file.copy_map", "file.docs_frame")
_DATA_IDS = ("file.copy_list", "file.export_list")
_EXPORT_IDS = _IMAGE_IDS + _IMAGE_PAIR + _DATA_IDS


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the Export menu: a container between Edit and Profile ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_menus = menu_map(win)
_titles = list(_menus)

check("§1 the menubar reads File → Edit → EXPORT → Profile (the new container is 3rd)",
      _titles[:4] == [_t("menu.file"), _t("menu.edit"), _t("menu.export"), _t("menu.profile")],
      str(_titles))
check("§1 the new menu is registered for re-translation (the language switch reaches it)",
      any(w is _menus[_t("menu.export")] and k == "menu.export" for w, k in win._menu_i18n))

_export_menu = _menus[_t("menu.export")]
_export_actions = [a for a in _export_menu.actions() if not a.isSeparator()]
_file_menu = _menus[_t("menu.file")]
_file_actions = [a for a in _file_menu.actions() if not a.isSeparator()]
check("§1 EVERY export of the application lives in the new menu",
      all(win._hotkey_targets[aid][0] in _export_actions for aid in _EXPORT_IDS)
      and len(_export_actions) == len(_EXPORT_IDS),
      f"{len(_export_actions)} items for {len(_EXPORT_IDS)} ids")
check("§1 ...and NO export is left in File (the move is complete, not a copy)",
      not any(win._hotkey_targets[aid][0] in _file_actions for aid in _EXPORT_IDS))

# The three groups are the SUBJECT of the report: image / the clipboard-poster pair / the data.
_seps = [i for i, a in enumerate(_export_menu.actions()) if a.isSeparator()]
check("§1 ...and their LABELS are the `file.*` keys (the i18n family did not move)",
      all(win._hotkey_targets[aid][0].text() == _t(aid) for aid in _EXPORT_IDS),
      str([win._hotkey_targets[aid][0].text() for aid in _EXPORT_IDS]))
check("§1 the separators cut the three readable groups (image · clipboard/poster · data)",
      _seps == [len(_IMAGE_IDS), len(_IMAGE_IDS) + 1 + len(_IMAGE_PAIR)],
      f"separators at {_seps} of {len(_export_menu.actions())}")
check("§1 the action IDS survived the move (a `hotkeys` value is keyed by the id)",
      all(aid in action_ids() for aid in _EXPORT_IDS)
      and all(aid in win._hotkey_targets and win._hotkey_targets[aid] for aid in _EXPORT_IDS))
check("§1 ...and they stay in their `file.*` family (the Hotkeys tab groups them as before)",
      all(aid.startswith("file.") and action_family(aid) == "file" for aid in _EXPORT_IDS))
check("§1 the export items are still created through the ONE menu builder (no hand-made row)",
      all(f'"{aid}"' in _src("ui", "main_window.py") for aid in _EXPORT_IDS)
      and "export_menu" in _src("ui", "main_window.py"))

_project_ids = ("file.new", "file.open", "file.save", "file.save_as", "file.restore_autosave",
                "file.backups", "file.import_servers", "file.import_ssh_config", "file.exit")
check("§1 File keeps the project's life (new / open / save / save as / autosave / backups / "
      "imports / exit)",
      all(win._hotkey_targets[aid][0] in _file_actions for aid in _project_ids),
      str([a.text() for a in _file_actions]))

# The DATA pair keeps its enable rule — the table has to exist (the map collapsed).
win._sync_list_mode()
check("§1 the DATA pair is disabled while the map is expanded (no table on screen)",
      not win.act_copy_list.isEnabled() and not win.act_export_list.isEnabled())
win.act_show_map.setChecked(False)          # a real toggle → _on_map_toggled → _sync_list_mode
app.processEvents()
check("§1 ...and enabled in LIST mode (the same ONE mode resolver stays in charge)",
      win.act_copy_list.isEnabled() and win.act_export_list.isEnabled())
win.act_show_map.setChecked(True)
app.processEvents()

win._switch_language("ru")
app.processEvents()
check("§1 the language switch re-texts the new menu (an ordinary i18n container)",
      menu_map(win).get(_t("menu.export")) is not None
      and _t("menu.export") == _t("menu.export") != "Export",
      _t("menu.export"))
win._switch_language("en")
app.processEvents()
check("§1 ...and the switch back restores the English title",
      _t("menu.export") == "Export" and _t("empty.state.open_map") == "Open an existing map",
      _t("menu.export"))
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the third door of the first screen: an existing map ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_overlay = win.empty_state
check("§2 a fresh empty window shows the hint with THREE doors (ONE declaration)",
      _overlay.is_state_visible() and len(_overlay.buttons()) == 3
      and _overlay.buttons() == (_overlay.btn_add_first, _overlay.btn_open_map,
                                 _overlay.btn_example))
check("§2 the new button carries the new key (and never the raw key as its text)",
      _overlay.btn_open_map.text() == _t("empty.state.open_map")
      and _overlay.btn_open_map.text() not in ("", "empty.state.open_map"),
      _overlay.btn_open_map.text())
check("§2 all three are visible with the hint (one visibility walk)",
      all(b.isVisible() for b in _overlay.buttons()))

_add_geo = _overlay.btn_add_first.geometry()
_open_geo = _overlay.btn_open_map.geometry()
_ex_geo = _overlay.btn_example.geometry()
check("§2 the new door sits BETWEEN the two (the primary action, then it, then the demo)",
      _add_geo.right() <= _open_geo.left() and _open_geo.right() <= _ex_geo.left(),
      f"{_add_geo} {_open_geo} {_ex_geo}")
check("§2 the three share ONE row (the same top and height) and stay inside the card",
      len({g.top() for g in (_add_geo, _open_geo, _ex_geo)}) == 1
      and len({g.height() for g in (_add_geo, _open_geo, _ex_geo)}) == 1
      and _ex_geo.right() <= _overlay.geometry().right()
      and _add_geo.left() >= _overlay.geometry().left(),
      f"card={_overlay.geometry()}")
check("§2 the WIDE card is measured for the three full labels (not one of them)",
      _overlay.width() >= (_add_geo.width() + _open_geo.width() + _ex_geo.width()
                           + 2 * _overlay.GAP),
      f"card={_overlay.width()} row={_add_geo.width()}+{_open_geo.width()}+{_ex_geo.width()}")

# The narrow view: the row shares what there is and the card never leaves the canvas.
win.resize(420, 420)
app.processEvents()
win._position_empty_state()
app.processEvents()
_geos = [b.geometry() for b in _overlay.buttons()]
check("§2 a narrow view shares the row instead of overflowing the card",
      all(g.width() > 0 for g in _geos)
      and all(g.left() >= 0 and g.right() <= _overlay.width() for g in _geos),
      f"card={_overlay.width()} row={_geos}")
check("§2 ...and the three still stay in the same ORDER (the layout never reorders them)",
      _geos[0].right() <= _geos[1].left() and _geos[1].right() <= _geos[2].left(),
      str(_geos))
win.resize(1100, 760)
app.processEvents()
win._position_empty_state()

# The real path: the widget EMITS, the window owns the dialog and the load.
_path = os.path.join(WORK, "opened_by_the_door.json")
with open(_path, "w", encoding="utf-8") as f:
    f.write('{"version": "0.9", "servers": [{"id": "door-1", "alias": "door", '
            '"host": "10.5.5.5", "user": "root", "x": 0, "y": 0}], "connections": []}')
_orig_open_dialog = PIO.QFileDialog.getOpenFileName
PIO.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (_path, ""))
try:
    _overlay.btn_open_map.click()
    app.processEvents()
finally:
    PIO.QFileDialog.getOpenFileName = _orig_open_dialog
check("§2 the new door opens the ORDINARY project path (the dialog → `_load_project_at`)",
      win.scene.node_count() == 1 and win._project_file == _path,
      f"nodes={win.scene.node_count()} file={win._project_file!r}")
check("§2 ...and the opened project is the file's (the drop / File → Open share this path)",
      win.scene.nodes()[0].data.alias == "door")
check("§2 the door is wired by the WINDOW (the widget only emits)",
      hasattr(_overlay, "open_map_requested")
      and "open_map_requested.connect(self._open_project)"
      in _src("ui", "main_window.py").replace(" ", ""))

win._new_project()
app.processEvents()
check("§2 the hint comes back on the cleared map with all three doors",
      _overlay.is_state_visible() and all(b.isVisible() for b in _overlay.buttons()))
win._switch_language("ru")
app.processEvents()
check("§2 the retranslate walk re-texts the third door too",
      _overlay.btn_open_map.text() == _t("empty.state.open_map")
      and _overlay.btn_open_map.text() != "",
      _overlay.btn_open_map.text())
win._switch_language("en")
app.processEvents()
_overlay.set_state_visible(False)
check("§2 hiding the hint hides ALL three buttons (they are siblings, not children)",
      not any(b.isVisible() for b in _overlay.buttons()))
_overlay.set_state_visible(True)
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the environment moves from the strip to the ICON ==")
# ════════════════════════════════════════════════════════════════════════════

#: a realistic record: the info plaque is what makes the card wide enough for the chip.
_FULL = dict(os_name="Ubuntu 22.04.3 LTS x86_64", cpu="Intel Xeon E5-2670 v3",
             ram="32 GB DDR4", disk="512 GB SSD", ip="192.0.2.10")


def card(**kw):
    return ServerNode(ServerData(id="uic-1", host="192.0.2.10", user="root", **_FULL, **kw))


_prod = card(alias="web-01", tags=["prod", "web"])
_staging = card(alias="web-01", tags=["staging"])
_dev = card(alias="web-01", tags=["dev"])
_free = card(alias="web-01", tags=["webfarm", "db"])
_plain = card(alias="web-01")
check("§3 the ICON is the environment channel: `prod` / `staging` / `dev` take the declared tones",
      _prod._icon.brush().color().name() == ServerNode.tag_color("prod").name()
      and _staging._icon.brush().color().name() == ServerNode.tag_color("staging").name()
      and _dev._icon.brush().color().name() == ServerNode.tag_color("dev").name(),
      f"{_prod._icon.brush().color().name()} / {_staging._icon.brush().color().name()}")
check("§3 ...and the declared roles are the theme's own status tones (no new colour)",
      ServerNode.tag_color("prod").name() == QColor(theme.THEME.status_offline).name()
      and ServerNode.tag_color("staging").name() == QColor(theme.THEME.status_warn).name()
      and ServerNode.tag_color("dev").name() == QColor(theme.THEME.status_online).name())
check("§3 an ARBITRARY tag gets its deterministic palette tone on the icon",
      _free._icon.brush().color().name() == ServerNode.tag_color(env_tag(["webfarm", "db"])).name()
      and _free._icon.brush().color().name() in
      {QColor(c).name() for c in ServerNode.TAG_PALETTE})
check("§3 a card WITHOUT tags keeps the neutral tone it has always had",
      _plain._icon.brush().color().name() == QColor(theme.NODE_ICON_BG).name(),
      _plain._icon.brush().color().name())
check("§3 NO strip item survives anywhere (the item, the constants and the builder are gone)",
      not hasattr(_prod, "_tag_segments")
      and not any(n.startswith("TAG_STRIP") for n in dir(ServerNode))
      and "_rebuild_tag_strip" not in dir(ServerNode)
      and "TAG_STRIP" not in _src("graphics", "server_node.py")
      and "_tag_segments" not in _src("graphics", "server_node.py"))

_prod.toggle_collapsed()
check("§3 the tone lives in BOTH card modes (the icon is always on the card)",
      _prod._current_height == ServerNode.COLLAPSED_HEIGHT
      and _prod._icon.brush().color().name() == ServerNode.tag_color("prod").name())
_prod.toggle_collapsed()

_prod.data.tags = ["staging"]
_prod.refresh_tags()
check("§3 `refresh_tags()` (the public hook after an edit) moves the icon tone",
      _prod._icon.brush().color().name() == ServerNode.tag_color("staging").name())
_prod.data.tags = ["prod", "web"]
_prod.refresh_tags()

_dark_icon = _prod._icon.brush().color().name()
theme_qss.apply_theme(theme.LIGHT, app=app, refresh_windows=False)
_prod.refresh_theme()
check("§3 a theme switch re-resolves the icon tone (a brush is a VALUE)",
      _prod._icon.brush().color().name() != _dark_icon
      and _prod._icon.brush().color().name() == ServerNode.tag_color("prod").name(),
      f"{_dark_icon} -> {_prod._icon.brush().color().name()}")
theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)
_prod.refresh_theme()
check("§3 ...and switching back restores the dark tone",
      _prod._icon.brush().color().name() == _dark_icon)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the environment chip in the free band above the alias ==")
# ════════════════════════════════════════════════════════════════════════════

_row = _prod._alias.boundingRect().translated(_prod._alias.pos())
_chip = _prod._env_chip.path().boundingRect()
check("§4 the chip is drawn and says the USER's tag (the TEXT channel survives the strip)",
      _prod._env_badge.isVisible() and _prod._env_badge.text() == "prod",
      repr(_prod._env_badge.text()))
check("§4 it sits in the band ABOVE the alias (the name keeps its whole row)",
      0.0 <= _chip.top() and _chip.bottom() <= _row.top() + 0.01
      and _chip.left() >= ServerNode.LABEL_X - 0.01,
      f"chip={_chip} alias row={_row}")
check("§4 ...left-aligned with the alias and stopping clear of the chevron",
      _chip.right() <= _prod._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01
      and _chip.right() <= _prod._status_dot.pos().x() - 0.01,
      f"chip right={_chip.right()} band right={_prod._current_width - ServerNode.BADGE_RIGHT_INSET}")
check("§4 a badge never enters the card's HEIGHT (the geometry formula is untouched)",
      _chip.top() > 0.0 and _chip.bottom() < _prod._current_height)
check("§4 the chip is tinted with the SAME tone the icon paints (one tag, two channels)",
      _prod._env_chip.pen().color().name() == _prod._icon.brush().color().name())

_long = card(alias="web-01", tags=["free-form-tag-" + "x" * 60])
check("§4 a long tag is ELIDED to the band (and keeps its full tooltip)",
      _long._env_badge.text() != _long.data.tags[0]
      and _long._env_badge.text().endswith("…")
      and _long._env_badge.toolTip() == _long.data.tags[0],
      repr(_long._env_badge.text()))
check("§4 ...and it never leaves the card (the elide is bounded by the band's right edge)",
      _long._env_chip.path().boundingRect().right()
      <= _long._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01)

# v1.5.6 (the customer requests): the chip has a band of its OWN, so the tag is on EVERY
# tagged card — a long name never pushes it off, and the name itself is not shortened for it.
_CUSTOMER = dict(os_name="Ubuntu 24.04.4 LTS", cpu="8 core", ram="15.6 gb", disk="468.4 gb",
                 ip="192.168.3.76", comment="Rancher, VPN")
_elided = ServerNode(ServerData(id="uic-e", alias="master-node-01.example", host="192.168.3.76",
                                user="root", tags=["prod"], **_CUSTOMER))
_alias_only = ServerNode(ServerData(id="uic-f", alias="master-node-01.example", host="192.168.3.76",
                                    user="root", **_CUSTOMER))
check("§4 a LONG alias never pushes the tag off the card (the chip has its own band)",
      _elided._alias.toPlainText().endswith("…")
      and _elided._env_badge is not None and _elided._env_badge.isVisible()
      and _elided._env_badge.text() == "prod",
      f"alias={_elided._alias.toPlainText()!r} W={_elided._current_width}")
check("§4 ...and the name is NOT shortened for the tag (tagged == untagged text)",
      _elided._alias.toPlainText() == _alias_only._alias.toPlainText()
      and _elided._current_width == _alias_only._current_width,
      f"{_elided._alias.toPlainText()!r} vs {_alias_only._alias.toPlainText()!r}")
check("§4 a MIN card carries the chip too (the band is always above the alias)",
      _elided._current_width >= ServerNode.MIN_NODE_WIDTH
      and _prod._env_badge.isVisible())
check("§4 v1.5.6 the alias is a SIZE STEP SMALLER (more of the name fits before the elide)",
      ServerNode.ALIAS_FONT_SIZE == 10
      and _elided._alias.font().pointSize() == ServerNode.ALIAS_FONT_SIZE
      and _elided._alias.font().bold(),
      f"pointSize={_elided._alias.font().pointSize()}")

_narrow = ServerNode(ServerData(id="uic-n", alias="web-01", host="192.0.2.11", user="root",
                                tags=["prod"]))
check("§4 a MIN card with a tag still shows the chip (never a '…'-only one)",
      _narrow._env_badge is not None and _narrow._env_badge.isVisible()
      and not _narrow._env_badge.text().startswith("…"),
      f"text={_narrow._env_badge.text()!r} W={_narrow._current_width}")
check("§4 ...while the ICON carries the environment as well",
      _narrow._icon.brush().color().name() == ServerNode.tag_color("prod").name())
check("§4 the unreadable-elide guard is DECLARED (a font-independent minimum)",
      ServerNode.BADGE_MIN_CHARS >= 2
      and _narrow._badge_readable("p…") is False
      and _narrow._badge_readable("pro…") is True
      and _narrow._badge_readable("prod") is True)

check("§4 a card WITHOUT tags builds no badge item at all (the lazy rule holds)",
      _plain._env_chip is None and _plain._env_badge is None
      and _plain._demo_chip is None and _plain._demo_badge is None)

_msn = card(alias="web-01", tags=["prod"])
_msn.set_status("warn", emulated=True)
_mark = _msn._demo_chip.path().boundingRect()
check("§4 the EMULATED marker keeps its own band and its precedence (placed first)",
      _msn._demo_badge.isVisible() and _mark.bottom() <= 18.0
      and _msn._env_badge.isVisible()
      and not _mark.intersects(_msn._env_chip.path().boundingRect()),
      f"marker={_mark} chip={_msn._env_chip.path().boundingRect()}")


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the collapse diamonds are drawn as BUTTONS ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_side_btn = win.sidebar.collapse_btn
_map_btn = win._map_collapse_btn
check("§5 both corners are plain QToolButtons (no auto-raise — the frame is always drawn)",
      isinstance(_side_btn, QToolButton) and isinstance(_map_btn, QToolButton)
      and not _side_btn.autoRaise() and not _map_btn.autoRaise())
check("§5 the look comes from ONE registry entry (not an inline QSS in the widgets)",
      "collapse.button" in theme_qss.style_names()
      and _side_btn.styleSheet() == theme_qss.style("collapse.button") != ""
      and _map_btn.styleSheet() == theme_qss.style("collapse.button"))
check("§5 ...and the entry really paints a FRAME (a surface fill + a border + a radius)",
      "background-color" in theme_qss.style("collapse.button")
      and "border:" in theme_qss.style("collapse.button")
      and "border-radius" in theme_qss.style("collapse.button")
      and theme.THEME.surface_alt in theme_qss.style("collapse.button"),
      theme_qss.style("collapse.button")[:80])
check("§5 the style is applied by ONE helper (no second copy of the QSS)",
      _src("ui", "main_window.py").count("def _style_collapse_btn") == 1
      and "theme_qss.refresh(btn, \"collapse.button\")" in _src("ui", "main_window.py"))
check("§5 the sidebar button stays in the panel's bottom row, the map's on the view",
      _side_btn.parentWidget() is win.sidebar and _map_btn.parentWidget() is win.view)
check("§5 both still carry the diamond icon (the ink walk is unchanged)",
      not _side_btn.icon().isNull() and not _map_btn.icon().isNull())

win._position_map_collapse_btn()
app.processEvents()
_view_w, _view_h = win.view.width(), win.view.height()
_vp = win.view.viewport().geometry()
check("§5 the framed MAP button is BIGGER than the old 24 px floor (the frame is real)",
      _map_btn.width() > 24 and _map_btn.height() > 24,
      f"{_map_btn.width()}x{_map_btn.height()}")
check("§5 ...and it stays INSIDE the view after the move up and to the left",
      _map_btn.x() >= 0 and _map_btn.y() >= 0
      and _map_btn.x() + _map_btn.width() <= _view_w
      and _map_btn.y() + _map_btn.height() <= _view_h,
      f"btn=({_map_btn.x()},{_map_btn.y()},{_map_btn.width()},{_map_btn.height()}) "
      f"view={_view_w}x{_view_h}")
check("§5 v1.5.6 the corner is the VIEWPORT's (the frame and the SCROLLBARS are excluded)",
      win.COLLAPSE_BTN_MARGIN > 0 and win.COLLAPSE_BTN_RAISE > 0
      and _map_btn.x() + _map_btn.width() <= _vp.right() + 1
      and _map_btn.y() + _map_btn.height() <= _vp.bottom() + 1
      and "viewport().geometry()" in _src("ui", "main_window.py"),
      f"btn={_map_btn.geometry()} viewport={_vp}")
check("§5 v1.5.6 ...and it is raised out of the corner (a different level from the sidebar's)",
      _map_btn.y() + _map_btn.height()
      <= _vp.bottom() + 1 - win.COLLAPSE_BTN_MARGIN - win.COLLAPSE_BTN_RAISE + 1
      and _map_btn.y() != _side_btn.geometry().y(),
      f"map y={_map_btn.y()} sidebar y={_side_btn.geometry().y()} viewport bottom={_vp.bottom()}")
# The reported defect: with content on the map the scrollbars appear — and the button must not
# be drawn over them (it used to sit in the VIEW's corner, which includes both).
for _i in range(4):
    win.scene.add_server(ServerData(id=f"uic-scroll-{_i}", alias=f"node-{_i}", host="10.0.0.9",
                                    user="root", x=_i * 700.0, y=_i * 500.0))
app.processEvents()
app.processEvents()
win._position_map_collapse_btn()
app.processEvents()
_vbar = win.view.verticalScrollBar()
_hbar = win.view.horizontalScrollBar()
check("§5 v1.5.6 the button keeps clear of the SCROLLBARS that appear with content",
      _vbar.isVisible() and _hbar.isVisible()
      and not QRect(_map_btn.geometry()).intersects(QRect(_vbar.geometry()))
      and not QRect(_map_btn.geometry()).intersects(QRect(_hbar.geometry()))
      and _map_btn.x() + _map_btn.width() <= win.view.viewport().geometry().right() + 1,
      f"btn={_map_btn.geometry()} vbar={_vbar.geometry()} hbar={_hbar.geometry()}")
check("§5 ...the placement follows the ranges too (a scrollbar appearing resizes the viewport)",
      "rangeChanged" in _src("ui", "main_window.py"))
check("§5 it is still the bottom-right corner (the top is the minimap's)",
      _map_btn.y() > _view_h // 2 and _map_btn.x() + _map_btn.width() > _view_w // 2)
check("§5 the ONE position resolver owns the move (no second geometry owner)",
      _src("ui", "main_window.py").count("def _position_map_collapse_btn") == 1
      and _src("ui", "main_window.py").count("def _collapse_btn_candidates") == 1
      and "_collapse_btn_candidates(" in _src("ui", "main_window.py"))

theme_qss.apply_theme(theme.LIGHT, app=app, refresh_windows=False)
win._refresh_icons()
check("§5 the theme walk re-applies the frame with the icon ink",
      _side_btn.styleSheet() == theme_qss.style("collapse.button")
      and theme.LIGHT.surface_alt in _side_btn.styleSheet()
      and _map_btn.styleSheet() == _side_btn.styleSheet(),
      _side_btn.styleSheet()[:70])
theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)
win._refresh_icons()
check("§5 ...and the switch back restores the dark frame",
      theme.DARK.surface_alt in _side_btn.styleSheet())

check("§5 the COLLAPSED state is deliberately untouched (the 18 px strip)",
      win._sidebar_strip.minimumWidth() == 18 and win._map_strip.minimumWidth() == 18,
      f"{win._sidebar_strip.minimumWidth()} / {win._map_strip.minimumWidth()}")
check("§5 the buttons still drive the ONE toggle action of their panel",
      win.act_show_sidebar.isChecked())
win.sidebar.collapse_btn.click()
app.processEvents()
check("§5 ...the click collapses the panel through that action (one mechanism, no second path)",
      win.act_show_sidebar.isChecked() is False and win.sidebar.isHidden())
win.act_show_sidebar.setChecked(True)
app.processEvents()
check("§5 ...and the toggle back expands it again",
      win.act_show_sidebar.isChecked() and not win.sidebar.isHidden())
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the release state and the 'no new contract' audit ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("§6 EXPECTED_APP_VERSION is the shipped release (the pin quotes the CURRENT one)",
      EXPECTED_APP_VERSION == "1.5.7.1"
      and re.fullmatch(r"1\.5\.7(\.\d+)?", EXPECTED_APP_VERSION) is not None,
      EXPECTED_APP_VERSION)
check("§6 the pin counts the shipped release (708 + the 29 keys of v1.5.7)",
      EXPECTED_I18N_KEYS == 737, str(EXPECTED_I18N_KEYS))
for _key in ("menu.export", "empty.state.open_map"):
    check(f"§6 the key {_key} is present and non-empty in every discovered language",
          all(str(_langs[code].get(_key) or "").strip() for code in _langs),
          str({c: _langs[c].get(_key) for c in sorted(_langs)}))
check("§6 no new colour field (60 in both themes — the tone is an existing tag colour)",
      len(__import__("dataclasses").fields(theme.Theme)) == 60
      and theme.THEME.tag_colors["prod"] == theme.THEME.status_offline
      and theme.THEME.tag_colors["staging"] == theme.THEME.status_warn)
_hub = SettingsDialog(make_main())
check("§6 no new config key (the settings hub still collects its 22)",
      len(_hub.collect()) == 22
      and not any("export" in k or "empty_state" in k for k in _hub.collect()),
      str(sorted(_hub.collect()))[:120])
_hub.close()
check("§6 no new dependency (the four pinned ones and nothing else)",
      all(f"{d}>=" in _src("requirements.txt")
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("§6 VERSION_FORMAT did not move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9")
check("§6 the registry is untouched by the release (the menu is a CONTAINER, not a family)",
      len(action_ids()) == 56 and len(_EXPORT_IDS) == 8)

_questions.restore()
PIO.QFileDialog.getSaveFileName = _orig_save_dialog
finish()
