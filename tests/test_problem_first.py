"""v1.5.4 — trouble first: the map answers "where is the problem".

The topical gate of the FOURTH patch ON the released 1.5. v1.5rc4 made the CHROME answer
the same questions as the map; this release makes the MAP answer the one question a
hundred equal cards cannot: *where is the trouble*. The three halves:

  §1 the group AGGREGATE (ROADMAP task 1): the worst member status plus the counts, read
     LIVE from the members, painted on the title band of the frame (which the FOLD keeps)
     with the DECLARED status shape and the status colour — and never written into the
     group's JSON (a view fact, the v1.4.2 rule for view state);
  §2 the "problems only" LENS (ROADMAP task 2): ONE transient toggle beside the status
     counters that dims everything that is not `warn` / `offline` / stale; it COMPOSES
     with the tag filter and the map search instead of replacing them, it never writes a
     config key, and the counters keep telling the whole truth;
  §3 the ACTIVE-FILTER PLAQUE (ROADMAP task 3): the floating panel that NAMES the active
     filters with one × each, joins the v1.5rc4 priority resolver (the collapse diamond is
     never covered), never reaches an export and owns `retranslate()`;
  §4 the release state: the version/pins, the eleven new i18n keys, and the "no new
     contract" audit (no new registry action, no new colour field, no new config key, no
     new dependency).

Everything runs offscreen and hermetic: no socket is opened, no probe is started — the
statuses are set through the ORDINARY `set_status()` / `_on_node_status_changed()` paths.

Run: python tests/test_problem_first.py   (from the project root) or python tests/run_all.py
"""
import dataclasses
import json
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, check_i18n_parity,
                     check_i18n_format, check_release_state)

ROOT, WORK = bootstrap()  # HOME isolation + offscreen Qt + sys.path (BEFORE any app import)

from PySide6.QtCore import QRect, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsItem  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t  # noqa: E402
import version as _version  # noqa: E402
from models.server import ServerData  # noqa: E402
from graphics.node_group import (NodeGroup, STATUS_SEVERITY, PROBLEM_STATUSES,  # noqa: E402
                                 aggregate_status, is_in_trouble, status_caption,
                                 worst_status)
import graphics.server_node as SN  # noqa: E402
from ui import theme  # noqa: E402
from ui.filter_plaque import FilterPlaque  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402

LANGS = load_i18n_langs(ROOT)

NEW_KEYS = [
    # the group aggregate (task 1)
    "group.status.empty", "group.status.unchecked",
    # the "problems only" lens (task 2)
    "statusbar.problems", "statusbar.problems.tooltip", "statusbar.problems.active",
    # the active-filter plaque (task 3)
    "filter.plaque.title", "filter.plaque.search", "filter.plaque.tag",
    "filter.plaque.status", "filter.plaque.problems", "filter.plaque.tooltip",
]


def _fake_t(key, **kw):
    """A `translate` stand-in for the PURE caption test: it reports the key + its params."""
    return f"{key}{sorted(kw)}" if kw else key


def _cfg():
    try:
        from i18n import load_config
        return load_config() or {}
    except Exception:  # noqa: BLE001 — without a config the check below is trivially true
        return {}


def read_cfg():
    """The live `config.json` of the sandboxed HOME (the settings-hub key audit)."""
    try:
        from i18n import load_config
        return load_config() or {}
    except Exception:  # noqa: BLE001
        return {}


def write_cfg(data):
    try:
        from i18n import save_config
        save_config(data)
    except Exception:  # noqa: BLE001 — the audit then sees an empty file
        pass


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the group aggregate — the worst member status and the counts (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the severity order is DECLARED and ascending (the last entry is the worst)",
      STATUS_SEVERITY == ("online", "warn", "offline") and PROBLEM_STATUSES == ("warn", "offline"),
      f"{STATUS_SEVERITY} / {PROBLEM_STATUSES}")
