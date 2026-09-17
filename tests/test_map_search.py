"""Regression v0.9.8 — map search (Ctrl+F).

ROADMAP v0.9.8:
  #1 Ctrl+F → the search bar over the canvas: the highlighting of the matching nodes
     (alias/host/ip/comment) — ServerNode.set_search_match (the frame #38bdf8,
     the priority below the selection) + the counter "k / N".
  #2 Enter/Shift+Enter — the walk through the results with the centering and
     the accent frame (reveal_flash — the pulse pattern of set_status), the wrap-around.
  #3 the non-matching nodes are dimmed (set_dimmed, DIM_OPACITY) — the matches are read
     instantly; the tag filter and the search combine with AND (the semantics of the sidebar).

Run:  python tests/test_map_search.py   (from the project root) or python tests/run_all.py
"""
import os, sys, tempfile, traceback

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)


from i18n import t as it, set_language as _set_lang
from models.server import ServerData
import ui.main_window as MW

# The language: since v1.1.1 the default is en (ROADMAP item 2), but the test starts with ru —
# the sidebar width depends on the buttons' minSizeHint ("Add server" is 280 px in ru,
# 232 px in en), and the QSplitter distribution is fixed at the first layout: we set ru
# explicitly BEFORE the window is created, for determinism. The geometric baseline (the panel center x)
# since v1.2.4.1 it is computed DYNAMICALLY from the actual viewport — the view lives in
# container [strip | view], and a direct resize(view) is no longer ignored by the splitter.
_set_lang("ru")

win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

# Three servers: web-1 (host+ip 10.0.0.5), db-1 (host db.internal, no IP),
# redis-cache (host+ip 10.0.0.9). Queries: "web" → 1 match;
# "10.0.0" → 2; "zzz-no-match" → 0. Case-insensitive ("WEB").
n_web = win.scene.add_server(ServerData(id="ms8a", alias="web-1", host="10.0.0.5",
                                        user="ops", ip="10.0.0.5", comment="frontend",
                                        x=200, y=150))
n_db = win.scene.add_server(ServerData(id="ms8b", alias="db-1", host="db.internal",
                                       user="dba", ip="", comment="postgres",
                                       x=600, y=400))
n_cache = win.scene.add_server(ServerData(id="ms8c", alias="redis-cache", host="10.0.0.9",
                                          user="ops", ip="10.0.0.9", comment="",
                                          x=200, y=500))
win.refresh_sidebar()
app.processEvents()

bar = win.map_search
line = bar._line

