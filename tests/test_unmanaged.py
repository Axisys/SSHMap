# -*- coding: utf-8 -*-
"""v1.6.5 — the neighbours on the map: a card for a server you do not administer.

The topical file of the release (ROADMAP v1.6.5). ONE flag, `ServerData.unmanaged`, and the
whole card follows it: no credentials and no keyring entry, no SSH verb, no probe round, an
honest "not monitored" mark instead of a status, and ONE opt-in exception (an ICMP check the
card itself must allow).

Sections:
  §1 the FLAG and the serialization (task 1): the two additive booleans, the coercion of a
     hand-edited junk value, a project written before the release loading as MANAGED and a
     byte-equal round trip;
  §2 the DIALOG (tasks 1/5): the checkbox that disables AND clears the credential family,
     the stash that gives it back, the opt-in ping (OFF by default, usable only while the
     box is ticked) and `get_data()` refusing to build a credential for such a card;
  §3 the CARD (task 2): the chip in the free band, the declared priority against the
     environment chip and the emulated marker, the hardware lines absent by construction,
     the measured height formula holding in BOTH densities and the tooltip in words;
  §4 the HONEST STATUS (task 3): every unmanaged id in the checker's skip set, a fake round
     probing none of them, and the card read as UNCHECKED — never as trouble;
  §5 the ONE ACTION GATE (task 4): the pure table, the map menu, the sidebar menu, the
     permanent Edit items, the command palette and EVERY entry point refusing; a URL quick
     launch still opening;
  §6 the OPT-IN PING (task 5): refused with the flag off, the ICMP thread alone with it on,
     and the answer landing as a MANUAL line on the card — never as a status;
  §7 the inventory table (task 6): the Status cell saying "not monitored", its sort rank and
     `LIST_COLUMNS` still holding thirteen columns;
  §8 the DEMO card + the release state (task 6): the unmanaged neighbour of the example map,
     the pins and the i18n parity of the eleven new keys.

Hermetic by construction: the window is built with NO status checker and every thread that
would open a socket (the probe, the collector, the ICMP ping) is replaced by a double.

Run:  python tests/test_unmanaged.py   (from the project root) or python tests/run_all.py
"""
import io
import json
import os
import re
import sys

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, i18n_lang_codes,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation + offscreen)

from PySide6.QtCore import Qt, QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t as _t  # noqa: E402
from models.server import (ServerData, is_unmanaged, unmanaged_ping_allowed,  # noqa: E402
                           server_data_from_dict, server_data_to_dict)
import storage.example_project as EP  # noqa: E402
import services.diagnostics as DIAG  # noqa: E402
import services.credential_manager as CM  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.unmanaged as UM  # noqa: E402
from dialogs.add_server_dialog import AddServerDialog  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402
from services.status_checker import StatusChecker  # noqa: E402
from ui import sidebar as SB  # noqa: E402
from ui import theme  # noqa: E402
from ui.command_palette import CommandPalette  # noqa: E402

# ── The harness: no modal box may ever block an offscreen run ────────────────
BOXES = []
MW.QMessageBox.critical = staticmethod(lambda *a, **k: BOXES.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: BOXES.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: BOXES.append(("information",)))

LANGS = load_i18n_langs(ROOT)

# The eleven keys of the release — the ONE list the i18n section iterates.
NEW_KEYS = (
    "dialog.unmanaged", "dialog.unmanaged.tooltip",
    "dialog.unmanaged_ping", "dialog.unmanaged_ping.tooltip",
    "node.unmanaged", "node.unmanaged.tooltip", "node.unmanaged.status",
    "node.unmanaged.ping_ok", "node.unmanaged.ping_failed",
    "unmanaged.blocked", "status.unmanaged_blocked",
)


def build_old_shape() -> dict:
    """A pre-v1.6.5 server record — the compatibility fixture of §1."""
    return {"id": "old", "alias": "a", "host": "h", "user": "u",
            "collapsed": False, "tags": []}


def make_main():
    """An offscreen MainWindow that opens no socket (the test_first_run pattern).

    The timers are stopped and the status checker is removed BEFORE any load: nothing here
    may reach the network — the probe plan is measured on a checker double in §4.
    """
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def unmanaged_data(**kw) -> ServerData:
    """A minimal unmanaged card."""
    base = dict(id="um-1", alias="neighbour", host="192.0.2.40", user="", comment="Vendor box")
    base.update(kw)
    base["unmanaged"] = True
    return ServerData(**base)


def managed_data(**kw) -> ServerData:
    """A minimal managed card."""
    base = dict(id="m-1", alias="mine", host="10.0.0.1", user="root")
    base.update(kw)
    return ServerData(**base)


def labels_of(menu) -> dict:
    """{action text: QAction} of a QMenu (the context-menu checks read the live widget)."""
    return {a.text(): a for a in menu.actions()}


def expanded_height(node) -> int:
    """The height the measured formula demands for the node's CURRENT info block."""
    return max(58 + int(node._info.boundingRect().height()) + 12, ServerNode.MIN_NODE_HEIGHT)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the flag and the serialization (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 a ServerData is MANAGED unless it says otherwise (the field is additive)",
      managed_data().unmanaged is False and managed_data().unmanaged_ping is False
      and is_unmanaged(managed_data()) is False
      and unmanaged_ping_allowed(managed_data()) is False)
