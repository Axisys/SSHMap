# -*- coding: utf-8 -*-
"""v1.2.4.1 — Сворачивание сайдбара и карты в тонкую линию (кнопки + меню, ROADMAP v1.2.4.1).

Тематический тест релиза (конвенция «новый тематический файл»): offscreen, без сети
(пробы статусов мгновенно offline; терминальные сессии — на фейковых потоках).

§1 Структура: QSplitter[container_sidebar | container_map]; setCollapsible(0/1)=False
   (ручка до нуля не дотягивается); полоски _CollapseStrip 18px (скрыты в развёрнутом
   состоянии); угловые кнопки с ромбом «◇» (нижний ряд SidebarPanel / overlay в правом
   НИЖНЕМ углу MapView — верх зарезервирован под миникарту, v1.2.4.1-fix); пункты
   меню «Вид» act_show_sidebar/act_show_map — checkable с иконками пары.

§2 Сайдбар — ТРИ пути: угловая кнопка (click), клик по полоске (QTest.mouseClick),
   пункт меню (trigger() — PySide6 6.11: клик инвертирует checked сам и эмитит).
   Каждый путь: панель hide()/show(), полоска на её месте, галочка пункта = состояние,
   персистентность в config.json.

§3 Карта — те же три пути (overlay-кнопка + перепозиция по resizeEvent — правый нижний
   угол, полоска, меню).

§4 Запрет двойного сворачивания (v1.2.4.1-fix, запрос тестировщика): обе панели
   ОДНОВРЕМЕННО свёрнутыми быть не могут (окно-«пустышка» из двух полосок недопустимо,
   даже при открытом доке). Первая панель сворачивается; попытка свернуть вторую — все
   три пути (меню/кнопка/setChecked) отклоняются: панель остаётся развёрнутой, галочка
   не расходится с механикой, статус-подсказка; после развёртывания первой вторая снова
   сворачивается.

§5 Guard no-op при свёрнутой карте: fit_to_content/_center_view/reveal-узел/навигация
   поиска (Enter/Shift+Enter) — без исключений и без авто-показа карты; выделение и
   статусы работают в фоне (scene-based), точки появляются при разворачивании.

§6 Экспорт PNG/PDF/drawio при свёрнутой карте: файлы создаются (сцена рендерится,
   вид не нужен).

§7 terminal_mode="tabs": карта свёрнута → док «Терминалы» жив, сессия печатает,
   отрыв дока в окно и возврат работают (QDockWidget независим от сплиттера).

§8 Персистентность: ui_sidebar_collapsed/ui_map_collapsed в config.json (merge-write —
   чужие ключи не сбрасываются); новое окно применяет состояние при старте ПОСЛЕ
   restoreState(); ручная запись ОБОИХ ключей True (старый config) — при старте
   применяется только сайдбар, карта остаётся развёрнутой (инвариант §4); частичное
   развёртывание пишет только свой ключ.

§9 Ручка сплиттера до нуля не дотягивается: setSizes([0, …]) клампится minimumWidth'ом
   контейнера (160/240).

§10 i18n-паритет (421 = 417 + 3 + 1: view.toggle_map + tooltip'ы полосок +
    status.collapse_both_forbidden) + состояние релиза (пин _common.py; версия без
    изменений — v1.2.4.1-fix).

Запуск: python tests/test_view_toggles.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QDockWidget

app = QApplication(sys.argv)

# Сеть в тестах запрещена: пробы статусов возвращают результат мгновенно.
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import i18n
import modules.ssh_terminal as ST
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# Обвязка
# ════════════════════════════════════════════════════════════

def _cfg_path():
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def write_config(d):
    """Merge-запись в config.json (семантика i18n.save_config)."""
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cur = {}
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cur = data
        except (json.JSONDecodeError, OSError):
            pass
    cur.update(d)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cur, f)


def clear_config():
    try:
        os.remove(_cfg_path())
    except OSError:
        pass


# QMessageBox — без модалок в offscreen; question → Discard (закрытие без сохранения).
boxes = []


def _fake_question(*a, **k):
    boxes.append(("question", str(a[1]) if len(a) > 1 else ""))
    return QMessageBox.Discard


MW.QMessageBox.question = staticmethod(_fake_question)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))


class _FakeThread(QThread):
    """Idle-поток: тот же API, что у SSHTerminalThread (реальный SSH не нужен)."""
    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.client = None
        self.channel = None
        self.running = True
        self.stop_calls = 0

    def run(self):
        pass

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def send_data(self, data_bytes):
        pass


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread  # все сессии в этом файле — на фейке


def make_main():
    """Offscreen-MainWindow с остановленным autosave-таймером (детерминизм)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