check("§1 the worst status does not depend on the order of the members",
      worst_status(["warn", "online", "offline"]) == "offline"
      and worst_status(["offline", "online", "warn"]) == "offline"
      and worst_status(["online", "warn"]) == "warn")
check("§1 a member without a declared status never wins the aggregate",
      worst_status(["", "nonsense", None, "online"]) == "online"
      and worst_status(["", None]) == "")
_summary = aggregate_status(["online", "offline", "offline", "warn", "", "oops"])
check("§1 the aggregate counts every DECLARED status and the members that carry one",
      _summary == {"worst": "offline",
                   "counts": {"online": 1, "warn": 1, "offline": 2}, "total": 4,
                   "members": 6},
      str(_summary))
check("§1 an empty composition is a summary of zeros, not an error",
      aggregate_status([]) == {"worst": "", "counts": {"online": 0, "warn": 0, "offline": 0},
                               "total": 0, "members": 0},
      str(aggregate_status([])))
check("§1 'in trouble' is ONE predicate: warn / offline, or a STALE datum",
      is_in_trouble("warn") and is_in_trouble("offline") and is_in_trouble("online", True)
      and not is_in_trouble("online") and not is_in_trouble("")
      and not is_in_trouble("", False))
check("§1 an UNCHECKED card is not trouble — there is no measurement to call a problem",
      not is_in_trouble("", stale=False))

check("§1 the caption of an empty group says so (the task's acceptance)",
      status_caption(aggregate_status([]), _fake_t) == "group.status.empty",
      status_caption(aggregate_status([]), _fake_t))
check("§1 a group whose members were never checked says that instead",
      status_caption(aggregate_status(["", ""]), _fake_t) == "group.status.unchecked",
      status_caption(aggregate_status([""]), _fake_t))
_problem_caption = status_caption(aggregate_status(["offline", "warn", "warn", "online"]),
                                  _fake_t)
check("§1 the caption names the PROBLEMS, worst first (the status words are the legend's)",
      _problem_caption == "legend.status.offline 1 · legend.status.warn 2",
      _problem_caption)
check("§1 a healthy group still says how many cards answered",
      status_caption(aggregate_status(["online", "online"]), _fake_t) == "legend.status.online 2",
      status_caption(aggregate_status(["online"]), _fake_t))
_group_src = open(os.path.join(ROOT, "graphics", "node_group.py"), encoding="utf-8").read()
check("§1 the caption reuses the EXISTING status words (no fourth spelling of the statuses)",
      "legend.status." in _group_src and "legend.status.online" in _group_src)

# ── the live group: a frame, four cards, a probe round ──────────────────────
_win = MainWindow()
_win._autosave_timer.stop()
_win.show()
app.processEvents()

GROUP = _win.scene.add_group(name="Cluster", x=-600.0, y=-600.0, width=1100.0, height=700.0)
_cards = {}
for _i, (_alias, _tags) in enumerate((("web-01", ["prod"]), ("web-02", ["prod"]),
                                      ("db-01", ["prod"]), ("cache-01", []))):
    _n = _win.scene.add_server(ServerData(id=f"g{_i}", alias=_alias, host=f"192.0.2.{10 + _i}",
                                          user="root", tags=list(_tags),
                                          x=-540.0 + _i * 220.0, y=-540.0))
    _cards[_alias] = _n
_win.scene.resync_group_members()
check("§1 the four cards are members of the group (the geometric invariant)",
      GROUP.member_count() == 4, str(GROUP.member_count()))
check("§1 a group of never-checked cards reports 'not checked'",
      GROUP.status_summary()["worst"] == "" and GROUP.status_caption() == t("group.status.unchecked"),
      GROUP.status_caption())

_win._on_node_status_changed("g0", "online")
_win._on_node_status_changed("g1", "online")
_win._on_node_status_changed("g2", "offline")
_win._on_node_status_changed("g3", "warn")
check("§1 the aggregate follows a probe round (worst + counts, read LIVE)",
      GROUP.status_summary() == {"worst": "offline",
                                 "counts": {"online": 2, "warn": 1, "offline": 1}, "total": 4,
                                 "members": 4},
      str(GROUP.status_summary()))