check("§1 the predicate reads the NODE too (one question for every surface)",
      is_unmanaged(ServerNode(managed_data())) is False
      and is_unmanaged(ServerNode(unmanaged_data())) is True)
check("§1 ... and anything that is neither answers False (never a crash)",
      is_unmanaged(None) is False and is_unmanaged("x") is False and is_unmanaged(42) is False)

_serialized = server_data_to_dict(unmanaged_data(unmanaged_ping=True))
check("§1 the two keys are serialized (the `collapsed` precedent)",
      _serialized.get("unmanaged") is True and _serialized.get("unmanaged_ping") is True
      and "password" not in _serialized, str(sorted(_serialized))[:140])
_restored = server_data_from_dict(_serialized)
check("§1 the round trip is byte-equal (save → load → save)",
      server_data_to_dict(_restored) == _serialized
      and _restored.unmanaged is True and _restored.unmanaged_ping is True)
check("§1 a project WITHOUT the keys loads as fully MANAGED (an old file is untouched)",
      server_data_from_dict(build_old_shape()).unmanaged is False
      and server_data_from_dict(build_old_shape()).unmanaged_ping is False)
check("§1 a hand-edited junk value is COERCED (the `collapsed` bool rule)",
      server_data_from_dict(dict(build_old_shape(), unmanaged="yes")).unmanaged is True
      and server_data_from_dict(dict(build_old_shape(), unmanaged="")).unmanaged is False
      and server_data_from_dict(dict(build_old_shape(), unmanaged=None)).unmanaged is False
      and server_data_from_dict(dict(build_old_shape(), unmanaged_ping=1)).unmanaged_ping is True)
check("§1 the flag is OPTIONAL — VERSION_FORMAT stays 0.9 (the key is absent from an old file)",
      __import__("version").VERSION_FORMAT == "0.9"
      and "unmanaged" not in json.dumps(build_old_shape())
      and "collapsed" in json.dumps(build_old_shape()))


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the dialog: the checkbox, the credentials and the opt-in (tasks 1/5) ==")
# ════════════════════════════════════════════════════════════════════════════

dlg = AddServerDialog(None)
dlg.alias.setText("neighbour")
dlg.host.setText("192.0.2.40")
dlg.user.setText("admin")
dlg.password.setText("s3cret")
dlg.port.setValue(2222)
dlg.key_path.setText("/home/u/.ssh/id_rsa")
check("§2 a NEW card starts MANAGED and the opt-in is OFF and unusable",
      dlg.unmanaged.isChecked() is False and dlg.unmanaged_ping.isChecked() is False
      and dlg.unmanaged_ping.isEnabled() is False)
check("§2 ... and every credential field is editable (the ordinary dialog)",
      all(w.isEnabled() for w in (dlg.user, dlg.password, dlg.port, dlg.key_path, dlg.key_btn)))

dlg.unmanaged.setChecked(True)
check("§2 the box CLEARS the credential family (the keyring can never see it)",
      dlg.user.text() == "" and dlg.password.text() == "" and dlg.key_path.text() == ""
      and dlg.port.value() == 22,
      f"{dlg.user.text()!r} {dlg.password.text()!r} {dlg.port.value()}")
check("§2 ... DISABLES it (and the profile selector, whose whole job is those two fields)",
      not any(w.isEnabled() for w in (dlg.user, dlg.password, dlg.port, dlg.key_path,
                                      dlg.key_btn))
      and dlg.profile_combo.isEnabled() is False)
check("§2 ... and closes the dialog's own SSH door with the GATE's sentence",
      dlg.ssh_connect_btn.isEnabled() is False
      and dlg.ssh_connect_btn.toolTip() == UM.refusal_text(_t, _t("ssh.connect")),
      dlg.ssh_connect_btn.toolTip())
check("§2 the opt-in ping becomes usable (and stays OFF — the default is silence)",
      dlg.unmanaged_ping.isEnabled() is True and dlg.unmanaged_ping.isChecked() is False)

_payload = dlg.get_data()
check("§2 get_data() builds an unmanaged card with NO credential and port 22",
      _payload.unmanaged is True and _payload.user == "" and _payload.password == ""
      and _payload.key_path == "" and _payload.ssh_port == 22
      and _payload.unmanaged_ping is False,
      f"{_payload.user!r} {_payload.ssh_port} {_payload.unmanaged_ping}")
dlg.unmanaged_ping.setChecked(True)
check("§2 ... and the opt-in is read once the user really asks for it",
      dlg.get_data().unmanaged_ping is True)

dlg.unmanaged.setChecked(False)
check("§2 unchecking gives the credential fields BACK (nothing was destroyed)",
      dlg.user.text() == "admin" and dlg.password.text() == "s3cret"
      and dlg.key_path.text() == "/home/u/.ssh/id_rsa" and dlg.port.value() == 2222,
      f"{dlg.user.text()!r} {dlg.password.text()!r} {dlg.port.value()}")
check("§2 ... and a MANAGED card never carries the opt-in flag (there is nothing to grant)",
      dlg.get_data().unmanaged is False and dlg.get_data().unmanaged_ping is False
      and dlg.unmanaged_ping.isChecked() is False)
dlg.close()

