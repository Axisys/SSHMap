# SSH Map (NodeVisualSSH) — v1.1.3

Десктопное приложение (Python + PySide6): интерактивная карта IT-инфраструктуры с прямым SSH-подключением к узлам.
Slogan: *"Draw your infrastructure. Organize it. Connect to it."*

Единый источник истины для версии — `version.py` (APP_VERSION); история выпущенных версий — CHANGELOG.md, планируемые функции — ROADMAP.md.

---

## 1. Запуск и тесты

```bash
pip install PySide6 paramiko keyring pyte   # все зависимости из requirements.txt
python main.py                              # запуск GUI

# installable-идентичность (pyproject.toml) — установка как пакета:
pipx install .                            # или pip install . → команда sshmap (entry point main:main)

# Тесты без pytest: тематические файлы test_*.py + единый параллельный раннер.
# Тесты изолированы: пишут во временный HOME, UTF-8 stdout ставится сами —
# на cp1251-консолях и в CI дополнительное окружение не требуется:
python tests/run_all.py              # ВСЁ (45 файлов): параллельно (4 воркера), таблица результатов + единый exit code (0 ⇔ всё зелёное)
python tests/run_all.py --workers 8  # число воркеров (1 = последовательно, как раньше)
python tests/run_all.py keyring      # фильтр по подстроке в имени файла
python tests/test_tags.py            # один файл (из корня проекта)
```

Карта сьюта — что какой `test_*.py` покрывает и откуда пришёл, конвенции: `tests/INDEX.md`.
Обвязка `tests/_common.py`: HOME-изоляция (песочница для `~/.sshmap/*`), offscreen,
faulthandler-таймаут 180 c; каждый файл завершается exit 0 = ALL PASS.
Пины релиза централизованы внизу `_common.py` (`EXPECTED_APP_VERSION`, `EXPECTED_I18N_KEYS`
+ общие проверки): при релизе правится одно место.

Требования: Python 3.10+, Windows/Linux/macOS. Логи: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler 5MB × 3).

---

## 2. Структура проекта

