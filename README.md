# SSH Map (NodeVisualSSH) — v1.0

Десктопное приложение (Python + PySide6): интерактивная карта IT-инфраструктуры с прямым SSH-подключением к узлам.
Slogan: *"Draw your infrastructure. Organize it. Connect to it."*

Единый источник истины для версии — `version.py` (APP_VERSION);

---

## 1. Запуск и тесты

```bash
pip install PySide6 paramiko keyring pyte   # все зависимости из requirements.txt
python main.py                              # запуск GUI

# installable-идентичность (pyproject.toml) — установка как пакета:
pipx install .                            # или pip install . → команда sshmap (entry point main:main)

# Тесты без pytest: тематические файлы test_*.py + единый раннер.
# Тесты изолированы: пишут во временный HOME, UTF-8 stdout ставится сами —
# на cp1251-консолях и в CI дополнительное окружение не требуется:
python tests/run_all.py              # ВСЁ (38 файлов): таблица результатов + единый exit code (0 ⇔ всё зелёное)
python tests/run_all.py keyring      # фильтр по подстроке в имени файла
python tests/test_tags.py            # один файл (из корня проекта)
```

Карта сьюта — что какой `test_*.py` покрывает и откуда пришёл, конвенции: `tests/INDEX.md`.
Обвязка `tests/_common.py`: HOME-изоляция (песочница для `~/.sshmap/*`), offscreen,
faulthandler-таймаут 180 c; каждый файл завершается exit 0 = ALL PASS.

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
├── ssh_terminal.py          # SSHTerminalThread + SSHTerminalWindow (dirty-рендер без таймера — _on_output→update(); resize PTY: guard по сетке + дебаунс ~150 мс; кнопка «Закрыть терминал» убрана);
│                            #   connected_signal (после invoke_shell) + initial_command — первая команда Быстрого запуска в shell;
│                            #   load_terminal_settings() — ключи terminal_palette/terminal_font/terminal_font_size/terminal_history_lines из ~/.sshmap/config.json (дефолты = текущее поведение)
├── terminal_widget.py       # TerminalWidget — посячейный холст QWidget+QPainter: runs, кэш форматов, блок-курсор (+cursor.hidden), широкие глифы; полная клавиатура (F1–F12/PgUp/PgDn/Home/End/Delete, Ctrl+C/D/Z, bracketed paste, AltGr-guard) + выделение мышью (selection_cells, координаты (row,col)) и копирование; скроллбэк колесом/Ctrl+Shift+PgUp/PgDn (голые PgUp/PgDn — в shell) + QTimer мигания курсора
├── terminal_screen.py       # TerminalScreen: pyte.HistoryScreen(120x32)+ByteStream, feed под threading.Lock; PALETTES+resolve_color (TERMINAL.md §5.1), snapshot(); скроллбэк scroll_up/scroll_down/at_bottom (авто-возврат к live встроен в pyte); render() — deprecated
├── host_key_policy.py       # SshKnownHostsPolicy: ~/.sshmap/known_hosts; изменённый ключ → BadHostKeyException (MITM)
├── external_terminal.py     # системный терминал ОС; настройки ~/.sshmap_settings.json; пароль НЕ в argv
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
├── status_checker.py        # StatusChecker: QTimer разводит раунды, пробы в _ProbeThread; probe_ssh() → online/warn/offline
└── system_info_collector.py # SystemInfoCollector: автосбор ОС/CPU/RAM/диск Linux-сервера одной exec_command-сессией
version.py                   # единая точка версий: APP_VERSION="1.0", VERSION_FORMAT="0.9"
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
i18n/                        # t(key,**kwargs); en.json/ru.json/zh.json — 326 ключей, наборы идентичны; ru — дефолт
tests/                       # тематический сьют без pytest: 37 × test_*.py + _common.py (обвязка), run_all.py (единый раннер), check_i18n_keys.py; карта — tests/INDEX.md
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
`probe_ssh(host, port)`: TCP открыт + SSH-баннер → `online`; порт открыт без баннера → `warn`; иначе `offline`. Пробы только в `_ProbeThread` (не на GUI-потоке). `start_status_checks()` вызывается из main.py один раз после `show()`.