# ══ i18n: 6 new keys × en/ru/zh (the parity — _common.check_i18n_parity) ══
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = ["view.find_on_map", "search.map_placeholder", "search.count",
            "search.no_results", "hint.map_search", "status.no_matches"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 6 new v0.9.8 keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# ══ MapSearchBar: the keyboard (Enter / Shift+Enter / Esc) and the counter ══
print("== MapSearchBar widget ==")
events = []
bar.next_requested.connect(lambda: events.append("next"))
bar.prev_requested.connect(lambda: events.append("prev"))
bar.close_requested.connect(lambda: events.append("close"))

QTest.keyClick(line, Qt.Key_Return)
check("Enter emits next_requested (and only it)", events == ["next"], str(events))
events.clear()
QTest.keyClick(line, Qt.Key_Enter, Qt.ShiftModifier)
check("Shift+Enter emits prev_requested", events == ["prev"], str(events))
events.clear()
QTest.keyClick(line, Qt.Key_Escape)
check("Esc emits close_requested", events == ["close"], str(events))

bar.set_count(2, 5)
check("set_count renders 'k / N' via i18n search.count",
      bar._count.text() == it("search.count").format(cur=2, total=5),
      f"text={bar._count.text()!r}")
bar.set_count(0, 0)
check("set_count with zero total renders 'no results'",
      bar._count.text() == it("search.no_results"), f"text={bar._count.text()!r}")

# ══ The menu item "View → Search on the map…" with the Ctrl+F hotkey ══
print("== menu ==")
# IMPORTANT: menu is taken from the i18n registry, and NOT via act.menu() on the temporary wrappers —
# in PySide6 6.11 the death of the Python QAction wrapper with an attached QMenu destroys the C++ menu
# (see the MainWindow._qaction_guard guard; the same is checked in a separate block below).
view_menu = None
for w, k in win._menu_i18n:
    if k == "menu.view":
        view_menu = w
        break
find_act = None
if view_menu is not None:
    for a in list(view_menu.actions()):
        if a.text() == it("view.find_on_map"):
            find_act = a
check("View menu has 'Find on Map…' action", find_act is not None,
      f"menu={view_menu.title() if view_menu else None}")
check("action shortcut is Ctrl+F",
      find_act is not None and find_act.shortcut().toString() == "Ctrl+F",
      find_act.shortcut().toString() if find_act is not None else "no action")

# ══ The open: the panel is visible, at the top center of the viewport, the focus on the input field ══
print("== open ==")
check("bar hidden before first open", not bar.isVisible())
win._toggle_map_search()
app.processEvents()
check("Ctrl+F (menu action path) opens the bar", bar.isVisible())
geo = bar.geometry(); vp = view.viewport().rect()
check("bar positioned inside viewport, top area",
      geo.x() >= 0 and geo.y() == 10 and geo.width() <= vp.width(),
      f"geo=({geo.x()},{geo.y()},{geo.width()}x{geo.height()}) vp={vp.width()}x{vp.height()}")
check("input focused with all text selected after open",
      line.hasFocus() and line.selectedText() == line.text())
check("status bar shows the navigation hint",
      win.statusBar().currentMessage() == it("hint.map_search"),
      f"msg={win.statusBar().currentMessage()!r}")

# ══ v0.9.9.1 fix: on a window resize the panel returns to the center (MapView.resized) ══
# Before v0.9.9.1, connect of view.resized fell into an AttributeError and was swallowed by try/except —
# after the window narrowing the panel stayed at the old x (240 instead of ~40 at vp 500).
# v1.2.4.1: the baseline is DYNAMIC (the view in the container [strip | view]: a direct
# resize(view) is honoured by the container layout, viewport = view − the scrollbar; in v1.2.4
# splitter ignored the resize, and x=240@vp900 was an artifact of a 1200px window). The invariant
# the same: the panel at the top center of the actual viewport (the same formula as in
# MainWindow._position_map_search_bar).
print("== resize reposition (v0.9.9.1 fix) ==")
vp_before = view.viewport().width()
w_before = min(bar.PREFERRED_WIDTH, max(vp_before - 16, bar.MIN_WIDTH))
x_expected_before = max(8, (vp_before - w_before) // 2)
x_before = bar.geometry().x()
check("bar centered before resize (baseline: the top center of the actual viewport)",
      x_before == x_expected_before,
      f"x={x_before} expected={x_expected_before} vp={vp_before}")
view.resize(500, 700); app.processEvents()
geo_r = bar.geometry(); vp_r = view.viewport().rect()
w_r = min(bar.PREFERRED_WIDTH, max(vp_r.width() - 16, bar.MIN_WIDTH))
x_expected = max(8, (vp_r.width() - w_r) // 2)
check("bar re-centered after viewport resize (no longer stuck at old x)",
      geo_r.x() == x_expected and geo_r.y() == 10,
      f"x={geo_r.x()} expected={x_expected} vp_w={vp_r.width()}")
check("position actually changed on resize", x_before != geo_r.x(),
      f"before={x_before} after={geo_r.x()}")
# "Grow back" limits the window/the splitter (offscreen) — we check the dynamic
# the center by the actual viewport, not the hard-coded 240.
view.resize(900, 700); app.processEvents()
vp_back = view.viewport().rect()
w_back = min(bar.PREFERRED_WIDTH, max(vp_back.width() - 16, bar.MIN_WIDTH))
x_back_expected = max(8, (vp_back.width() - w_back) // 2)
check("bar re-centered again when viewport grows back",
      bar.geometry().x() == x_back_expected and bar.geometry().y() == 10,
      f"x={bar.geometry().x()} expected={x_back_expected} vp_w={vp_back.width()}")

# ══ #1/#3: the "web" query — 1 match highlighted, the rest dimmed ══
print("== query 'web' ==")
bar.set_query("web")
app.processEvents()
check("exactly one node matches 'web'",
      [n for n in (n_web, n_db, n_cache) if n.search_matched] == [n_web],
      f"matched={[n.data.id for n in (n_web, n_db, n_cache) if n.search_matched]}")
check("matched node: full opacity + accent frame #38bdf8",
      n_web.opacity() == 1.0 and n_web._bg.pen().color().name() == "#38bdf8",
      f"opacity={n_web.opacity()} pen={n_web._bg.pen().color().name()}")
check("non-matching nodes dimmed (DIM_OPACITY) without match frame",
      all(n.opacity() < 1.0 and not n.search_matched for n in (n_db, n_cache)),
      f"db=({n_db.opacity()},{n_db.search_matched}) cache=({n_cache.opacity()},{n_cache.search_matched})")
check("counter shows '1 / 1' (first result current)",
      bar._count.text() == it("search.count").format(cur=1, total=1),
      f"text={bar._count.text()!r}")

# ══ #2: Enter — the selection + the centering + the flash; then it fades ══
print("== navigation ==")
QTest.keyClick(line, Qt.Key_Return)
app.processEvents()
check("Enter selects the matched node (sidebar follows via selection sync)",
      win.scene.get_selected_node() is n_web,
      f"selected={win.scene.get_selected_node().data.id if win.scene.get_selected_node() else None}")
c = view.mapFromScene(n_web.sceneBoundingRect().center())
vc = view.viewport().rect().center()
check("view centered on the node",
      abs(float(c.x()) - float(vc.x())) < 3.0 and abs(float(c.y()) - float(vc.y())) < 3.0,
      f"node=({c.x():.1f},{c.y():.1f}) vp=({vc.x():.1f},{vc.y():.1f})")
check("accent flash visible right after Enter (reveal_flash pattern)",
      n_web._pulse.isVisible() and abs(n_web._pulse.opacity() - 1.0) < 1e-6,
      f"visible={n_web._pulse.isVisible()} opacity={n_web._pulse.opacity()}")
wait_until(lambda: not n_web._pulse.isVisible(), timeout_ms=2500)
check("flash fades out and hides (900 ms animation completes)", not n_web._pulse.isVisible())
# 1 match: Enter loops on it — the node stays selected
QTest.keyClick(line, Qt.Key_Return)
app.processEvents()
check("single match wraps to itself (still selected, counter '1 / 1')",
      win.scene.get_selected_node() is n_web and bar._count.text().endswith("/ 1"))

# ══ #2: two matches — Enter/Shift+Enter go in a circle ══
print("== two matches ==")
bar.set_query("10.0.0")   # web-1 (host+ip) and redis-cache (host+ip); db-1 — no
app.processEvents()
matches2 = [n for n in (n_web, n_db, n_cache) if n.search_matched]
check("'10.0.0' matches exactly web-1 and redis-cache",
      matches2 == [n_web, n_cache], f"matched={[n.data.id for n in matches2]}")
check("counter reset to first result '1 / 2'",
      bar._count.text() == it("search.count").format(cur=1, total=2),
      f"text={bar._count.text()!r}")

QTest.keyClick(line, Qt.Key_Return)   # → the 2nd result
app.processEvents()
check("Enter advances to the 2nd match (counter '2 / 2')",
      win.scene.get_selected_node() is n_cache and bar._count.text().endswith("/ 2"),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")
QTest.keyClick(line, Qt.Key_Return)   # → wrapping back to the 1st
app.processEvents()
check("Enter wraps around to the 1st match",
      win.scene.get_selected_node() is n_web
      and bar._count.text() == it("search.count").format(cur=1, total=2),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")
QTest.keyClick(line, Qt.Key_Enter, Qt.ShiftModifier)  # → back to the 2nd
app.processEvents()
check("Shift+Enter goes back to the 2nd match",
      win.scene.get_selected_node() is n_cache and bar._count.text().endswith("/ 2"),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")

# ══ The case is not considered ══
print("== case-insensitive ==")
bar.set_query("WEB")
app.processEvents()
check("'WEB' matches web-1 (case-insensitive)", n_web.search_matched,
      f"matched={[n.data.id for n in (n_web, n_db, n_cache) if n.search_matched]}")

# ══ No matches: all dimmed, Enter — a message in the status bar ══
print("== no matches ==")
bar.set_query("zzz-no-match")
app.processEvents()
check("zero matches → counter shows 'no results'",
      bar._count.text() == it("search.no_results"), f"text={bar._count.text()!r}")
check("all nodes dimmed (none matches)",
      all(n.opacity() < 1.0 and not n.search_matched for n in (n_web, n_db, n_cache)))
QTest.keyClick(line, Qt.Key_Return)
app.processEvents()
check("Enter with no matches → status bar message with the query",
      it("status.no_matches", query="zzz-no-match") == win.statusBar().currentMessage(),
      f"msg={win.statusBar().currentMessage()!r}")

# ══ The close: Esc — the panel is hidden, the dimming and the frames are removed ══
print("== close ==")
QTest.keyClick(line, Qt.Key_Escape)
app.processEvents()
check("Esc closes the bar", not bar.isVisible())
check("dimming cleared on close (all nodes full opacity)",
      all(n.opacity() == 1.0 for n in (n_web, n_db, n_cache)),
      f"opacities={[n.opacity() for n in (n_web, n_db, n_cache)]}")
check("match frames cleared on close",
      not any(n.search_matched for n in (n_web, n_db, n_cache)))
# The "×" button — the same close path (re-open → click). On a re-open
# the query left in the field ("zzz-no-match") comes back to life: a recompute by the scene.
win._toggle_map_search()
app.processEvents()
check("reopened bar re-activates the retained query (counter recomputed)",
      bar._count.text() == it("search.no_results"), f"text={bar._count.text()!r}")
check("reopened: dimming re-applied for the retained no-match query",
      all(n.opacity() < 1.0 for n in (n_web, n_db, n_cache)))
bar._close_btn.click()
app.processEvents()
check("close button '×' closes the bar too", not bar.isVisible())

# ══ #3: the tag filter + the search combine with AND (the sidebar semantics) ══
print("== tag filter + search ==")
n_web.data.tags = ["prod"]
win.refresh_sidebar()
app.processEvents()
idx_prod = win.tag_filter.findData("prod")
check("tag filter combo has 'prod'", idx_prod >= 0, f"idx={idx_prod}")
win.tag_filter.setCurrentIndex(idx_prod)
app.processEvents()
# The prod tag is active: web-1 (prod) glows, the others are dimmed — the search is still closed
check("tag filter alone dims non-tagged nodes",
      n_web.opacity() == 1.0 and all(n.opacity() < 1.0 for n in (n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
# Search "db": only db-1 matches, but it has no prod tag → the AND logic: all are dimmed
win._toggle_map_search()
bar.set_query("db")
app.processEvents()
check("search 'db' + tag 'prod': AND semantics — all nodes dimmed",
      all(n.opacity() < 1.0 for n in (n_web, n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
# Search "web": web-1 passes both the tag and the query → it glows; the others are dimmed
bar.set_query("web")
app.processEvents()
check("search 'web' + tag 'prod': only web-1 passes both filters",
      n_web.opacity() == 1.0 and all(n.opacity() < 1.0 for n in (n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
win._close_map_search()
app.processEvents()
# Resetting the tag filter — all the nodes are back in full brightness
win.tag_filter.setCurrentIndex(0)
app.processEvents()
check("resetting the tag filter restores full brightness",
      all(n.opacity() == 1.0 for n in (n_web, n_db, n_cache)))

# ══ The language switch: the panel is translated again (the placeholder + the counter) ══
print("== language switch ==")
win._switch_language("en")
app.processEvents()
check("placeholder retranslated to English",
      line.placeholderText() == langs["en"]["search.map_placeholder"],
      f"ph={line.placeholderText()!r}")
bar.set_query("web")
app.processEvents()
check("counter retranslated on next update (English '1 / 1')",
      bar._count.text() == "1 / 1", f"text={bar._count.text()!r}")
win._close_map_search()
# The panel on closing saves the last counter state (the query text too
# remains — like in a browser); to check the translation we explicitly set "no matches".
bar.set_count(0, 0)
win._switch_language("ru")
app.processEvents()
check("back to Russian: placeholder and counter in ru",
      line.placeholderText() == langs["ru"]["search.map_placeholder"]
      and bar._count.text() == it("search.no_results"),
      f"ph={line.placeholderText()!r} count={bar._count.text()!r}")

# ══ v0.9.8 bugfix: PySide6 6.11 — the QAction wrappers with an attached QMenu ══
# The death of the Python wrapper of such a QAction destroys the C++ QMenu (verified offscreen AND
# native). MainWindow._qaction_guard keeps all such actions immortal;
# _switch_language no longer goes through action.menu(). Regression: after the "dangerous"
# workarounds ALL the registered menus/actions must live.
print("== menu survival (PySide6 guard) ==")
def _dead_registered():
    dead = []
    for w, k in win._menu_i18n:
        try:
            if isinstance(w, QMenu):
                _ = w.title()
            else:
                _ = w.text()
        except RuntimeError:
            dead.append(k)
    return dead

check("all registered menu widgets alive before stress", not _dead_registered(),
      str(_dead_registered()))

# The pattern that killed the menu: the temporary wrappers + act.menu() (the palette/the old _switch_language)
for top in win.menuBar().actions():
    child = top.menu()
    if child is not None:
        for sub in list(child.actions()):
            pass
app.processEvents()
check("menus survive palette-style walk with temporary wrappers",
      not _dead_registered(), str(_dead_registered()))

# A language switch (twice) — the menu and the actions are alive, the active language mark is set
win._switch_language("en")
app.processEvents()
check("all registered menu widgets alive after switch to en",
      not _dead_registered(), str(_dead_registered()))
lang_menu = next((w for w, k in win._menu_i18n if k == "lang.menu"), None)
en_act = next((a for a in list(lang_menu.actions()) if a.data() == "en"), None) if lang_menu else None
check("active language checkmark set on 'en' action",
      en_act is not None and en_act.isChecked(), f"act={en_act}")
win._switch_language("ru")
app.processEvents()
check("all registered menu widgets alive after switch back to ru",
      not _dead_registered(), str(_dead_registered()))
ru_act = next((a for a in list(lang_menu.actions()) if a.data() == "ru"), None) if lang_menu else None
check("active language checkmark moved to 'ru' action",
      ru_act is not None and ru_act.isChecked() and en_act is not None and not en_act.isChecked(),
      f"ru={ru_act.isChecked() if ru_act else None} en={en_act.isChecked() if en_act else None}")

# ══ The project switch closes the search (the old query is stale for the new nodes) ══
print("== project switch ==")
win._toggle_map_search()
bar.set_query("web")
app.processEvents()
check("search open with a query before project switch", bar.isVisible())
win._new_project()
app.processEvents()
check("new project closes the map search", not bar.isVisible())
check("search state cleared after new project (empty query)",
      win._map_search_query == "" and win._map_search_matches == []
      and win._map_search_index == -1)

# ══ Robustness: the close on an already-closed panel — a safe no-op ══
try:
    win._close_map_search()
    check("_close_map_search() twice is a safe no-op", True)
except Exception as e:
    check("_close_map_search() twice is a safe no-op", False, repr(e))

# Cleanup: first reset dirty — otherwise closeEvent would go to the save dialog.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
