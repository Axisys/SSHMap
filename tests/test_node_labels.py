"""Ревью-фиксы v0.8.0: elide/макс. ширина узлов, маркеры статусов в сайдбаре (бывш. smoke_test).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * #4 узел с длинным alias/host/comment → потолок MAX_NODE_WIDTH + полный текст в tooltip'ах
    (elide-инвариант шрифто-независимый: либо полный текст без tooltip, либо elided + tooltip;
    правый край не заходит под точки [W-46, W-10]);
  * узел с крошечным контентом → MIN-размер; идемпотентность update_appearance;
  * #3 маркеры статусов в дереве сайдбара: иконка строки + live-обновление без пересбора
    (idle серый → online зелёный, tooltip i18n с host, неизвестный статус игнорируется,
    refresh_sidebar пересобирает строки с текущими маркерами).

Запуск: python tests/test_node_labels.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData
from graphics.server_node import ServerNode as _SN

# ══ Ревью-фиксы v0.8.0: elide/макс.ширина узлов, маркеры статусов в сайдбаре ═══
# (#1 центрирование _add_server покрыт test_ssh_terminal.py; #2 версия — test_connections.py)
print("== review fixes v0.8.0 ==")

from PySide6.QtGui import QFontMetrics as _QFM  # ревью-фикс v0.8.0 (#4)

win_rev = MW.MainWindow()
win_rev.show(); app.processEvents()


def _label_invariant(node, item, fm, source):
    """Elide-инвариант подписи (шрифто-независимый): либо полный текст без tooltip,
    либо elided + полный текст в tooltip; правый край не заходит под точки [W-46, W-10]."""
    rendered = item.toPlainText()
    ovh = max(0.0, item.boundingRect().width() - fm.horizontalAdvance(rendered)) if rendered else 0.0
    end = 55 + fm.horizontalAdvance(rendered) + ovh
    zone_ok = end <= node._current_width - 46 - 2
    detail = f"rendered={rendered[:30]!r} tip={(item.toolTip() or '')[:30]!r} W={node._current_width}"
    if rendered.endswith("\u2026"):
        return item.toolTip() == source and rendered != source and zone_ok, detail
    return item.toolTip() == "" and rendered == source and zone_ok, detail


# #4: узел с длинным alias/host/comment → потолок MAX_NODE_WIDTH + полный текст в tooltip'ах
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

# #4: узел с крошечным контентом → MIN-размер, elide не нужен; идемпотентность пересборки
n_tiny = win_rev.scene.add_server(ServerData(id="revtiny", alias="A", host="h", user="u"))
check("tiny node keeps MIN width (no stretch)", n_tiny._current_width == _SN.MIN_NODE_WIDTH, str(n_tiny._current_width))
_snap = (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText())
n_rev.update_appearance()
check("update_appearance idempotent (width+texts stable)",
      (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText()) == _snap)

# #3: маркеры статусов в дереве сайдбара — иконка строки + live-обновление без пересбора
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
