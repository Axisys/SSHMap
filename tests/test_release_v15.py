# -*- coding: utf-8 -*-
"""v1.5 — the release that closes the 1.5 line: the environment badge, the panel snap,
the emulated demo statuses.

The closing release of the line "Design & confidence". Its rc series (`1.5rc1` … `1.5rc5`)
froze and implemented the line's contract; this release ships the THREE features the
interface review left over, and they are the last ones that extend nothing:

  * **the environment badge on the server card** — the primary tag as TEXT in the free band
    above the alias, with the tag's colour as a redundant tint (§1);
  * **the floating-panel SNAP** — dropping a panel at the edge it hangs from re-anchors it
    and CLEARS the saved position, so every anchored rule comes back (§2);
  * **the emulated demo statuses** — the demo map declares green/amber/red instead of
    opening grey and settling into five red cards, and an emulated status is always MARKED
    as emulated and never leaves the demo map (§3).

The topical files of the rc series keep their own checks (`test_theme_contrast.py`,
`test_encoding.py`, `test_first_run.py`, `test_chrome.py`, `test_audit_v15rc5.py`); this
file carries the RELEASE-level ones: the version/pins, the cross-cutting acceptance of the
three features, and the "no new contract" audit the ROADMAP demands of a closing release
(no new colour, no new config key, no new action, no new dependency) — §4.

Run: python tests/test_release_v15.py   (from the project root) or python tests/run_all.py
"""
import dataclasses
import os
import re

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from models.server import ServerData  # noqa: E402
from graphics.server_node import ENV_TAGS, ServerNode, env_tag  # noqa: E402
import storage.example_project as EP  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
from ui import theme  # noqa: E402
from i18n import t as _t  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402

_SRC = {}
#: the discovered language files — the parity gate of §4 and the wording checks of §3
_langs = load_i18n_langs(ROOT)


def _src(*parts) -> str:
    """The source of a production file (read once) — for the "it lives in ONE place" audits."""
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


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the environment badge on the server card ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the vocabulary is DECLARED in the card module (one place, precedence order)",
      ENV_TAGS == ("prod", "staging", "stage", "dev", "test")
      and "_apply_env_badge" in _src("graphics", "server_node.py"))
check("§1 the resolver is pure and the vocabulary WINS the pick",
      env_tag(["web", "prod"]) == "prod" and env_tag(["dev", "prod"]) == "prod"
      and env_tag(["Prod"]) == "Prod")
check("§1 ...so a free-form map still gets a header (the FIRST tag, the primary label)",
      env_tag(["webfarm", "db"]) == "webfarm" and env_tag([]) == "")

# A realistic record: the info plaque is what makes the card wide enough for the chip
# (the chip lives on the alias row, so a MIN-width card has no room for it — its ICON
# carries the environment alone, which is exactly the fallback the geometry defines).
_FULL = dict(os_name="Ubuntu 22.04.3 LTS x86_64", cpu="Intel Xeon E5-2670 v3",
             ram="32 GB DDR4", disk="512 GB SSD", ip="192.0.2.10")
_card = ServerNode(ServerData(id="rel-env", alias="web-01", host="192.0.2.10", user="root",
                              tags=["prod", "web"], **_FULL))
check("§1 the badge is TEXT (the meaning) on a tint of the tag colour (the redundant channel)",
      _card._env_badge.text() == "prod"
      and _card._env_chip.pen().color().name() == ServerNode.tag_color("prod").name()
      and _card._env_badge.brush().color().name()
      != _card._env_chip.pen().color().name())
check("§1 v1.5.6 the colour channel is the card's ICON — the strip is gone",
      _card._icon.brush().color().name() == ServerNode.tag_color("prod").name()
      and not hasattr(_card, "_tag_segments")
      and "TAG_STRIP" not in _src("graphics", "server_node.py"))
_plain = ServerNode(ServerData(id="rel-env2", alias="web-01", host="192.0.2.10", user="root",
                               **_FULL))
_long = ServerNode(ServerData(id="rel-env4", alias="web-01", host="192.0.2.10", user="root",
                              tags=["free-form-" + "x" * 60], **_FULL))
check("§1 ...and it does not enter the card's WIDTH formula (an arbitrarily long tag does not "
      "stretch the card)",
      _long._current_width == _plain._current_width
      and _long._env_badge.text().endswith("…")
      and _long._env_badge.toolTip() == "free-form-" + "x" * 60,
      f"{_plain._current_width} vs {_long._current_width} ({_long._env_badge.text()!r})")
