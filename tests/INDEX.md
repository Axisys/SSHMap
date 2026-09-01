# tests/ — карта тестового сьюта SSHMap

Сьют — plain-python скрипты **без pytest**: каждый файл сам по себе запускается,
печатает `ok`/`FAIL` по каждой проверке и завершается exit 0 (всё зелёное) или 1.
Общая обвязка — `_common.py`; единый запуск всех файлов — `run_all.py`.

## Запуск

```
python tests/run_all.py              # все файлы test_*.py + check_i18n_keys.py, таблица результатов
python tests/run_all.py keyring      # только файлы, чьё имя содержит подстроку
python tests/test_tags.py            # один файл (из корня проекта)
```

Каждый файл — отдельный процесс: `bootstrap()` внутри делает изоляцию HOME
(тесты пишут `~/.sshmap/*` в песочницу), offscreen-платформу Qt, UTF-8 stdout
и faulthandler-таймаут 180 c. Отключить изоляцию HOME:
`SSHMAP_TEST_NO_HOME_ISOLATION=1`.

## Обвязка (_common.py)

Паттерн файла (bootstrap — ПЕРВЫМ делом, до импортов модулей приложения):

```python
from _common import bootstrap, check, finish
ROOT, WORK = bootstrap()          # HOME-изоляция, offscreen, sys.path, faulthandler
...тело теста: check("имя", условие, detail)...
finish()                          # сводка + exit code
```

Вспомогательные утилиты: `wait_until(cond)` — настоящий Qt event loop до условия;
`viewport_point(view, scene_pos)` — сцена → координаты viewport;
`snapshot_i18n_config()` / `restore_i18n_config()` — снимок конфига i18n
(нужен только при SSHMAP_TEST_NO_HOME_ISOLATION=1).

## Файлы сьюта (test_*.py)

### Разбито из smoke_test.py (v0.6–v0.9.2, удалён в v0.9.9.x)

| файл | покрывает |
|---|---|
| `test_core.py` | compile всех модулей; i18n-паритет en/ru/zh + fallback; models.server (from_dict robustness, to_dict без пароля); ANSI-очистка; профили без паролей в JSON + keyring update(None) |
| `test_save_load.py` | headless save/load round-trip: dirty [*]-маркер, пароль → keyring, key_path в JSON, защита от дублирующихся связей A→B |
| `test_ssh_dialogs.py` | SSHConnectDialog (accept без success-окна v0.9.5.6, keyring-save), AddServerDialog («Подключиться по SSH» + флаг _connect_after_accept) |
| `test_connections.py` | Безье-стрелки: геометрия cubic Bezier, edge-to-edge, A→B/B→A на противоположные стороны, 6 типов + prefill диалога, drag-режим Shift+ЛКМ (полный путь QTest-вводом), backward-compat v0.6 без поля type |
| `test_worker_guard.py` | реестр SSHWorker: видимость после construction, исчезновение по finished; wait_for_worker; _ensure_worker_done; closeEvent диалога |
| `test_status_checker.py` | probe_ssh на локальных сокетах (online/warn/offline); цвет рамки узла + tooltip + пульс-оверлей; полный раунд StatusChecker; интеграция с MainWindow |
| `test_notes.py` | sticky notes: сериализация, clamp MIN/MAX, drag/resize через полный pipeline view→scene→item (QTest), edit по двойному клику, Delete-клавиша, JSON round-trip + backward-compat |
| `test_context_menus.py` | v0.7.3 контекстные меню узла и стрелки: remove_connection, EditConnectionDialog prefill, _copy_node_info в буфер, _ping_node (headless-герметичность), _classify_at (геометрия кривой) |
| `test_groups.py` | v0.8.1 группы: id/сериализация, геометрическое членство (верхняя группа), drag группы QTest'ом, resize с клампом, вход/выход узла из рамки, JSON round-trip + backward-compat |
| `test_ui_polish.py` | boundingRect с тенью, точка статуса + затемнение offline, адаптивная сетка, fit_to_content, set_zoom_and_center, статус-бар (zoom %, счётчики), векторные иконки, hit-зона стрелок |
| `test_node_labels.py` | v0.8.0: elide/макс. ширина узлов (шрифто-независимый инвариант), MIN-размер, идемпотентность update_appearance; маркеры статусов в сайдбаре (live-обновление без пересбора) |
| `test_external_terminal.py` | v0.8.2 modules/external_terminal.py: build_ssh_args/build_command для всех терминалов, detect_terminal, настройки ~/.sshmap_settings.json (round-trip/merge/invalid→auto), launch() с моком Popen, error paths, UI-интеграция |
| `test_system_info.py` | v0.9 services/system_info_collector.py: парсеры INFO_BATCH, bytes_to_gb, модель + backward-compat, версия формата JSON 0.9, сигналы, точки входа MainWindow |
| `test_hotkeys_palette.py` | v0.9.2: хоткеи Ctrl+Return/Ctrl+E/Ctrl+Shift+N/Ctrl+K как QShortcut; CommandPalette fuzzy_score, сбор команд, reveal (выделение + centerOn) |

