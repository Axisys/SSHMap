# -*- coding: utf-8 -*-
"""v1.1: Диалог настроек (хаб) — ROADMAP v1.1, задачи 1–6; v1.1.1 — опции вокруг хаба.

QTabWidget «Общие / Терминал / Статусы / Автосохранение / Карта / Язык»:
централизованные настройки приложения + точки входа (меню «Настройки» и кнопка
⚙ сайдбара — в ui/main_window.py / ui/sidebar.py). Каждая следующая идея из
ROADMAP добавляется полем/чекбоксом в существующую вкладку, а не новой UI-версией.

Хранение — ЕДИНЫЙ ~/.sshmap/config.json (i18n.save_config, атомарная merge-запись);
все ключи опциональны, дефолты = текущее поведение:
  * Общие:          external_terminal (v1.1: перенесён из ~/.sshmap_settings.json,
                     миграция при чтении — modules/external_terminal.py, задача 7)
                     + v1.1.1: ui_font_family/ui_font_size (шрифт UI, на лету),
                     ui_show_sidebar_buttons (блок кнопок сайдбара);
  * Терминал:       terminal_palette / terminal_font_size / terminal_history_lines
                     (ключи v1.0) + terminal_close_behavior (v1.1: "close"|"ask")
                     + v1.1.1: terminal_font (семейство; читался с v1.0, UI впервые),
                     terminal_max_open (лимит своих терминалов, дефолт 4);
  * Статусы:        status_interval_sec / status_probe_timeout_sec (v1.1; дефолты
                     30 c / 3.0 c — поведение v1.0, services/status_checker.py);
  * Автосохранение: autosave_enabled / autosave_interval_sec / backup_count (v0.9.7);
  * Карта:          v1.1.1: ui_node_double_click ("properties"|"connect"),
                     ui_show_connection_type (тип на плашке связи);
  * Язык:           language — немедленное применение (signal language_changed →
                     MainWindow._switch_language; пункт «Помощь → Язык» сохранён).

v1.1.1: load_ui_settings() — валидатор ui_* ключей (паттерн get_status_settings);
применение на лету без перезапуска — MainWindow (_apply_settings_from_dialog):
QApplication.setFont, шрифт открытых окон терминала, видимость кнопок сайдбара,
режим двойного клика, перерисовка плашек связей.

Сигналы (паттерн модуля — как ui/sidebar.py: диалог не знает о MainWindow):
    applied()            — конфиг сохранён по ОК; MainWindow применяет на лету
                           автосохранение (QTimer), статусы (StatusChecker) и
                           v1.1.1-опции (шрифты/кнопки/двойной клик/плашки);
                           терминал читает конфиг при следующем создании окна;
    language_changed(str)— выбор языка во вкладке «Язык» (немедленно, до ОК).

i18n: ключи settings.* × en/ru/zh; реестр строк — в retranslate() (смена языка
внутри открытого диалога обновляет его собственные подписи).
"""

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QPushButton, QMessageBox,
)

try:  # i18n — top-level пакет (плоский запуск из корня проекта)
    from i18n import t as _translate
except Exception:  # pragma: no cover - запасной путь
    try:
        from .i18n import t as _translate
    except Exception:
        _translate = None

try:  # v1.1 (задача 7): единый источник — config.json; миграция внутри модуля
    from ..modules.external_terminal import (
        TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
        load_external_terminal_setting,
    )
except ImportError:
    try:
        from modules.external_terminal import (
            TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
            load_external_terminal_setting,
        )
    except ImportError:  # flat-раскладка без модуля — вкладка «Общие» без комбо
        TERMINAL_CHOICES_WINDOWS = ["auto"]
        TERMINAL_CHOICES_LINUX = ["auto"]
        def load_external_terminal_setting():  # noqa: N802
            return "auto"


def _t(key: str, **kw) -> str:
    """Безопасный перевод (как в ui/command_palette.py): без i18n — сам ключ."""
    if _translate is not None:
        try:
            return _translate(key, **kw) if kw else _translate(key)
        except Exception:  # noqa: BLE001 — сбой i18n не роняет диалог
            pass
    return key