check("§1 the worst severity WINS the frame colour (the status tone, not the group violet)",
      GROUP._state_colors()[0].name().lower() == theme.STATUS_OFFLINE.lower(),
      f"{GROUP._state_colors()[0].name()} vs {theme.STATUS_OFFLINE}")

# the mark is the DECLARED shape of the worst status (the second channel of the 1.5 line)
_mark_rect, _text_rect = GROUP.aggregate_rects()
import ui.status_shape as SS  # noqa: E402

check("§1 the plaque carries the DECLARED shape of the worst status (never a colour alone)",
      _mark_rect.width() > 0 and SS.shape_id("offline") == theme.status_shape("offline")
      and theme.status_shape("offline") == theme.STATUS_SHAPE_TRIANGLE,
      f"{_mark_rect} {SS.shape_id('offline')}")
check("§1 the caption is painted inside the title band of the frame",
      _text_rect.width() > 0 and _text_rect.height() > 0
      and _text_rect.top() >= 0 and _text_rect.bottom() <= GROUP.TITLE_ZONE_H,
      f"{_text_rect} band={GROUP.TITLE_ZONE_H}")
check("§1 the tooltip keeps the WORDS of the aggregate (the tooltips rule of the 1.5 line)",
      t("legend.status.offline") in GROUP.toolTip()
      and t("legend.status.warn") in GROUP.toolTip(), repr(GROUP.toolTip()))