STRIP_W = 18

# ════════════════════════════════════════════════════════════
# 1. Структура: контейнеры, полоски, кнопки, пункты меню
# ════════════════════════════════════════════════════════════
print("== 1. structure ==")

clear_config()
win = make_main()
sp = win._splitter
check("QSplitter: два члена (контейнеры панелей)", sp.count() == 2, f"count={sp.count()}")
check("setCollapsible(0)=False и setCollapsible(1)=False",
      not sp.isCollapsible(0) and not sp.isCollapsible(1))
check("сайдбар живёт в контейнере [sidebar | полоска]",
      win.sidebar.parentWidget() is win._sidebar_container,
      f"parent={win.sidebar.parentWidget()}")
check("карта живёт в контейнере [полоска | view]",
      win.view.parentWidget() is win._map_container)
for name, strip in (("sidebar", win._sidebar_strip), ("map", win._map_strip)):
    check(f"полоска {name}: фиксированная ширина {STRIP_W}px",
          strip.minimumWidth() == STRIP_W and strip.maximumWidth() == STRIP_W,
          f"min={strip.minimumWidth()} max={strip.maximumWidth()}")
    check(f"полоска {name}: скрыта в развёрнутом состоянии", not strip.isVisible())
check("угловая кнопка сайдбара: QToolButton в нижнем ряду панели (правый угол)",
      win.sidebar.collapse_btn.parentWidget() is win.sidebar)
check("угловая кнопка карты: overlay на MapView (child of view)",
      win._map_collapse_btn.parentWidget() is win.view)
# v1.2.4.1-fix: иконка — ромб «◇» у обеих панелей; кнопка карты — в правом НИЖНЕМ углу
check("угловые кнопки: ромбовидная иконка задана (не пуста)",
      not win.sidebar.collapse_btn.icon().isNull()
      and not win._map_collapse_btn.icon().isNull())
check("кнопка карты: правый НИЖНИЙ угол view (верх — под миникарту)",
      win._map_collapse_btn.y() > win.view.height() // 2
      and win._map_collapse_btn.x() + win._map_collapse_btn.width() <= win.view.width(),
      f"btn=({win._map_collapse_btn.x()},{win._map_collapse_btn.y()}) "
      f"view={win.view.width()}x{win.view.height()}")
check("act_show_sidebar: checkable, checked по умолчанию, иконка не пуста",
      win.act_show_sidebar.isCheckable() and win.act_show_sidebar.isChecked()
      and not win.act_show_sidebar.icon().isNull())
check("act_show_map: checkable, checked по умолчанию, иконка не пуста",
      win.act_show_map.isCheckable() and win.act_show_map.isChecked()
      and not win.act_show_map.icon().isNull())
from ui.icons import get_icon
check("иконки пары в _DRAWERS: sidebar_panel/map_panel рендерятся",
      not get_icon("sidebar_panel").isNull() and not get_icon("map_panel").isNull())

# ════════════════════════════════════════════════════════════
# 2. Сайдбар — три пути сворачивания/разворачивания
# ════════════════════════════════════════════════════════════
print("== 2. sidebar: three control paths ==")

# ── путь A: угловая кнопка (нижний ряд сайдбара) ─────────────────────────────
win.sidebar.collapse_btn.click()
app.processEvents()
check("кнопка: сайдбар свёрнут (панель скрыта, полоска показана)",
      win.sidebar.isHidden() and win._sidebar_strip.isVisible())
check("кнопка: контейнер = ширина полоски",
      win._sidebar_container.width() == STRIP_W, f"w={win._sidebar_container.width()}")
check("кнопка: пункт меню снят (checked = развёрнут)", not win.act_show_sidebar.isChecked())
check("кнопка: config ui_sidebar_collapsed=True",
      i18n.load_config().get("ui_sidebar_collapsed") is True)

# ── путь B: клик по полоске (реальное мышиное событие) ───────────────────────
QTest.mouseClick(win._sidebar_strip, Qt.LeftButton)
app.processEvents()
check("клик по полоске: сайдбар развёрнут",
      not win.sidebar.isHidden() and not win._sidebar_strip.isVisible())
check("клик по полоске: пункт меню отмечен", win.act_show_sidebar.isChecked())
check("клик по полоске: config ui_sidebar_collapsed=False",
      i18n.load_config().get("ui_sidebar_collapsed") is False)

# ── путь C: пункт меню «Вид → Сайдбар» (PySide6 6.11: trigger() = клик —
#    сам инвертирует checked и эмитит; двойная setChecked+trigger запрещена) ──
win.act_show_sidebar.trigger()
app.processEvents()
check("меню (trigger #1): сайдбар свёрнут, пункт снят",
      win.sidebar.isHidden() and not win.act_show_sidebar.isChecked())
