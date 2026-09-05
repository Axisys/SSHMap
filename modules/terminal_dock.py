# -*- coding: utf-8 -*-
"""v1.2.2 (ROADMAP v1.2.2): «Терминалы» как док окно карты (terminal.mode = "tabs").

TerminalDockContent — встраиваемый контейнер сессий, аналог SSHTerminalWindow.
session_tabs (v1.2.1), но для MainWindow: QTabWidget из TerminalSessionPage +
собственная статус-строка (label + SFTP-прогресс-бар). Контракт тот же: каждый
таб = одна сессия, заголовок таба — alias узла, tooltip — terminal.tab_close_tooltip;
закрытие таба = cleanup ЛОКАЛЬНОЙ страницы (gate «ask» confirm_close → единый
teardown shutdown, соседние табы не затрагиваются). Отличие от окна: закрытие
ПОСЛЕДНЕГО таба НЕ уничтожает контейнер — сигнал last_tab_closed (TerminalsDock
прячет док); сессии закрываются постранично, контейнер переживает их.

Мост «статус-бар» — только АКТИВНЫЙ таб (паттерн v1.2.1), но в статус-строку
САМОГО ДОКА, а не в статус-бар карты: при отрыве дока в отдельное окно сообщения
и прогресс следуют за контейнером и не конфликтуют со статус-баре MainWindow.

TerminalsDock(QDockWidget) — отрываемый док (флаги по умолчанию Movable|Closable|
Floatable): float → отдельное окно с вкладками, возврат → обратно на карту; из
одного механизма получаются и «вкладки», и «окна». Карта остаётся центральным
виджетом MainWindow — self.view не трогается. WA_DeleteOnClose НЕ ставится:
контейнер живёт до закрытия MainWindow (создаётся лениво на первую сессию в
режиме "tabs", повторное создание при переключении режима не нужно).

Тестовые швы — те же, что у страницы (v1.2): класс потока и QMessageBox берутся
из модуля ssh_terminal в момент вызова (TerminalSessionPage._st_module()).
"""
import itertools

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QProgressBar,
    QDockWidget,
)

try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage


def _st_module():
    """Модуль ssh_terminal в момент вызова (тестовый шов подмены атрибутов)."""
    try:
        from . import ssh_terminal as _st
    except ImportError:
        import ssh_terminal as _st
    return _st


def get_translator():
    """Safe i18n helper — как в terminal_page/ssh_terminal."""
    return _st_module().get_translator()