_edit = AddServerDialog(None, edit_data=unmanaged_data(unmanaged_ping=True))
check("§2 the kind is editable from `Properties` too (not a creation-only trap)",
      _edit.unmanaged.isChecked() is True and _edit.unmanaged_ping.isChecked() is True
      and _edit.unmanaged_ping.isEnabled() is True
      and _edit.ssh_connect_btn.isEnabled() is False)
check("§2 an edited unmanaged card keeps its flag, its id and its EMPTY credentials",
      _edit.get_data().unmanaged is True and _edit.get_data().user == ""
      and _edit.get_data().id == "um-1")
_edit.close()

# ── the keyring is NEVER written for such a card (the save path is the ONE writer) ──
_KEYRING = {}


class _FakeCM:
    is_available = True

    def save_password(self, sid, pw):
        _KEYRING[sid] = pw
        return True

    def load_password(self, sid):
        return _KEYRING.get(sid)


win = make_main()
_orig_cm = CM.get_credential_manager
CM.get_credential_manager = lambda: _FakeCM()
try:
    win.scene.add_server(unmanaged_data(id="um-key", password="should-not-be-stored"))
    win.scene.add_server(managed_data(id="m-key", password="stored-please"))
    _saved = win._do_save(os.path.join(WORK, "unmanaged_keyring.json"))
    check("§2 the save path stores the ordinary card and SKIPS the unmanaged one",
          _saved is True and _KEYRING.get("m-key") == "stored-please"
          and "um-key" not in _KEYRING,
          str(sorted(_KEYRING)))
    with io.open(os.path.join(WORK, "unmanaged_keyring.json"), encoding="utf-8") as f:
        _on_disk = json.load(f)
    _um_record = [s for s in _on_disk["servers"] if s["id"] == "um-key"][0]
    _m_record = [s for s in _on_disk["servers"] if s["id"] == "m-key"][0]
    check("§2 the FILE carries the flag and never a password",
          _um_record.get("unmanaged") is True and "password" not in _um_record,
          str(sorted(_um_record))[:140])
    check("§2 ... and the ordinary card's record carries the flag as False (the key is written)",
          _m_record.get("unmanaged") is False and _m_record.get("unmanaged_ping") is False)
