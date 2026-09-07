# -*- coding: utf-8 -*-
"""v1.2.3 (ROADMAP v1.2.3): Мультинабор — broadcast ввода активной сессии во все остальные открытые сессии.

Единственная точка ввода (архитектура без переделки): **весь** пользовательский ввод
проходит через `TerminalWidget.keyPressEvent()` → `_send(bytes)` →
`terminal_thread.send_data()`. Хаб вешается ровно на эту точку: при включённом режиме
`_send` слает те же байты в `send_data()` всех остальных живых сессий реестра
(v1.2 — `MainWindow._terminal_windows` хранит TerminalSessionPage). Ctrl+V (bracketed
paste) проходит через тот же `_send` — дублируется тоже (иначе «набралось» не везде).

Источник — только окно/вкладка с фокусом: байты идут от клавиатуры фокусированного
виджета, а не из вывода — эха по определению нет (broadcast не ре-транслирует чужой
вывод и не шлёт в источник повторно). Сессия, умершая во время набора (error → close),
убирается из реестра штатным путём (`_forget_terminal_window` по `destroyed`), а
broadcast дополнительно фильтрует потоки по живости — мёртвый канал байты не получит.

UI (MainWindow/SshMixin): checkable QAction в меню «Вид» + F12 — ВЫХОД из режима
(не Esc: Esc уходит в shell как \\x1b!) — при включённом режиме RC2-маппинг
F12→\\x1b[24~ приостанавливается (клавиша не доходит до shell), при выключенном F12
работает как раньше; плашка «МУЛЬТИ: N сессий» в статус-баре со кнопкой выхода;
подсветка — бейджи вкладок «MULTI · <alias>» + рамка контейнера
(apply_container_highlight, окна и док).

Тестовые швы: явный `multi_hub` в конструкторе TerminalWidget (изоляция от
модульного хабa); `hub.reset()` — сброс состояния между секциями тестового файла.

Диагностика (v1.2.4-fix, инцидент «ручной тест не подтвердил broadcast»):
смена состояния режима → INFO в лог приложения; каждый broadcast → DEBUG-строка
(в TerminalWidget._send); режим включён, но байты никуда не ушли (реестр пуст /
все потоки мёртвы) → rate-limited WARNING с деталями — виден и в консоли.
"""

import time

_t_cache = None


def get_translator():
    """Safe i18n helper — returns cached translator or fallback (как в ssh_terminal)."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache


# ── Подсветка: цвет рамки/бейджа «MULTI» + objectName рамки (QSS-селектор) ─────
MULTI_ACCENT = "#f59e0b"                          # amber — рамка/бейдж режима
MULTI_FRAME_OBJECT_NAME = "sshmap_multi_frame"    # селектор QSS только для контейнера


def _thread_alive(thread) -> bool:
    """Жив ли терминальный поток для broadcast'а (ROADMAP v1.2.3, задача 4).

    Живой — канал открыт (реальный SSHTerminalThread во время сессии) ИЛИ поток ещё
    работает (QThread.isRunning()). Мёртвый: закрытый канал (error → close, stop()) —
    в него байты не шлются. Тест-дубль без channel/isRunning считается живым (его
    send_data() безопасен). Никогда не бросает."""
    try:
        ch = getattr(thread, "channel", None)
        if ch is not None and not bool(getattr(ch, "closed", False)):
            return True
        is_running = getattr(thread, "isRunning", None)
        if callable(is_running):
            return bool(is_running())
        return True
    except Exception:
        return False


class MultiInputHub:
    """Состояние режима мультинабора + broadcast ввода во все открытые сессии.

    `provider` — callable() → список открытых сессий (реестр v1.2: объекты
    TerminalSessionPage с `.terminal_thread` и `.widget`); None — broadcast выключен.
    `listeners` — колбэки UI (active: bool) на смену состояния (MainWindow: QAction,
    плашка статус-бара, подсветка контейнеров, статус-сообщение). Один процесс — один
    хаб (get_hub()); TerminalWidget берёт его по умолчанию.
    """

    def __init__(self):
        self._active = False
        self._provider = None
        self._listeners = []
        # v1.2.4-fix: rate-limit WARNING «0 получателей» (не спамить на каждую клавишу)
        self._last_zero_warn = 0.0

    # ── состояние режима ────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self._active

    @property
    def session_provider(self):
        return self._provider

    def set_session_provider(self, provider):
        """Реестр открытых сессий (callable() → list[page]); None — broadcast выключен."""
        self._provider = provider

    def add_listener(self, callback):
        """UI-колбэк (active: bool) на смену состояния; идемпотентно."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass  # не был подключён — делать нечего

    def set_active(self, on: bool):
        """Вкл/выкл режима; слушатели уведомляются ТОЛЬКО при реальной смене.

        Диагностика (v1.2.4-fix): смена состояния логируется INFO — в файле лога
        (~/.sshmap/logs/sshmap.log) видно, ВКЛЮЧАЛСЯ ли режим и когда выключился
        (F12 / меню / кнопка ✕ плашки). Никогда не бросает."""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        try:
            from modules.logger import get_logger as _get_log
            _get_log("modules.multi_input").info(
                f"Multi-input mode {'enabled' if on else 'disabled'}")
        except Exception:
            pass  # логгер недоступен — смена состояния важнее записи о ней
        for cb in list(self._listeners):
            try:
                cb(on)
            except Exception:
                pass  # UI-колбэк под teardown не должен ломать смену состояния

    def toggle(self) -> bool:
        """Переключить режим; возвращает новое состояние."""
        self.set_active(not self._active)
        return self._active

    # ── broadcast (единственная точка ввода) ────────────────────────────────
    def broadcast(self, data: bytes, source_widget=None) -> int:
        """Те же байты — в send_data() всех остальных живых сессий реестра.

        source_widget — TerminalWidget, от которого пришли байты (окно/вкладка с
        фокусом): её сессия пропускается (уже получила их через _send). Возвращает
        число получателей. Никогда не бросает: мёртвый C++-объект/поток в реестре
        молча пропускается (сам реестр обновляет штатный teardown — destroyed →
        _forget_terminal_window), остальные сессии продолжают получать ввод."""
        if not data or self._provider is None:
            return 0
        try:
            pages = list(self._provider())
        except Exception:
            return 0
        sent = 0
        others = 0   # сессий, кроме источника (для диагностики «0 получателей»)
        dead = 0     # из них — мёртвые потоки/каналы
        for page in pages:
            try:
                widget = getattr(page, "widget", None)
                if widget is not None and widget is source_widget:
                    continue  # источник — окно/вкладка с фокусом (уже получила)
                others += 1
                thread = getattr(page, "terminal_thread", None)
                if thread is None or not _thread_alive(thread):
                    dead += 1
                    continue  # мёртвая сессия (error → close) — в мёртвый канал не шлём
                thread.send_data(data)
                sent += 1
            except Exception:
                continue  # C++-объект под teardown — пропускаем, остальные получают
        if sent == 0 and others > 0:
            self._warn_zero_receivers(others, dead)
        return sent

    def _warn_zero_receivers(self, others: int, dead: int):
        """v1.2.4-fix (диагностика): режим включён, но байты никуда не ушли.

        Это тихий сбой-сценарий ручного теста «набираю — во втором терминале
        ничего»: WARNING (виден и в консоли) с деталями — сколько сессий в
        реестре кроме источника и сколько из них мёртвых. Rate-limit 5 c, чтобы
        быстрый набор не заспамил лог; никогда не бросает."""
        now = time.monotonic()
        if now - self._last_zero_warn < 5.0:
            return
        self._last_zero_warn = now
        try:
            from modules.logger import get_logger as _get_log
            _get_log("modules.multi_input").warning(
                f"multi-input: active but 0 receivers "
                f"(other sessions={others}, dead threads={dead}) — "
                f"input is NOT being duplicated")
        except Exception:
            pass  # логгер недоступен — broadcast важнее записи о нём

    def reset(self):
        """Тестовый шов: полный сброс состояния (режим выключен, реестра нет)."""
        self._active = False
        self._provider = None
        self._listeners = []
        self._last_zero_warn = 0.0