class TerminalDockContent(QWidget):
    """v1.2.2: контейнер сессий для дока «Терминалы» (QTabWidget из страниц).

    Состав: session_tabs (QTabWidget, табы закрываемые) + статус-строка
    (status_label + sftp_progress). Страницы создаются с parent=session_tabs
    (уничтожаются вместе с контейнером) и привязываются к контенту через
    set_host_window(self) — close_terminal() страницы вызывает close_page(self),
    т.е. тот же путь, что у SSHTerminalWindow (v1.2.1).

    Мост сигналов АКТИВНОЙ страницы: status_message → status_label (timeout_ms > 0
    — авто-очистка по таймеру с token-guard'ом), progress_busy/update/hidden →
    sftp_progress. При переключении табов мост переподключается; сообщения
    неактивных табов в статус-строку не доходят (вид v1.2.1).
    """

    # v1.2.2: последний таб закрыт — контейнер пуст (TerminalsDock прячет док)
    last_tab_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        t = get_translator()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # v1.2.2 (задача 2): QTabWidget из TerminalSessionPage — каждый таб = одна
        # SSH-сессия; табы закрываемые: закрытие таба = cleanup ЛОКАЛЬНОЙ страницы.
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.session_tabs.currentChanged.connect(self._on_current_tab_changed)
        layout.addWidget(self.session_tabs, 1)

        # Статус-строка самого дока (не статус-бар карты): при отрыве дока в окно
        # сообщения/прогресс следуют за контейнером. Вид — как у окна терминала:
        # sticky-текст слева, SFTP-прогресс справа (скрыт, когда передач нет).
        row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #94a3b8; padding: 2px 0;")
        self.sftp_progress = QProgressBar()
        self.sftp_progress.setFixedWidth(180)
        self.sftp_progress.setTextVisible(True)
        self.sftp_progress.setVisible(False)
        row.addWidget(self.status_label, 1)
        row.addWidget(self.sftp_progress)
        layout.addLayout(row)

        self._bridged_page = None      # активная страница (мост статус-строки)
        self._status_tokens = itertools.count()   # token-guard авто-очистки label
        self._status_token = None

    # ── v1.2.2: табы = сессии (контракт SSHTerminalWindow, v1.2.1) ────────────

    def add_session(self, server_data, password: str = None,
                    initial_command: str = "") -> "TerminalSessionPage":
        """Новая сессия = новый таб (существующий путь «подключиться к узлу»).

        Страница создаётся с parent=session_tabs, привязывается к хосту
        (set_host_window(self) — close_page живёт на контенте) и добавляется как
        таб: заголовок — alias узла, tooltip — terminal.tab_close_tooltip. Новый
        таб явно активируется (Qt: addTab делает текущим только ПЕРВЫЙ таб)."""
        t = get_translator()
        page = TerminalSessionPage(
            server_data, parent=self.session_tabs,
            password=password, initial_command=initial_command)
        page.set_host_window(self)
        idx = self.session_tabs.addTab(page, server_data.alias)
        self.session_tabs.setCurrentIndex(idx)
        try:
            self.session_tabs.setTabToolTip(idx, t("terminal.tab_close_tooltip"))
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия) — tooltip не критичен
        return page

    def close_page(self, page):
        """Закрыть ОДИН таб — cleanup ЛОКАЛЬНОЙ страницы (gate «ask» confirm_close
        → единый teardown shutdown); соседние табы не затрагиваются. Закрытие
        ПОСЛЕДНЕГО таба НЕ уничтожает контейнер: сигнал last_tab_closed
        (TerminalsDock прячет док; следующая сессия в режиме "tabs" покажет его)."""
        idx = self.session_tabs.indexOf(page)
        if idx < 0:
            return  # таб уже удалён (гонка teardown)
        try:
            if not page.confirm_close():
                return  # «ask» + Cancel — таб остаётся открытым
        except RuntimeError:
            pass  # C++-объект уже удалён — закрываем без вопросов (как раньше)
        try:
            page.shutdown()
        except Exception:  # noqa: BLE001 — teardown-устойчивость
            pass
        self.session_tabs.removeTab(idx)   # currentChanged → мост переподключается
        page.deleteLater()
        if self.session_tabs.count() == 0:
            self.last_tab_closed.emit()

    def _on_tab_close_requested(self, index: int):
        """Крестик на табе (setTabsClosable) → close_page."""
        try:
            page = self.session_tabs.widget(index)
        except RuntimeError:
            return  # C++-объект уже удалён (гонка закрытия)
        if page is not None:
            self.close_page(page)

    # ── v1.2.2: мост «статус-строка» — только активный таб (паттерн v1.2.1) ───

    def _on_current_tab_changed(self, index: int):
        try:
            page = (self.session_tabs.widget(index)
                    if 0 <= index < self.session_tabs.count() else None)
        except RuntimeError:
            page = None  # C++-объект уже удалён (гонка закрытия)
        self._set_bridged_page(page)

    def _set_bridged_page(self, page):
        """Мост сигналов АКТИВНОГО таба в статус-строку дока; при смене таба —
        переподключение (сообщения неактивных табов не доходят). SFTP-прогресс
        синхронизируется со состоянием активного таба."""
        old = self._bridged_page
        if old is not None and old is not page:
            try:
                old.status_message.disconnect(self._on_page_status_message)
                old.progress_busy.disconnect(self._on_page_progress_busy)
                old.progress_update.disconnect(self._on_page_progress_update)
                old.progress_hidden.disconnect(self.sftp_progress.hide)
            except (TypeError, RuntimeError):
                pass  # слот не был подключён / C++-объект удалён — делать нечего
        self._bridged_page = page
        if page is None:
            return
        try:
            page.status_message.connect(self._on_page_status_message)
            page.progress_busy.connect(self._on_page_progress_busy)
            page.progress_update.connect(self._on_page_progress_update)
            page.progress_hidden.connect(self.sftp_progress.hide)
        except RuntimeError:
            return  # C++-объект уже удалён (гонка закрытия) — мостить нечего
        try:
            if getattr(page, "_sftp_busy", 0) > 0:
                self.sftp_progress.setRange(0, 0)   # пока не прилетел total — busy
                self.sftp_progress.setValue(0)
                self.sftp_progress.show()
            else:
                self.sftp_progress.hide()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def _on_page_status_message(self, text: str, timeout_ms: int):
        """Сообщение активной страницы → статус-строка дока. timeout_ms > 0 —
        авто-очистка по таймеру (token-guard: ЛЮБОЕ новое сообщение, включая
        sticky (timeout_ms = 0), инвалидирует отложенный таймаут предыдущего)."""
        try:
            self.status_label.setText(text)
        except RuntimeError:
            return  # C++-объект уже удалён (гонка закрытия)
        token = next(self._status_tokens)
        self._status_token = token
        if timeout_ms > 0:
            try:
                QTimer.singleShot(timeout_ms, lambda tk=token: self._expire_status(tk))
            except RuntimeError:
                pass  # C++-объект уже удалён (гонка закрытия)

    def _expire_status(self, token):
        """Таймаут истёк — очистить label только если не пришло более новое."""
        try:
            if token == self._status_token:
                self.status_label.setText("")
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def _on_page_progress_busy(self):
        try:
            self.sftp_progress.setRange(0, 0)   # пока не прилетел total — busy
            self.sftp_progress.setValue(0)
            self.sftp_progress.show()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def _on_page_progress_update(self, done: int, total: int):
        try:
            if total > 0:
                self.sftp_progress.setRange(0, total)
                self.sftp_progress.setValue(done)
            else:
                self.sftp_progress.setRange(0, 0)   # total неизвестен — busy
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)