```
main.py                      # точка входа: setup_logging() → QApplication → MainWindow → start_status_checks()
pyproject.toml               # installable-идентичность (имя/версия/deps из version.py и requirements.txt, entry point sshmap = main:main) — сверка tests/test_pyproject.py
models/
├── server.py                # ServerData dataclass; server_data_from_dict/to_dict (password исключается);
│                            #   quick_launch — список пунктов Быстрого запуска + sanitize_quick_launch
└── profile.py               # Profile; CRUD; JSON ~/.sshmap_profiles.json (пароли в keyring, префикс "profile:{id}")
graphics/
├── map_scene.py             # MapScene: _nodes/_arrows/_notes/_groups; resync_group_members (геометрическое членство)
├── map_view.py              # MapView: зум 0.1–5.0, панорамирование, Shift+drag связи, ctx-меню,
│                            #   node_drag_committed, мультивыделение Ctrl+клик/рамкой + nodes_drag_committed
├── server_node.py           # ServerNode: карточка со статусом online/warn/offline (#22c55e/#facc15/#ef4444)
├── connection_arrow.py      # ConnectionArrow: кубическая Безье, 6 типов связей, hit-зона ~10px через contains()
├── sticky_note.py           # StickyNote: QGraphicsProxyWidget+QTextEdit, ручной drag/resize/edit
├── node_group.py            # NodeGroup: рамка кластера z=-5; членство = центр узла внутри верхней группы
└── background_image.py      # BackgroundImage: фон-изображение z=-10, drag/resize за угол
modules/
├── ssh_worker.py            # SSHWorker (одноразовый QThread); реестр get_active_worker/wait_for_worker
├── ssh_terminal.py          # SSHTerminalThread + SSHTerminalWindow (dirty-рендер без таймера — _on_output→update(); resize PTY: guard по сетке + дебаунс ~150 мс);
│                            #   connected_signal (после invoke_shell) + initial_command — первая команда Быстрого запуска в shell;
│                            #   load_terminal_settings() — ключи terminal_* из ~/.sshmap/config.json (дефолты = текущее поведение, см. §4 «Настройки»);
│                            #   v1.1.3: QTabWidget [Терминал | Файлы] — ленивый open_sftp() на том же transport + прогресс в статус-баре
├── sftp_worker.py           # SftpWorker (v1.1.3): один worker-поток с очередью задач list/upload/download поверх живого transport'а;
│                            #   отмена — флаг между операциями, корректный shutdown, реестр орфано-worker'ов
├── sftp_tab.py              # SftpTab (v1.1.3): вкладка «Файлы» — листинг текущего каталога + навигация «..», upload/download выбранных,
│                            #   кнопка «Отменить»; GUI не блокируется (все операции SFTP — в worker-потоке)
├── terminal_widget.py       # TerminalWidget — посячейный холст QWidget+QPainter: runs, кэш форматов, блок-курсор (+cursor.hidden), широкие глифы; полная клавиатура (F1–F12/PgUp/PgDn/Home/End/Delete, Ctrl+C/D/Z, bracketed paste, AltGr-guard) + выделение мышью (selection_cells, координаты (row,col)) и копирование; скроллбэк колесом/Ctrl+Shift+PgUp/PgDn (голые PgUp/PgDn — в shell) + QTimer мигания курсора
├── terminal_screen.py       # TerminalScreen: pyte.HistoryScreen(120x32)+ByteStream, feed под threading.Lock; PALETTES+resolve_color, snapshot(); скроллбэк scroll_up/scroll_down/at_bottom (авто-возврат к live встроен в pyte); render() — deprecated
├── window_geometry.py       # сохранение/восстановление размеров окон — saveGeometry()/saveState() → base64 → config.json (ui_window_geometry_main/terminal); никогда не бросает
├── host_key_policy.py       # SshKnownHostsPolicy: ~/.sshmap/known_hosts; изменённый ключ → BadHostKeyException (MITM)
├── external_terminal.py     # системный терминал ОС; настройки в ~/.sshmap/config.json (миграция из legacy ~/.sshmap_settings.json); пароль НЕ в argv
├── undo_commands.py         # 13 QUndoCommand: MoveNode(merge), MoveNodes(групповой drag),
│                            #   MoveGroup, ResizeGroup, EditGroupName, AddRemoveNode(+стрелки),
│                            #   AddRemoveNodeBatch(импорт TXT — один undo), AddRemoveConnection,
│                            #   ConnectSelected, AddRemoveNote, EditTextNote(дебаунс 600мс),
│                            #   EditConnection, EditNodeData
└── logger.py                # setup_logging()/get_logger(__name__)
storage/project.py           # save_project/load_project + serialize_scene()/write_project_json() — JSON версии (VERSION_FORMAT из version.py; + ключ "background")
storage/autosave.py          # автосохранение ~/.sshmap/autosave/<key>.json + кольцевой буфер бэкапов ~/.sshmap/backups/<key>_NNN.json (без Qt, атомарные записи)
storage/export_drawio.py     # экспорт карты в .drawio (mxGraph XML, ElementTree, без новых зависимостей)
services/
├── credential_manager.py    # keyring-абстракция (синглтон get_credential_manager()): только проверенный бэкенд (Windows — wincred, иначе — отказ от записи)
├── diagnostics.py           # PingThread + ReverseDnsThread — ping и обратный DNS вне GUI-потока (перенесено из ui/main_window.py)
├── host_importer.py         # массовый импорт серверов из TXT: parse_hosts_file, is_ip_address, resolve_host
├── status_checker.py        # StatusChecker: QTimer разводит раунды, пробы ПАРАЛЛЕЛЬНО в _ProbeThread (ThreadPoolExecutor); probe_ssh() → online/warn/offline
└── system_info_collector.py # SystemInfoCollector: автосбор ОС/CPU/RAM/диск Linux-сервера одной exec_command-сессией
version.py                   # единая точка версий: APP_VERSION="1.1.3", VERSION_FORMAT="0.9"
dialogs/                     # AddServerDialog (+кнопка «Быстрый запуск…»), SSHConnectDialog (+кнопка внешнего терминала),
                             #   ConnectionDialog/EditConnectionDialog, ProfileManagerDialog,
                             #   BackupsDialog (бэкапы + автосохранение, откат), QuickLaunchDialog (Быстрый запуск)
ui/main_window.py            # MainWindow: контроллер; undo_stack (QUndoStack), dirty по canUndo()+baseline;
                             #   дублирование узла Ctrl+D (keyring-пароль под новым id), групповые операции
                             #   экспорт карты в PNG/JPEG/PDF, экспорт в drawio, установка/удаление фона, «Собрать информацию»
                             #   поиск по карте Ctrl+F, _qaction_guard — guard на QActions с прикреплённым QMenu;
                             #   сайдбар-кластер вынесен в ui/sidebar.py (MainWindow — фасад)
ui/sidebar.py                # SidebarPanel(QWidget) — кнопки, заголовок, поиск, тег-фильтр, дерево с маркерами
                             #   статусов, контекстное меню строки; i18n через колбэк + retranslate
ui/map_search_bar.py         # MapSearchBar — плавающая строка поиска поверх canvas (Enter/Shift+Enter/Esc, счётчик k/N)
ui/command_palette.py        # CommandPalette: Ctrl+K, fuzzy-поиск по действиям меню и серверам
i18n/                        # t(key,**kwargs); en.json/ru.json/zh.json — 398 ключей, наборы идентичны; en — дефолт для новых пользователей
tests/                       # тематический сьют без pytest: 44 × test_*.py + _common.py (обвязка), run_all.py (параллельный раннер, 4 воркера), check_i18n_keys.py; карта — tests/INDEX.md
```