win.act_show_sidebar.trigger()
app.processEvents()
check("меню (trigger #2): сайдбар развёрнут, пункт отмечен",
      not win.sidebar.isHidden() and win.act_show_sidebar.isChecked())

# ════════════════════════════════════════════════════════════
# 3. Карта — те же три пути (+ перепозиция overlay-кнопки по resize)
# ════════════════════════════════════════════════════════════
print("== 3. map: three control paths ==")

win._map_collapse_btn.click()
app.processEvents()
check("кнопка: карта свёрнута (view скрыт, полоска показана)",
      win.view.isHidden() and win._map_strip.isVisible())
check("кнопка: контейнер карты = ширина полоски",
      win._map_container.width() == STRIP_W, f"w={win._map_container.width()}")
check("кнопка: пункт «Карта» снят", not win.act_show_map.isChecked())
check("кнопка: config ui_map_collapsed=True",
      i18n.load_config().get("ui_map_collapsed") is True)

QTest.mouseClick(win._map_strip, Qt.LeftButton)
app.processEvents()
check("клик по полоске: карта развёрнута",
      not win.view.isHidden() and not win._map_strip.isVisible())
check("клик по полоске: пункт «Карта» отмечен", win.act_show_map.isChecked())

win.act_show_map.trigger()
app.processEvents()
check("меню (trigger #1): карта свёрнута, пункт снят",
      win.view.isHidden() and not win.act_show_map.isChecked())
win.act_show_map.trigger()
app.processEvents()
check("меню (trigger #2): карта развёрнута, пункт отмечен",
      not win.view.isHidden() and win.act_show_map.isChecked())

# overlay-кнопка следует за resizeEvent (сигнал MapView.resized) — в правом НИЖНЕМ углу
win.resize(1400, 800)
app.processEvents()
btn = win._map_collapse_btn
check("overlay-кнопка после resize: правый нижний угол view",
      btn.y() + btn.height() >= win.view.height() - 12
      and btn.x() + btn.width() <= win.view.width()
      and btn.y() > win.view.height() // 2,
      f"btn=({btn.x()},{btn.y()}) view={win.view.width()}x{win.view.height()}")

# ════════════════════════════════════════════════════════════
# 4. Запрет двойного сворачивания (v1.2.4.1-fix, запрос тестировщика)
# ════════════════════════════════════════════════════════════
print("== 4. both collapsed is forbidden ==")

# Первая панель сворачивается — можно (карта развёрнута).
win.act_show_sidebar.trigger()
app.processEvents()
check("первая панель свёрнута: сайдбар скрыт, полоска видна",
      win.sidebar.isHidden() and win._sidebar_strip.isVisible())
w_before = win.width()

# Попытка свернуть ВТОРУЮ (карту) — все три пути отклоняются.
# Путь меню: Qt сам инвертирует checked → toggled(False) → forbidden → галочка возвращается.
win.act_show_map.trigger()
check("статус-подсказка при отказе (проверено до processEvents)",
      win.statusBar().currentMessage() == i18n.t("status.collapse_both_forbidden"))
app.processEvents()
check("меню: вторая панель НЕ сворачивается (карта видна, полоска скрыта)",
      not win.view.isHidden() and not win._map_strip.isVisible())
check("меню: галочка не расходится с механикой (пункт «Карта» отмечен)",
      win.act_show_map.isChecked())

# Путь угловой кнопки.
win._map_collapse_btn.click()
app.processEvents()
check("кнопка: вторая панель тоже НЕ сворачивается",
      not win.view.isHidden() and win.act_show_map.isChecked())

# Путь программного setChecked (тот же, что применение config при старте).
win.act_show_map.setChecked(False)
app.processEvents()
check("setChecked(False): тоже запрещено",
      not win.view.isHidden() and win.act_show_map.isChecked())

check("окно не меняется (размер сохранён)", win.width() == w_before,
      f"{w_before} -> {win.width()}")
check("config: ui_map_collapsed НЕ записан True",
      i18n.load_config().get("ui_map_collapsed") is not True)

# После развёртывания первой панели вторая снова может сворачиваться.
win.act_show_sidebar.trigger()  # развернуть сайдбар
app.processEvents()
check("сайдбар развёрнут", not win.sidebar.isHidden())
win.act_show_map.setChecked(False)  # теперь разрешено
app.processEvents()
check("после возврата первой панели вторая сворачивается (карта = полоска)",
      win.view.isHidden() and win._map_strip.isVisible()
      and not win.act_show_map.isChecked())
