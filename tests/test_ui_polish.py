"""UI polish: ноды, сетка, fit/zoom, статус-бар, иконки, hit-зона стрелок (бывш. smoke_test).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * boundingRect узла включает полоску тени; декоративная кнопка 🔒 удалена;
  * точка статуса + затемнение контента offline-узла до 0.55;
  * адаптивная сетка: шаг 20px при зуме >= 1, удвоение при мелком зуме;
  * fit_to_content (с контентом → True, пустая сцена → False без падения);
  * set_zoom_and_center: валидные значения применяются, битые игнорируются;
  * _center_view центрирует по содержимому карты;
  * статус-бар: % зума + счётчики серверов/связей (ru);
  * векторные иконки 20x20, неизвестное имя → пустой QIcon;
  * hit-область стрелки ловит середину кривой (shape шире видимого штриха);
  * i18n: ключи v0.7.3 + UI polish + v0.8.1 во всех трёх языках.

Запуск: python tests/test_ui_polish.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, snapshot_i18n_config, restore_i18n_config

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict
from graphics.server_node import ServerNode as _SN
from i18n import set_language

# ══ UI polish (quick wins): ноды, сетка, fit/zoom, статус-бар, иконки ═══
print("== UI polish ==")

# Фикстура: окно с двумя узлами и БЕЗ связей — состояние win73 в smoke_test после
# секции v0.7.3 (стрелка удалена _remove_connection): счётчик «Связи: 0» ниже зависит от этого.
win = MW.MainWindow()
d_a = server_data_from_dict({"alias": "ctx-a", "host": "192.168.3.52", "user": "u", "ip": "192.0.2.10", "x": 100, "y": 100})
d_b = server_data_from_dict({"alias": "ctx-b", "host": "192.168.3.53", "user": "u", "x": 450, "y": 160})
n_a = win.scene.add_server(d_a)
n_b = win.scene.add_server(d_b)

# Узел: полоска тени входит в boundingRect; декоративная кнопка 🔒 удалена
check("node boundingRect includes shadow strip",
      abs(n_a.boundingRect().height() - (_SN.MIN_NODE_HEIGHT + _SN.SHADOW_BOTTOM)) < 0.5,
      str(n_a.boundingRect()))
check("decorative SSH lock button removed from node", not hasattr(n_a, "_ssh_btn"))

# Точка статуса + затемнение контента offline-узла (рамка и точки остаются яркими)
n_a.set_status("offline")
check("status dot turns red on offline",
      n_a._status_dot.brush().color().name() == _SN.STATUS_COLORS["offline"].name())
check("offline node content dimmed to 0.55",
      abs(n_a._alias.opacity() - 0.55) < 1e-6 and abs(n_a._icon.opacity() - 0.55) < 1e-6)
n_a.set_status("online")
check("content opacity restored on online", n_a._alias.opacity() == 1.0)

# Адаптивная сетка: базовый шаг при зуме >= 1; удвоение шага при мелком зуме
check("grid step stays 20px at scale >= 1", win.scene._current_grid_step(1.0) == 20)
check("grid step adapts to low zoom (screen interval stays in [16, 32) px)",
      16.0 <= win.scene._current_grid_step(0.1) * 0.1 < 32.0)

# «Вписать карту»: есть контент -> True и зум в диапазоне; пустая сцена -> False без падения
fit_ok = win.view.fit_to_content()
check("fit_to_content fits existing nodes", fit_ok and 0.1 <= win.view.zoom <= 5.0,
      f"zoom={win.view.zoom}")
_empty_win = MW.MainWindow()
check("fit on empty map returns False (no crash)", _empty_win.view.fit_to_content() is False)
_empty_win.close(); _empty_win.destroy()

# Восстановление сохранённого вида: валидные значения применяются, битые игнорируются
win.view.set_zoom_and_center(2.0, -100, -50)
check("set_zoom_and_center applies zoom", abs(win.view.zoom - 2.0) < 1e-6)
try:
    win.view.set_zoom_and_center("garbage", None, "x")  # битые значения — вид не меняется
except Exception as _bad_view_exc:
    check("set_zoom_and_center ignores bad values (no exception)", False, str(_bad_view_exc))
check("set_zoom_and_center ignores bad values", abs(win.view.zoom - 2.0) < 1e-6)

# Центрирование по содержимому карты (а не по началу координат сцены)
_crect = win.view.content_bounding_rect()
win._center_view()
_mapped = win.view.mapFromScene(_crect.center())
_vp_center = win.view.viewport().rect().center()
check("_center_view centers on map content",
      abs(float(_mapped.x()) - float(_vp_center.x())) < 2.0
      and abs(float(_mapped.y()) - float(_vp_center.y())) < 2.0,
      f"mapped=({_mapped.x():.1f},{_mapped.y():.1f}) vp=({_vp_center.x():.1f},{_vp_center.y():.1f})")

# Статус-бар: % зума и счётчики (язык фиксируем на ru для стабильного ассерта)
_lang_snap = snapshot_i18n_config()
set_language("ru")
win._on_zoom_changed(1.5)
check("zoom label shows percent", win.zoom_label.text() == "150%", win.zoom_label.text())
win._update_counts_label()
check("counts label has servers and connections (ru)",
      "Серверы: 2" in win.counts_label.text() and "Связи: 0" in win.counts_label.text(),
      win.counts_label.text())

# Векторные иконки: известные рендерятся 20x20, неизвестное имя -> пустой QIcon
from ui.icons import get_icon as _gi_up
_ic_fit = _gi_up("fit")
check("icons module renders vector icons (20x20)",
      not _ic_fit.isNull() and _ic_fit.pixmap(20).width() == 20)
check("unknown icon name -> empty QIcon", _gi_up("no_such_icon").isNull())

# Hit-область стрелки: середина кривой теперь ловится (contains() шире видимого штриха —
# в этом PySide6 strokeToFill/strokedPath не пробиндены, и fill-only contains точку ровно
# на линии НЕ ловил; тонкая линия 1.8 px физически была некликабельна)
from graphics.connection_arrow import build_curve as _bc73, curve_midpoint as _cm73, edge_point as _ep73
_arrow_hit = win.scene.add_connection(d_a.id, d_b.id, "up-hit", "ssh")
if _arrow_hit is not None:
    _s_r = _arrow_hit.source.sceneBoundingRect()
    _t_r = _arrow_hit.target.sceneBoundingRect()
    _hp0 = _ep73(_s_r, _s_r.center(), _t_r.center())
    _hp3 = _ep73(_t_r, _t_r.center(), _s_r.center())
    _hpath, _hc1, _hc2 = _bc73(_hp0, _hp3)
    cls_up = win.view._classify_at(_cm73(_hp0, _hc1, _hc2, _hp3))
    check("arrow hit area catches curve midpoint (shape widened)", cls_up[1] is _arrow_hit, str(cls_up))
else:
    check("arrow recreated for hit test", False)

# i18n: новые ключи v0.7.3 + UI polish присутствуют во всех 3 языках
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
      and all(len(_langs73[_l]) >= 213 for _l in _langs73),  # v0.8.2: +6 ключей = 219
      str({l: len(d) for l, d in _langs73.items()}))

# Headless-герметичность закрытия: win сейчас dirty, а глобальная заглушка question()
# отвечает Save → closeEvent ушёл бы в _save_project_as() → модальный QFileDialog в
# offscreen зависает навсегда. Поток сохранения уже покрыт test_save_load.py —
# здесь проверяем только чистое close/destroy.
win._dirty = False
win.close()
win.destroy()

restore_i18n_config(_lang_snap)
finish()