# ── Singleton приложения ───────────────────────────────────────────────────────
# MainWindow и TerminalWidget используют ОДИН хаб: виджет берёт его по умолчанию,
# когда в конструкторе не передан явный multi_hub. Один процесс — один хаб.
_default_hub = MultiInputHub()


def get_hub() -> MultiInputHub:
    """Хаб мультинабора по умолчанию (singleton процесса)."""
    return _default_hub


# ── Подсветка контейнеров сессий (рамка + бейджи вкладок «MULTI») ─────────────

def apply_container_highlight(host, on: bool) -> bool:
    """Подсветить/сбросить контейнер сессий (SSHTerminalWindow / TerminalDockContent).

    Оба контейнера имеют `session_tabs` (QTabWidget из страниц с `.server_data.alias`)
    — duck-typing без импорта ssh_terminal/terminal_dock (нет цикла). При входе:
    бейджи вкладок «MULTI · <alias>» + рамка QTabWidget (objectName-селектор, чтобы
    не затронуть Внутренние табы страницы [Терминал|Файлы]); у окна — префикс
    заголовка `terminal.multi_title_prefix` (база хранится в `_multi_base_title`).
    При выходе — всё сбрасывается. Идемпотентно; RuntimeError мёртвого C++-объекта
    не распространяется (teardown-устойчивость). True — применено."""
    try:
        tabs = getattr(host, "session_tabs", None)
        if tabs is None:
            return False
        t = get_translator()
        for i in range(tabs.count()):
            try:
                page = tabs.widget(i)
                alias = getattr(getattr(page, "server_data", None), "alias", "?")
            except RuntimeError:
                continue  # C++-объект уже удалён (гонка закрытия) — таб пропускаем
            try:
                text = t("terminal.multi_tab_badge", alias=alias) if on else str(alias)
                tabs.setTabText(i, text)
            except RuntimeError:
                pass  # C++-объект уже удалён (гонка закрытия) — бейдж не критичен
        try:
            if on:
                tabs.setObjectName(MULTI_FRAME_OBJECT_NAME)
                tabs.setStyleSheet(
                    f"QTabWidget#{MULTI_FRAME_OBJECT_NAME} "
                    f"{{ border: 2px solid {MULTI_ACCENT}; }}")
            else:
                tabs.setObjectName("")   # симметричный сброс: селектор рамки уходит полностью
                tabs.setStyleSheet("")
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия) — рамка не критична
        base_title = getattr(host, "_multi_base_title", None)
        if base_title is not None:
            try:
                title = (t("terminal.multi_title_prefix") + base_title) if on else base_title
                host.setWindowTitle(title)
            except RuntimeError:
                pass  # C++-объект уже удалён (гонка закрытия) — заголовок не критичен
        return True
    except Exception:
        return False