# К обе развёрнуты (для следующих секций).
QTest.mouseClick(win._map_strip, Qt.LeftButton)
app.processEvents()
check("обе панели развёрнуты",
      not win.sidebar.isHidden() and not win.view.isHidden()
      and not win._sidebar_strip.isVisible() and not win._map_strip.isVisible())

# ════════════════════════════════════════════════════════════
# 5. Guard no-op при свёрнутой карте
# ════════════════════════════════════════════════════════════
print("== 5. guards with map collapsed ==")

n = win.scene.add_server(ServerData(id="vt-1", alias="GuardNode", host="10.99.0.1", user="root"))
win.act_show_map.setChecked(False)
app.processEvents()

guard_ok = True
try:
    win._fit_to_content()
    win._center_view()
    win._reveal_node_on_map(n)
except Exception as e:  # noqa: BLE001
    guard_ok = False
    print("   guard exception:", repr(e))
check("fit/center/reveal при свёрнутой карте: без исключений", guard_ok)
check("карта не показывается автоматически", win.view.isHidden())
check("reveal всё равно выделяет узел (scene-based)", n.isSelected())

# навигация поиска Enter/Shift+Enter
win.map_search.show()  # панель — child скрытого view: живёт, но не видна; исключений нет
app.processEvents()
win._on_map_search_query("guardnode")
app.processEvents()
nav_ok = True
try:
    win._map_search_step(1)
    win._map_search_step(-1)
except Exception as e:  # noqa: BLE001
    nav_ok = False
    print("   search-nav exception:", repr(e))
check("навигация поиска (Enter/Shift+Enter): без исключений, карта не показана",
      nav_ok and win.view.isHidden())

# статус-чеки работают в фоне (scene-based), точки появятся при разворачивании
n.set_status("online")
app.processEvents()
marker_ok = True
try:
    win._update_sidebar_status_marker(n.data.id)
except Exception as e:  # noqa: BLE001
    marker_ok = False
    print("   status marker exception:", repr(e))
check("статус в фоне: узел online, маркер сайдбара обновлён без исключений",
      marker_ok and n._status_dot.brush().color().name() == "#22c55e")
win.act_show_map.trigger()  # развернуть карту — точка на месте
app.processEvents()
check("после разворачивания: карта видна, статус-точка на узле",
      not win.view.isHidden() and n._status_dot.brush().color().name() == "#22c55e")

# ════════════════════════════════════════════════════════════
# 6. Экспорт PNG/PDF/drawio при свёрнутой карте
# ════════════════════════════════════════════════════════════
print("== 6. exports with map collapsed ==")

win.act_show_map.setChecked(False)
app.processEvents()

_export_path = {"p": None}


def _fake_save_name(*a, **k):
    return (_export_path["p"], "")


MW.QFileDialog.getSaveFileName = staticmethod(_fake_save_name)

_export_path["p"] = os.path.join(WORK, "vt_map.png")
win._export_map_image()
check("экспорт PNG при свёрнутой карте: файл создан",
      os.path.isfile(_export_path["p"]) and os.path.getsize(_export_path["p"]) > 0)

_export_path["p"] = os.path.join(WORK, "vt_map.pdf")
win._export_map_pdf()
pdf_ok = False
if os.path.isfile(_export_path["p"]):
    with open(_export_path["p"], "rb") as f:
        pdf_ok = f.read(5) == b"%PDF-" and os.path.getsize(_export_path["p"]) > 1024
check("экспорт PDF при свёрнутой карте: валидный файл", pdf_ok)

_export_path["p"] = os.path.join(WORK, "vt_map.drawio")
win._export_map_drawio()
check("экспорт drawio при свёрнутой карте: файл создан",
      os.path.isfile(_export_path["p"]) and os.path.getsize(_export_path["p"]) > 0)

# ════════════════════════════════════════════════════════════
# 7. terminal_mode="tabs": карта свёрнута → док жив, сессии печатают
# ════════════════════════════════════════════════════════════
print("== 7. terminals dock with map collapsed ==")

write_config({"terminal_mode": "tabs"})
node_d = win.scene.add_server(ServerData(id="vt-d", alias="DockNode", host="10.99.0.2", user="root"))
dock = win._spawn_terminal_window(node_d)
app.processEvents()
check("режим 'tabs': док «Терминалы» создан (карта свёрнута)",
      isinstance(dock, QDockWidget) and dock.objectName() == "terminals_dock"
      and win.view.isHidden())