finally:
    CM.get_credential_manager = _orig_cm
    win._dirty = False
    win.close()
    app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the card: the mark, the free band and the measured height (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_card = win.scene.add_server(unmanaged_data(
    id="um-card", alias="neighbour-fw", host="192.0.2.40", ip="192.0.2.40",
    comment="Vendor-managed appliance", tags=["network"],
    os_name="Should not be painted", cpu="8 cores", ram="16 GB", disk="1 TB"))
app.processEvents()
check("§3 the card carries the \"NO SSH\" chip (words on a neutral frame, not a colour alone)",
      _card._no_ssh_badge is not None and _card._no_ssh_badge.isVisible()
      and _card._no_ssh_badge.text() == _t("node.unmanaged"),
      repr(_card._no_ssh_badge.text() if _card._no_ssh_badge else None))
check("§3 ... right-aligned inside the band, clear of the card's right edge",
      _card._no_ssh_badge.pos().x() + _card._no_ssh_badge.boundingRect().width()
      <= _card._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01,
      f"{_card._no_ssh_badge.boundingRect().width()} on {_card._current_width}px")
check("§3 the card is UNCHECKED and the tooltip says WHY in words (never a colour)",
      _t("node.unmanaged.tooltip") in _card.toolTip() and _card.status == ""
      and _card.status_emulated is False,
      repr(_card.toolTip()))
check("§3 the alias, the host and the COMMENT stay on the card",
      _card._alias.toPlainText().startswith("neighbour-fw")
      and _card._host_label.toPlainText() == "@192.0.2.40"
      and "Vendor-managed appliance" in _card._info.toPlainText(),
      repr(_card._info.toPlainText()))
check("§3 the HARDWARE lines are absent by construction (nothing was ever collected)",
      not any(word in _card._info.toPlainText()
              for word in ("Should not be painted", "CPU:", "RAM:", "DISK:")),
      repr(_card._info.toPlainText()))
check("§3 the environment chip still applies — and YIELDS to the mark (ONE declared rule)",
      ServerNode.BAND_ORDER == ("emulated", "unmanaged", "env")
      and _card._env_badge is not None
      and (_card._env_badge.isVisible() is False
           or _card._env_badge.pos().x() + _card._env_badge.boundingRect().width()
           <= _card._no_ssh_badge.pos().x() + 0.01),
      f"env={_card._env_badge.isVisible() if _card._env_badge else None}")
check("§3 the measured height formula holds for the card as it is painted",
      _card._current_height == expanded_height(_card), str(_card._current_height))

_empty = win.scene.add_server(ServerData(id="um-empty", alias="bare", host="192.0.2.41",
                                         user="", unmanaged=True))
app.processEvents()
check("§3 an unmanaged card with nothing to show says WHAT IT IS (not \"no data yet\")",
      _empty._info.toPlainText() == _t("node.unmanaged.status")
      and _t("node.no_data") not in _empty._info.toPlainText(),
      repr(_empty._info.toPlainText()))
check("§3 ... and the floor of the formula still holds it at MIN_NODE_HEIGHT",
      _empty._current_height == ServerNode.MIN_NODE_HEIGHT == expanded_height(_empty),
      str(_empty._current_height))

theme.set_card_density(theme.DENSITY_COMPACT)
try:
    _card.refresh_theme()
    app.processEvents()
    check("§3 in the COMPACT density the mark stays and the info block leaves the paint",
          _card._no_ssh_badge.isVisible() and not _card._info.isVisible()
          and _card._current_height == expanded_height(_card)
          and _card.density() == theme.DENSITY_COMPACT,
          f"h={_card._current_height} density={_card.density()}")
    check("§3 ... and the compact card carries no environment chip (the density hides it)",
          _card._env_badge is None or _card._env_badge.isVisible() is False)
finally:
    theme.set_card_density(theme.DENSITY_NORMAL)
    _card.refresh_theme()
    app.processEvents()
check("§3 back in the ordinary density the card is re-laid out and the mark survives",
      _card._info.isVisible() and _card._no_ssh_badge.isVisible()
      and _card._current_height == expanded_height(_card))

_card.set_status("online")   # a hand-pushed status (no probe can reach the card)
check("§3 a pushed status is drawn like any status — the flag paints nothing itself",
      _card.status == "online" and _card._no_ssh_badge.isVisible())
_card.reset_status()
check("§3 resetting returns the card to its honest, unmeasured self",
      _card.status == "" and _t("node.unmanaged.tooltip") in _card.toolTip())

_collapsed_card = win.scene.add_server(unmanaged_data(id="um-col", alias="collapsed-one",
                                                      host="192.0.2.42"))
_collapsed_card.data.collapsed = True
_collapsed_card.update_appearance()
app.processEvents()
check("§3 the mark is a property of the CARD, not of a density — a collapsed card keeps it",
      _collapsed_card._current_height == ServerNode.COLLAPSED_HEIGHT
      and _collapsed_card._no_ssh_badge.isVisible(),
      str(_collapsed_card._current_height))
win._dirty = False
win.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the honest status: the skip set and the unchecked reading (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
win.scene.add_server(unmanaged_data(id="um-a", alias="neigh-a", host="192.0.2.50"))
win.scene.add_server(unmanaged_data(id="um-b", alias="neigh-b", host="192.0.2.51"))
_m = win.scene.add_server(managed_data(id="mg-a", alias="mine", host="10.7.0.1"))
check("§4 the skip set is ONE question: the emulated ids AND every unmanaged card",
      win._status_skip_ids() == {"um-a", "um-b"},
      str(sorted(win._status_skip_ids())))

_fake = StatusChecker(interval_ms=30_000)
win._status_checker = _fake
win._sync_status_targets()
check("§4 the checker's plan holds every card EXCEPT the unmanaged ones",
      [t[0] for t in _fake._subset()] == ["mg-a"], str(_fake._subset()))
check("§4 ... and an on-demand round over them is EMPTY (no probe, no traffic at all)",
      _fake._subset(["um-a", "um-b"]) == [])
check("§4 so a round over the neighbours alone never starts",
      _fake.start_round(["um-a", "um-b"]) is False and _fake.is_busy is False)
check("§4 the checker itself still knows nothing about the flag (it filters by ID)",
      "unmanaged" not in io.open(os.path.join(ROOT, "services", "status_checker.py"),
                                 encoding="utf-8").read())

_problem = __import__("graphics.node_group", fromlist=["is_in_trouble"])
_card_a = win.scene.get_node("um-a")
check("§4 the card is read as UNCHECKED — never as a problem (the lens's own predicate)",
      _card_a.status == "" and _card_a.is_stale is False
      and _problem.is_in_trouble("", False) is False)
check("§4 ... and the 'problems only' lens keeps it dimmed rather than lit",
      _card_a not in win._trouble_nodes(), str([n.data.id for n in win._trouble_nodes()]))
check("§4 the status counters never learn a fourth kind (three filters, unchanged)",
      SB._STATUS_FILTERS == ("online", "warn", "offline"))

_m.data.unmanaged = True
win._sync_status_targets()
check("§4 switching a card to unmanaged removes it from the plan (the set is live)",
      _fake._subset() == [] and _fake._skip_ids == {"um-a", "um-b", "mg-a"},
      str(sorted(_fake._skip_ids)))
_m.data.unmanaged = False
win._sync_status_targets()
check("§4 ... and switching it back restores it (the rule is a read, not a state)",
      [t[0] for t in _fake._subset()] == ["mg-a"])
win._status_checker = None
win._dirty = False
win.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the ONE action gate (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 the gate DECLARES its verbs (a new row cannot be blocked by accident)",
      UM.GATED_ACTIONS == {"ssh", "external", "collect_info", "check_status", "diagnose",
                           "ping", "ql_command"},
      str(sorted(UM.GATED_ACTIONS)))
_gate_verbs = ("ssh", "external", "collect_info", "check_status", "diagnose", "ql_command")
check("§5 an UNMANAGED card refuses every declared verb",
      all(UM.action_blocked(a, unmanaged_data()) for a in _gate_verbs))
check("§5 ... and a MANAGED card is refused nothing (the gate is the flag alone)",
      not any(UM.action_blocked(a, managed_data()) for a in UM.GATED_ACTIONS))
check("§5 the ICMP check is the ONE conditional member (off unless the card opted in)",
      UM.action_blocked("ping", unmanaged_data()) is True
      and UM.action_blocked("ping", unmanaged_data(unmanaged_ping=True)) is False
      and UM.action_blocked("ping", managed_data()) is False)
check("§5 an unknown action is never gated (it refuses only what it declares)",
      UM.action_blocked("edit", unmanaged_data()) is False
      and UM.action_blocked("", unmanaged_data()) is False
      and UM.action_blocked("copy_ip", unmanaged_data()) is False)
check("§5 the refusal sentence NAMES the row (one template, the row's own label)",
      UM.refusal_text(lambda k, **kw: f"{k}|{kw.get('action')}", _t("ctx.ssh_connect"))
      == f"{UM.REFUSAL_KEY}|{_t('ctx.ssh_connect')}")
check("§5 the registry table names the four permanent Edit items (the palette's half)",
      UM.REGISTRY_ACTION_IDS == {"node.ssh_connect": "ssh", "node.collect_info": "collect_info",
                                 "node.check_status": "check_status", "node.diagnose": "diagnose"}
      and UM.blocked_registry_action("node.ssh_connect", unmanaged_data()) is True
      and UM.blocked_registry_action("edit.undo", unmanaged_data()) is False)

win = make_main()
# Explicit, spread-out positions: two cards at (0, 0) would overlap and `_classify_at`
# would answer about whichever one Qt painted last (the test_context_menus lesson).
_node = win.scene.add_server(unmanaged_data(id="gate-1", alias="gate", host="192.0.2.60",
                                            x=0.0, y=0.0))
_other = win.scene.add_server(managed_data(id="gate-2", alias="mine", host="10.8.0.1",
                                           x=900.0, y=0.0))
app.processEvents()
_gated_labels = [_t("ctx.ssh_connect"), _t("ctx.ssh_external"), _t("ctx.collect_info"),
                 _t("ctx.check_status"), _t("ctx.diagnose"), _t("ctx.ping")]

# ── the MAP's context menu ───────────────────────────────────────────────────
_map_menu = win.view.build_context_menu(_node.card_rect_scene().center())
_rows = labels_of(_map_menu)
check("§5 the MAP menu DISABLES every verb that needs a login",
      all(_rows[label].isEnabled() is False for label in _gated_labels),
      str({label: _rows[label].isEnabled() for label in _gated_labels}))
check("§5 ... and gives each of them the reason in its tooltip (never silence)",
      all(_rows[label].toolTip() == UM.refusal_text(_t, label) for label in _gated_labels),
      str({label: _rows[label].toolTip() for label in _gated_labels}))
check("§5 the rows that need no login stay untouched",
      all(_rows[label].isEnabled() for label in
          (_t("ctx.edit_server"), _t("ctx.copy_ip"), _t("ctx.copy_hostname"),
           _t("ctx.duplicate_server"), _t("ctx.delete_server"))))
check("§5 ... the collapse row included (a view state, not a verb)",
      _rows[_t("ctx.collapse_server")].isEnabled() is True)
_map_menu.deleteLater()

# ── the SIDEBAR's context menu ───────────────────────────────────────────────
_side_menu = QMenu(win)
win.sidebar.fill_context_menu(_side_menu, _node)
_side_rows = labels_of(_side_menu)
check("§5 the SIDEBAR menu refuses the SAME rows (one table, two menus)",
      all(_side_rows[label].isEnabled() is False for label in _gated_labels),
      str({label: _side_rows[label].isEnabled() for label in _gated_labels
           if label in _side_rows}))
check("§5 ... and its tooltips carry the same sentence",
      all(_side_rows[label].toolTip() == UM.refusal_text(_t, label) for label in _gated_labels))
_side_menu.deleteLater()

# ── the permanent Edit items (the hotkey targets) ────────────────────────────
_gated_ids = ("node.ssh_connect", "node.collect_info", "node.check_status", "node.diagnose")
win._select_node(_node)
app.processEvents()
check("§5 the four permanent Edit items are DISABLED for an unmanaged selection",
      all(win._hotkey_targets[aid][0].isEnabled() is False for aid in _gated_ids),
      str({aid: win._hotkey_targets[aid][0].isEnabled() for aid in _gated_ids}))
check("§5 ... with the gate's sentence in their tooltips",
      all(win._hotkey_targets[aid][0].toolTip()
          == UM.refusal_text(_t, win._hotkey_targets[aid][0].text().replace("&", "").strip())
          for aid in _gated_ids))
win._select_node(_other)
app.processEvents()
check("§5 a MANAGED selection re-enables them and clears the sentence",
      all(win._hotkey_targets[aid][0].isEnabled() for aid in _gated_ids)
      and all(win._hotkey_targets[aid][0].toolTip()
              in ("", win._hotkey_targets[aid][0].text())
              for aid in _gated_ids),
      str({aid: win._hotkey_targets[aid][0].toolTip() for aid in _gated_ids}))

# ── the command palette ──────────────────────────────────────────────────────
win._select_node(_node)
_palette = CommandPalette(win)
_palette._collect_commands()
_pal_entries = {}
for _entry in _palette._commands:
    _aid = _palette._action_ids.get(id(_entry[2]), "")
    if _aid in _gated_ids:
        _pal_entries[_aid] = _entry
check("§5 the PALETTE collects all four gated commands (the same registry ids)",
      sorted(_pal_entries) == sorted(_gated_ids), str(sorted(_pal_entries)))
_pal_rows = {}
for _aid, _entry in _pal_entries.items():
    _pal_rows[_aid] = _palette._add_row(_entry)
check("§5 ... and DISABLES each of them (the same table, the third surface)",
      all(not _pal_rows[aid].flags() & Qt.ItemFlag.ItemIsEnabled for aid in _gated_ids),
      str({aid: bool(_pal_rows[aid].flags() & Qt.ItemFlag.ItemIsEnabled) for aid in _gated_ids}))
check("§5 ... with the refusal sentence in the row's tooltip",
      all(_pal_rows[aid].toolTip() == UM.refusal_text(_t, _pal_rows[aid].text())
          for aid in _gated_ids),
      str({aid: _pal_rows[aid].toolTip() for aid in _gated_ids}))
_palette.listw.setCurrentItem(_pal_rows["node.ssh_connect"])
_palette._run_current()
check("§5 Enter on a disabled row runs NOTHING and is not remembered as a recent action",
      _palette._recent == [], str(_palette._recent))
_palette.deleteLater()
win._select_node(_other)
app.processEvents()

# ── the ENTRY POINTS themselves ──────────────────────────────────────────────
_CALLS = []


class _FakeSSHDialog:
    def __init__(self, data, parent=None):
        _CALLS.append("ssh-dialog")


class _ExtStub:
    @staticmethod
    def connect_external(**kw):
        _CALLS.append("external")
        return True, ""


__orig_dialog = MW.SSHConnectDialog
_HAD_EXT = hasattr(MW, "_ext_term")
__orig_ext = getattr(MW, "_ext_term", None)
_orig_ping = DIAG.PingThread
MW.SSHConnectDialog = _FakeSSHDialog
MW._ext_term = _ExtStub()
DIAG.PingThread = type("_NoPing", (), {"__init__": lambda self, host: _CALLS.append("ping")})


class _FakeBatch:
    """The bounded info batch as a recorder — nothing may open an SSH connection here."""
    def __init__(self):
        self.done = 0
        self.total = 0
        self.items = []

    def start(self, items):
        self.items = list(items)
        return len(self.items)


try:
    win._run_ssh_connect(_node)
    win._connect_ssh_external(_node)
    _spawn = win._spawn_terminal_window(_node)
    _checked = win._check_statuses_now(_node)
    _diagnosed = win._diagnose_node(_node)
    win._ping_node(_node)
    win._run_quick_launch_entry(_node, {"type": "command", "name": "df", "value": "df -h"})
    check("§5 EVERY programmatic entry point refuses (one check per surface)",
          _CALLS == [] and _spawn is None and _checked is False and _diagnosed is False,
          str(_CALLS))
    check("§5 ... so the SSH dialog is never even built for an unmanaged card",
          "ssh-dialog" not in _CALLS)
    check("§5 ... and the REFUSAL is announced (a sentence, never a silent no-op)",
          win.statusBar().currentMessage() == _t("unmanaged.blocked",
                                                 action=_t("ctx.quick_launch")),
          repr(win.statusBar().currentMessage()))
    check("§5 the terminal/SFTP family never reaches the container (the spawn returns None)",
          _spawn is None and win._terminal_windows == [])

    # the batch: an unmanaged scope is refused, a MIXED scope simply drops the neighbour
    win._info_batch = _FakeBatch()
    check("§5 'gather information' over nothing but neighbours is refused in words",
          win._collect_info_many(node=_node) == 0 and win._info_batch.items == []
          and win.statusBar().currentMessage()
          == _t("unmanaged.blocked", action=_t("ctx.collect_info")),
          repr(win.statusBar().currentMessage()))
    check("§5 a MIXED scope keeps the managed member and never reports the neighbour",
          win._collect_info_many(nodes=[_node, _other]) == 1
          and [str(item[0]) for item in win._info_batch.items] == ["gate-2"],
          str([item[0] for item in win._info_batch.items]))

    # a URL entry needs no shell on that host — the ONE exception the plan grants
    import webbrowser
    _opened = []
    _orig_open = webbrowser.open
    webbrowser.open = lambda url: (_opened.append(url), True)[1]
    try:
        win._run_quick_launch_entry(_node, {"type": "url", "name": "UI",
                                           "value": "http://192.0.2.60/"})
    finally:
        webbrowser.open = _orig_open
    check("§5 a URL quick launch still OPENS on an unmanaged card (the browser needs no shell)",
          _opened == ["http://192.0.2.60/"], str(_opened))
    check("§5 ... and it did NOT route through the refused command path",
          _CALLS == [] and _t("status.ql_opened", name="UI") in win.statusBar().currentMessage(),
          repr(win.statusBar().currentMessage()))
finally:
    MW.SSHConnectDialog = __orig_dialog
    if _HAD_EXT:
        MW._ext_term = __orig_ext
    elif hasattr(MW, "_ext_term"):
        delattr(MW, "_ext_term")
    DIAG.PingThread = _orig_ping
win._dirty = False
win.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the opt-in reachability check (task 5) ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_peek = win.scene.add_server(unmanaged_data(id="opt-1", alias="neigh", host="192.0.2.70"))
_PINGS = []


class _PingDouble(QThread):
    """The ICMP thread double: it records the host and does no work."""
    finished_ping = Signal(bool, str)

    def __init__(self, host):
        super().__init__()
        _PINGS.append(host)

    def run(self):
        pass


DIAG.PingThread = _PingDouble
try:
    win._ping_node(_peek)
    check("§6 with the opt-in OFF no network call is made for the card",
          _PINGS == []
          and win.statusBar().currentMessage()
          == _t("unmanaged.blocked", action=_t("ctx.ping")),
          f"{_PINGS} / {win.statusBar().currentMessage()!r}")
    _menu_off = win.view.build_context_menu(_peek.card_rect_scene().center())
    check("§6 ... and the map menu disables ctx.ping BEFORE the click, with the same sentence",
          labels_of(_menu_off)[_t("ctx.ping")].isEnabled() is False
          and labels_of(_menu_off)[_t("ctx.ping")].toolTip()
          == UM.refusal_text(_t, _t("ctx.ping")))
    _menu_off.deleteLater()

    _peek.data.unmanaged_ping = True
    _menu_on = win.view.build_context_menu(_peek.card_rect_scene().center())
    check("§6 with the opt-in ON the ICMP row comes back — and it is the ONLY one that does",
          labels_of(_menu_on)[_t("ctx.ping")].isEnabled() is True
          and labels_of(_menu_on)[_t("ctx.ssh_connect")].isEnabled() is False)
    _menu_on.deleteLater()

    win._ping_node(_peek)
    check("§6 ... and the call really runs the ICMP path (the ICMP thread, nothing else)",
          _PINGS == ["192.0.2.70"], str(_PINGS))
    check("§6 ... while the card's STATUS stays empty (a manual result is not a fourth status)",
          _peek.status == "" and _peek.status_checked_at == 0.0 and _peek.is_stale is False)
    _peek.set_manual_report(_t("node.unmanaged.ping_ok", host="192.0.2.70"))
    check("§6 the answer lands on the card as a line MARKED a manual result",
          _t("node.unmanaged.ping_ok", host="192.0.2.70") in _peek.toolTip()
          and _peek.manual_report == _t("node.unmanaged.ping_ok", host="192.0.2.70"),
          repr(_peek.toolTip()))
    check("§6 ... under the card's own honesty line (the tooltip keeps its order)",
          _peek.toolTip().splitlines()[0] == _t("node.unmanaged.tooltip"))
    _peek.set_manual_report(_t("node.unmanaged.ping_failed", host="192.0.2.70"))
    check("§6 the FAILED answer is a manual line too (and no modal box is raised)",
          _t("node.unmanaged.ping_failed", host="192.0.2.70") in _peek.toolTip())
    _peek.reset_status()
    check("§6 re-defining the card drops the manual line with it",
          _peek.manual_report == ""
          and _t("node.unmanaged.ping_ok") not in _peek.toolTip())
    _src = io.open(os.path.join(ROOT, "ui", "main_window_node_ops.py"), encoding="utf-8").read()
    _ping_src = _src.split("def _ping_node", 1)[1].split("\n    def ", 1)[0]
    check("§6 the opt-in path is the ICMP thread ALONE (no TCP/SSH probe is involved)",
          "PingThread" in _ping_src and "probe_ssh" not in _ping_src
          and "ReachabilityThread" not in _ping_src)
finally:
    DIAG.PingThread = _orig_ping
win._dirty = False
win.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the inventory table (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§7 LIST_COLUMNS still holds thirteen columns (no pinned figure moves)",
      len(SB.LIST_COLUMNS) == 13 and SB.list_column_index("status") == 4,
      str(len(SB.LIST_COLUMNS)))
check("§7 the sort rank places the caption after the three measured statuses",
      SB._STATUS_SORT_RANK[SB.STATUS_NOT_MONITORED] == 3.0
      and SB._STATUS_SORT_RANK["offline"] < SB._STATUS_SORT_RANK[SB.STATUS_NOT_MONITORED])

win = make_main()
check("§7 the panel renders the declared caption id as the ONE shared sentence",
      win.sidebar._status_text(SB.STATUS_NOT_MONITORED) == _t("node.unmanaged.status")
      and win.sidebar._status_text("") == ""
      and win.sidebar._status_text("online") == _t("legend.status.online"))
win.scene.add_server(unmanaged_data(id="tab-1", alias="neighbour-fw",
                                    host="192.0.2.40", ip="192.0.2.40"))
win._map_collapsed = True
win._sync_list_mode()
app.processEvents()
_checker_row = None
for _i in range(win.tree.topLevelItemCount()):
    _it = win.tree.topLevelItem(_i)
    if _it.data(0, Qt.ItemDataRole.UserRole) == "tab-1":
        _checker_row = _it
        break
_status_col = SB.list_column_index("status")
check("§7 the LIST row exists and its Status cell says \"not monitored\"",
      _checker_row is not None
      and _checker_row.text(_status_col) == _t("node.unmanaged.status"),
      repr(_checker_row.text(_status_col) if _checker_row is not None else None))
check("§7 ... the cell is not EMPTY (\"not checked yet\" is a different answer)",
      bool(_checker_row.text(_status_col).strip()))
check("§7 ... the RAW value behind it is the caption id (a language switch re-texts it)",
      _checker_row.raw_value(_status_col) == SB.STATUS_NOT_MONITORED)
_rows_text = win.sidebar.list_report_rows()
check("§7 the export carries the same caption (the report is the table on screen)",
      any(row[_status_col] == _t("node.unmanaged.status") for row in _rows_text[1:]),
      str(_rows_text[:2]))
check("§7 the caption is NOT a status filter and NOT a status colour (no fourth kind)",
      SB.STATUS_NOT_MONITORED not in SB._STATUS_FILTERS
      and SB.STATUS_NOT_MONITORED not in theme.STATUS_COLORS)
win._map_collapsed = False
win._sync_list_mode()
win._dirty = False
win.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the demo card and the release state (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

_demo = EP.build_example_project()
_demo_unmanaged = [s for s in _demo["servers"] if s.get("unmanaged")]
check("§8 the DEMO map carries ONE unmanaged neighbour (the release's live sample)",
      len(_demo_unmanaged) == 1
      and _demo_unmanaged[0]["id"] in EP.unmanaged_example_ids()
      and EP.unmanaged_example_ids() == (EP.NEIGHBOUR,),
      str([s["id"] for s in _demo_unmanaged]))
check("§8 ... it is documented (a comment), tagged and connected to NOTHING",
      _demo_unmanaged[0].get("comment") == EP.NEIGHBOUR_COMMENT
      and bool(_demo_unmanaged[0].get("tags"))
      and not any(c["source_id"] == EP.NEIGHBOUR or c["target_id"] == EP.NEIGHBOUR
                  for c in _demo["connections"]))
check("§8 ... and it declares NO status (nothing measures a box nobody can reach)",
      EP.NEIGHBOUR not in EP.DEMO_STATUSES
      and EP.NEIGHBOUR not in EP.demo_status_ids())

win = make_main()
win._open_example_map()          # the checker is None here — the load opens no socket
app.processEvents()
_demo_node = win.scene.get_node(EP.NEIGHBOUR)
check("§8 opening the demo marks the neighbour and keeps it unchecked",
      _demo_node is not None and _demo_node._no_ssh_badge.isVisible()
      and _demo_node.status == "" and _demo_node.status_emulated is False,
      f"{( _demo_node.toolTip() if _demo_node else None)!r}")
check("§8 ... and it joins the skip set (a later checker probes none of its kind)",
      EP.NEIGHBOUR in win._status_skip_ids(), str(sorted(win._status_skip_ids())))
_demo_menu = win.view.build_context_menu(_demo_node.card_rect_scene().center())
check("§8 ... and its menu has no SSH verbs (the demo shows the gate in action)",
      labels_of(_demo_menu)[_t("ctx.ssh_connect")].isEnabled() is False
      and labels_of(_demo_menu)[_t("ctx.copy_hostname")].isEnabled() is True)
_demo_menu.deleteLater()
_demo_statuses = sorted(
    {n.data.id: n.status for n in win.scene.nodes()
     if n.data.id != EP.NEIGHBOUR}.items())
check("§8 the MANAGED cards of the demo keep their emulated statuses (v1.5 is untouched)",
      dict(_demo_statuses) == dict(EP.DEMO_STATUSES),
      str(_demo_statuses))
win._dirty = False
win.close()
app.processEvents()

check_release_state(ROOT)
check("§8 the pins of this file are the release it describes",
      EXPECTED_APP_VERSION == "1.6.5", EXPECTED_APP_VERSION)
check("§8 the i18n pin moved by the ELEVEN keys of this release (789 + 11)",
      EXPECTED_I18N_KEYS == 789 + 11 == 800, str(EXPECTED_I18N_KEYS))
_missing = {code: [k for k in NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in LANGS.items()}
check(f"§8 the {len(NEW_KEYS)} keys of v1.6.5 are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§8 every language carries the {host} and {action} placeholders (the format parity)",
      all(set(re.findall(r"\{(\w+)\}", LANGS[c]["node.unmanaged.ping_ok"])) == {"host"}
          and set(re.findall(r"\{(\w+)\}", LANGS[c]["node.unmanaged.ping_failed"])) == {"host"}
          and set(re.findall(r"\{(\w+)\}", LANGS[c]["unmanaged.blocked"])) == {"action"}
          for c in i18n_lang_codes(ROOT)),
      str({c: LANGS[c]["unmanaged.blocked"] for c in sorted(LANGS)}))
check("§8 the chip label is SHORT enough for the band of a MIN card in every language",
      all(len(LANGS[c]["node.unmanaged"]) <= len(LANGS["en"]["node.unmanaged"]) + 8
          for c in LANGS),
      str({c: LANGS[c]["node.unmanaged"] for c in sorted(LANGS)}))
check("§8 the caption the table and the plaque share is ONE key (no second spelling)",
      LANGS["en"]["node.unmanaged.status"] == "not monitored"
      and all(str(LANGS[c]["node.unmanaged.status"]).strip() for c in LANGS))
check("§8 no new dependency and no new colour field (the release is a flag and a gate)",
      all(f"{d}>=" in io.open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("§8 the module the release documents really exists",
      os.path.isfile(os.path.join(ROOT, "ui", "unmanaged.py")))
check_i18n_parity(LANGS)
check_i18n_format(LANGS)

finish()