---

## 3. Формат проекта (JSON `.json` / `.sshmap`)

```json
{
  "version": "0.9",
  "servers":  [{"id": "710602ee", "alias": "...", "host": "...", "user": "...",
                "x": 0.0, "y": 0.0, "cpu": "", "ram": "", "disk": "", "ip": "",
                "comment": "", "ssh_port": 22, "key_path": "",
                "os_name": "", "cpu_model": "", "tags": ["prod", "dev"],
                "quick_launch": [{"type": "url", "name": "Webmin", "value": "http://host:10000/"},
                                 {"type": "command", "name": "K9S", "value": "k9s"}]}],
  "connections": [{"source_id": "...", "target_id": "...", "label": "", "type": "ssh"}],
  "notes":  [{"id": "...", "text": "", "x": 0.0, "y": 0.0, "width": 240.0, "height": 160.0}],
  "groups": [{"id": "...", "name": "", "x": 0.0, "y": 0.0, "width": 480.0, "height": 320.0}],
  "background": {"path": "/path/to/background.png", "x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0},
  "zoom": 1.0, "center_x": 0.0, "center_y": 0.0
}
```

Инварианты формата:
- `password` **никогда** не сериализуется — только keyring (`server_data_to_dict()` исключает).
- Типы связей: `ssh|vpn|http|database|nfs|kubernetes`; неизвестный/отсутствующий тип → `ssh`. Поле `version` при загрузке не валидируется (файлы 0.6+ читаются).
- Членство в группах **не хранится** — вычисляется из геометрии (центр карточки внутри верхней группы, эксклюзивно).
- `tags` — массив строк у записи сервера; отсутствует или не массив в старых JSON → пустой список (`server_data_from_dict` нормализует).
- `quick_launch` — массив пунктов Быстрого запуска `{"type": "url"|"command", "name", "value"}`; отсутствует в старых JSON → пустой список, битые записи отбрасываются (`sanitize_quick_launch`). URL открывается в браузере по умолчанию, команда — первая команда в SSH-терминале.
- `background` хранит **путь** к изображению (файл НЕ встраивается в JSON); отсутствующий файл при загрузке игнорируется с warning. Геометрия фона в undo не входит.

---

## 4. Ключевые поведения (важно для модификации кода)

### Статусы
`probe_ssh(host, port)`: TCP открыт + SSH-баннер → `online`; порт открыт без баннера → `warn`; иначе `offline`. Пробы только в `_ProbeThread` (не на GUI-потоке); внутри раунда — **параллельно** (`ThreadPoolExecutor`, потолок `status_max_parallel`, дефолт 16): худший случай раунда `ceil(N/max_parallel) × timeout` вместо `N × timeout`; результаты прилетают по мере готовности, отмена (stop/shutdown) не даёт результатов пробам, ещё не начавшимся. Мягкий авто-интервал: N > 50 узлов → интервал раундов удваивается (`effective_interval_ms()`) + одноразовая подсказка в статус-баре; жёсткого лимита числа серверов нет. `start_status_checks()` вызывается из main.py один раз после `show()`.

