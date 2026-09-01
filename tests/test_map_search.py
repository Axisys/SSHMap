"""Регрессия v0.9.8 — поиск по карте (Ctrl+F).

ROADMAP v0.9.8:
  #1 Ctrl+F → строка поиска поверх canvas: подсветка совпадающих узлов
     (alias/host/ip/comment) — ServerNode.set_search_match (рамка #38bdf8,
     приоритет ниже выделения) + счётчик «k / N».
  #2 Enter/Shift+Enter — переход между результатами с центрированием и
     рамкой-акцентом (reveal_flash — паттерн пульса set_status), зацикливание.
  #3 Несовпавшие ноды затемняются (set_dimmed, DIM_OPACITY) — совпадения читаются
     мгновенно; тег-фильтр и поиск комбинируются И (семантика сайдбара).

Запуск:  python tests/test_map_search.py   (из корня проекта) или python tests/run_all.py
"""
import os, sys, json, tempfile, traceback

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)


from i18n import t as it, set_language as _set_lang
from models.server import ServerData
import ui.main_window as MW

win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

# Три сервера: web-1 (host+ip 10.0.0.5), db-1 (host db.internal, без IP),
# redis-cache (host+ip 10.0.0.9). Запросы: "web" → 1 совпадение;
# "10.0.0" → 2; "zzz-no-match" → 0. Регистр не учитывается ("WEB").
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