### Переименованы из regression_v*.py (содержимое то же, обвязка — _common.py)

| файл | бывший | покрывает |
|---|---|---|
| `test_ssh_terminal.py` | regression_v081 | терминал печатает bytes (Signal(bytes), pyte E2E); _add_server bool-guard; ПКМ→SSH без bool.setSelected; fingerprint SHA256 (paramiko>=5 asbytes) |
| `test_undo_redo.py` | regression_v083 | undo/redo round-trip всех операций, merge перемещений одним жестом, dirty-маркер = индекс стека |
| `test_export_background.py` | regression_v091 | экспорт карты в PNG/JPG + фон-изображение (JSON round-trip, legacy без ключа) |
| `test_duplicate_multiselect.py` | regression_v093 | дублирование узла + мультивыделение + групповой drag (undo-команда) |
| `test_tags.py` | regression_v094 | теги/цветные метки серверов: модель, JSON, UI сайдбара (тег-фильтр), backward-compat |
| `test_keyring_fail_backend.py` | regression_v094b | CredentialManager на fail-бэкенде (NoKeyringError 25.x), атомарная запись профилей, notes() итератор |
| `test_keyring_validation.py` | regression_v0955_keyring | безопасность: plaintext/fail-бэкенды отклоняются; гард save/load/delete; round-trip на реальном бэкенде (15–18 проверок, зависит от машины) |
| `test_sidebar_context_menu.py` | regression_v096_sidebar_ctx | контекстное меню дерева сайдбара: состав/порядок пунктов, reveal-акцент, guarded-удаление, i18n ctx.reveal_on_map |
| `test_autosave_backups.py` | regression_v097_autosave | автосохранение + кольцевой буфер бэкапов: project_key, кольцо N=3, restore, конфиг-дефолты/клампы, тики dirty/clean/no-file, open-промпт, BackupsDialog, откат на слот |
| `test_map_search.py` | regression_v098_map_search | поиск по карте Ctrl+F: панель, совпадения alias/host/ip/comment, подсветка/затемнение (И с тег-фильтром), Enter/Shift+Enter навигация, счётчик k/N, retranslate, закрытие при смене проекта; PySide6-menu guard; resize-перестановка панели (v0.9.9.1) |
| `test_selection_sync.py` | regression_v0991_selection_sync | selection sync без blockSignals: reentry-guard, внешние слоты работают во время программной смены, идемпотентный пересчёт, MapView.resized |
| `test_ext_terminal_dialog.py` | regression_v0992_ext_terminal_ui | v0.9.9.2 UI внешнего терминала: i18n 326 ключа × en/ru/zh (пinned), состав комбобокса по платформе, сохранение пресета сразу, «Сбросить к умолчанию», detect_terminal уважает пресет |

### Новые в серии v0.9.9.x (без предшественника)

| файл | покрывает |
|---|---|
| `test_diagnostics.py` | v0.9.9.3 services/diagnostics.py: перенесённые PingThread/ReverseDnsThread (подклассы QThread, сигнатуры сигналов), командные строки ping'а по ОС + CREATE_NO_WINDOW, ok/fail/exception-пути (фейковый subprocess.run), гигиена main_window.py (вложенные классы исчезли), регрессия _ping_node (старт/финиш/cleanup, guard AUDIT v0.7.2 #8) и _copy_node_info(hostname/ip) |
| `test_sidebar_panel.py` | v0.9.9.4 ui/sidebar.py: фасад MainWindow (панель встроена, win.tree/tag_filter/search_edit/btn_* — виджеты панели, методы окна), сигналы кнопок → слоты окна, гигиена main_window.py, refresh через фасад (строки/маркеры/поиск/тег-фильтр + AND-затемнение), unit-уровень (translate_fn=None, ValueError на недостающий колбэк, fill_context_menu 9+4), регрессия бага v0.9.2: retranslate при смене языка ru→en→ru |
| `test_pyproject.py` | v0.9.9.6 pyproject.toml (без установки): парсится (tomllib/tomli); имя ↔ APP_NAME из version.py (нормализация «SSH Map» → sshmap); версия == APP_VERSION; deps ↔ requirements.txt (набор имя+пин); entry point sshmap = main:main → существующая top-level `def main` в main.py (ast, без импорта) + модуль в сборке ([tool.setuptools]); [build-system] присутствует |
| `test_pdf_export.py` | v0.9.9.7 PDF-экспорт карты: MapScene.render_to_pdf (QPdfWriter, offscreen, без парсинга содержимого) — существование/размер > 1 KB/заголовок %PDF/%%EOF, возвращённое значение == размеру на диске; пустая сцена (fallback-rect) + портретная карта (portrait-страница); привязка MainWindow (_export_map_pdf, i18n-реестр меню «Файл»); i18n 2 ключа × en/ru/zh + идентичность наборов (304) |