### Терминал
Сырые байты SSH → `TerminalScreen.feed()` (pyte.HistoryScreen, под lock) → посячейный холст `TerminalWidget` (QWidget+QPainter: runs, цветовой движок `resolve_color`, блок-курсор с миганием). Dirty-рендер без таймера: `_on_output` → `widget.update()` напрямую (queued signal уже в GUI-потоке). Resize PTY — только при реальной смене сетки + дебаунс ~150 мс перед `channel.resize_pty` (начальный `invoke_shell` 120×32, первый resizeEvent синхронизирует с окном). Скроллбэк — готовый `pyte.HistoryScreen`: колесо мыши и Ctrl+Shift+PageUp/PageDown, авто-возврат к live-строке при новом выводе; **голые PageUp/PageDown остаются форвардом в shell** (`\x1b[5~`/`\x1b[6~` — пейджинг less/man). Клавиатура — полная таблица: F1–F12, Home/End/Delete, стрелки, явные Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C при выделении копирует в буфер), bracketed paste Ctrl+V (единый блок), AltGr-guard (Ctrl+Alt не уходит как управляющие коды). Выделение мышью — координаты всегда `(row, col)` (`selection_cells()`), копирование мульти-строчного текста. Окно закрывается штатным крестиком (кнопка «Закрыть терминал» убрана). Известный хост пиннится в `~/.sshmap/known_hosts`. Настройки терминала: опциональные ключи `~/.sshmap/config.json` — `terminal_palette` (`default|nord|dracula|tokyo_night`, неизвестная → default), `terminal_font` (семейство, пусто → системный моноширинный), `terminal_font_size` (pt 6–72, иначе 10), `terminal_history_lines` (глубина скроллбэка HistoryScreen; дефолт 1000 — включён, явный 0 — отключён); применяются при создании окна (`load_terminal_settings()`).

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
- **Windows / keyring:** принимается только системный бэкенд Windows Credential Manager (`keyrings.win.*`, т.е. требуется pywin32 — раскомментируйте его в requirements.txt). Plaintext-файловые fallback-бэкенды (`keyrings.alt.file`) отвергаются: пароли не будут сохранены, а не уехают в открытый файл. На Linux/macOS отвергаются бэкенды `keyrings.alt.*`. Если безопасный бэкенд недоступен — приложение работает, но пароли не сохраняются между запусками.

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
ru (дефолт) / en / zh. Правило: новый ключ добавляется во все 3 файла сразу; проверка — `python tests/check_i18n_keys.py`. Модули с горячим путём (ssh_worker, ssh_terminal) используют кэшированный `get_translator()`.

---

## 7. Состояние и roadmap

**Реализовано полностью:**
- карта (узлы/Безье-связи 6 типов/заметки/группы)
- статусы online/warn/offline
- терминал на pyte
- внешний системный терминал
- undo/redo
- автосбор информации о Linux-сервере
- профили + keyring
- перевод приложения i18n ru/en/zh
- контекстные меню всех объектов
- fit/zoom/центрирование
- экспорт карты в PNG/JPEG/PDF и фоновое изображение с drag/resize
- горячие клавиши и палитра команд Ctrl+K
- дублирование узла Ctrl+D с копированием keyring-пароля под новым id
- мультивыделение (Ctrl+клик, рамка, групповой drag, соединить/удалить выделенные)
- теги/цветные метки серверов: цветная полоска на карточке
- фильтр по тегам в сайдбаре с затемнением несовпадающих узлов на карте, поиск по тегам
- экспорт карты в draw.io `.drawio` — узлы/связи/группы-контейнеры/стикеры/фон отдельным слоем; файл открывается в diagrams.net и VS Code-плагине 
- массовый импорт серверов из TXT
- контекстное меню дерева серверов сайдбара + «Показать на карте»
- автосохранение проекта (~/.sshmap/autosave/) + кольцевой буфер бэкапов при каждом save (~/.sshmap/backups/, откат через «Файл → Бэкапы…» / «Восстановить из автосохранения…») и предложение восстановления из автосохранения при открытии файла
- поиск по карте (Ctrl+F): строка поиска поверх canvas с подсветкой совпадений (alias/host/ip/comment), переход Enter/Shift+Enter с центрированием и рамкой-акцентом, затемнение несовпавших узлов (комбинируется с тег-фильтром по И)
- **Быстрый запуск**: per-server список ссылок/команд — подменю «Быстрый запуск» ПЕРВЫМ пунктом контекстного меню (ПКМ в списке серверов и на карте, выше «Подключиться по SSH»); URL открывается в браузере по умолчанию, команда отправляется первой командой в SSH-терминал сервера; настройка — кнопка «Быстрый запуск…» в свойствах сервера и «Настроить…» из подменю; хранится в JSON проекта (`quick_launch`), изменения через undo

**Известные ограничения:** undo не покрывает статусы узлов и геометрию фона; фоновое изображение хранится путём (при переносе проекта на другую машину файл нужно переносить вместе с картой); язык интерфейса выбирается через меню «Помощь → Язык» (с персистентностью в ~/.sshmap/config.json); в v1.1 планируется перенос переключателя в диалог настроек.

**Roadmap (по приоритету, детали — в ROADMAP.md):**
- **v1.1**: диалог настроек (шрифты UI и терминала, палитра/размер шрифта/глубина истории терминала, интервалы StatusChecker, автосохранение, язык интерфейса) + SFTP-вкладка в окне терминала (тот же transport, один worker с очередью, прогресс и отмена).
- **v1.2**: полировка карты (анимированный поток по связям, плавные перелёты камеры, центральная тема `ui/theme.py`) + опции терминала (табы сессий, выделение слова/строки).
- Бэклог (без версии): импорт из ~/.ssh/config, экспорт/импорт профилей, Prometheus-метрики, интеграции Docker/K8s·Proxmox·WoL·SNMP, мини-карта и другие «большого уровня».

---

## 8. Лицензия и безопасность

- MIT License
- Пароли никогда не покидают машину: keyring ОС (Windows Credential Manager / GNOME Keyring / macOS Keychain); в JSON проекта пароль не пишется никогда.
- known_hosts-пиннинг (`~/.sshmap/known_hosts`): смена ключа хоста → отказ подключения (защита от MITM). Первое подключение — TOFU: новый ключ принимается автоматически (отпечаток логируется).
- Внешний системный терминал: пароль вводится ssh-клиенту ОС интерактивно, никогда не передаётся в argv.