def _render_group(group):
    """Render a group into an ARGB image + the SCENE rect it was rendered from.

    The pixel probe of the two marks: the geometry says where a mark SHOULD be, and the
    render says whether it is really painted there (the `tests/test_encoding.py`
    discipline — a declared channel is a measured one).
    """
    from PySide6.QtGui import QImage, QPainter
    source = group.sceneBoundingRect()
    image = QImage(max(int(source.width()) + 4, 1), max(int(source.height()) + 4, 1),
                   QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        group.scene().render(painter, QRectF(image.rect()), source)
    finally:
        painter.end()
    return image, source


def _tone_pixels(image, source, rgb, area_scene):
    """Count the pixels of one tone inside a SCENE rect of the rendered image."""
    want = rgb.lstrip("#").lower()
    x0 = int(area_scene.left() - source.left())
    y0 = int(area_scene.top() - source.top())
    hits = 0
    for x in range(x0, x0 + max(int(area_scene.width()), 0)):
        for y in range(y0, y0 + max(int(area_scene.height()), 0)):
            if 0 <= x < image.width() and 0 <= y < image.height():
                if image.pixelColor(x, y).name().lstrip("#").lower() == want:
                    hits += 1
    return hits


_image, _source = _render_group(GROUP)
_mark_scene = GROUP.mapRectToScene(_mark_rect)
_frame_scene = GROUP.mapRectToScene(QRectF(2.0, 0.0, GROUP.size()[0] - 4.0, 3.0))
check("§1 a rendered group really PAINTS the declared shape of the worst status",
      _tone_pixels(_image, _source, theme.STATUS_OFFLINE, _mark_scene) >= 4,
      f"{_mark_scene} / {_tone_pixels(_image, _source, theme.STATUS_OFFLINE, _mark_scene)} px")
check("§1 ...and the FRAME itself carries the trouble tone (a second channel, measured)",
      _tone_pixels(_image, _source, theme.STATUS_OFFLINE, _frame_scene) >= 20,
      str(_tone_pixels(_image, _source, theme.STATUS_OFFLINE, _frame_scene)))

# the worst one recovers: the frame goes back to the ordinary group tone
_win._on_node_status_changed("g2", "online")
check("§1 the aggregate follows a RECOVERY too (the frame gives the tone back)",
      GROUP.worst_member_status() == "warn"
      and GROUP._state_colors()[0].name().lower() == theme.STATUS_WARN.lower(),
      f"{GROUP.worst_member_status()} {GROUP._state_colors()[0].name()}")

# ── the FOLD keeps it ───────────────────────────────────────────────────────
_caption_before = GROUP.status_caption()
GROUP.collapse()
check("§1 the FOLD keeps the aggregate (the title band survives the re-fit)",
      GROUP.is_collapsed() and GROUP.status_caption() == _caption_before
      and GROUP.aggregate_rects()[1].width() > 0
      and GROUP._state_colors()[0].name().lower() == theme.STATUS_WARN.lower(),
      f"{GROUP.status_caption()} {GROUP.aggregate_rects()}")
GROUP.expand()

# ── the membership: a change repaints, and NOTHING is serialized ────────────
_win.scene.remove_server("g3")
_win._update_counts_label()   # the window's own removal path does this (a direct scene call does not)
check("§1 a member that leaves changes the aggregate (the warn tone goes with it)",
      GROUP.member_count() == 3
      and GROUP.status_summary() == {"worst": "online",
                                     "counts": {"online": 3, "warn": 0, "offline": 0},
                                     "total": 3, "members": 3}
      and GROUP._state_colors()[0].name().lower() != theme.STATUS_WARN.lower(),
      f"{GROUP.status_summary()} {GROUP._state_colors()[0].name()}")
_group_json = GROUP.to_dict()
check("§1 NO status is ever written into the group's JSON (a view fact, the v1.4.2 rule)",
      set(_group_json) == {"id", "name", "x", "y", "width", "height"}
      and not any(k in _group_json for k in ("status", "worst", "counts", "offline", "warn")),
      str(sorted(_group_json)))
check("§1 ...and the JSON of a FOLDED group carries the fold keys only",
      set(NodeGroup(name="x", collapsed=True, expanded_width=480.0,
                    expanded_height=320.0).to_dict())
      == {"id", "name", "x", "y", "width", "height", "collapsed",
          "expanded_width", "expanded_height"})

_empty_group = NodeGroup(name="Empty", x=2000.0, y=2000.0)
check("§1 an EMPTY group says so in its caption and in its tooltip",
      _empty_group.member_count() == 0
      and _empty_group.status_caption() == t("group.status.empty")
      and _empty_group.toolTip() == t("group.status.empty"),
      repr(_empty_group.toolTip()))
check("§1 an empty group carries no mark (nothing to draw)",
      _empty_group.aggregate_rects()[0].width() == 0.0)

# the SCENE is the nudge: the card asks for the repaint, so every path behaves the same
check("§1 the card notifies the map on a status change (ONE point, every path)",
      "refresh_group_aggregates" in SN.__dict__ or
      "refresh_group_aggregates"
      in open(os.path.join(ROOT, "graphics", "server_node.py"), encoding="utf-8").read())
check("§1 the scene narrows the walk to the groups that really hold the node",
      _win.scene.refresh_group_aggregates(_cards["web-01"]) >= 1
      and _win.scene.refresh_group_aggregates(None) >= 1,
      "the scene hook answers a count")

for _key in ("group.status.empty", "group.status.unchecked"):
    check(f"§1 i18n/en carries {_key}", _key in LANGS["en"])


# ════════════════════════════════════════════════════════════════════════════
print('== §2 the "problems only" lens — one transient toggle (task 2) ==')
# ════════════════════════════════════════════════════════════════════════════

_chip = _win.problems_chip
check("§2 the status bar carries the toggle next to the status counters",
      _chip is not None and _chip in _win._status_bar_permanent_widgets())
check("§2 it starts off, and it is TRANSIENT (nothing was written to config.json)",
      _win.problems_only is False and _chip.is_active() is False
      and not [k for k in read_cfg() if "problem" in k.lower()],
      str(sorted(read_cfg())))
check("§2 the chip counts the servers that need attention (a TOTAL, like its neighbours)",
      _chip.text() == t("statusbar.problems", count=0), repr(_chip.text()))

# one trouble of each KIND: an offline card, a stale online card, a healthy one, an unchecked one
_win._on_node_status_changed("g0", "offline")     # trouble: offline
_win._on_node_status_changed("g1", "online")      # healthy while fresh
_win._on_node_status_changed("g2", "online")
_lens_nodes = [_win.scene.get_node("g0"), _win.scene.get_node("g1"),
               _win.scene.get_node("g2")]
_lens_nodes[1].set_checked_at(1.0, 90.0)          # a datum of 1970 — stale by definition
_lens_nodes[1].refresh_freshness()
_unchecked = _win.scene.add_server(ServerData(id="g9", alias="fresh-01", host="192.0.2.99",
                                              user="root", x=900.0, y=900.0))
check("§2 a card whose datum has grown STALE is trouble (the lens reads freshness too)",
      _lens_nodes[1].is_stale is True and is_in_trouble("online", _lens_nodes[1].is_stale))
_win._update_counts_label()
check("§2 the chip counts the offline card AND the stale one, not the healthy two",
      _win._sync_problems_chip() == 2 and _chip.text() == t("statusbar.problems", count=2),
      f"{_win._trouble_nodes()} / {_chip.text()}")

_offline_counter = _win.status_filter_labels["offline"].text()
_chip.clicked.emit()
app.processEvents()
check("§2 the click turns the lens on (the widget only reports; the window owns it)",
      _win.problems_only is True and _chip.is_active() is True)
check("§2 everything that is not warn / offline / stale is DIMMED",
      _lens_nodes[0].opacity() == 1.0 and _lens_nodes[1].opacity() == 1.0
      and _lens_nodes[2].opacity() == SN.ServerNode.DIM_OPACITY
      and _unchecked.opacity() == SN.ServerNode.DIM_OPACITY,
      f"{[_n.opacity() for _n in _lens_nodes]} {_unchecked.opacity()}")
check("§2 an UNCHECKED card is dimmed, not called an incident (a false alarm is worse)",
      _unchecked.status == "" and _unchecked.opacity() == SN.ServerNode.DIM_OPACITY)
check("§2 the counters keep telling the WHOLE truth while the lens is on",
      _win.status_filter_labels["offline"].text() == _offline_counter)
check("§2 the lens never changes a status (it is a view, not a measurement)",
      [_n.status for _n in _lens_nodes] == ["offline", "online", "online"])
check("§2 the toggle announces itself in the status bar",
      _win.statusBar().currentMessage() == t("statusbar.problems.active"),
      repr(_win.statusBar().currentMessage()))

# a probe result re-applies the lens (a card that went red lights up without a rebuild)
_win._on_node_status_changed("g2", "offline")
check("§2 a live probe result re-applies the lens (a card that went red lights up)",
      _win.scene.get_node("g2").opacity() == 1.0 and _win.problems_only is True)
_win._on_node_status_changed("g2", "online")
check("§2 ...and a recovered card recedes again",
      _win.scene.get_node("g2").opacity() == SN.ServerNode.DIM_OPACITY)

# ── it COMPOSES with the tag filter and the search (the acceptance) ─────────
# g0 is in trouble AND tagged; g1 is in trouble (stale) and NOT tagged; g2 is healthy.
_win.scene.get_node("g0").data.tags = ["prod"]
_win.scene.get_node("g1").data.tags = []
_win.scene.get_node("g2").data.tags = []
_win.refresh_sidebar()
_combo = _win.tag_filter
_combo.setCurrentIndex(_combo.findData("prod"))
app.processEvents()
check("§2 the lens AND the tag filter are applied together (a trouble card without the tag recedes)",
      _win._active_tag_filter() == "prod"
      and _win.scene.get_node("g1").opacity() == SN.ServerNode.DIM_OPACITY
      and _win.scene.get_node("g0").opacity() == 1.0,
      f"{_win._active_tag_filter()} {_win.scene.get_node('g1').opacity()}")
_combo.setCurrentIndex(0)
app.processEvents()

_win._open_map_search()
_win._on_map_search_query("01")
app.processEvents()
check("§2 a search hit that is IN trouble keeps both the frame and its brightness",
      _win.scene.get_node("g0").search_matched is True
      and _win.scene.get_node("g0").opacity() == 1.0,
      f"{_win.scene.get_node('g0').search_matched} {_win.scene.get_node('g0').opacity()}")
check("§2 the search marks its match even when the LENS dims it (the frame survives the AND)",
      _win.scene.get_node("g2").search_matched is True
      and _win.scene.get_node("g2").opacity() == SN.ServerNode.DIM_OPACITY,
      f"{_win.scene.get_node('g2').search_matched} {_win.scene.get_node('g2').opacity()}")
check("§2 ...and a card the search does NOT match recedes even though it is in trouble",
      _win.scene.get_node("g1").search_matched is False
      and _win.scene.get_node("g1").opacity() == SN.ServerNode.DIM_OPACITY)
_win._close_map_search()
_combo.setCurrentIndex(0)
app.processEvents()

_chip.clicked.emit()
check("§2 a second click resets the lens, and the map comes back whole",
      _win.problems_only is False and _chip.is_active() is False
      and all(_n.opacity() == 1.0 for _n in _lens_nodes)
      and _unchecked.opacity() == 1.0)
check("§2 the lens is TRANSIENT — still no config key after two toggles",
      not [k for k in read_cfg() if "problem" in k.lower()], str(sorted(read_cfg())))
check("§2 the lens takes NO registry action and NO hotkey (it is a status-bar control)",
      not [a for a in HR.action_ids() if "problem" in a])

for _key in ("statusbar.problems", "statusbar.problems.tooltip", "statusbar.problems.active"):
    check(f"§2 i18n/en carries {_key}", _key in LANGS["en"])


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the active-filter plaque — the map says what it is showing (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

_plaque = _win.filter_plaque
check("§3 the window owns a plaque widget and the widget declares its rows",
      _plaque is not None and FilterPlaque.KINDS == ("search", "tag", "status", "problems"),
      str(FilterPlaque.KINDS))
check("§3 it is a WIDGET over the scene, never a scene item (so it cannot reach an export)",
      isinstance(_plaque, FilterPlaque) and not isinstance(_plaque, QGraphicsItem)
      and _plaque.parent() is _win.view
      and _plaque not in _win.scene.items())
check("§3 it is a child of the view, i.e. outside `itemsBoundingRect()` and 'fit to content'",
      _plaque.parentWidget() is _win.view and _plaque not in _win.scene.items())

# ── the widget's own contract (no window needed) ─────────────────────────────
_probe = FilterPlaque(_win.view)
check("§3 an empty state is an empty panel (it hides itself)",
      _probe.is_empty() and _probe.rows() == [] and _probe.body_height() == _probe.HEADER_H
      + _probe.PADDING)
check("§3 `set_state` is idempotent (a repeated push is not a change)",
      _probe.set_state(problems=True) is True and _probe.set_state(problems=True) is False)
check("§3 the rows follow the DECLARED order, not the order of the call",
      [kind for kind, _text in _probe.rows()] == ["problems"])
_probe.set_state(search="web", tag="prod", status="offline", problems=True)
check("§3 every active filter gets its own row, in the declared order",
      [kind for kind, _text in _probe.rows()] == ["search", "tag", "status", "problems"]
      and len(_probe.rows()) == 4)
check("§3 the captions print the VALUES the user typed (the query and the tag)",
      "web" in dict(_probe.rows())["search"] and "prod" in dict(_probe.rows())["tag"],
      str(_probe.rows()))
check("§3 the status row reuses the legend's word for the status",
      t("legend.status.offline") in dict(_probe.rows())["status"],
      str(dict(_probe.rows())["status"]))
check("§3 every visible row carries ONE ×, and a hidden kind carries none",
      all(_probe.clear_rect(kind).width() == _probe.CLEAR_W for kind, _t2 in _probe.rows())
      and _probe.clear_rect("nope").isEmpty())
check("§3 the × of a row sits inside that row",
      all(_probe.row_rect(i).contains(_probe.clear_rect(kind))
          for i, (kind, _t3) in enumerate(_probe.rows())))
_probe.set_state()
check("§3 clearing the state empties the panel again", _probe.is_empty() is True)
_probe.deleteLater()

# ── the live wiring: only while a filter is active, one × per filter ─────────
check("§3 with no filter the plaque is hidden",
      _win._sync_filter_plaque() is False and _plaque.isVisible() is False)

_win._open_map_search()
_win._on_map_search_query("web-01")
app.processEvents()
check("§3 the search opens the plaque with a SEARCH row",
      _plaque.isVisible() and [k for k, _t4 in _plaque.rows()] == ["search"],
      str(_plaque.rows()))
check("§3 the plaque names the ACTIVE filters of the priority resolver too",
      any(rect == QRect(_plaque.geometry()) for rect in _win._overlay_panel_rects(_win.view)),
      f"{_plaque.geometry()} / {_win._overlay_panel_rects(_win.view)}")
_resolver_src = open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8").read()
check("§3 ...because it joined `_overlay_panel_rects()` (the one floating-panel resolver)",
      '"empty_state", "map_search", "minimap", "legend", "filter_plaque"' in _resolver_src)

_win._set_problems_only(True, announce=False)
_win._status_filter = "offline"
_win.sidebar.set_status_filter("offline")
_win.refresh_sidebar()
app.processEvents()
check("§3 three active filters are three named rows",
      [k for k, _t5 in _plaque.rows()] == ["search", "status", "problems"],
      str(_plaque.rows()))

# each × clears ONLY its own filter (the acceptance)
_plaque.clear_requested.emit("search")
app.processEvents()
check("§3 the × of the search clears the SEARCH and nothing else",
      _win._map_search_query == "" and _win.map_search.isVisible() is False
      and [k for k, _t6 in _plaque.rows()] == ["status", "problems"],
      str(_plaque.rows()))
_plaque.clear_requested.emit("problems")
app.processEvents()
check("§3 the × of the lens clears the LENS and nothing else",
      _win.problems_only is False
      and [k for k, _t7 in _plaque.rows()] == ["status"], str(_plaque.rows()))
_plaque.clear_requested.emit("status")
app.processEvents()
check("§3 the × of the status clears the STATUS filter and hides the plaque with the last one",
      _win._status_filter == "" and _plaque.isVisible() is False and _plaque.is_empty(),
      f"{_win._status_filter} {_plaque.isVisible()}")

# the tag filter names itself too
_win.tag_filter.setCurrentIndex(_win.tag_filter.findData("prod"))
app.processEvents()
check("§3 the tag filter gets its own named row",
      _plaque.isVisible() and [k for k, _t8 in _plaque.rows()] == ["tag"],
      str(_plaque.rows()))
_plaque.clear_requested.emit("tag")
app.processEvents()
check("§3 and its × clears exactly the tag pick",
      _win._active_tag_filter() == "" and _plaque.isVisible() is False)

# ── the priority rule: the diamond is never covered ─────────────────────────
_win._set_problems_only(True, announce=False)
app.processEvents()
_plaque.move(_win.view.width() - _plaque.width() - 8,
             _win.view.height() - _plaque.height() - 8)
_win._position_map_collapse_btn()
_btn_rect = QRect(_win._map_collapse_btn.geometry())
check("§3 a plaque moved over the corner never covers the collapse diamond",
      not _btn_rect.intersects(QRect(_plaque.geometry())),
      f"diamond={_btn_rect} plaque={_plaque.geometry()}")
_win._position_filter_plaque()
_btn_rect = QRect(_win._map_collapse_btn.geometry())
check("§3 ...and the ordinary placement keeps it clear of the diamond anyway",
      not _btn_rect.intersects(QRect(_plaque.geometry())),
      f"diamond={_btn_rect} plaque={_plaque.geometry()}")

# ── the language switch reaches it (the v1.3.3.1 container invariant) ────────
_en_title = _plaque._row_text("problems")
i18n.set_language("ru")
_win._apply_ui_translations()
app.processEvents()
check("§3 `_apply_ui_translations()` re-texts the plaque (the container invariant)",
      _plaque._row_text("problems") != _en_title
      and _plaque._row_text("problems") == LANGS["ru"]["filter.plaque.problems"],
      f"{_en_title} -> {_plaque._row_text('problems')}")
i18n.set_language("en")
_win._apply_ui_translations()
app.processEvents()
check("§3 the switch never touched the filter STATE (values are data, captions are text)",
      _win.problems_only is True and _plaque._row_text("problems") == _en_title)
check("§3 the plaque writes no config key (a filter is UI state, the v1.5rc4/v1.4.5 rule)",
      not [k for k in read_cfg() if k.startswith("ui_filter") or "plaque" in k],
      str(sorted(read_cfg())))

for _key in ("filter.plaque.title", "filter.plaque.search", "filter.plaque.tag",
             "filter.plaque.status", "filter.plaque.problems", "filter.plaque.tooltip"):
    check(f"§3 i18n/en carries {_key}", _key in LANGS["en"])

_win._set_problems_only(False, announce=False)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the version pin is the version this file describes",
      EXPECTED_APP_VERSION == "1.5.7" and _version.APP_VERSION == "1.5.7",
      f"{EXPECTED_APP_VERSION} / {_version.APP_VERSION}")
check("§4 the i18n pin counts the SHIPPED release (681 + 11 of v1.5.4 + 14 of v1.5.5"
      " + 2 of v1.5.6 + 29 of v1.5.7)",
      EXPECTED_I18N_KEYS == 737, str(EXPECTED_I18N_KEYS))
check("§4 the eleven new keys are present and non-empty in every language",
      all(str(LANGS[c].get(k, "")).strip() for k in NEW_KEYS for c in LANGS)
      and len(NEW_KEYS) == 11,
      str([k for k in NEW_KEYS for c in LANGS if not str(LANGS[c].get(k, "")).strip()]))
check("§4 the placeholders of the new keys match en in every language",
      all({m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS[c][k])}
          == {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"][k])}
          for k in NEW_KEYS for c in LANGS))
check("§4 the eleven keys of THIS release stayed in the pin (the later releases only add)",
      EXPECTED_I18N_KEYS >= 681 + len(NEW_KEYS)
      and all(k in LANGS["en"] for k in NEW_KEYS))
check("§4 no new registry action (the lens and the plaque are controls, not menu items; the "
      "v1.5.5 inventory pair takes the registry to 56 / 33)",
      len(HR.HOTKEY_ACTIONS) == 56 and len(HR.empty_default_action_ids()) == 33,
      f"{len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")
check("§4 no new colour field (the release reuses the status tones and the declared shapes)",
      len(dataclasses.fields(theme.DARK)) == 60
      and len(dataclasses.fields(theme.LIGHT)) == 60,
      f"{len(dataclasses.fields(theme.DARK))} / {len(dataclasses.fields(theme.LIGHT))}")
check("§4 the schema does NOT change (a view fact is not a project-format field)",
      _version.VERSION_FORMAT == "0.9", _version.VERSION_FORMAT)
_req = [ln.split(">=")[0].strip() for ln in
        open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().splitlines()
        if ln.strip() and not ln.strip().startswith("#")]
check("§4 no new dependency (requirements.txt keeps its four)",
      _req == ["PySide6", "paramiko", "keyring", "wcwidth"], str(_req))

from ui.settings_dialog import SettingsDialog  # noqa: E402

_dlg = SettingsDialog(None)
_keys = _dlg.collect()
check("§4 the settings hub still collects exactly 22 keys (the release adds no option)",
      len(_keys) == 22 and "theme" in _keys
      and not [k for k in _keys if "problem" in k or "filter" in k],
      str(sorted(_keys)))
_dlg.close()

_win._dirty = False
_win._undo_baseline_dirty = False
_win.close()

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)

finish()
