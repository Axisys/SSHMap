"""Review fixes v0.8.0: node elide/max width, status markers in the sidebar (former smoke_test).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * #4 the node with a long alias/host/comment → the cap MAX_NODE_WIDTH + the full text in the tooltips
    (the elide invariant is font-independent: either the full text without the tooltip, or elided + the tooltip;
    the right edge does not slip under the dots [W-46, W-10]);
  * the node with a tiny content → the MIN size; the idempotency of update_appearance;
  * #3 the status markers in the sidebar tree: the icon of the row + the live update without the rebuild
    (the idle gray → the online green, the i18n tooltip with the host, the unknown status is ignored,
    refresh_sidebar rebuilds the rows with the current markers).

Run: python tests/test_node_labels.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData
from graphics.server_node import ServerNode as _SN

# ══ The review fixes v0.8.0: the elide/the max width of the nodes, the status markers in the sidebar ═══
# (#1 centering of _add_server is covered by test_ssh_terminal.py; #2 the version — test_connections.py)
print("== review fixes v0.8.0 ==")

from PySide6.QtGui import QFontMetrics as _QFM  # the review fix v0.8.0 (#4)

win_rev = MW.MainWindow()
win_rev.show(); app.processEvents()


def _label_invariant(node, item, fm, source):
    """The elide invariant of the caption (font-independent): either the full text with no tooltip,
    or elided + the full text in the tooltip; the right edge does not slip under the dots [W-46, W-10]."""
    rendered = item.toPlainText()
    ovh = max(0.0, item.boundingRect().width() - fm.horizontalAdvance(rendered)) if rendered else 0.0
    end = 55 + fm.horizontalAdvance(rendered) + ovh
    zone_ok = end <= node._current_width - 46 - 2
    detail = f"rendered={rendered[:30]!r} tip={(item.toolTip() or '')[:30]!r} W={node._current_width}"
    if rendered.endswith("\u2026"):
        return item.toolTip() == source and rendered != source and zone_ok, detail
    return item.toolTip() == "" and rendered == source and zone_ok, detail


# #4: a node with a long alias/host/comment → the MAX_NODE_WIDTH ceiling + full text in the tooltips
rev_alias = "production-web-server-04-eu-west-1-cluster-node"
rev_host = "very-long-hostname.example.corp.internal-dns-name"
rev_comment = "x" * 300
n_rev = win_rev.scene.add_server(ServerData(
    id="revlong", alias=rev_alias, host=rev_host, user="u", comment=rev_comment,
    cpu="64 core", ram="512 gb", disk="10 tb"))
check("long node width capped at MAX_NODE_WIDTH",
      n_rev._current_width == int(_SN.MAX_NODE_WIDTH), str(n_rev._current_width))
ok, det = _label_invariant(n_rev, n_rev._alias, _QFM(n_rev._alias.font()), rev_alias)
check("elided alias: full text in tooltip, clear of dot zone", ok, det)
ok, det = _label_invariant(n_rev, n_rev._host_label, _QFM(n_rev._host_label.font()), "@" + rev_host)
check("elided host: full text in tooltip, clear of dot zone", ok, det)
rev_info_lines = n_rev._info.toPlainText().splitlines()
check("comment elided at MAX while short lines stay full",
      any(l.endswith("\u2026") for l in rev_info_lines) and "CPU: 64 core" in n_rev._info.toPlainText(),
      str(rev_info_lines[:3]))
check("info tooltip carries the full (unelided) text block",
      bool(n_rev._info.toolTip()) and rev_comment in n_rev._info.toolTip() and "RAM: 512 gb" in n_rev._info.toolTip(),
      f"tip_len={len(n_rev._info.toolTip() or '')}")

# #4: a node with tiny content → MIN size, no elide needed; rebuild idempotency
n_tiny = win_rev.scene.add_server(ServerData(id="revtiny", alias="A", host="h", user="u"))
check("tiny node keeps MIN width (no stretch)", n_tiny._current_width == _SN.MIN_NODE_WIDTH, str(n_tiny._current_width))
_snap = (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText())
n_rev.update_appearance()
check("update_appearance idempotent (width+texts stable)",
      (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText()) == _snap)

# #3: status markers in the sidebar tree — row icon + live update without a rebuild
win_rev.refresh_sidebar()
check("sidebar has a row per node with status icon",
      win_rev.tree.topLevelItemCount() == 2 and not win_rev.tree.topLevelItem(0).icon(0).isNull())
_it_idle = win_rev.tree.topLevelItem(0)
idle_px = _it_idle.icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("unverified node shows idle (gray) dot",
      idle_px == _SN.COLOR_DOT_IDLE.name().lower(), idle_px)

_item_before = win_rev.tree.topLevelItem(0)
win_rev._on_node_status_changed("revlong", "online")
_it_now = win_rev.tree.topLevelItem(0)
check("status marker updates in place (row not rebuilt)", _it_now is _item_before, f"{id(_item_before)} vs {id(_it_now)}")
green_px = _it_now.icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("online node dot turns green", green_px == _SN.STATUS_COLORS["online"].name().lower(), green_px)
_tip = _it_now.toolTip(0) or ""
check("sidebar tooltip is i18n text with host (not a raw key)",
      bool(_tip) and rev_host in _tip and not _tip.startswith("node."), repr(_tip))

win_rev._on_node_status_changed("revlong", "bogus-status")
_still = win_rev.tree.topLevelItem(0).icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("unknown status ignored (node and marker stay online)", n_rev.status == "online" and _still == green_px)

win_rev.refresh_sidebar()
_kept = win_rev.tree.topLevelItem(0).icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("refresh_sidebar rebuilds rows with current markers", _kept == green_px, _kept)

win_rev._dirty = False
win_rev.close(); win_rev.destroy()

finish()