### Терминал
- Конвейер: сырые байты SSH → `TerminalScreen.feed()` (pyte.HistoryScreen, под lock) → посячейный холст `TerminalWidget` (QWidget+QPainter: runs, цветовой движок `resolve_color`, блок-курсор с миганием).
- Dirty-рендер без таймера: `_on_output` → `widget.update()` напрямую (queued signal уже в GUI-потоке).
- Resize PTY — только при реальной смене сетки + дебаунс ~150 мс перед `channel.resize_pty` (начальный `invoke_shell` 120×32, первый resizeEvent синхронизирует с окном).
- Скроллбэк — готовый `pyte.HistoryScreen`: колесо мыши и Ctrl+Shift+PageUp/PageDown, авто-возврат к live-строке при новом выводе; **голые PageUp/PageDown остаются форвардом в shell** (`\x1b[5~`/`\x1b[6~` — пейджинг less/man).
- Клавиатура — полная таблица: F1–F12, Delete/PageUp/PageDown (всегда CSI ~), стрелки и Home/End — по состоянию DECCKM: TUI шлют smkx `\x1b[?1h` и ждут SS3 — `_cursor_key_seq()` шлёт `\x1bOA/B/C/D`, `\x1bOH/\x1bOF`; обычный режим — CSI; состояние — `tscreen.application_cursor_keys()`, в pyte 0.8.2 DECCKM = 32 в `screen.mode`. Явные Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C при выделении копирует в буфер), bracketed paste Ctrl+V (единый блок), AltGr-guard (Ctrl+Alt не уходит как управляющие коды).
- Выделение мышью — координаты всегда `(row, col)` (`selection_cells()`), копирование мульти-строчного текста.
- Окно закрывается штатным крестиком (отдельной кнопки «Закрыть терминал» нет); известный хост пиннится в `~/.sshmap/known_hosts`.
- Настройки — опциональные ключи `terminal_*` в `~/.sshmap/config.json`; полный список и дефолты — ниже, «Настройки».

### Настройки
- Диалог (хаб, `ui/settings_dialog.py`) — QTabWidget «Общие / Терминал / Статусы / Автосохранение / Карта / Язык»; точки входа: меню «Настройки» между «Вид» и «Помощь» + кнопка ⚙ внизу сайдбара (векторная шестерёнка `ui/icons.py`); палитра команд Ctrl+K подхватывает пункт автоматически.
- Хранение — **единый** `~/.sshmap/config.json` (`i18n.save_config`, атомарная merge-запись): все ключи опциональны, дефолты = поведение v1.0. Статусы и автосохранение применяются на лету; терминал и внешний терминал читают конфиг при следующем создании окна/запуске.
- Ключи:
  - `external_terminal` (перенесён из отдельного `~/.sshmap_settings.json` с миграцией при чтении — старый файл удаляется);
  - `terminal_palette` (`default|nord|dracula|tokyo_night`, неизвестная → default), `terminal_font` (семейство, пусто → системный моноширинный; на лету в открытые окна), `terminal_font_size` (pt 6–72, иначе 10), `terminal_history_lines` (глубина скроллбэка HistoryScreen; дефолт 1000 — включён, явный 0 — отключён), `terminal_close_behavior` (`"close"` по умолчанию | `"ask"` — подтверждение закрытия активной сессии в closeEvent; уже завершённая закрывается без диалога), `terminal_max_open` (лимит своих терминалов, дефолт 4 — при достижении не отказ, а предложение закрыть старейшую сессию / отмена);
  - `status_interval_sec`/`status_probe_timeout_sec`/`status_max_parallel` (дефолты 30 c / 3.0 c / 16 параллельных проб; на лету через `StatusChecker.set_interval/set_probe_timeout/set_max_parallel`);
  - `autosave_enabled/autosave_interval_sec/backup_count` (на лету — QTimer автосохранения);
  - `language` (немедленное применение, до ОК);
  - `ui_font_family/ui_font_size` (шрифт UI, на лету через `QApplication.setFont`, 0 = системный), `ui_node_double_click` (`"properties"` дефолт | `"connect"` — двойной клик по узлу сразу открывает SSHConnectDialog), `ui_show_sidebar_buttons` (блок кнопок сайдбара; весь сайдбар прячется пунктом меню «Вид → Сайдбар»), `ui_show_connection_type` (тип на плашке связи: «SSH · <метка>», удобно для экспорта PNG/PDF) + лимит 20 символов метки связи (только на ввод — старые проекты с длинными метками читаются без изменений).

