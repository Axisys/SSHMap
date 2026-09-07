# -*- coding: utf-8 -*-
"""v1.2.4-fix — РЕГРЕССИЯ: реальный путь клика по checkable-пунктам меню (QAction.trigger()).

Инцидент: ручное тестирование не подтвердило мультинабор — «ставлю галочку в
Вид → Мультинабор, и ничего не происходит: нет рамки, бейджей, плашки». Корень
(эмпирика на PySide6 6.11.1, offscreen): авто-подключение QMenu.addAction(text, slot)
— то, что делает MainWindow._add_menu_action — эмитит QAction.triggered в Python-слот
БЕЗ аргументов (явный action.triggered.connect(slot) передаёт новое состояние, а
авто-подключение — нет). _toggle_multi_input(checked=None) падал в no-op-ветку
(target = текущее состояние) — режим из меню не включался и не выключался вообще;
двигалась только галочка (её переворачивает сам Qt), F12 молчал (шорткат вешается
только в активном режиме).

Фикс: пункт подключён к toggled(bool) (новое состояние — там же, где и у явного
triggered.connect); checked=None в _toggle_multi_input — теперь реальный toggle.

Этот тест идёт ТОЧНО тем путём, что клик пользователя: act.trigger() — Qt сам
инвертирует checked и эмитит сигналы (так работают и пункт меню, и F12-шорткат на
том же QAction). SSH не нужен: хаб/provider/плашка живут без терминалов; для
проверки рамки/бейджа в реестр кладётся один duck-typed фейк-контейнер.

Запуск:  python tests/test_menu_actions_regression.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import ui.main_window as MW  # noqa: E402
from modules.multi_input import get_hub, MULTI_FRAME_OBJECT_NAME  # noqa: E402


class _FakePageData:
    alias = "fake-a"


class _FakePage:
    """Запись реестра (duck-typing TerminalSessionPage): только то, что используют
    _on_multi_changed/_multi_refresh_ui (_host_window). terminal_thread=None —
    broadcast здесь не проверяется (его закрывает test_multi_input_e2e.py)."""

    def __init__(self, host):
        self._host_window = host
        self.widget = None
        self.terminal_thread = None


class _FakeHost(QWidget):
    """Duck-typing SSHTerminalWindow/TerminalDockContent для apply_container_highlight:
    session_tabs (QTabWidget) + страницы с .server_data.alias + _multi_base_title."""

    def __init__(self):
        super().__init__()
        self.session_tabs = QTabWidget()
        page = QWidget()
        page.server_data = _FakePageData()
        self.session_tabs.addTab(page, "fake-a")
        self._multi_base_title = "fake host"


hub = get_hub()   # singleton процесса (тот же, что у MainWindow и виджетов)
hub.reset()

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("предусловие: режим выключен, плашка скрыта, пункт не отмечен",
      hub.active is False and mw._multi_plaque.isHidden()
      and not mw.act_multi_input.isChecked())

# Одна фейковая сессия в реестре — для счётчика/бейджа/рамки
host = _FakeHost()
mw._terminal_windows.append(_FakePage(host))
app.processEvents()

# ════════════════════════════════════════════════════════════
# 1. ТО, ЧТО ЛОПАЛОСЬ: клик «Вид → Мультинабор» (act.trigger() = клик пользователя)
# ════════════════════════════════════════════════════════════
print("== 1. клик по пункту меню (реальный путь Qt-событий) ==")
mw.act_multi_input.trigger()
app.processEvents()

check("клик: хаб АКТИВЕН (до фикса — no-op, режим не включался)",
      hub.active is True, f"active={hub.active}")
check("клик: галочка на пункте", mw.act_multi_input.isChecked())
check("клик: плашка «МУЛЬТИ: 1 сессия» видима со счётчиком",
      not mw._multi_plaque.isHidden()
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=1),
      repr(mw._multi_label.text()))
check("клик: рамка контейнера (objectName) + бейдж вкладки «MULTI · fake-a»",
      host.session_tabs.objectName() == MULTI_FRAME_OBJECT_NAME
      and host.session_tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="fake-a"),
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r}")
check("клик: префикс заголовка окна сессии",
      host.windowTitle() == i18n.t("terminal.multi_title_prefix") + "fake host",
      repr(host.windowTitle()))
check("клик: статус-сообщение (status.multi_enabled)",
      mw.statusBar().currentMessage() == i18n.t("status.multi_enabled"),
      repr(mw.statusBar().currentMessage()))
check("клик: F12-шорткат ВЕШЕН (выход из режима)",
      mw.act_multi_input.shortcut().toString() == "F12",
      repr(mw.act_multi_input.shortcut().toString()))

# ════════════════════════════════════════════════════════════
# 2. Выход: повторный клик = то, что делает F12 (шорткат на том же QAction)
# ════════════════════════════════════════════════════════════
print("== 2. выход повторным кликом / F12 ==")
mw.act_multi_input.trigger()
app.processEvents()

check("выход: режим выключен, галочка снята",
      hub.active is False and not mw.act_multi_input.isChecked())
check("выход: плашка скрыта, подсветка сброшена (рамка/бейдж/заголовок)",
      mw._multi_plaque.isHidden()
      and host.session_tabs.objectName() == ""
      and host.session_tabs.tabText(0) == "fake-a"
      and host.windowTitle() == "fake host",
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r} "
      f"title={host.windowTitle()!r}")
check("выход: F12-шорткат снят (клавиша снова уходит в shell)",
      mw.act_multi_input.shortcut().toString() == "")

# ════════════════════════════════════════════════════════════
# 3. Запасной путь: безаргументный вызов — реальный toggle (до фикса — no-op)
# ════════════════════════════════════════════════════════════
print("== 3. _toggle_multi_input() без аргумента ==")
mw._toggle_multi_input()
check("безаргументный вызов: режим ВКЛЮЧИЛСЯ (до фикса — no-op)", hub.active is True)
mw._toggle_multi_input()
check("повторный безаргументный вызов: режим выключился", hub.active is False)

# ════════════════════════════════════════════════════════════
# 4. Кнопка выхода на плашке ✕ (явный False) — при активном режиме
# ════════════════════════════════════════════════════════════
print("== 4. кнопка ✕ на плашке ==")
mw.act_multi_input.trigger()   # включение через меню-путь
app.processEvents()
check("✕: режим активен до клика по кнопке", hub.active is True)
mw._multi_exit_btn.click()
app.processEvents()
check("✕: режим выключен, галочка снята, плашка скрыта",
      hub.active is False and not mw.act_multi_input.isChecked()
      and mw._multi_plaque.isHidden())

# уборка: фейк убираем из реестра (реальный teardown делает это по destroyed)
mw._terminal_windows.clear()
finish()