# ══ i18n: 6 новых ключей × en/ru/zh, наборы идентичны (326 на язык; +13 в v0.9.9.2, +2 в v0.9.9.7, +22 в v1.0RC4) ══
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["view.find_on_map", "search.map_placeholder", "search.count",
            "search.no_results", "hint.map_search", "status.no_matches"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("6 новых ключей v0.9.8 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (326 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 326 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# ══ MapSearchBar: клавиатура (Enter / Shift+Enter / Esc) и счётчик ══
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

# ══ Пункт меню «Вид → Поиск по карте…» с хоткеем Ctrl+F ══
print("== menu ==")
# ВАЖНО: menu берём из i18n-реестра, а НЕ через act.menu() на временных обёртках —
# в PySide6 6.11 смерть Python-обёртки QAction с прикреплённым QMenu уничтожает C++-меню
# (см. guard MainWindow._qaction_guard; это же проверено отдельным блоком ниже).
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

# ══ Открытие: панель видна, в верхнем центре viewport, фокус на поле ввода ══
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

# ══ v0.9.9.1 fix: при ресайзе окна панель возвращается в центр (MapView.resized) ══
# До v0.9.9.1 connect view.resized падал в AttributeError и глотался try/except —
# после сужения окна панель оставалась на старом x (240 вместо ~40 при vp 500).
print("== resize reposition (v0.9.9.1 fix) ==")
x_before = bar.geometry().x()
check("bar centered before resize (baseline x=240 at vp 900)", x_before == 240, f"x={x_before}")
view.resize(500, 700); app.processEvents()
geo_r = bar.geometry(); vp_r = view.viewport().rect()
w_r = min(bar.PREFERRED_WIDTH, max(vp_r.width() - 16, bar.MIN_WIDTH))
x_expected = max(8, (vp_r.width() - w_r) // 2)
check("bar re-centered after viewport resize (no longer stuck at old x)",
      geo_r.x() == x_expected and geo_r.y() == 10,
      f"x={geo_r.x()} expected={x_expected} vp_w={vp_r.width()}")
check("position actually changed on resize", x_before != geo_r.x(),
      f"before={x_before} after={geo_r.x()}")
# «Рост обратно» ограничивает окно/сплиттер (offscreen) — проверяем динамический
# центр по фактическому viewport, а не жёсткие 240.
view.resize(900, 700); app.processEvents()
vp_back = view.viewport().rect()
w_back = min(bar.PREFERRED_WIDTH, max(vp_back.width() - 16, bar.MIN_WIDTH))
x_back_expected = max(8, (vp_back.width() - w_back) // 2)
check("bar re-centered again when viewport grows back",
      bar.geometry().x() == x_back_expected and bar.geometry().y() == 10,
      f"x={bar.geometry().x()} expected={x_back_expected} vp_w={vp_back.width()}")

# ══ #1/#3: запрос "web" — подсветка 1 совпадения, остальные затемнены ══
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

# ══ #2: Enter — выбор + центрирование + вспышка; затем гаснет ══
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
# 1 совпадение: Enter зацикливается на нём же — узел остаётся выделенным
QTest.keyClick(line, Qt.Key_Return)
app.processEvents()
check("single match wraps to itself (still selected, counter '1 / 1')",
      win.scene.get_selected_node() is n_web and bar._count.text().endswith("/ 1"))

# ══ #2: два совпадения — Enter/Shift+Enter ходят по кругу ══
print("== two matches ==")
bar.set_query("10.0.0")   # web-1 (host+ip) и redis-cache (host+ip); db-1 — нет
app.processEvents()
matches2 = [n for n in (n_web, n_db, n_cache) if n.search_matched]
check("'10.0.0' matches exactly web-1 and redis-cache",
      matches2 == [n_web, n_cache], f"matched={[n.data.id for n in matches2]}")
check("counter reset to first result '1 / 2'",
      bar._count.text() == it("search.count").format(cur=1, total=2),
      f"text={bar._count.text()!r}")

QTest.keyClick(line, Qt.Key_Return)   # → 2-й результат
app.processEvents()
check("Enter advances to the 2nd match (counter '2 / 2')",
      win.scene.get_selected_node() is n_cache and bar._count.text().endswith("/ 2"),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")
QTest.keyClick(line, Qt.Key_Return)   # → зацикливание на 1-й
app.processEvents()
check("Enter wraps around to the 1st match",
      win.scene.get_selected_node() is n_web
      and bar._count.text() == it("search.count").format(cur=1, total=2),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")
QTest.keyClick(line, Qt.Key_Enter, Qt.ShiftModifier)  # → назад на 2-й
app.processEvents()
check("Shift+Enter goes back to the 2nd match",
      win.scene.get_selected_node() is n_cache and bar._count.text().endswith("/ 2"),
      f"selected={win.scene.get_selected_node().data.id} text={bar._count.text()!r}")

# ══ Регистр не учитывается ══
print("== case-insensitive ==")
bar.set_query("WEB")
app.processEvents()
check("'WEB' matches web-1 (case-insensitive)", n_web.search_matched,
      f"matched={[n.data.id for n in (n_web, n_db, n_cache) if n.search_matched]}")

# ══ Нет совпадений: все затемнены, Enter — сообщение в статус-баре ══
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

# ══ Закрытие: Esc — панель скрыта, затемнение и рамки сняты ══
print("== close ==")
QTest.keyClick(line, Qt.Key_Escape)
app.processEvents()
check("Esc closes the bar", not bar.isVisible())
check("dimming cleared on close (all nodes full opacity)",
      all(n.opacity() == 1.0 for n in (n_web, n_db, n_cache)),
      f"opacities={[n.opacity() for n in (n_web, n_db, n_cache)]}")
check("match frames cleared on close",
      not any(n.search_matched for n in (n_web, n_db, n_cache)))
# Кнопка «×» — тот же путь закрытия (открыть заново → клик). При повторном открытии
# оставшийся в поле запрос ("zzz-no-match") оживает заново: пересчёт по сцене.
win._toggle_map_search()
app.processEvents()
check("reopened bar re-activates the retained query (counter recomputed)",
      bar._count.text() == it("search.no_results"), f"text={bar._count.text()!r}")
check("reopened: dimming re-applied for the retained no-match query",
      all(n.opacity() < 1.0 for n in (n_web, n_db, n_cache)))
bar._close_btn.click()
app.processEvents()
check("close button '×' closes the bar too", not bar.isVisible())

# ══ #3: тег-фильтр + поиск комбинируются И (семантика сайдбара) ══
print("== tag filter + search ==")
n_web.data.tags = ["prod"]
win.refresh_sidebar()
app.processEvents()
idx_prod = win.tag_filter.findData("prod")
check("tag filter combo has 'prod'", idx_prod >= 0, f"idx={idx_prod}")
win.tag_filter.setCurrentIndex(idx_prod)
app.processEvents()
# Тег prod активен: web-1 (prod) светится, остальные затемнены — поиск ещё закрыт
check("tag filter alone dims non-tagged nodes",
      n_web.opacity() == 1.0 and all(n.opacity() < 1.0 for n in (n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
# Поиск "db": совпадает только db-1, но у него нет тега prod → И-логика: все затемнены
win._toggle_map_search()
bar.set_query("db")
app.processEvents()
check("search 'db' + tag 'prod': AND semantics — all nodes dimmed",
      all(n.opacity() < 1.0 for n in (n_web, n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
# Поиск "web": web-1 проходит и тег, и запрос → светится; остальные затемнены
bar.set_query("web")
app.processEvents()
check("search 'web' + tag 'prod': only web-1 passes both filters",
      n_web.opacity() == 1.0 and all(n.opacity() < 1.0 for n in (n_db, n_cache)),
      f"web={n_web.opacity()} db={n_db.opacity()} cache={n_cache.opacity()}")
win._close_map_search()
app.processEvents()
# Сброс тег-фильтра — все узлы снова в полной яркости
win.tag_filter.setCurrentIndex(0)
app.processEvents()
check("resetting the tag filter restores full brightness",
      all(n.opacity() == 1.0 for n in (n_web, n_db, n_cache)))

# ══ Смена языка: панель переведена заново (плейсхолдер + счётчик) ══
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
# Панель при закрытии сохраняет последнее состояние счётчика (текст запроса тоже
# остаётся — как в браузере); для проверки перевода явно ставим «нет совпадений».
bar.set_count(0, 0)
win._switch_language("ru")
app.processEvents()
check("back to Russian: placeholder and counter in ru",
      line.placeholderText() == langs["ru"]["search.map_placeholder"]
      and bar._count.text() == it("search.no_results"),
      f"ph={line.placeholderText()!r} count={bar._count.text()!r}")

# ══ v0.9.8 bugfix: PySide6 6.11 — обёртки QAction с прикреплённым QMenu ══
# Смерть Python-обёртки такого QAction уничтожает C++-QMenu (проверено offscreen И
# native). MainWindow._qaction_guard держит все такие действия бессмертными;
# _switch_language больше не ходит через action.menu(). Регрессия: после «опасных»
# обходов ВСЕ зарегистрированные меню/действия должны жить.
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

# Паттерн, который убивал меню: временные обёртки + act.menu() (палитра/старый _switch_language)
for top in win.menuBar().actions():
    child = top.menu()
    if child is not None:
        for sub in list(child.actions()):
            pass
app.processEvents()
check("menus survive palette-style walk with temporary wrappers",
      not _dead_registered(), str(_dead_registered()))

# Смена языка (дважды) — меню и действия живы, отметка активного языка стоит
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

# ══ Смена проекта закрывает поиск (старый запрос к новым узлам неактуален) ══
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

# ══ Robustness: закрытие при уже закрытой панели — безопасный no-op ══
try:
    win._close_map_search()
    check("_close_map_search() twice is a safe no-op", True)
except Exception as e:
    check("_close_map_search() twice is a safe no-op", False, repr(e))

# Cleanup: сначала сбрасываем dirty — иначе closeEvent уйдёт в диалог сохранения.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