### Undo/Redo
- Любое изменение сцены делается через `MainWindow._push_command(cmd)`; сцена меняется **только** внутри `redo()/undo()` команды — `QUndoStack.push()` сам вызывает redo.
- Dirty-маркер: `self._dirty = undo_stack.canUndo() or self._undo_baseline_dirty`; `_do_save()` вызывает `_reset_undo_stack()` (новая baseline). `_undo_baseline_dirty` покрывает dirty-причины вне undo (статусы, фон).
- В undo НЕ входят: статусы узлов, координаты при загрузке, геометрия фона. Группы (move/resize/переименование) — входят (CmdMoveGroup/CmdResizeGroup/CmdEditGroupName).
- Перетаскивание узла: MapView ловит release, эмитит `node_drag_committed(node, old, new)` → CmdMoveNode.
- Групповой drag: если тянется уже выделенный узел и выделено >1 — двигаются ВСЕ выделенные; одна команда CmdMoveNodes на жест.

### Горячие клавиши + палитра команд
- Хоткеи: Ctrl+N/O/S — проект; Ctrl+Z/Y(+Shift) — undo/redo; Ctrl+Shift+A/G/C — сервер/группа/связь; Ctrl+I — свойства; **Ctrl+Enter** — SSH к выделенному узлу; **Ctrl+E** — редактировать узел; **Ctrl+D** — дублировать узел; **Ctrl+Shift+N** — заметка в центре видимой области; Delete — удалить выделенное; Ctrl+Shift+F — вписать карту; **Ctrl+F** — поиск по карте (строка поиска поверх canvas, Enter/Shift+Enter — переход между совпадениями с центрированием и рамкой-акцентом, Esc — закрыть).
- Мультивыделение: Ctrl+клик по узлу добавляет к выделению (нативный Qt), **Ctrl+drag по пустому месту** — рамка выделения (Shift+Ctrl добавляет к текущему); групповой drag двигает все выделенные; ПКМ при мультивыделении → «Соединить выделенные» / «Удалить выделенные» (одно подтверждение, guarded для каждого).
- **Ctrl+K** — палитра команд (`ui/command_palette.py`): fuzzy-поиск (subsequence-скоринг, без зависимостей) по всем QAction меню + по серверам проекта; выбор сервера → выделение узла + centerOn. Enter/Up/Down/Esc.

### Безопасность
Пароли: только keyring (профили `"profile:{id}"`, серверы по server_id). При недоступном keyring приложение работает, но пароли не переживают перезапуск. Внешний терминал: пароль вводит ssh-клиент ОС, никогда не argv.

**Ограничения:**
- **TOFU при первом подключении:** ключ хоста, которого нет в `~/.sshmap/known_hosts`, принимается автоматически (отпечаток показывается в логе). Это стандартное поведение paramiko-клиентов, но это **не** полная защита от MITM на самом первом подключении: защита срабатывает на *смене* уже зафиксированного ключа. Для критичных хостов сверяйте отпечаток первого подключения по доверенному каналу.
- **Windows / keyring:** принимается только системный бэкенд Windows Credential Manager (`keyrings.win.*`, т.е. требуется pywin32 — раскомментируйте его в requirements.txt). Plaintext-файловые fallback-бэкенды (`keyrings.alt.file`) отвергаются: пароли не будут сохранены, а не уехут в открытый файл. На Linux/macOS отвергаются бэкенды `keyrings.alt.*`. Если безопасный бэкенд недоступен — приложение работает, но пароли не сохраняются между запусками.

---

## 5. Нюансы PySide6 / Qt 6.11 (обязательные знания)