_band = _card._env_chip.path().boundingRect()
_alias_row = _card._alias.boundingRect().translated(_card._alias.pos())
check("§1 v1.5 the chip sits in the free band ABOVE the alias (left-aligned with it)",
      0.0 <= _band.top() and _band.bottom() <= _alias_row.top() + 0.01
      and _band.left() >= ServerNode.LABEL_X - 0.01
      and _band.right() <= _card._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01,
      f"{_band} alias row={_alias_row}")
check("§1 a card without tags builds NO badge item (byte-identical to a pre-v1.5 card)",
      _plain._env_chip is None and _plain._env_badge is None and _plain._demo_chip is None
      and _plain._demo_badge is None
      and _plain._icon.brush().color().name() == QColor(theme.NODE_ICON_BG).name())
_plain.toggle_collapsed()
_card.toggle_collapsed()
check("§1 a collapsed card hides the chip (one line, no band) and keeps the TONE",
      _card._env_badge.isVisible() is False
      and _card._icon.brush().color().name() == ServerNode.tag_color("prod").name()
      and _card._current_height == ServerNode.COLLAPSED_HEIGHT)
_card.toggle_collapsed()

check("§1 the badge reuses the tag colour — NO new colour field",
      len(dataclasses.fields(theme.Theme)) == 60
      and not any("env" in f.name or "badge" in f.name
                  for f in dataclasses.fields(theme.Theme)))
_badge_body = _src("graphics", "server_node.py").split("def _apply_env_badge")[1].split(
    "def _apply_demo_badge")[0]
check("§1 the badge text is the USER's tag — no i18n lookup on that path",
      "_t(" not in _badge_body and "env_tag(" in _badge_body)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the floating-panel SNAP (one resolver, two panels) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§2 the threshold is DECLARED once and is twice the 12 px default margin",
      MW.MainWindow.SNAP_PX == 24
      and MW.MainWindow.SNAP_PX == 2 * MW.MainWindow.LEGEND_MARGIN)
check("§2 ONE resolver serves both panels (no second copy of the geometry)",
      _src("ui", "main_window.py").count("def _snap_panel") == 1
      and _src("ui", "main_window.py").count("self._snap_panel(") == 2)
check("§2 the anchored edges are the documented ones (the legend LEFT|BOTTOM, the minimap RIGHT|TOP)",
      '_snap_panel(getattr(self, "legend", None), pos, "lb")' in _src("ui", "main_window.py")
      and '_snap_panel(getattr(self, "minimap", None), pos, "rt")' in _src("ui", "main_window.py"))
check("§2 the saved position is cleared with the NULL sentinel (a merge write cannot delete)",
      '{"x": None, "y": None}' in _src("ui", "main_window.py")
      and MW.MainWindow._saved_position({"x": None, "y": None}) is None
      and MW.MainWindow._saved_position(["a", "b"]) is None)
check("§2 it costs NO new menu entry, action or hotkey (the rejected \"Reset positions\"; "
      "the 56 of v1.5.5 are the inventory pair and the 59 of v1.6 the bulk-edit/arrangement/report trio)",
      not any("reset_panel" in a or "reset.position" in a for a in HR.HOTKEY_ACTIONS)
      and len(HR.HOTKEY_ACTIONS) == 59)

win = make_main()
_legend = win.legend
_view = win.view

# Right at the corner: a drop there is a no-op that re-anchors and clears.
_legend.move(win.LEGEND_MARGIN, _view.height() - _legend.height() - win.LEGEND_MARGIN)
win._on_legend_moved(_legend.pos())
check("§2 dropping the legend at its documented corner clears the saved position",
      win._legend_pos is None and _legend.x() == win.LEGEND_MARGIN)

# Somewhere in the middle: the detached spot is remembered as before.
_legend.move(200, 150)
win._on_legend_moved(_legend.pos())
check("§2 a drop in the middle keeps the detached spot (the snap is a threshold, not a magnet)",
      win._legend_pos == QPoint(200, 150)
      and win.legend.pos() == QPoint(200, 150))

