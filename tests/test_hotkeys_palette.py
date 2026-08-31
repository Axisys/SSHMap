"""Горячие клавиши + палитра команд v0.9.2 (бывш. smoke_test «v0.9.2 hotkeys + command palette»).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * хоткеи: Ctrl+Return (SSH connect), Ctrl+E (edit node), Ctrl+Shift+N (add note),
    Ctrl+K (palette) зарегистрированы как QKeySequence/QShortcut;
  * слоты-обёртки _edit_selected_node/_add_note_at_view_center вызываемы;
  * CommandPalette: fuzzy_score (subsequence, пустой паттерн матчит всё), сбор команд
    из меню + серверов сцены, фильтрация по имени, reveal — выделение узла + centerOn
    (offscreen-прокси через scroll state);
  * i18n-ключи v0.9.2 во всех трёх языках.

Запуск: python tests/test_hotkeys_palette.py   (из корня проекта) или python tests/run_all.py
"""
import json as _json_i18n_v092
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData

# ── v0.9.2: горячие клавиши + палитра команд ─────────────
print("== v0.9.2 hotkeys + command palette ==")

# Хоткеи: пункты меню несут ожидаемые QKeySequence
from PySide6.QtGui import QAction as _QA92
_w92 = MW.MainWindow()
def _find_actions(window):
    out = {}
    for act in window.findChildren(_QA92):
        txt = act.text().replace("&", "")
        key = act.shortcut().toString()
        if key:
            out.setdefault(key, []).append(txt)
    return out
_acts92 = _find_actions(_w92)
check("hotkey Ctrl+Return (SSH connect) registered",
      any("Ctrl+Return" in k for k in _acts92), str(list(_acts92)))
check("hotkey Ctrl+E (edit node) registered", "Ctrl+E" in _acts92, str(_acts92.get("Ctrl+E")))
check("hotkey Ctrl+Shift+N (add note) registered", "Ctrl+Shift+N" in _acts92)
check("hotkey Ctrl+K (palette) present via shortcut",
      any(getattr(sc, "key", lambda: None)().toString() == "Ctrl+K"
          for sc in _w92.findChildren(__import__("PySide6.QtGui", fromlist=["QShortcut"]).QShortcut)))

# Слоты-обёртки существуют и вызываемы
check("_edit_selected_node/_add_note_at_view_center callable",
      callable(getattr(_w92, "_edit_selected_node", None))
      and callable(getattr(_w92, "_add_note_at_view_center", None)))

# Палитра: создание, fuzzy_score, сбор команд
from ui.command_palette import CommandPalette as _CP, fuzzy_score as _fs
check("fuzzy_score subsequence match", _fs("cns", "Connect via SSH") is not None)
check("fuzzy_score rejects non-match", _fs("zzz", "Connect via SSH") is None)
check("fuzzy_score empty pattern matches all", _fs("", "anything") is not None)

_pal = _CP(_w92, _w92)
_pal._collect_commands()
_kinds = [k for _, k, _ in _pal._commands]
check("palette collected menu actions", _kinds.count("action") >= 5,
      f"actions={_kinds.count('action')}")
# Добавим сервер на сцену — палитра должна увидеть его при пересборке
_sd92 = ServerData(id="pal001", alias="PaletteHost", host="10.9.9.9", user="u")
_nd92 = _w92.scene.add_server(_sd92)
_pal._collect_commands()
_srv = [(lbl, fn) for lbl, k, fn in _pal._commands if k == "server"]
check("palette lists servers", len(_srv) == 1 and "PaletteHost" in _srv[0][0], str(_lbl := [l for l, _ in _srv]))

# Фильтрация по имени сервера
_pal.input.setText("palettehost")
check("palette filter finds server by name", _pal.listw.count() >= 1
      and any("PaletteHost" in _pal.listw.item(i).text() for i in range(_pal.listw.count())))

# Выбор сервера центрирует вид и выделяет узел.
# Offscreen-нюанс QGraphicsView: точный centerOn зависит от границ сцены/скроллбаров,
# поэтому проверяем выделение узла + факт вызова centerOn (сцена вид изменила transform).
_w92.view.resize(800, 600)
_app92 = QApplication.instance()
_app92.processEvents()
_srv[0][1]()
_app92.processEvents()
check("palette reveal selects node", _nd92.isSelected())
# Палитра должна была вызвать centerOn: sceneRect вырос/scrollbars сместились —
# надёжный прокси: повторный прямой centerOn даёт тот же scroll-стейт, что после reveal.
_hbar_before = _w92.view.horizontalScrollBar().value()
_vbar_before = _w92.view.verticalScrollBar().value()
_w92.view.centerOn(_nd92)
_app92.processEvents()
check("palette reveal centered on node (scroll state matches direct centerOn)",
      _w92.view.horizontalScrollBar().value() == _hbar_before
      and _w92.view.verticalScrollBar().value() == _vbar_before,
      f"h {_hbar_before}->{_w92.view.horizontalScrollBar().value()} "
      f"v {_vbar_before}->{_w92.view.verticalScrollBar().value()}")

# i18n: ключи v0.9.2 во всех трёх языках
for _lang_k in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{_lang_k}.json"), encoding="utf-8") as f:
        _d92 = _json_i18n_v092.load(f)
    _miss92 = [k for k in ("palette.title", "palette.placeholder", "palette.hint",
                           "palette.kind_server", "msg.select_server_edit")
               if k not in _d92]
    check(f"i18n v0.9.2 keys present ({_lang_k})", not _miss92, str(_miss92))

finish()