class TerminalsDock(QDockWidget):
    """v1.2.2 (задача 2): док «Терминалы» в MainWindow (terminal.mode = "tabs").

    Отрываемый (флаги QDockWidget по умолчанию: Movable|Closable|Floatable):
    float → отдельное окно с вкладками, возврат → обратно на карту — из одного
    механизма получаются и «вкладки», и «окна». Карта остаётся центральным
    виджетом MainWindow (self.view не трогается).

    WA_DeleteOnClose НЕ ставится: закрытие дока (крестик в заголовке) только
    прячет его — сессии продолжают жить (как скрытое окно; вернуть док можно из
    контекстного меню menubar'а QMainWindow). Закрытие ПОСЛЕДНЕГО таба тоже
    прячет док (last_tab_closed → hide), а не уничтожает: следующая сессия в
    режиме "tabs" покажет тот же контейнер. Teardown сессий — постраничный
    (page.shutdown()), контейнер переживает свои сессии."""

    def __init__(self, main_window=None):
        t = get_translator()
        super().__init__(t("terminal.dock_title"), main_window)
        self.setObjectName("terminals_dock")
        self.content = TerminalDockContent(self)
        self.setWidget(self.content)
        self.setMinimumWidth(300)
        # v1.2.2 (задача 3): последний таб закрыт — сессии уже очищены постранично,
        # контейнер пуст: прячем док (не уничтожаем — см. docstring).
        self.content.last_tab_closed.connect(self.hide)