### Новые в v1.0RC (Терминал v1)

| файл | покрывает |
|---|---|
| `test_terminal_colors.py` | v1.0RC1 цветовой движок + посячейный холст: resolve_color headless (brown/brightbrown → yellow/br_yellow, hex-passthrough 256/truecolor, опечатка pyte bfightmagenta, default-fallback, структура палитр black…white + br_* × 4); E2E через pyte (SGR 33/93/38;5;196/38;2;… → Char → resolve_color — путь `ls --color`); кэш форматов (hit/различие/лимит→clear, TERMINAL.md §5.1); рендер runs offscreen (split_row_runs — чистая функция: широкие глифы/заглушки, пиксельные цвета ячеек SGR 31/33/93/41/256/truecolor, блок-курсор через свап + cursor.hidden ESC[?25l/h, счётчик drawText — runs а не по-символьно); интеграция (SSHTerminalWindow → TerminalWidget, render() помечен DEPRECATED) |
| `test_terminal_input.py` | v1.0RC2 клавиатура + выделение/копирование: selection_cells без GUI (однострочное/многострочное/инвертированные границы/зажим колонок + regression на ошибку черновика №4 — координаты (row,col), построчный порядок); клавиатура offscreen (F1–F12 xterm-последовательности SS3/CSI, PageUp/Down/Home/End/Delete, базовый набор RC1, Ctrl+C без выделения → \x03, Ctrl+D/Z, AltGr-guard Ctrl+Alt → ничего, thread=None — без исключений); bracketed paste Ctrl+V (многострочный буфер со смешанными EOL — единый блок \x1b[200~…\x1b[201~, пустой буфер → ничего); мышь/копирование (drag в обе стороны, мульти-строчное копирование в буфер, Ctrl+C при выделении → канал не получает байты, простой клик → сброс + SIGINT, clamp за сетью); рендер подсветки offscreen (пиксели оверлея + stats) |
| `test_terminal_scroll.py` | v1.0RC3 resize PTY + скроллбэк + dirty-рендер: HistoryScreen headless (ввод только \r\n — факт №10: рост истории, страница = ceil(lines×ratio), авто-возврат к live при новом выводе, границы no-op, лимит глубины); resize-guard offscreen (фейковый channel считает resize_pty: 10 событий с одной сеткой → ровно 1 вызов PTY; invoke_shell 120×32 до первого resizeEvent; серия быстрых смен → один вызов с последними размерами; закрытый канал → guard); клавиатура (Ctrl+Shift+PgUp/PgDn → скроллбэк ДО голых PageUp/Down, голые PgUp/PgDn и Shift+PgUp без Ctrl → \x1b[5~/\x1b[6~ в shell, AltGr-guard); колесо (вверх/вниз/no-op на границах, thread=None — локально); dirty-рендер (нет _render_timer/_dirty, E2E через окно, paintEvent прошёл); мигание курсора (QTimer: show/hide, реальное переключение фазы, пиксели фаз); кнопка «Закрыть терминал» убрана (нет QPushButton, close_terminal() сохранён) |

### Новые в v1.0RC4

| файл | покрывает |
|---|---|
| `test_quick_launch.py` | v1.0RC4 Быстрый запуск: модель (дефолт [], порядок, старые JSON → [], sanitize битых записей/типов, round-trip без пароля); QuickLaunchDialog (prefill таблицы, валидация name/value/http(s)-схемы/дубликата, добавление url+command, удаление строки, пустой диалог нового сервера); AddServerDialog (кнопка «Быстрый запуск…», quick_launch переживает правку других полей, подхват результата QuickLaunchDialog); E2E сайдбар (подменю ПЕРВЫМ пунктом выше SSH, состав Webmin/K9S/«Настроить…», URL → webbrowser.open с точным URL); E2E карта (синтетический QContextMenuEvent: подменю первым, command-пункт → терминал с initial_command="k9s" при key auth); SSHTerminalWindow с фейковым потоком (до connected_signal байты не уходят, после — ровно b"k9s\n", повторный emit не дублирует, окно без команды сигнал игнорирует); настройка из подменю (undo восстанавливает список, _do_save пишет quick_launch в JSON, перезагрузка восстанавливает); v1.0-fix §7b: KeyError "name" in LogRecord — логирование успеха URL/команды без extra-коллизии с LogRecord.name; i18n 22 ключа × en/ru/zh + паритет 326 |

### Новые в v1.0 (финал)

| файл | покрывает |
|---|---|
| `test_terminal_acceptance.py` | v1.0 финал — полный acceptance всех RC одним прогоном без сети: состояние релиза (APP_VERSION == "1.0", pyproject-сверка, TerminalScreen.render() на месте и DEPRECATED — удаление не раньше v1.2, i18n-паритет 326); bash (промпт + ls --color через окно: SGR 34/93/256/truecolor → пиксельные чернила холста, ввод только \r\n); vim (ESC[?25l/h — курсор скрыт/виден по пустой строке, SGR 41-фон, known limitation: режима 1049 нет — экран не восстанавливается); htop (повторяющиеся полноэкранные фреймы ESC[2J, dirty-рендер без таймера); копирование (выделение мышью → буфер, Ctrl+C при выделении = копирование/в канал ничего, без выделения = \x03, Ctrl+V = bracketed paste единым блоком); конфиг задачи 9 (load_terminal_settings: дефолты/валидные/битые/явный 0; окно: nord → фон #2e3440, Consolas 12, глубина истории 50, неизвестная палитра → default, без конфига → скроллбэк включён 1000) |

### Отдельные смоуки (перенесены на _common.py)

| файл | бывший | покрывает |
|---|---|---|
| `test_collapse.py` | smoke_collapse | сворачивание плашек v0.8.4: toggle_collapsed/boundingRect, JSON round-trip collapsed, legacy без ключа, идемпотентность update_appearance, клик по шеврону |
| `test_drawio_export.py` | smoke_v095_drawio | экспорт drawio v0.9.5: валидный XML, структура (узлы/связи/группы/заметки/слои), координаты членов групп относительно parent, метки узлов |

## Вспомогательные файлы

| файл | роль |
|---|---|
| `_common.py` | обвязка: bootstrap/check/finish/wait_until и т.д. (не тест — run_all его пропускает) |
| `run_all.py` | единый раннер: собирает ровно `test_*.py` + `check_i18n_keys.py` (сам себя и прочие мета-скрипты НЕ включает — иначе рекурсия), по одному процессу на файл, таблица + единый exit code |
| `check_i18n_keys.py` | паритет i18n-ключей en/ru/zh (используемые в коде ключи × 3 языка) — входит в run_all |

## Конвенции

1. **Новая версия → новый тематический файл** `test_<тема>.py` (не «regression_vXXX»):
   имя говорит, ЧТО проверяется, а не когда добавлено; провенанс — в докстроке
   («бывш. regression_v098_map_search.py»). Файл самодостаточен: `bootstrap()` →
   проверки → `finish()`.
2. **Мышиный ввод** — только через `PySide6.QtTest.QTest` (widget) или синтетический
   `QGraphicsSceneMouseEvent` для QGraphicsItem (вывод v0.7.3, см. test_collapse.py).
3. **i18n-пину ключей:** при добавлении i18n-ключей в код обновить числовой пин
   «N ключей» в файлах, которые его проверяют (test_sidebar_context_menu /
   test_autosave_backups / test_map_search / test_ext_terminal_dialog /
   test_pdf_export / test_quick_launch) — иначе сьют упадёт на следующем релизе.
   `check_i18n_keys.py` ловит сами пропуски.
4. **HOME-изоляция обязательна** для всех тестов, пишущих в `~/.sshmap*`
   (bootstrap делает это сам); реальный home пользователя не трогать.
5. **Не трогать:** публичный API MainWindow, undo-стек, keyring-путь паролей,
   i18n-ключи (только добавление) — общие «Не трогать» серии v0.9.9.x.
6. Сьют обязан быть зелёным (`run_all.py` exit 0) в каждом релизе — конвенция
   ROADMAP; offscreen-режим не оставляет фоновых потоков.
