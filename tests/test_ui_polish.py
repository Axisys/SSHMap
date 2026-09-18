"""UI polish: nodes, grid, fit/zoom, status bar, icons, arrow hit zones (former smoke_test).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * the node's boundingRect includes the shadow halo (v1.4.2: a cached pixmap);
    the decorative 🔒 button removed; the anchors use `card_rect_scene()`;
  * the status dot + the dimming of the offline node's content down to 0.55;
  * the adaptive grid: a 20px step at zoom >= 1, the doubling at a small zoom;
  * fit_to_content (with the content → True, an empty scene → False without a crash);
  * set_zoom_and_center: the valid values are applied, the broken ones are ignored;
  * _center_view centers by the map's content;
  * the status bar: the % of the zoom + the counters of servers/connections (ru);
  * the vector icons 20x20, an unknown name → an empty QIcon;
  * the arrow's hit area catches the middle of the curve (the shape is wider than the visible stroke);
  * i18n: the v0.7.3 keys + UI polish + v0.8.1 in all three languages.

Run: python tests/test_ui_polish.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, snapshot_i18n_config, restore_i18n_config

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict
from graphics.server_node import ServerNode as _SN
from i18n import set_language

# ══ The UI polish (quick wins): the nodes, the grid, the fit/zoom, the status bar, the icons ═══
print("== UI polish ==")

# The fixture: a window with two nodes and WITHOUT connections — the win73 state in smoke_test after
# v0.7.3 section (the arrow was removed by _remove_connection): the "Connections: 0" counter below depends on this.
win = MW.MainWindow()
d_a = server_data_from_dict({"alias": "ctx-a", "host": "192.168.3.52", "user": "u", "ip": "192.0.2.10", "x": 100, "y": 100})
d_b = server_data_from_dict({"alias": "ctx-b", "host": "192.168.3.53", "user": "u", "x": 450, "y": 160})
n_a = win.scene.add_server(d_a)
n_b = win.scene.add_server(d_b)

# The node: the shadow halo is in the boundingRect (v1.4.2 — a cached pixmap on all four
# sides, SHADOW_BOTTOM = 2*SHADOW_BLUR + SHADOW_DY is the derived total); the card rect
# (`card_rect_scene`) is what the anchors use. The decorative 🔒 button is removed.
check("node boundingRect includes the shadow halo",
      abs(n_a.boundingRect().height() - (_SN.MIN_NODE_HEIGHT + _SN.SHADOW_BOTTOM)) < 0.5
      and abs(n_a.boundingRect().top() + _SN.SHADOW_BLUR) < 0.5,
      str(n_a.boundingRect()))
check("v1.4.2: card_rect_scene() is the card inside the halo",
      abs(n_a.card_rect_scene().width() - n_a._current_width) < 0.5
      and abs(n_a.card_rect_scene().height() - n_a._current_height) < 0.5,
      str(n_a.card_rect_scene()))
check("v1.4.2: the shadow is a shared cached PIXMAP (not an effect, not a path)",
      isinstance(n_a._shadow, QGraphicsPixmapItem) and not n_a._shadow.pixmap().isNull(),
      type(n_a._shadow).__name__)
check("decorative SSH lock button removed from node", not hasattr(n_a, "_ssh_btn"))

# The status dot + dimming the offline node's content (the frame and the dots stay bright)
n_a.set_status("offline")
check("status dot turns red on offline",
      n_a._status_dot.brush().color().name() == _SN.STATUS_COLORS["offline"].name())
check("offline node content dimmed to 0.55",
      abs(n_a._alias.opacity() - 0.55) < 1e-6 and abs(n_a._icon.opacity() - 0.55) < 1e-6)
n_a.set_status("online")
check("content opacity restored on online", n_a._alias.opacity() == 1.0)

# The adaptive grid: the base step at zoom >= 1; a doubled step at a small zoom
check("grid step stays 20px at scale >= 1", win.scene._current_grid_step(1.0) == 20)
check("grid step adapts to low zoom (screen interval stays in [16, 32) px)",
      16.0 <= win.scene._current_grid_step(0.1) * 0.1 < 32.0)

# "Fit map": there is content -> True and the zoom is in range; an empty scene -> False without a crash
fit_ok = win.view.fit_to_content()
check("fit_to_content fits existing nodes", fit_ok and 0.1 <= win.view.zoom <= 5.0,
      f"zoom={win.view.zoom}")
_empty_win = MW.MainWindow()
check("fit on empty map returns False (no crash)", _empty_win.view.fit_to_content() is False)
_empty_win.close(); _empty_win.destroy()

# Restoring the saved view: valid values are applied, corrupt ones are ignored
win.view.set_zoom_and_center(2.0, -100, -50)
check("set_zoom_and_center applies zoom", abs(win.view.zoom - 2.0) < 1e-6)
try:
    win.view.set_zoom_and_center("garbage", None, "x")  # the corrupt values — the view does not change
except Exception as _bad_view_exc:
    check("set_zoom_and_center ignores bad values (no exception)", False, str(_bad_view_exc))
check("set_zoom_and_center ignores bad values", abs(win.view.zoom - 2.0) < 1e-6)

# Centering by the map content (not by the start of the scene coordinates)
_crect = win.view.content_bounding_rect()
win._center_view()
_mapped = win.view.mapFromScene(_crect.center())
_vp_center = win.view.viewport().rect().center()
check("_center_view centers on map content",
      abs(float(_mapped.x()) - float(_vp_center.x())) < 2.0
      and abs(float(_mapped.y()) - float(_vp_center.y())) < 2.0,
      f"mapped=({_mapped.x():.1f},{_mapped.y():.1f}) vp=({_vp_center.x():.1f},{_vp_center.y():.1f})")

# The status bar: the % zoom and the counters (we pin the language to ru for a stable assert)
_lang_snap = snapshot_i18n_config()
set_language("ru")
win._on_zoom_changed(1.5)
check("zoom label shows percent", win.zoom_label.text() == "150%", win.zoom_label.text())
win._update_counts_label()
check("counts label has servers and connections (ru)",
      "Серверы: 2" in win.counts_label.text() and "Связи: 0" in win.counts_label.text(),
      win.counts_label.text())

# Vector icons: the known ones render at 20x20, an unknown name -> an empty QIcon
from ui.icons import get_icon as _gi_up
_ic_fit = _gi_up("fit")
check("icons module renders vector icons (20x20)",
      not _ic_fit.isNull() and _ic_fit.pixmap(20).width() == 20)
check("unknown icon name -> empty QIcon", _gi_up("no_such_icon").isNull())

# The arrow hit area: the middle of the curve is now caught (contains() is wider than the visible stroke —
# in this PySide6 strokeToFill/strokedPath are not bound, and the fill-only contains is the point exactly
# on the line it did NOT catch; the thin 1.8 px line was physically unclickable)
from graphics.connection_arrow import build_curve as _bc73, curve_midpoint as _cm73, edge_point as _ep73
_arrow_hit = win.scene.add_connection(d_a.id, d_b.id, "up-hit", "ssh")
if _arrow_hit is not None:
    # v1.4.2 (ROADMAP task 4): the arrow geometry is anchored on the CARD rect —
    # the probe rebuilds the same curve from `card_rect_scene()`.
    _s_r = _arrow_hit.source.card_rect_scene()
    _t_r = _arrow_hit.target.card_rect_scene()
    _hp0 = _ep73(_s_r, _s_r.center(), _t_r.center())
    _hp3 = _ep73(_t_r, _t_r.center(), _s_r.center())
    _hpath, _hc1, _hc2 = _bc73(_hp0, _hp3)
    cls_up = win.view._classify_at(_cm73(_hp0, _hc1, _hc2, _hp3))
    check("arrow hit area catches curve midpoint (shape widened)", cls_up[1] is _arrow_hit, str(cls_up))
else:
    check("arrow recreated for hit test", False)

# i18n: the new v0.7.3 + UI polish keys are present in all 3 languages
_langs73 = {}
for _l in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{_l}.json"), encoding="utf-8") as _f:
        _langs73[_l] = json.load(_f)
_v73_keys = ["ctx.ssh_connect", "ctx.edit_server", "ctx.copy_ip", "ctx.copy_hostname",
             "ctx.ping", "ctx.delete_server", "ctx.edit_connection", "ctx.delete_connection",
             "dialog.edit_connection", "status.copied_to_clipboard", "status.ping_ok",
             "status.ping_failed", "status.ping_running", "status.connection_updated",
             "status.connection_deleted", "msg.confirm_delete_connection"]
_up_keys = ["view.fit_map", "status.counts", "status.fit_nothing"]  # UI polish (quick wins)
_grp_keys = ["edit.add_group", "ctx.add_group", "ctx.rename_group", "ctx.delete_group",
             "dialog.rename_group", "group.default_name", "group.name_label",
             "status.group_added", "status.group_renamed", "status.group_deleted"]  # v0.8.1
check("v0.7.3 + UI polish + v0.8.1 i18n keys present in en/ru/zh (>=213 keys each)",
      all(_k in _langs73[_l] for _k in (_v73_keys + _up_keys + _grp_keys) for _l in _langs73)
      and all(len(_langs73[_l]) >= 213 for _l in _langs73),  # v0.8.2: +6 keys = 219
      str({l: len(d) for l, d in _langs73.items()}))

# The headless hermeticity of closing: win is now dirty, and the global question() stub
# answers Save → closeEvent would have gone to _save_project_as() → a modal QFileDialog in
# offscreen hangs forever. The save thread is already covered by test_save_load.py —
# here we check only a clean close/destroy.
win._dirty = False
win.close()
win.destroy()

restore_i18n_config(_lang_snap)
finish()