# One pixel outside the threshold vs one pixel inside — the boundary is exact.
_legend.move(win.SNAP_PX + 1, 150)
win._on_legend_moved(_legend.pos())
check("§2 ...exactly SNAP_PX + 1 px from the edge is still detached",
      win._legend_pos == QPoint(win.SNAP_PX + 1, 150), str(win._legend_pos))
_legend.move(win.SNAP_PX, 150)
win._on_legend_moved(_legend.pos())
check("§2 ...and exactly SNAP_PX re-anchors it",
      win._legend_pos is None and _legend.x() == win.LEGEND_MARGIN,
      f"pos={_legend.pos()} saved={win._legend_pos}")

# The minimap's anchored edges are the OTHER two: a drop at the bottom-left stays detached
# for it (BOTTOM and LEFT are not its edges) while that same drop re-anchors the legend.
_mini = win.minimap
_mini.move(30, _view.height() - _mini.height() - 2)
win._on_minimap_moved(_mini.pos())
check("§2 each panel has its OWN anchored edges (the minimap ignores LEFT|BOTTOM)",
      win._minimap_pos == QPoint(30, _mini.y()),
      f"pos={_mini.pos()} saved={win._minimap_pos}")
_mini.move(_view.width() - _mini.width() - 2, 200)
win._on_minimap_moved(_mini.pos())
check("§2 ...and re-anchors at its own RIGHT edge",
      win._minimap_pos is None and _mini.x() == _view.width() - _mini.width() - 12,
      f"pos={_mini.pos()} saved={win._minimap_pos}")

# A hidden panel is placed but never moved by the snap (a hidden widget has no drag).
win.act_show_legend.setChecked(False)
app.processEvents()
_legend.move(500, 300)
win._on_legend_moved(_legend.pos())
check("§2 the panel reports its OWN geometry — the snap reads the live widgets",
      win._legend_pos == QPoint(500, 300), str(win._legend_pos))
win.act_show_legend.setChecked(True)
app.processEvents()
win._dirty = False
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the emulated demo statuses (marked, and never outside the demo) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§3 the demo DECLARES its statuses in code (the format keeps no status field)",
      set(EP.DEMO_STATUSES) == set(EP.demo_status_ids())
      and "DEMO_STATUSES" in _src("storage", "example_project.py")
      and not any("status" in s for s in EP.build_example_project()["servers"][0]))
check("§3 the declaration shows all THREE statuses — the demo is the legend at a glance",
      sorted(set(EP.DEMO_STATUSES.values())) == ["offline", "online", "warn"])

win = make_main()
win._open_example_map()
app.processEvents()
_cards = {n.data.id: n for n in win.scene.nodes()}
check("§3 the demo opens with exactly the declared statuses",
      {sid: n.status for sid, n in _cards.items()} == dict(EP.DEMO_STATUSES),
      str({sid: n.status for sid, n in _cards.items()}))
check("§3 every one of them is MARKED emulated on the card, in the tooltip and by the badge",
      all(n.status_emulated and _t("node.status.emulated") in n.toolTip()
          and n._demo_badge.isVisible()
          and n._demo_badge.text() == _t("node.status.emulated")
          for n in _cards.values()))
check("§3 ...and none of them claims an age (an emulation was never measured)",
      all(n.freshness_text() == "" and n.status_checked_at == 0.0 and n.is_stale is False
          for n in _cards.values()))
check("§3 the declaration is COMPLETE (a node left out would open unchecked)",
      len(_cards) == len(EP.DEMO_STATUSES))

# "Save as" produces an ordinary project: no status in the file, no emulation in the window.
_path = os.path.join(WORK, "release_v15_demo.json")
_saved = win._do_save(_path)
app.processEvents()
with open(_path, encoding="utf-8") as f:
    _raw = f.read()
check("§3 saving the demo writes an ordinary file WITHOUT any status",
      _saved is True and '"status"' not in _raw and EP.build_example_project()["version"] in _raw)
check("§3 ...and the window DROPS the emulation with it (the copy probes for real)",
      win._emulated_statuses == {} and win._example_project is False)
check("§3 ...while the cards keep what they show — still marked as the demo's",
      all(n.status_emulated for n in win.scene.nodes()),
      str([n.status_emulated for n in win.scene.nodes()]))
win._dirty = False
win.close()