| Проблема | Решение |
|---|---|
| Мышиный ввод в тестах QGraphicsView | Только `PySide6.QtTest.QTest.mousePress/Move/Release/DClick` — самодельные QMouseEvent ядро игнорирует |
| Monkey-patch C++-слотов с возвращаемым значением (`itemChange`, `eventFilter`) | ЗАПРЕЩЕНО: бесконечная рекурсия или Access Violation 0xC0000005. Только override в подклассе |
| `QPropertyAnimation(target=QGraphicsItem)` | Не работает («non-existing property opacity») → использовать QVariantAnimation |
| `QGraphicsItemGroup.boundingRect()` | Не пересчитывается из детей (нулевой rect) → явный override (см. ServerNode) |
| `itemChange(ItemPositionChange)` | Вызывается ДО применения позиции → целевые rect передавать явно (паттерн resync_group_members) |
| QGraphicsProxyWidget «съедает» мышь | Drag StickyNote/NodeGroup обрабатывается вручную; MapView временно переключает dragMode в NoDrag |
| strokeToFill/strokedPath QPainterPath | Не пробиндованы в PySide6 → hit-зона стрелки через свой contains() с сэмплированием кривой |
| focusIn/focusOut сигналы QWidget | В Qt6 их нет → eventFilter |
| Смерть Python-обёртки QAction с прикреплённым QMenu | PySide6 6.11 уничтожает за ней C++-QMenu (проверено offscreen И native): временные обёртки из `menubar.actions()`/`act.menu()` убивали ВСЕ меню, кроме последнего — при открытии палитры Ctrl+K и смене языка. Лечение: постоянное хранение таких QAction (`MainWindow._qaction_guard`) + не ходить через `action.menu()` там, где есть прямой путь (реестр `_menu_i18n`) |

---

## 6. i18n

```python
from i18n import t, set_language, get_available_languages
t("btn.add_server", alias="web-1")   # форматирование {alias}
```
en (дефолт) / ru / zh. Правило: новый ключ добавляется во все 3 файла сразу; проверка — `python tests/check_i18n_keys.py`. Модули с горячим путём (ssh_worker, ssh_terminal) используют кэшированный `get_translator()`.

---

## 7. Состояние и roadmap

**Реализованные функции приложения** (детали — в разделах 3–4):
- интерактивная карта: узлы, Безье-связи 6 типов, заметки, группы, фоновое изображение с drag/resize
- статусы узлов online/warn/offline: параллельные пробы, авто-интервал для больших карт
- встроенный SSH-терминал на pyte (скроллбэк, выделение мышью, полная клавиатура) + внешний системный терминал
- SFTP-вкладка в окне терминала (v1.1.3): файлы по тому же SSH-соединению — листинг/навигация «..», upload/download с прогрессом в статус-баре и отменой
- undo/redo сценарных операций
- автосбор информации о Linux-сервере (ОС/CPU/RAM/диск)
- профили и пароли в keyring ОС — пароль никогда не пишется в JSON
- i18n: en (дефолт) / ru / zh
- контекстные меню всех объектов, fit/zoom/центрирование
- мультивыделение: Ctrl+клик, рамка, групповой drag, «соединить/удалить выделенные»
- теги: цветная полоска на карточке + фильтр по тегам в сайдбаре с затемнением несовпадающих узлов
- поиск по карте (Ctrl+F): подсветка совпадений, переход Enter/Shift+Enter, затемнение несовпавших
- быстрый запуск на сервер: список URL/команд (URL — браузер, команда — первая команда терминала)
- диалог настроек (хаб): единый `~/.sshmap/config.json`, применение на лету без перезапуска
- автосохранение + кольцевой буфер бэкапов с откатом («Файл → Бэкапы…»)
- экспорт в PNG/JPEG/PDF и draw.io `.drawio`; массовый импорт серверов из TXT
- горячие клавиши и палитра команд (Ctrl+K)

**Известные ограничения:**
- undo не покрывает статусы узлов и геометрию фона — детали в «Undo/Redo»;
- фоновое изображение хранится путём в JSON: при переносе проекта на другую машину файл нужно переносить вместе с картой;
- TOFU при первом подключении (новый ключ хоста принимается автоматически) и ограничения keyring — детали в «Безопасность».

**Roadmap** (задачи, порядок и acceptance — в ROADMAP.md):
- **v1.1.4**: гигиена main_window.py — разрез на миксины, публичный API без изменений.
- **Серия v1.2.x**: рефактор терминала «окно → страница»; сессии табами в окне и доком окна карты; мультинабор; крепление заметок к серверам; центральная тема `ui/theme.py` + анимации карты; выделение и контекстное меню терминала; D&D в SFTP-вкладку; удаление мёртвого кода + полный wcwidth CJK; подсветка логов (opt-in).
- **Серия v1.3.x**: панель файлов внизу окна карты + просмотрщик текста; настройка горячих клавиш; языки без написания кода; лёгкие плагины.

---

## 8. Лицензия и безопасность

- MIT License (LICENSE).
- Модель безопасности: пароли только в keyring ОС (никогда не в JSON проекта), known_hosts-пиннинг с TOFU при первом подключении, внешний терминал без пароля в argv — детали и ограничения: раздел 4 «Безопасность».
