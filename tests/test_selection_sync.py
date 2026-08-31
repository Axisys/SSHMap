"""Регрессия v0.9.9.1 — selection sync без blockSignals (reentry-guard).

ROADMAP v0.9.9.1 (закрытие «Открытого замечания» CHANGELOG):
  #1 Вместо scene.blockSignals / tree.blockSignals в _select_node и
     _sync_selection_state — reentry-guard флаг MainWindow._selection_syncing
     (обычный bool, GUI-поток; сброс в finally). Эхо собственных сигналов
     во время программной смены возвращается сразу (без рекурсии), а явная
     синхронизация после смены идемпотентна: полный пересчёт состояния
     («дерево = текущему выделению сцены»), а не «применить дельту».
  #2 Сигналы больше не блокируются глобально — остальные слоты
     selectionChanged продолжают работать; внешнее изменение в окне
     синхронизации не теряется, следующее выравнивание сходится.

Сопутствующий фикс v0.9.9.1 (поведенческий тест — в test_map_search.py):
  MapView.resized + resizeEvent — строка поиска переставляется при ресайзе окна
  (ранее connect падал в AttributeError и молча глотался try/except).

Запуск:  python tests/test_selection_sync.py   (из корня проекта) или python tests/run_all.py
"""
import os, sys, json, tempfile, traceback, inspect

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from models.server import ServerData
import ui.main_window as MW

win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

# Три сервера (уникальные id — файл изолирован от других regression).
n_web = win.scene.add_server(ServerData(id="ss91a", alias="web-1", host="10.0.0.5",
                                        user="ops", ip="10.0.0.5", comment="frontend",
                                        x=200, y=150))
n_db = win.scene.add_server(ServerData(id="ss91b", alias="db-1", host="db.internal",
                                       user="dba", ip="", comment="postgres",
                                       x=600, y=400))
n_cache = win.scene.add_server(ServerData(id="ss91c", alias="redis-cache", host="10.0.0.9",
                                          user="ops", ip="10.0.0.9", comment="",
                                          x=200, y=500))
win.refresh_sidebar()
app.processEvents()


def tree_row(node_id):
    for i in range(win.tree.topLevelItemCount()):
        it = win.tree.topLevelItem(i)
        if it.data(0, Qt.UserRole) == node_id:
            return it
    return None


# ══ i18n: новых ключей в релизе нет — наборы en/ru/zh остаются идентичными ══
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
check("key sets identical across en/ru/zh (no new keys in v0.9.9.1)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"]),
      str({c: len(d) for c, d in langs.items()}))

# ══ Reentry-guard: базовые свойства флага ══
print("== reentry guard ==")
check("_selection_syncing exists and starts False",
      getattr(win, "_selection_syncing", None) is False)

# Статика: вызовы blockSignals в путях синхронизации выделения не осталось
# (комментарии не считаются — в них исторически упоминается старый подход).
def _code_only(fn):
    return "\n".join(l for l in inspect.getsource(fn).splitlines()
                     if not l.strip().startswith("#"))

check("no blockSignals calls left in _select_node",
      "blockSignals" not in _code_only(type(win)._select_node))
check("no blockSignals calls left in _sync_selection_state",
      "blockSignals" not in _code_only(type(win)._sync_selection_state))

# ══ Сигналы больше не блокируются: чужие слоты работают во время программной смены ══
print("== signals not blocked ==")
# Пользовательский путь (клик по карте): выделение напрямую в сцене — дерево следует.
win.scene.clearSelection()
n_web.setSelected(True)
app.processEvents()
check("user-style scene selection still drives the tree",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_web.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

emissions = []
spy = win.scene.selectionChanged.connect(lambda: emissions.append(1))
try:
    win._select_node(n_db)
    app.processEvents()
finally:
    win.scene.selectionChanged.disconnect(spy)
check("selectionChanged reaches external slots during _select_node (no blockSignals)",
      len(emissions) >= 1, f"emissions={len(emissions)}")
check("_selection_syncing reset after _select_node", win._selection_syncing is False)
check("tree follows programmatic selection (_select_node)",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_db.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

# ══ Эхо в окне синхронизации: guard возвращает сразу, дерево не трогается;
#     явный пересчёт после окна сходится к актуальному состоянию сцены ══
print("== echo window + convergence ==")
row_db = tree_row(n_db.data.id)
tree_during_window = []
probe = win.scene.selectionChanged.connect(lambda: tree_during_window.append(win.tree.currentItem()))
try:
    # Симуляция production-сценария: внешнее изменение выделения, пока флаг установлен.
    win._selection_syncing = True
    try:
        win.scene.clearSelection()
        n_cache.setSelected(True)
    finally:
        win._selection_syncing = False
finally:
    win.scene.selectionChanged.disconnect(probe)
check("echo signals were delivered (not blocked) during the sync window",
      len(tree_during_window) >= 1, f"emissions={len(tree_during_window)}")
check("guard early-return: tree untouched while flag is set",
      all(t is row_db for t in tree_during_window),
      f"tree items seen during window={[t.data(0, Qt.UserRole) if t else None for t in tree_during_window]}")
# Явная синхронизация после окна — полный пересчёт: дерево = текущему выделению сцены.
win._sync_selection_state()
check("convergence: explicit sync realigns tree to the external change",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_cache.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

# ══ Идемпотентность: рассинхронизированное дерево выравнивается полным пересчётом ══
print("== idempotent full recompute ==")
row_web = tree_row(n_web.data.id)
win.tree.setCurrentItem(row_web)  # намеренная рассинхронизация (сцена — n_cache)
win._sync_selection_state()
check("desynced tree realigns to scene selection on plain _sync_selection_state",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_cache.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

# ══ Путь «клик по дереву» (itemClicked → _select_node) не сломан ══
print("== tree click path ==")
row_db2 = tree_row(n_db.data.id)
win._on_tree_item_clicked(row_db2, 0)
app.processEvents()
check("tree click selects the node in the scene",
      win.scene.get_selected_node() is n_db and not n_cache.isSelected(),
      f"selected={win.scene.get_selected_node().data.id if win.scene.get_selected_node() else None}")

# ══ MapView.resized: сигнал существует и эмитится при смене размера (инфраструктура фикса) ══
print("== MapView.resized ==")
resizes = []
view.resized.connect(lambda: resizes.append(1))
view.resize(700, 650); app.processEvents()
check("MapView emits resized on resize", len(resizes) >= 1, f"emissions={len(resizes)}")
view.resize(900, 700); app.processEvents()

# Cleanup: сначала сбрасываем dirty — иначе closeEvent уйдёт в диалог сохранения.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
