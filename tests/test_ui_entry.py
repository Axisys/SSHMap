# -*- coding: utf-8 -*-
"""v1.9.7 — the first ten minutes (ROADMAP v1.9.7): the card that is really compact, the Add
Server dialog's four declared sections and their hints, the empty map that stops pointing at
nothing, and the ONE dashed selection frame the card and the group share.

The topical test of the release: offscreen, no network, no real session. §1 the compact card's
OWN floor and the unchanged elision (§4.6, `graphics/server_node.py`); §2 the dialog's labels,
placeholders, sections and footer; §3 the two shipped strings of the catalogue; §4 the empty
map's two questions, the status sentence and the TXT door; §5 the selection's declared pattern
and §6 the i18n parity and the release state."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QLineEdit, QSpinBox

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, read_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

app = QApplication(sys.argv)

import i18n
from models.server import ServerData
import ui.main_window as MW
from ui import theme
from graphics.server_node import ServerNode

# The TXT door must be the window's ORDINARY import path: the class-level patch is installed
# BEFORE the window is built, so the connection the overlay makes lands on the recorder.
_imports = []
MW.MainWindow._import_servers_from_txt = lambda self, *a, **k: _imports.append(1)


def make_card(alias="web-01", host="192.0.2.10", **kw):
    """A card laid out in the ACTIVE density (the density is read live, never cached)."""
    return ServerNode(ServerData(id="entry-card", alias=alias, host=host, user="root", **kw))


def layout(card, density):
    """Re-lay the card out in one density and answer (width, height, alias, host)."""
    theme.set_card_density(density)
    card._density = density
    card.update_appearance()
    return (card._current_width, card._current_height,
            card._alias.toPlainText(), card._host_label.toPlainText())


def make_main():
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def close_window(win):
    win._dirty = False
    win._undo_baseline_dirty = False
    win.close()
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The compact card (task 1)
# ════════════════════════════════════════════════════════════
print("== 1. the compact card ==")

check("§1 the mode declares its OWN floor and the ordinary one does not move",
      ServerNode.COMPACT_NODE_HEIGHT < ServerNode.MIN_NODE_HEIGHT
      and ServerNode.MIN_NODE_HEIGHT == 130,
      f"compact={ServerNode.COMPACT_NODE_HEIGHT} normal={ServerNode.MIN_NODE_HEIGHT}")

_cases = (
    ("one info line", dict(ip="192.0.2.10")),
    ("the info line is the widest", dict(comment="a long comment no host line would ever reach")),
    ("a dense card", dict(os_name="Ubuntu 22.04", cpu="Xeon", ram="32 gb", ip="192.0.2.10")),
    ("nothing collected at all", {}),
    ("an unmanaged card", dict(unmanaged=True)),
)
_sizes = []
for _name, _kw in _cases:
    _card = make_card(**_kw)
    _normal = layout(_card, theme.DENSITY_NORMAL)
    _painted = _card._info.isVisible()
    _compact = layout(_card, theme.DENSITY_COMPACT)
    _sizes.append((_name, _normal, _compact, _card._info.isVisible()))
    check(f"§1 compact < normal on the height, the plaque leaves the paint ({_name})",
          _compact[1] < _normal[1] and _compact[1] == ServerNode.COMPACT_NODE_HEIGHT
          and _painted is True and _card._info.isVisible() is False,
          f"{_normal[:2]} -> {_compact[:2]} info={_painted}/{_card._info.isVisible()}")
theme.set_card_density(theme.DENSITY_NORMAL)

check("§1 no identifier is elided EARLIER than the ordinary layout elides it "
      "(the width comes from the same content)",
      all(_compact[0] >= _normal[0] for _n, _normal, _compact, _vis in _sizes),
      str([(_n, _normal[0], _compact[0]) for _n, _normal, _compact, _vis in _sizes]))
check("§1 ...and the alias/host really painted are the same text in both modes",
      all(_compact[2] == _normal[2] and _compact[3] == _normal[3]
          for _n, _normal, _compact, _vis in _sizes),
      str([(_n, _normal[2], _compact[2], _normal[3], _compact[3])
           for _n, _normal, _compact, _vis in _sizes]))

# The widest-content case: the ordinary card is stretched by its info line, and the compact one
# is not allowed to be narrower — the N69 defect (10 px + one character of the host).
_wide = make_card(comment="a comment line that stretches the ordinary card to its cap")
_wide_normal = layout(_wide, theme.DENSITY_NORMAL)
_wide_compact = layout(_wide, theme.DENSITY_COMPACT)
theme.set_card_density(theme.DENSITY_NORMAL)
check("§1 the widest-info card keeps the ordinary width in compact (the N69 measurement)",
      _wide_compact[0] == _wide_normal[0] and _wide_compact[1] < _wide_normal[1],
      f"{_wide_normal[:2]} -> {_wide_compact[:2]}")

# The FREE BAND rule: a badge is painted in the band and never enters the height.
_bare = layout(make_card(), theme.DENSITY_COMPACT)
_badged = layout(make_card(tags=["production"]), theme.DENSITY_COMPACT)
theme.set_card_density(theme.DENSITY_NORMAL)
check("§1 a badge never enters the height — the compact floor is the floor either way",
      _badged[1] == _bare[1] == ServerNode.COMPACT_NODE_HEIGHT
      and _badged[0] >= _bare[0],
      f"bare={_bare[:2]} badged={_badged[:2]}")

# ════════════════════════════════════════════════════════════
# 2. The Add Server dialog (tasks 2-4)
# ════════════════════════════════════════════════════════════
print("== 2. the Add Server dialog ==")

from dialogs.add_server_dialog import AddServerDialog  # noqa: E402

i18n.set_language("en")
dlg = AddServerDialog()

_groups = dlg.findChildren(QGroupBox)
check("§2 the sixteen flat rows are FOUR declared sections (one QGroupBox each)",
      len(_groups) == 4
      and [g.title() for g in _groups] == [i18n.t("server.section.identity"),
                                           i18n.t("server.section.connection"),
                                           i18n.t("server.section.hardware"),
                                           i18n.t("server.section.notes")],
      str([g.title() for g in _groups]))

_main = dlg.layout()
check("§2 the sections keep the declared reading order, after the profile block",
      _main.indexOf(dlg.identity_group) > 0
      and _main.indexOf(dlg.identity_group) < _main.indexOf(dlg.connection_group)
      < _main.indexOf(dlg.hardware_group) < _main.indexOf(dlg.notes_group),
      str([_main.indexOf(g) for g in (dlg.identity_group, dlg.connection_group,
                                      dlg.hardware_group, dlg.notes_group)]))


def _label(form, row):
    item = form.itemAt(row, form.ItemRole.LabelRole)
    return item.widget().text() if item is not None and item.widget() is not None else ""


check("§2 Identity carries the two required fields, both MARKED",
      dlg.identity_form.rowCount() == 2
      and _label(dlg.identity_form, 0).endswith("*")
      and _label(dlg.identity_form, 1).endswith("*")
      and i18n.t("server.alias") in _label(dlg.identity_form, 0)
      and i18n.t("server.host") in _label(dlg.identity_form, 1),
      f"{_label(dlg.identity_form, 0)!r} / {_label(dlg.identity_form, 1)!r}")
check("§2 ...and the marker explains itself in a tooltip",
      dlg.identity_form.itemAt(0, dlg.identity_form.ItemRole.LabelRole).widget().toolTip()
      == i18n.t("server.required_hint"))
check("§2 the key row is no longer the one field WITHOUT a label (N70), and its button says what it opens",
      _label(dlg.connection_form, 5) == i18n.t("server.key_label")
      and bool(_label(dlg.connection_form, 5).strip())
      and dlg.key_btn.toolTip() == i18n.t("server.key_tooltip")
      and dlg.key_btn.text() == i18n.t("server.key"),
      f"{_label(dlg.connection_form, 5)!r} / {dlg.key_btn.toolTip()!r}")
check("§2 the two checkboxes left the row under `Host` (they are rows of Connection now)",
      all(_label(dlg.connection_form, r) == "" for r in (0, 1))
      and dlg.connection_form.itemAt(0, dlg.connection_form.ItemRole.FieldRole).widget()
      is dlg.unmanaged
      and dlg.connection_form.itemAt(1, dlg.connection_form.ItemRole.FieldRole).widget()
      is dlg.unmanaged_ping
      and dlg.unmanaged.parentWidget() is not dlg.host,
      f"{_label(dlg.connection_form, 0)!r} {_label(dlg.connection_form, 1)!r}")

_placeholders = {"alias": "server.alias_hint", "host": "server.host_hint",
                 "user": "server.user_hint", "key_path": "server.key_hint"}
check("§2 the four fields of the critical path carry example placeholders",
      all(getattr(dlg, _f).placeholderText() == i18n.t(_k)
          for _f, _k in _placeholders.items()),
      str({_f: getattr(dlg, _f).placeholderText() for _f in _placeholders}))
check("§2 the PASSWORD field carries none, and no placeholder replaces a label",
      dlg.password.placeholderText() == "" and dlg.password.echoMode() == QLineEdit.Password
      and all(_label(dlg.identity_form, r) for r in range(dlg.identity_form.rowCount()))
      and all(_label(dlg.connection_form, r) for r in (2, 3, 4, 5)))
check("§2 the SSH port keeps its label and its range as the hint (no placeholder)",
      isinstance(dlg.port, QSpinBox) and dlg.port.minimum() == 1 and dlg.port.maximum() == 65535
      and _label(dlg.connection_form, 4) == i18n.t("server.port"))
check("§2 the footer says what it does: `Save` (never the ambiguous `OK`)",
      dlg.buttons.button(dlg.buttons.StandardButton.Ok).text() == i18n.t("btn.save"),
      dlg.buttons.button(dlg.buttons.StandardButton.Ok).text())
check("§2 ...and the second action carries its promise in a tooltip",
      dlg.ssh_connect_btn.toolTip() == i18n.t("btn.save_and_connect")
      and dlg.ssh_connect_btn.text() == i18n.t("ssh.connect"),
      dlg.ssh_connect_btn.toolTip())
check("§2 the hardware and notes groups still hold their own fields",
      dlg.hardware_form.rowCount() == 5 and dlg.notes_form.rowCount() == 3
      and dlg.hardware_form.itemAt(3, dlg.hardware_form.ItemRole.FieldRole).widget()
      is dlg.disk_device_row,
      f"hardware={dlg.hardware_form.rowCount()} notes={dlg.notes_form.rowCount()}")
dlg.alias.setText("grouped")
check("§2 the dialog still builds its data (the grouping changed no field)",
      dlg.get_data().alias == "grouped")
dlg.deleteLater()

# ════════════════════════════════════════════════════════════
# 3. The two shipped strings (task 5)
# ════════════════════════════════════════════════════════════
print("== 3. the strings ==")

LANGS = load_i18n_langs(ROOT)
check("§3 `server.os` carries the colon its three siblings carry — in ALL four files",
      all(str(LANGS[c].get("server.os", "")).rstrip().endswith((":", "：")) for c in LANGS),
      str({c: LANGS[c].get("server.os") for c in LANGS}))
check("§3 ...and the language files were NOT normalised by a regex (zh keeps its own colons)",
      LANGS["zh"]["server.tags"].endswith("：") and LANGS["en"]["server.tags"].endswith(":"),
      f"{LANGS['zh']['server.tags']!r} {LANGS['en']['server.tags']!r}")
check("§3 the device field's placeholder names the DEVICE and states no rule",
      all("win" not in LANGS[c]["server.disk_device_hint"].lower()
          and "важнее" not in LANGS[c]["server.disk_device_hint"]
          and "sda" in LANGS[c]["server.disk_device_hint"] for c in LANGS),
      str({c: LANGS[c]["server.disk_device_hint"] for c in LANGS}))
check("§3 ...because the rule lives in the tooltip the field ALREADY had",
      all(any(_word in LANGS[c]["server.disk_device_tooltip"]
              for _word in ("WINS", "ВАЖНЕЕ", "优先", "GEWINNT")) for c in LANGS))
_disk_dlg = AddServerDialog()
check("§3 the live dialog applies exactly that pair",
      _disk_dlg.disk_device.lineEdit().placeholderText()
      == LANGS["en"]["server.disk_device_hint"]
      and _disk_dlg.disk_device.toolTip() == LANGS["en"]["server.disk_device_tooltip"])
_disk_dlg.deleteLater()

# ════════════════════════════════════════════════════════════
# 4. The empty map (task 6)
# ════════════════════════════════════════════════════════════
print("== 4. the empty map ==")

clear_cfg()
win = make_main()
overlay = win.empty_state

check("§4 a fresh window really is the empty map the first screen is about",
      len(list(win.scene.nodes())) == 0 and overlay.is_state_visible())
check("§4 the minimap asks TWO questions — the key is ON, the panel is OFF, nothing written away",
      win._minimap_enabled is True and win.minimap.isHidden() is True
      and win.minimap.isVisible() is False and read_cfg({}).get("ui_minimap") is None,
      f"key={win._minimap_enabled} hidden={win.minimap.isHidden()} cfg={read_cfg({})}")
check("§4 the status bar shows no node-properties hint while there is no node",
      win._status_ready_text() == "" and win.statusBar().currentMessage() == "",
      repr(win.statusBar().currentMessage()))
check("§4 the first screen offers the TXT import as a BUTTON beside the other doors",
      len(overlay.buttons()) == 4 and overlay.btn_import.isVisible()
      and overlay.btn_import.text() == i18n.t("file.import_servers"),
      str([b.text() for b in overlay.buttons()]))
check("§4 ...and it is no longer a phrase inside the hint sentence",
      i18n.t("file.import_servers") not in overlay.hint_text()
      and i18n.t("file.import_ssh_config") in overlay.hint_text(),
      overlay.hint_text())
check("§4 the four doors stay inside the view (the card never leaves the canvas)",
      overlay.x() >= 0 and overlay.x() + overlay.width() <= win.view.width()
      and all(b.geometry().right() <= win.view.width() for b in overlay.buttons()),
      f"card={overlay.geometry()} view={win.view.width()}")

overlay.btn_import.click()
app.processEvents()
check("§4 the button runs the window's OWN import path (File → Import Servers from TXT…)",
      len(_imports) == 1, str(len(_imports)))

win.scene.add_server(ServerData(id="entry-n1", alias="first", host="10.0.0.1", user="root"))
win._update_counts_label()
app.processEvents()
check("§4 the first card brings the minimap back — and that return wrote no preference",
      win.minimap.isVisible() is True and read_cfg({}).get("ui_minimap") is None,
      f"hidden={win.minimap.isHidden()} cfg={read_cfg({})}")
check("§4 ...and the idle sentence names the gesture again (the action can happen now)",
      win._status_ready_text() == i18n.t("status.ready"), repr(win._status_ready_text()))

win.scene.remove_server("entry-n1")
win._update_counts_label()
app.processEvents()
check("§4 the last card takes the panel away again and the first screen returns",
      win.minimap.isHidden() is True and overlay.is_state_visible()
      and win._status_ready_text() == "")

win.act_show_minimap.setChecked(False)
win.act_show_minimap.setChecked(True)
check("§4 the View item still writes the PREFERENCE (the two questions wrap it, never replace it)",
      win._minimap_enabled is True and read_cfg({}).get("ui_minimap") is True
      and win.minimap.isHidden() is True,
      f"cfg={read_cfg({}).get('ui_minimap')} hidden={win.minimap.isHidden()}")
close_window(win)

# ════════════════════════════════════════════════════════════
# 5. The selection frame (task 7)
# ════════════════════════════════════════════════════════════
print("== 5. the selection frame ==")

clear_cfg()
win = make_main()
_node = win.scene.add_server(ServerData(id="entry-sel", alias="sel", host="10.0.0.2",
                                        user="root"))
app.processEvents()

check("§5 ONE declared pattern and ONE declared width for a selected frame",
      isinstance(theme.SELECTION_DASH_PATTERN, tuple) and len(theme.SELECTION_DASH_PATTERN) == 2
      and all(float(v) > 0 for v in theme.SELECTION_DASH_PATTERN)
      and theme.SELECTION_FRAME_WIDTH > 2,
      f"{theme.SELECTION_DASH_PATTERN} / {theme.SELECTION_FRAME_WIDTH}")
check("§5 the pattern is distinct from the scene's two provisional dashes",
      theme.SELECTION_DASH_PATTERN != (4.0, 3.0)
      and theme.SELECTION_DASH_PATTERN != (4.0, 2.0),
      str(theme.SELECTION_DASH_PATTERN))

_plain = _node._state_pen()
check("§5 an unselected card's frame is SOLID (the pattern is the selection's alone)",
      _plain.style() == Qt.PenStyle.SolidLine, str(_plain.style()))

_node.setSelected(True)
_sel = _node._state_pen()
check("§5 a selected card's frame is DASHED at the declared pattern",
      _sel.style() == Qt.PenStyle.CustomDashLine
      and list(_sel.dashPattern()) == [float(v) for v in theme.SELECTION_DASH_PATTERN],
      f"{_sel.style()} {list(_sel.dashPattern())}")
check("§5 ...and keeps its width above the status frame's 2 px, in the amber selection",
      _sel.widthF() == float(theme.SELECTION_FRAME_WIDTH) > 2.0
      and _sel.color().name() == theme.SELECTION_AMBER.lower(),
      f"{_sel.widthF()} {_sel.color().name()}")
_node.setSelected(False)
check("§5 deselecting returns the SOLID frame (the pattern is a state, not a style leak)",
      _node._state_pen().style() == Qt.PenStyle.SolidLine)

_group = win.scene.add_group(name="entry group", x=-40, y=-40, width=300, height=200)
_group.setSelected(True)
_colors = _group._state_colors()
check("§5 a selected GROUP answers the SAME decision (the N79 second implementation)",
      _colors[1] == theme.SELECTION_FRAME_WIDTH
      and _colors[4] == Qt.PenStyle.CustomDashLine
      and _colors[0].name() == theme.SELECTION_AMBER.lower(),
      f"width={_colors[1]} style={_colors[4]}")
_group.setSelected(False)
check("§5 ...and the group's other states stay SOLID",
      _group._state_colors()[4] == Qt.PenStyle.SolidLine)
close_window(win)

# ════════════════════════════════════════════════════════════
# 6. i18n parity + the release state
# ════════════════════════════════════════════════════════════
print("== 6. i18n parity + release state ==")

_new_keys = ("btn.save", "btn.save_and_connect",
             "server.section.identity", "server.section.connection",
             "server.section.hardware", "server.section.notes",
             "server.alias_hint", "server.host_hint", "server.user_hint",
             "server.key_hint", "server.required_hint", "server.key_tooltip")
check("§6 the twelve v1.9.7 keys are present and non-empty in EVERY language",
      all(str(LANGS[c].get(k, "")).strip() for c in LANGS for k in _new_keys),
      str({c: [k for k in _new_keys if not str(LANGS[c].get(k, "")).strip()] for c in LANGS}))
check("§6 the four section titles are DISTINCT values in every language",
      all(len({LANGS[c][f"server.section.{_s}"] for _s in
               ("identity", "connection", "hardware", "notes")}) == 4 for c in LANGS))
check("§6 the value-only changes kept their keys (nothing was deleted or renamed)",
      all(k in LANGS[c] for c in LANGS
          for k in ("server.os", "server.key_label", "server.disk_device_hint",
                    "empty.state.import_hint", "status.ready")))
check_i18n_parity(LANGS)
check_release_state(ROOT)

finish()
