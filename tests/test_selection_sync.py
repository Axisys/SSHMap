"""Regression v0.9.9.1 — selection sync without blockSignals (reentry guard).

ROADMAP v0.9.9.1 (the closure of the "Open remark" in the CHANGELOG):
  #1 instead of scene.blockSignals / tree.blockSignals in _select_node and
     _sync_selection_state — the reentry-guard flag MainWindow._selection_syncing
     (a plain bool, the GUI thread; the reset in finally). The echo of own signals
     during the programmatic change returns immediately (without the recursion), and the explicit
     synchronization after the change is idempotent: the full recomputation of the state
     ("the tree = the current selection of the scene"), not the "apply of the delta".
  #2 the signals are no longer blocked globally — the other slots
     of selectionChanged keep working; the external change during the sync
     is not lost, the next alignment converges.

The accompanying fix v0.9.9.1 (the behavior test — in test_map_search.py):
  MapView.resized + resizeEvent — the search bar is repositioned on the window resize
  (earlier the connect fell into the AttributeError and was silently swallowed by the try/except).

Run:  python tests/test_selection_sync.py   (from the project root) or python tests/run_all.py
"""
import os, sys, json, tempfile, traceback, inspect

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from models.server import ServerData
import ui.main_window as MW

win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

# Three servers (unique ids — the file is isolated from the other regressions).
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


# ══ i18n: no new keys in the release — the en/ru/zh sets stay identical ══
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
check("key sets identical across en/ru/zh (no new keys in v0.9.9.1)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"]),
      str({c: len(d) for c, d in langs.items()}))

# ══ The reentry guard: the basic properties of the flag ══
print("== reentry guard ==")
check("_selection_syncing exists and starts False",
      getattr(win, "_selection_syncing", None) is False)

# Statics: the blockSignals calls in the selection-synchronization paths are gone
# (comments are not counted — they historically mention the old approach).
def _code_only(fn):
    return "\n".join(l for l in inspect.getsource(fn).splitlines()
                     if not l.strip().startswith("#"))

check("no blockSignals calls left in _select_node",
      "blockSignals" not in _code_only(type(win)._select_node))
check("no blockSignals calls left in _sync_selection_state",
      "blockSignals" not in _code_only(type(win)._sync_selection_state))

# ══ The signals are no longer blocked: the foreign slots work during the programmatic change ══
print("== signals not blocked ==")
# The user path (a click on the map): the selection directly on the scene — the tree follows.
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

# ══ The echo in the sync window: the guard returns immediately, the tree is not touched;
#     the explicit recompute after the window converges to the current scene state ══
print("== echo window + convergence ==")
row_db = tree_row(n_db.data.id)
tree_during_window = []
probe = win.scene.selectionChanged.connect(lambda: tree_during_window.append(win.tree.currentItem()))
try:
    # Simulating a production scenario: an external selection change while the flag is set.
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
# An explicit synchronization after the window — a full recompute: the tree = the current scene selection.
win._sync_selection_state()
check("convergence: explicit sync realigns tree to the external change",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_cache.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

# ══ The idempotence: an out-of-sync tree is aligned by a full recomputation ══
print("== idempotent full recompute ==")
row_web = tree_row(n_web.data.id)
win.tree.setCurrentItem(row_web)  # an intentional desynchronization (the scene — n_cache)
win._sync_selection_state()
check("desynced tree realigns to scene selection on plain _sync_selection_state",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.UserRole) == n_cache.data.id,
      f"current={win.tree.currentItem().data(0, Qt.UserRole) if win.tree.currentItem() else None}")

# ══ The "click on the tree" path (itemClicked → _select_node) is not broken ══
print("== tree click path ==")
row_db2 = tree_row(n_db.data.id)
win._on_tree_item_clicked(row_db2, 0)
app.processEvents()
check("tree click selects the node in the scene",
      win.scene.get_selected_node() is n_db and not n_cache.isSelected(),
      f"selected={win.scene.get_selected_node().data.id if win.scene.get_selected_node() else None}")

# ══ MapView.resized: the signal exists and is emitted on a size change (the fix infrastructure) ══
print("== MapView.resized ==")
resizes = []
view.resized.connect(lambda: resizes.append(1))
view.resize(700, 650); app.processEvents()
check("MapView emits resized on resize", len(resizes) >= 1, f"emissions={len(resizes)}")
view.resize(900, 700); app.processEvents()

# Cleanup: first reset dirty — otherwise closeEvent would go to the save dialog.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