page = dock.content.session_tabs.widget(0)
page.terminal_thread.output_signal.emit(b"hello from dock\r\n")
app.processEvents()
check("сессия печатает при свёрнутой карте (вывод на холсте)",
      "hello from dock" in page.widget.visible_text(),
      repr(page.widget.visible_text())[:80])

dock.setFloating(True)
app.processEvents()
check("отрыв дока: отдельное окно (isWindow), док жив",
      dock.isFloating() and dock.isWindow())
page.terminal_thread.output_signal.emit(b"still printing\r\n")
app.processEvents()
check("в оторванном доке сессия продолжает печатать",
      "still printing" in page.widget.visible_text())
dock.setFloating(False)
app.processEvents()
page.terminal_thread.output_signal.emit(b"back on map\r\n")
app.processEvents()
check("возврат дока на карту: не плавающий, сессия жива и продолжает печатать",
      not dock.isFloating() and "back on map" in page.widget.visible_text())

win.act_show_map.trigger()  # развернуть карту (док остаётся рядом)
app.processEvents()
check("карта развёрнута, док на месте",
      not win.view.isHidden() and dock.isVisible())

# ════════════════════════════════════════════════════════════
# 8. Персистентность: config.json + применение при старте ПОСЛЕ restoreState
# ════════════════════════════════════════════════════════════
print("== 8. persistence ==")

win._dirty = False
win.close()
app.processEvents()

clear_config()
write_config({"terminal_mode": "tabs", "language": "en"})  # чужие ключи — для merge-проверки
win_p = make_main()
win_p.act_show_sidebar.setChecked(False)  # только ОДНА панель (вторая — запрещена, §4)
app.processEvents()
cfg = i18n.load_config()
check("свёрнутость записана: ui_sidebar_collapsed=True",
      cfg.get("ui_sidebar_collapsed") is True, str(cfg))
check("merge-write: чужие ключи не сброшены (terminal_mode/language на месте)",
      cfg.get("terminal_mode") == "tabs" and cfg.get("language") == "en", str(cfg))
win_p._dirty = False
win_p.close()
app.processEvents()

# Ручная запись ОБОИХ ключей True (например, старый config): при старте применяется
# только первая панель (сайдбар — первый в порядке применения), сворачивание карты
# запрещено инвариантом §4 — карта остаётся развёрнутой.
write_config({"ui_sidebar_collapsed": True, "ui_map_collapsed": True})
win_p2 = make_main()  # новое окно — состояние применяется при старте (после restoreState)
check("новое окно: сайдбар свёрнут при старте",
      win_p2._sidebar_collapsed is True and win_p2.sidebar.isHidden()
      and not win_p2.act_show_sidebar.isChecked())
check("новое окно: карта НЕ сворачивается при старте (инвариант: хотя бы одна открыта)",
      win_p2._map_collapsed is False and not win_p2.view.isHidden()
      and win_p2.act_show_map.isChecked())

# частичное развёртывание — пишет только свой ключ
win_p2.act_show_sidebar.trigger()
app.processEvents()
cfg = i18n.load_config()
check("частичный возврат: ui_sidebar_collapsed=False, ui_map_collapsed=True (не сброшен)",
      cfg.get("ui_sidebar_collapsed") is False and cfg.get("ui_map_collapsed") is True, str(cfg))

win_p2._dirty = False
win_p2.close()
app.processEvents()

# ════════════════════════════════════════════════════════════
# 9. Ручка сплиттера до нуля не дотягивается
# ════════════════════════════════════════════════════════════
print("== 9. splitter handle cannot reach zero ==")

clear_config()
win_h = make_main()
win_h._splitter.setSizes([0, 1200])
app.processEvents()
check("setSizes([0, …]): сайдбар не сжимается ниже minimum (160px)",
      win_h._sidebar_container.width() >= win_h.SIDEBAR_MIN_WIDTH,
      f"w={win_h._sidebar_container.width()}")
win_h._splitter.setSizes([1200, 0])
app.processEvents()
check("setSizes([…, 0]): карта не сжимается ниже minimum (240px)",
      win_h._map_container.width() >= win_h.MAP_MIN_WIDTH,
      f"w={win_h._map_container.width()}")

win_h._dirty = False
win_h.close()
app.processEvents()

# ════════════════════════════════════════════════════════════
# 10. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== 10. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
new_keys = ["view.toggle_map", "view.strip_sidebar_tooltip", "view.strip_map_tooltip",
            "status.collapse_both_forbidden"]  # +1 — v1.2.4.1-fix (запрет двойного сворачивания)
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("4 ключа v1.2.4.1 (+fix) есть и не пусты в en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)  # 421 = 417 + 3 + 1 (пин _common.py; версия без изменений)
check_release_state(ROOT)

finish()