check("§3 the honesty rule is written where the reversed contract lives (the factory, the note)",
      "never leaves the demo map" in _src("storage", "example_project.py")
      and all("emul" in _langs[c]["example.note_text"].lower()          # en / de
              or "эмул" in _langs[c]["example.note_text"].lower()       # ru
              or "模拟" in _langs[c]["example.note_text"]                # zh
              for c in _langs),
      str({c: _langs[c]["example.note_text"][:60] for c in sorted(_langs)}))
check("§3 the demo map's note no longer promises the old behaviour (the v1.5rc3 wording is gone)",
      all("reports them offline" not in _langs[c]["example.note_text"] for c in _langs))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the release state & the \"no new contract\" audit ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
check("§4 the pin quotes the SHIPPED version (v1.6.2 — the terminal that stops lying, the "
      "second follow-up of the 1.6 line this file describes)",
      EXPECTED_APP_VERSION == "1.6.2" and re.fullmatch(r"1\.6(\.\d+)?", EXPECTED_APP_VERSION) is not None)
check("§4 the i18n pin moved on by the closing release's ONE key, v1.5.1's four, v1.5.2's "
      "thirteen (the activity panel's chrome), v1.5.3's twenty (the freshness family), "
      "v1.5.4's eleven (the aggregate, the lens and the filter plaque), v1.5.5's fourteen "
      "(the inventory columns, the age captions and the report), v1.5.6's two (the Export "
      "menu and the third first-run door) and v1.5.7's twenty-nine (the command-history tab, "
      "the panel chrome and the six menu items), v1.6's forty-one and v1.6.2's four on top",
      EXPECTED_I18N_KEYS == 782)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("§4 every language carries the marker key with a non-empty value",
      all(str(_langs[c].get("node.status.emulated", "")).strip() for c in _langs),
      str({c: _langs[c].get("node.status.emulated") for c in sorted(_langs)}))
check("§4 the reworded demo strings kept their placeholders and line breaks",
      all(_langs[c]["example.note_text"].count("\n") == 4 for c in _langs)
      and all("offline" not in _langs[c]["status.example_loaded"].lower() for c in _langs),
      str({c: _langs[c]["example.note_text"].count("\n") for c in sorted(_langs)}))
_marker_card = ServerNode(ServerData(id="rel-marker", alias="a", host="192.0.2.1", user="u"))
_marker_card.set_status("online", emulated=True)
check("§4 the marker is the release's ONLY new string — and it FITS the band of a MIN card",
      _marker_card._demo_badge.text() == _t("node.status.emulated")
      and _marker_card._demo_badge.pos().x() + _marker_card._demo_badge.boundingRect().width()
      <= _marker_card._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01,
      f"{_marker_card._demo_badge.text()!r} on a {_marker_card._current_width} px card")
check("§4 ...and its four translations are SHORT enough not to be elided there",
      all(len(_langs[c]["node.status.emulated"]) <= len(_t("node.status.emulated")) + 8
          for c in _langs),
      str({c: len(_langs[c]["node.status.emulated"]) for c in sorted(_langs)}))

_hub = SettingsDialog(make_main())
check("§4 no new config key from this section (the settings hub collects 23)",
      len(_hub.collect()) == 23, str(len(_hub.collect())))
_hub.close()
check("§4 no new action and no new empty default of THIS release (the registry grew with "
      "the two v1.5.1 File actions, the v1.5.2 View item, the v1.5.3 freshness pair and the "
      "v1.5.5 inventory pair after it)",
      len(HR.HOTKEY_ACTIONS) == 59 and len(HR.empty_default_action_ids()) == 36)
check("§4 no new theme field (the palette is the v1.5rc1 one)",
      len(dataclasses.fields(theme.Theme)) == 60)
_deps = {"PySide6", "paramiko", "keyring", "wcwidth"}
_req = _src("requirements.txt")
check("§4 no new dependency (the four pinned ones and nothing else)",
      all(f"{d}>=" in _req for d in _deps)
      and not re.search(r"^\s*(?!PySide6|paramiko|keyring|wcwidth|#)[A-Za-z][\w.-]*\s*[><=]",
                        _req, re.M))
check("§4 the version constants agree everywhere (version.py ↔ pyproject ↔ requirements)",
      __import__("version").APP_VERSION == "1.6.2"
      and '"1.6.2"' in _src("version.py") and 'version = "1.6.2"' in _src("pyproject.toml"))
check("§4 VERSION_FORMAT did NOT move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9")

finish()