def load_ui_settings():
    """v1.1.1 (ROADMAP v1.1.1): читает и валидирует ui_* ключи из ~/.sshmap/config.json.

    Паттерн тех же get_status_settings()/get_autosave_settings() — каждый домен
    читает собственные ключи; источник i18n.load_config() (никогда не падает).
    Возвращает:
      {"font_family": str,            # "" — не задан (системный шрифт)
       "font_size": int | None,       # None — не задан (системный размер; 0 = то же)
       "node_double_click": str,      # "properties" (дефолт) | "connect"
       "show_sidebar_buttons": bool,  # дефолт True — блок кнопок сайдбара виден
       "show_connection_type": bool}  # дефолт False — тип на плашке связи не рисуется
    Невалидные значения (чужой тип, вне диапазона) → дефолт. Никогда не бросает.
    """
    defaults = {"font_family": "", "font_size": None,
                "node_double_click": "properties",
                "show_sidebar_buttons": True, "show_connection_type": False}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("ui_font_family")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("ui_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and 6 <= v <= 72:
        defaults["font_size"] = v     # битое/0/вне диапазона → системный размер (дефолт)

    v = cfg.get("ui_node_double_click")
    if isinstance(v, str) and v.strip().lower() in ("properties", "connect"):
        defaults["node_double_click"] = v.strip().lower()  # битое/чужое → "properties"

    v = cfg.get("ui_show_sidebar_buttons")
    if isinstance(v, bool):
        defaults["show_sidebar_buttons"] = v

    v = cfg.get("ui_show_connection_type")
    if isinstance(v, bool):
        defaults["show_connection_type"] = v

    return defaults


class SettingsDialog(QDialog):
    """Диалог настроек (хаб): 6 вкладок, сохранение в ~/.sshmap/config.json по ОК."""

    applied = Signal()           # конфиг сохранён — применить на лету (MainWindow)
    language_changed = Signal(str)  # выбор языка во вкладке «Язык» (немедленно)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("settings.title"))
        self.resize(500, 400)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_general_tab()
        self._build_terminal_tab()
        self._build_statuses_tab()
        self._build_autosave_tab()
        self._build_map_tab()
        self._build_language_tab()

        # ── Кнопки ОК/Отмена (ОК = сохранение config.json + signal applied) ─────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.ok_btn = QPushButton(_t("settings.ok"))
        self.cancel_btn = QPushButton(_t("settings.cancel"))
        self.ok_btn.clicked.connect(self._on_accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    # ── Вкладка «Общие» (v1.1: external_terminal — единый config.json) ─────────

    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.ext_term_combo = QComboBox()
        choices = (TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                   else TERMINAL_CHOICES_LINUX)
        for tid in choices:
            # i18n-метки пресетов — существующие ключи ssh_ext.preset.* (v0.9.9.2)
            self.ext_term_combo.addItem(_t(f"ssh_ext.preset.{tid}"), tid)
        cur = load_external_terminal_setting()
        idx = next((i for i in range(self.ext_term_combo.count())
                    if self.ext_term_combo.itemData(i) == cur), 0)
        self.ext_term_combo.setCurrentIndex(idx)
        self._lbl_ext_term = QLabel(_t("settings.general.external_terminal"))
        form.addRow(self._lbl_ext_term, self.ext_term_combo)

        # v1.1.1 (пункт 1): шрифт интерфейса — семейство + размер (pt); применение
        # на лету без перезапуска (MainWindow: QApplication.setFont по ОК и при старте).
        ui_cfg = load_ui_settings()
        self.ui_font_family_edit = QLineEdit(ui_cfg["font_family"])
        self._lbl_ui_font_family = QLabel(_t("settings.general.ui_font_family"))
        form.addRow(self._lbl_ui_font_family, self.ui_font_family_edit)
        # 0 = системный размер (specialValueText); диапазон валидатора 6..72
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(0, 72)
        self.ui_font_size_spin.setValue(ui_cfg["font_size"] or 0)
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self._lbl_ui_font_size = QLabel(_t("settings.general.ui_font_size"))
        form.addRow(self._lbl_ui_font_size, self.ui_font_size_spin)

        # v1.1.1 (пункт 5): блок кнопок сайдбара — show/hide (layout сам перестроится);
        # весь сайдбар прячется отдельным пунктом меню «Вид» (MainWindow).
        self.sidebar_buttons_chk = QCheckBox(_t("settings.general.sidebar_buttons"))
        self.sidebar_buttons_chk.setChecked(ui_cfg["show_sidebar_buttons"])
        form.addRow("", self.sidebar_buttons_chk)

        self.tabs.addTab(tab, _t("settings.tab.general"))

    # ── Вкладка «Терминал» (ключи v1.0 + новое поведение закрытия) ─────────────

    def _build_terminal_tab(self):
        try:
            from ..modules.ssh_terminal import load_terminal_settings
        except ImportError:
            from modules.ssh_terminal import load_terminal_settings
        cfg = load_terminal_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.palette_combo = QComboBox()
        self.palette_combo.addItem(_t("settings.terminal.palette.default"), "default")
        self.palette_combo.addItem(_t("settings.terminal.palette.nord"), "nord")
        self.palette_combo.addItem(_t("settings.terminal.palette.dracula"), "dracula")
        self.palette_combo.addItem(_t("settings.terminal.palette.tokyo_night"), "tokyo_night")
        cur_pal = cfg["palette"] or "default"
        idx = next((i for i in range(self.palette_combo.count())
                    if self.palette_combo.itemData(i) == cur_pal), 0)
        self.palette_combo.setCurrentIndex(idx)
        self._lbl_palette = QLabel(_t("settings.terminal.palette"))
        form.addRow(self._lbl_palette, self.palette_combo)

        # v1.1.1 (пункт 1): семейство шрифта терминала (моноширинный); пустое —
        # системный моноширинный. Ключ terminal_font читался с v1.0, UI появляется
        # впервые; применение на лету — в открытые окна (MainWindow по ОК).
        self.term_font_family_edit = QLineEdit(cfg["font_family"])
        self._lbl_term_font_family = QLabel(_t("settings.terminal.font_family"))
        form.addRow(self._lbl_term_font_family, self.term_font_family_edit)

        # Размер шрифта: тот же диапазон валидатора (6–72 pt), дефолт 10
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(cfg["font_size"] or 10)
        self._lbl_font_size = QLabel(_t("settings.terminal.font_size"))
        form.addRow(self._lbl_font_size, self.font_size_spin)

        # v1.1.1 (пункт 3): лимит своих открытых терминалов — при достижении не
        # отказ, а предложение закрыть старейшую сессию (MainWindow._spawn_terminal_window).
        self.max_open_spin = QSpinBox()
        self.max_open_spin.setRange(1, 16)
        self.max_open_spin.setValue(cfg["max_open"])
        self._lbl_max_open = QLabel(_t("settings.terminal.max_open"))
        form.addRow(self._lbl_max_open, self.max_open_spin)

        # Глубина истории: диапазон валидатора (0 = скроллбэк выключен)
        self.history_spin = QSpinBox()
        self.history_spin.setRange(0, 1_000_000)
        self.history_spin.setValue(cfg["history_lines"])
        self._lbl_history = QLabel(_t("settings.terminal.history_lines"))
        form.addRow(self._lbl_history, self.history_spin)

        # v1.1 (задача 3): поведение закрытия сессии — новый ключ
        self.close_behavior_combo = QComboBox()
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.close"), "close")
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.ask"), "ask")
        idx = next((i for i in range(self.close_behavior_combo.count())
                    if self.close_behavior_combo.itemData(i) == cfg["close_behavior"]), 0)
        self.close_behavior_combo.setCurrentIndex(idx)
        self._lbl_close_behavior = QLabel(_t("settings.terminal.close_behavior"))
        form.addRow(self._lbl_close_behavior, self.close_behavior_combo)

        self.tabs.addTab(tab, _t("settings.tab.terminal"))

    # ── Вкладка «Статусы» (интервал + таймаут пробы StatusChecker) ─────────────

    def _build_statuses_tab(self):
        try:
            from ..services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL)
        except ImportError:
            from services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL)
        st = get_status_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.status_interval_spin = QSpinBox()
        self.status_interval_spin.setRange(5, 3600)
        self.status_interval_spin.setValue(st["interval_sec"])
        self._lbl_status_interval = QLabel(_t("settings.statuses.interval"))
        form.addRow(self._lbl_status_interval, self.status_interval_spin)

        self.probe_timeout_spin = QDoubleSpinBox()
        self.probe_timeout_spin.setRange(0.2, 60.0)
        self.probe_timeout_spin.setDecimals(1)
        self.probe_timeout_spin.setValue(st["probe_timeout_sec"])
        self._lbl_probe_timeout = QLabel(_t("settings.statuses.timeout"))
        form.addRow(self._lbl_probe_timeout, self.probe_timeout_spin)

        # v1.1.2 final (задача 2): потолок параллельных проб в раунде —
        # status_max_parallel (дефолт 16; диапазон = кламп get_status_settings).
        self.max_parallel_spin = QSpinBox()
        self.max_parallel_spin.setRange(1, _MPL)
        self.max_parallel_spin.setValue(st["max_parallel"])
        self._lbl_max_parallel = QLabel(_t("settings.statuses.max_parallel"))
        form.addRow(self._lbl_max_parallel, self.max_parallel_spin)

        self.tabs.addTab(tab, _t("settings.tab.statuses"))

    # ── Вкладка «Автосохранение» (ключи v0.9.7) ────────────────────────────────

    def _build_autosave_tab(self):
        try:
            from ..storage.autosave import get_autosave_settings
        except ImportError:
            from storage.autosave import get_autosave_settings
        as_cfg = get_autosave_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.autosave_enabled_chk = QCheckBox(_t("settings.autosave.enabled"))
        self.autosave_enabled_chk.setChecked(as_cfg["enabled"])
        form.addRow("", self.autosave_enabled_chk)

        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setRange(5, 86400)
        self.autosave_interval_spin.setValue(as_cfg["interval_sec"])
        self._lbl_autosave_interval = QLabel(_t("settings.autosave.interval"))
        form.addRow(self._lbl_autosave_interval, self.autosave_interval_spin)

        self.backup_count_spin = QSpinBox()
        self.backup_count_spin.setRange(1, 100)
        self.backup_count_spin.setValue(as_cfg["backup_count"])
        self._lbl_backup_count = QLabel(_t("settings.autosave.backups"))
        form.addRow(self._lbl_backup_count, self.backup_count_spin)

        self.tabs.addTab(tab, _t("settings.tab.autosave"))

    # ── Вкладка «Карта» (v1.1.1: опции карты — двойной клик узла, плашка связи) ─

    def _build_map_tab(self):
        ui_cfg = load_ui_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.1.1 (пункт 4): двойной клик по узлу — свойства (дефолт, поведение v1.1)
        # или сразу диалог входа SSH (_run_ssh_connect). Чекбокс «Подключиться по
        # SSH» в свойствах не ломается — новый режим лишь дублирует его быстрее.
        self.node_dblclick_combo = QComboBox()
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.properties"), "properties")
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.connect"), "connect")
        idx = next((i for i in range(self.node_dblclick_combo.count())
                    if self.node_dblclick_combo.itemData(i) == ui_cfg["node_double_click"]), 0)
        self.node_dblclick_combo.setCurrentIndex(idx)
        self._lbl_node_dblclick = QLabel(_t("settings.map.node_double_click"))
        form.addRow(self._lbl_node_dblclick, self.node_dblclick_combo)

        # v1.1.1 (пункт 6): тип связи на плашке («SSH · <метка>») — удобно для
        # экспорта PNG/PDF, где цвет менее заметен; по умолчанию выключено.
        self.show_conn_type_chk = QCheckBox(_t("settings.map.show_connection_type"))
        self.show_conn_type_chk.setChecked(ui_cfg["show_connection_type"])
        form.addRow("", self.show_conn_type_chk)

        self.tabs.addTab(tab, _t("settings.tab.map"))

    # ── Вкладка «Язык» (немедленное применение — до ОК) ────────────────────────

    def _build_language_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.language_combo = QComboBox()
        try:
            from i18n import get_available_languages, get_current_language
            for lg in get_available_languages():
                self.language_combo.addItem(lg["name"], lg["code"])
            cur = get_current_language()
        except Exception:  # noqa: BLE001 — без i18n вкладка не строится комбо
            cur = ""
        idx = next((i for i in range(self.language_combo.count())
                    if self.language_combo.itemData(i) == cur), 0)
        self.language_combo.setCurrentIndex(idx)
        # Немедленное применение — ПОСЛЕ установки начального индекса (иначе эхо
        # currentIndexChanged при конструировании переключило бы язык на свой же).
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._lbl_language = QLabel(_t("settings.language.label"))
        form.addRow(self._lbl_language, self.language_combo)
        self.tabs.addTab(tab, _t("settings.tab.language"))

    # ── Слоты ──────────────────────────────────────────────────────────────────

    def _on_language_changed(self, index: int):
        """Вкладка «Язык»: немедленное применение (set_language + retranslate UI)."""
        code = self.language_combo.itemData(index)
        if not code:
            return
        self.language_changed.emit(code)
        # Подписи самого диалога обновляем сразу (t() уже на новом языке).
        try:
            self.retranslate()
        except RuntimeError:
            pass  # Qt teardown

    def _on_accept(self):
        """ОК: сохранить собранные значения в config.json + signal applied."""
        try:
            from i18n import save_config
            if not save_config(self.collect()):
                QMessageBox.warning(
                    self, _t("msg.error_title"),
                    _t("msg.save_failed", error="~/.sshmap/config.json"))
                return  # не закрываем молча — пользователь видит ошибку
        except Exception:
            return
        self.applied.emit()
        self.accept()

    # ── Сбор значений (ключи config.json; language НЕ входит — он сразу) ───────

    def collect(self) -> dict:
        """Значения вкладок → ключи ~/.sshmap/config.json (все валидны по построению:
        комбо дают фиксированные id, спинбоксы — свой диапазон).

        v1.1.1: +7 ключей — шрифты UI/терминала (ui_font_family/ui_font_size/
        terminal_font), лимит терминалов (terminal_max_open), двойной клик узла
        (ui_node_double_click), кнопки сайдбара (ui_show_sidebar_buttons) и тип
        на плашке связи (ui_show_connection_type). ui_font_size = 0 — системный
        размер (валидатор load_ui_settings() читает диапазон 6..72, иначе дефолт).
        v1.1.2 final: +1 ключ — status_max_parallel (потолок параллельных проб;
        диапазон спинбокса = кламп валидатора get_status_settings()).
        """
        return {
            "external_terminal": self.ext_term_combo.currentData() or "auto",
            "terminal_palette": self.palette_combo.currentData() or "default",
            "terminal_font_size": int(self.font_size_spin.value()),
            "terminal_history_lines": int(self.history_spin.value()),
            "terminal_close_behavior": self.close_behavior_combo.currentData() or "close",
            "status_interval_sec": int(self.status_interval_spin.value()),
            "status_probe_timeout_sec": float(self.probe_timeout_spin.value()),
            # v1.1.2 final (задача 2): потолок параллельных проб в раунде
            "status_max_parallel": int(self.max_parallel_spin.value()),
            "autosave_enabled": bool(self.autosave_enabled_chk.isChecked()),
            "autosave_interval_sec": int(self.autosave_interval_spin.value()),
            "backup_count": int(self.backup_count_spin.value()),
            # v1.1.1: шрифты (UI + терминал) и лимит своих терминалов
            "ui_font_family": self.ui_font_family_edit.text().strip(),
            "ui_font_size": int(self.ui_font_size_spin.value()),
            "terminal_font": self.term_font_family_edit.text().strip(),
            "terminal_max_open": int(self.max_open_spin.value()),
            # v1.1.1: опции карты/сайдбара
            "ui_node_double_click": self.node_dblclick_combo.currentData() or "properties",
            "ui_show_sidebar_buttons": bool(self.sidebar_buttons_chk.isChecked()),
            "ui_show_connection_type": bool(self.show_conn_type_chk.isChecked()),
        }

    # ── i18n: retranslate собственных строк (смена языка в открытом диалоге) ───

    def retranslate(self):
        """Повторно применить перевод к строкам диалога (реестр — здесь)."""
        self.setWindowTitle(_t("settings.title"))
        self.tabs.setTabText(0, _t("settings.tab.general"))
        self.tabs.setTabText(1, _t("settings.tab.terminal"))
        self.tabs.setTabText(2, _t("settings.tab.statuses"))
        self.tabs.setTabText(3, _t("settings.tab.autosave"))
        self.tabs.setTabText(4, _t("settings.tab.map"))
        self.tabs.setTabText(5, _t("settings.tab.language"))

        self._lbl_ext_term.setText(_t("settings.general.external_terminal"))
        for i in range(self.ext_term_combo.count()):
            tid = self.ext_term_combo.itemData(i)
            if tid:
                self.ext_term_combo.setItemText(i, _t(f"ssh_ext.preset.{tid}"))

        # v1.1.1: шрифт UI + кнопки сайдбара (вкладка «Общие»)
        self._lbl_ui_font_family.setText(_t("settings.general.ui_font_family"))
        self._lbl_ui_font_size.setText(_t("settings.general.ui_font_size"))
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self.sidebar_buttons_chk.setText(_t("settings.general.sidebar_buttons"))

        self._lbl_palette.setText(_t("settings.terminal.palette"))
        for i in range(self.palette_combo.count()):
            pid = self.palette_combo.itemData(i)
            key = {
                "default": "settings.terminal.palette.default",
                "nord": "settings.terminal.palette.nord",
                "dracula": "settings.terminal.palette.dracula",
                "tokyo_night": "settings.terminal.palette.tokyo_night",
            }.get(pid)
            if key:
                self.palette_combo.setItemText(i, _t(key))
        self._lbl_term_font_family.setText(_t("settings.terminal.font_family"))
        self._lbl_font_size.setText(_t("settings.terminal.font_size"))
        self._lbl_max_open.setText(_t("settings.terminal.max_open"))
        self._lbl_history.setText(_t("settings.terminal.history_lines"))
        self._lbl_close_behavior.setText(_t("settings.terminal.close_behavior"))
        for i in range(self.close_behavior_combo.count()):
            cid = self.close_behavior_combo.itemData(i)
            key = {
                "close": "settings.terminal.close_behavior.close",
                "ask": "settings.terminal.close_behavior.ask",
            }.get(cid)
            if key:
                self.close_behavior_combo.setItemText(i, _t(key))

        self._lbl_status_interval.setText(_t("settings.statuses.interval"))
        self._lbl_probe_timeout.setText(_t("settings.statuses.timeout"))
        self._lbl_max_parallel.setText(_t("settings.statuses.max_parallel"))

        self.autosave_enabled_chk.setText(_t("settings.autosave.enabled"))
        self._lbl_autosave_interval.setText(_t("settings.autosave.interval"))
        self._lbl_backup_count.setText(_t("settings.autosave.backups"))

        # v1.1.1: опции карты (вкладка «Карта»)
        self._lbl_node_dblclick.setText(_t("settings.map.node_double_click"))
        for i in range(self.node_dblclick_combo.count()):
            cid = self.node_dblclick_combo.itemData(i)
            key = {
                "properties": "settings.map.node_double_click.properties",
                "connect": "settings.map.node_double_click.connect",
            }.get(cid)
            if key:
                self.node_dblclick_combo.setItemText(i, _t(key))
        self.show_conn_type_chk.setText(_t("settings.map.show_connection_type"))

        self._lbl_language.setText(_t("settings.language.label"))

        self.ok_btn.setText(_t("settings.ok"))
        self.cancel_btn.setText(_t("settings.cancel"))
