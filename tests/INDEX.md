# tests/ — карта тестового сьюта SSHMap

Сьют — plain-python скрипты **без pytest**: каждый файл сам по себе запускается,
печатает `ok`/`FAIL` по каждой проверке и завершается exit 0 (всё зелёное) или 1.
Общая обвязка — `_common.py`; единый запуск всех файлов — `run_all.py`.

## Запуск

```
python tests/run_all.py              # все test_*.py + check_i18n_keys.py, параллельно (4 воркера), таблица
python tests/run_all.py --workers 8  # число воркеров (1 = последовательно, как раньше)
python tests/run_all.py keyring      # только файлы, чьё имя содержит подстроку
python tests/test_tags.py            # один файл (из корня проекта)
```

Каждый файл — отдельный процесс: `bootstrap()` внутри делает изоляцию HOME
(тесты пишут `~/.sshmap/*` в песочницу), offscreen-платформу Qt, UTF-8 stdout
и faulthandler-таймаут 180 c. Отключить изоляцию HOME:
`SSHMAP_TEST_NO_HOME_ISOLATION=1`. При параллельном прогоне раннер передаёт
каждому файлу собственный рабочий каталог (`SSHMAP_TEST_WORKDIR`, создаётся в
%TEMP% и удаляется по завершении) — иначе `bootstrap()` соседнего процесса
сносил бы общий `_tmp_testdata`.

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

Пины релиза и общие проверки (внизу файла): константы `EXPECTED_APP_VERSION` /
`EXPECTED_I18N_KEYS` — обновлять при каждом релизе ТОЛЬКО здесь;
`load_i18n_langs(root)` — загрузка i18n/{en,ru,zh}.json; `check_i18n_parity(langs)` —
паритет наборов ключей + число; `check_release_state(root)` — APP_VERSION
(sentinel + формат X.Y.Z[.W][RCn]) + pyproject-сверка + заголовок requirements.txt.

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
| `test_ext_terminal_dialog.py` | regression_v0992_ext_terminal_ui | v0.9.9.2 UI внешнего терминала: i18n 13 ключей × en/ru/zh + паритет (пин — _common.py), состав комбобокса по платформе, сохранение пресета сразу, «Сбросить к умолчанию», detect_terminal уважает пресет |

### Новые в серии v0.9.9.x (без предшественника)

| файл | покрывает |
|---|---|
| `test_diagnostics.py` | v0.9.9.3 services/diagnostics.py: перенесённые PingThread/ReverseDnsThread (подклассы QThread, сигнатуры сигналов), командные строки ping'а по ОС + CREATE_NO_WINDOW, ok/fail/exception-пути (фейковый subprocess.run), гигиена main_window.py (вложенные классы исчезли; v1.1.4: source-проверка импортов потоков — против ui/main_window_node_ops.py, где живут _ping_node/_copy_node_info), регрессия _ping_node (старт/финиш/cleanup, guard AUDIT v0.7.2 #8) и _copy_node_info(hostname/ip) |
| `test_sidebar_panel.py` | v0.9.9.4 ui/sidebar.py: фасад MainWindow (панель встроена, win.tree/tag_filter/search_edit/btn_* — виджеты панели, методы окна), сигналы кнопок → слоты окна, гигиена main_window.py, refresh через фасад (строки/маркеры/поиск/тег-фильтр + AND-затемнение), unit-уровень (translate_fn=None, ValueError на недостающий колбэк, fill_context_menu 9+4), регрессия бага v0.9.2: retranslate при смене языка ru→en→ru |
| `test_pyproject.py` | v0.9.9.6 pyproject.toml (без установки): парсится (tomllib/tomli); имя ↔ APP_NAME из version.py (нормализация «SSH Map» → sshmap); версия == APP_VERSION; deps ↔ requirements.txt (набор имя+пин); entry point sshmap = main:main → существующая top-level `def main` в main.py (ast, без импорта) + модуль в сборке ([tool.setuptools]); [build-system] присутствует |
| `test_pdf_export.py` | v0.9.9.7 PDF-экспорт карты: MapScene.render_to_pdf (QPdfWriter, offscreen, без парсинга содержимого) — существование/размер > 1 KB/заголовок %PDF/%%EOF, возвращённое значение == размеру на диске; пустая сцена (fallback-rect) + портретная карта (portrait-страница); привязка MainWindow (_export_map_pdf, i18n-реестр меню «Файл»); i18n 2 ключа × en/ru/zh + паритет (пин — _common.py) |

### Новые в v1.0RC (Терминал v1)

| файл | покрывает |
|---|---|
| `test_terminal_colors.py` | v1.0RC1 цветовой движок + посячейный холст: resolve_color headless (brown/brightbrown → yellow/br_yellow, hex-passthrough 256/truecolor, опечатка pyte bfightmagenta, default-fallback, структура палитр black…white + br_* × 4); E2E через pyte (SGR 33/93/38;5;196/38;2;… → Char → resolve_color — путь `ls --color`); кэш форматов (hit/различие/лимит→clear, TERMINAL.md §5.1); рендер runs offscreen (split_row_runs — чистая функция: широкие глифы/заглушки, пиксельные цвета ячеек SGR 31/33/93/41/256/truecolor, блок-курсор через свап + cursor.hidden ESC[?25l/h, счётчик drawText — runs а не по-символьно); интеграция (SSHTerminalWindow → TerminalWidget, render() помечен DEPRECATED) |
| `test_terminal_input.py` | v1.0RC2 клавиатура + выделение/копирование: selection_cells без GUI (однострочное/многострочное/инвертированные границы/зажим колонок + regression на ошибку черновика №4 — координаты (row,col), построчный порядок); клавиатура offscreen (F1–F12 xterm-последовательности SS3/CSI, PageUp/Down/Home/End/Delete, базовый набор RC1, Ctrl+C без выделения → \x03, Ctrl+D/Z, AltGr-guard Ctrl+Alt → ничего, thread=None — без исключений); bracketed paste Ctrl+V (многострочный буфер со смешанными EOL — единый блок \x1b[200~…\x1b[201~, пустой буфер → ничего); мышь/копирование (drag в обе стороны, мульти-строчное копирование в буфер, Ctrl+C при выделении → канал не получает байты, простой клик → сброс + SIGINT, clamp за сетью); рендер подсветки offscreen (пиксели оверлея + stats) |
| `test_terminal_scroll.py` | v1.0RC3 resize PTY + скроллбэк + dirty-рендер: HistoryScreen headless (ввод только \r\n — факт №10: рост истории, страница = ceil(lines×ratio), авто-возврат к live при новом выводе, границы no-op, лимит глубины); resize-guard offscreen (фейковый channel считает resize_pty: 10 событий с одной сеткой → ровно 1 вызов PTY; invoke_shell 120×32 до первого resizeEvent; серия быстрых смен → один вызов с последними размерами; закрытый канал → guard); клавиатура (Ctrl+Shift+PgUp/PgDn → скроллбэк ДО голых PageUp/Down, голые PgUp/PgDn и Shift+PgUp без Ctrl → \x1b[5~/\x1b[6~ в shell, AltGr-guard); колесо (вверх/вниз/no-op на границах, thread=None — локально); dirty-рендер (нет _render_timer/_dirty, E2E через окно, paintEvent прошёл); мигание курсора (QTimer: show/hide, реальное переключение фазы, пиксели фаз); кнопка «Закрыть терминал» убрана (все QPushButton окна — внутри SFTP-вкладки v1.1.3; close_terminal() сохранён) |

### Новые в v1.0RC4

| файл | покрывает |
|---|---|
| `test_quick_launch.py` | v1.0RC4 Быстрый запуск: модель (дефолт [], порядок, старые JSON → [], sanitize битых записей/типов, round-trip без пароля); QuickLaunchDialog (prefill таблицы, валидация name/value/http(s)-схемы/дубликата, добавление url+command, удаление строки, пустой диалог нового сервера); AddServerDialog (кнопка «Быстрый запуск…», quick_launch переживает правку других полей, подхват результата QuickLaunchDialog); E2E сайдбар (подменю ПЕРВЫМ пунктом выше SSH, состав Webmin/K9S/«Настроить…», URL → webbrowser.open с точным URL); E2E карта (синтетический QContextMenuEvent: подменю первым, command-пункт → терминал с initial_command="k9s" при key auth); SSHTerminalWindow с фейковым потоком (до connected_signal байты не уходят, после — ровно b"k9s\n", повторный emit не дублирует, окно без команды сигнал игнорирует); настройка из подменю (undo восстанавливает список, _do_save пишет quick_launch в JSON, перезагрузка восстанавливает); v1.0-fix §7b: KeyError "name" in LogRecord — логирование успеха URL/команды без extra-коллизии с LogRecord.name; i18n 22 ключа × en/ru/zh + паритет (пин — _common.py) |

### Новые в v1.0 (финал)

| файл | покрывает |
|---|---|
| `test_terminal_acceptance.py` | v1.0 финал — полный acceptance всех RC одним прогоном без сети: состояние релиза (APP_VERSION == "1.1.4", pyproject-сверка, TerminalScreen.render() на месте и DEPRECATED — удаление не раньше v1.2, i18n-паритет 398: +33 в v1.1, +14 в v1.1.1, +2 в v1.1.2RC2, +2 в v1.1.2 final, +21 в v1.1.3 (sftp.*); в v1.1.2RC3 новых ключей нет; окно показано через show() как в продакшене — offscreen-окно без show() откладывает resize до первого paint); bash (промпт + ls --color через окно: SGR 34/93/256/truecolor → пиксельные чернила холста, ввод только \r\n); vim (ESC[?25l/h — курсор скрыт/виден по пустой строке, SGR 41-фон, known limitation: режима 1049 нет — экран не восстанавливается); htop (повторяющиеся полноэкранные фреймы ESC[2J, dirty-рендер без таймера); копирование (выделение мышью → буфер, Ctrl+C при выделении = копирование/в канал ничего, без выделения = \x03, Ctrl+V = bracketed paste единым блоком); конфиг задачи 9 + v1.1 + v1.1.1 (load_terminal_settings: дефолты/валидные/битые/явный 0, в т.ч. terminal_close_behavior — trim/"ask", битое → "close"; v1.1.1: terminal_max_open — дефолт 4, кламп 1..32, str/99 → дефолт; окно: nord → фон #2e3440, Consolas 12, глубина истории 50, неизвестная палитра → default, без конфига → скроллбэк включён 1000) |

### Новые в v1.1

| файл | покрывает |
|---|---|
| `test_settings_dialog.py` | v1.1 диалог настроек (хаб): i18n (+33 ключа, паритет 398 = 377 на v1.1.2 final + 21 sftp.* в v1.1.3), векторная иконка шестерёнки (`_DRAWERS["settings"]`), 6-я кнопка ⚙ сайдбара (кортеж в `_BUTTONS`, сигнал `settings_clicked`); миграция external_terminal (legacy `~/.sshmap_settings.json` → config.json: копирование, приоритет конфига, best-effort-удаление); StatusChecker (`get_status_settings()` клампы/битые значения, `set_interval()`/`set_probe_timeout()`); terminal_close_behavior (фейковый поток + patched QMessageBox.question: "ask" + живая сессия → подтверждение, Отмена держит окно, "close"/завершённая сессия — без диалога); SettingsDialog (порядок 6 вкладок, диапазоны виджетов, prefill из конфига, `collect()` ровно 18 ключей = v1.1:10 + v1.1.1:7 + v1.1.2 final:1 (status_max_parallel) + типы, OK → merge-запись + `applied()`, Cancel no-op); вкладка языка (немедленный `language_changed` + retranslate через `i18n.set_language`; сценарий ru→en — с v1.1.1 дефолтный язык en, стартовая точка ставится явно); точки входа MainWindow (меню «Настройки» между «Вид»/«Помощь», act_settings в actions меню, автоподхват CommandPalette, кнопка сайдбара открывает диалог, live-применение: StatusChecker 45 s / 2.5 s + таймер автосохранения stop/start) |

### Новые в v1.1.1 (опции вокруг хаба)

| файл | покрывает |
|---|---|
| `test_settings_options.py` | v1.1.1 тематический тест релиза (ROADMAP v1.1.1, 50 проверок): i18n (+14 ключей, паритет 359→373→377→398); дефолтный язык en — новый пользователь (без config.json) vs существующий (сохранённый ru через `get_last_language`), `i18n._default_language == "en"`; шрифты — валидатор `load_ui_settings()` (дефолты/trim/битые типы/0=системный/вне диапазона), поля «Общих»/«Терминала»/«Карта» + prefill, live-применение (`QApplication.setFont` без перезапуска + `widget.set_font()` в открытое окно; без ключей — не меняется); лимит своих терминалов — `terminal_max_open` (дефолт 4): ниже лимита без диалога, на лимите QMessageBox «закрыть старейшую» (Close → `close_terminal`+`_force_close` старейшей + новое окно; Cancel → None, реестр не тронут), `terminal_max_open=2` из конфига; двойной клик по узлу — `ui_node_double_click` properties/connect/битое→properties, кэш `_node_double_click_mode`, "connect" → `_run_ssh_connect`; кнопки сайдбара — `set_buttons_visible(False/True)` (6 кнопок), конфиг через `_apply_settings_from_dialog()` (дерево/поиск при этом видны), меню «Вид → Сайдбар» (PySide6 6.11: `trigger()` = клик — сам инвертирует checked и эмитит triggered с новым состоянием); плашка связи — `label_display_text` (выкл → только метка, вкл → «SSH · <метка>», без метки → тип), E2E стрелка + `refresh_label()` без пересоздания, maxLength 20 + подсказка `connection.label_hint`, старая 30-символьная метка НЕ обрезана (`_LabelLineEdit` — Qt setMaxLength обрезает существующий текст); состояние релиза (APP_VERSION == "1.1.4", pyproject) |

### Новые в серии v1.1.2 (RC + final)

| файл | покрывает |
|---|---|
| `test_ssh_undo_lifecycle.py` | v1.1.2RC1 SSH-путь (тема релиза, 47 проверок): N1 — `_on_worker_success()` не пишет в node.data сам (unit: реальный диалог + фейковый worker), E2E `_run_ssh_connect` → `CmdEditNodeData` на стеке → Ctrl+Z откатывает user/key/port → Ctrl+Y применяет; N2 — «conhost» вне TERMINAL_CHOICES_WINDOWS/комбобокса/detect, конфиг `"conhost"` читается как `"cmd"` без перезаписи файла (non-Windows → `"auto"`), legacy-миграция нормализует в config.json + удаляет legacy-файл, `build_command("conhost") == build_command("cmd")` (`[0] == "cmd.exe"`); N5 — password-ветка look_for_keys=False/allow_agent=False (фейковый SSHClient на месте paramiko.SSHClient) + контрольные key-ветка (False/True) и чистая key/agent-ветка (True/True) не тронуты; N4 — guard: stop() до ошибки → error_signal не эмитится, живой поток ошибку доставляет; реестр орфано-потоков `_orphan_threads`: окно закрыто во время подключения → поток зарегистрирован и жив, после finished() реестр самочищается; бонус-N11 — стэш keyring-пароля при создании CmdAddRemoveNode(mode="add"), undo удаляет узел + keyring-запись, redo восстанавливает пароль, свежее добавление — пустой стэш (без «фантомного» пароля), E2E `_duplicate_node` → Ctrl+Z → Ctrl+Y с паролем; состояние релиза (APP_VERSION == "1.1.4", pyproject, заголовок requirements v1.1.4) |
| `test_rc2_map_import_sidebar.py` | v1.1.2RC2 карта/импорт/сайдбар (тема релиза, 52 проверки): N3 — сброс «залипшего» drag-состояния MapView при потере фокуса/активации: реальный QTest mousePress по узлу → focusOutEvent (PySide6 6.11: blurEvent не существует) в середине перетаскивания → mouseReleaseEvent НЕ коммитит сдвиг, `_move_drag_node`/`_group_drag_olds` очищены, dragMode вернулась в ScrollHandDrag; changeEvent(ActivationChange) — то же самое, посторонние QEvent-типы игнорируются, чистое состояние (без drag) не ломает view; N6 — HostResolverThread (services/host_importer.py): unit — resolve_host вызывается вне GUI-потока (проверка thread id), прогресс (1,3)/(2,3)/(3,3), resolved_map с None для битых имён, stop() отменяет до следующего имени; E2E MainWindow — patched QFileDialog/QMessageBox + фейковый резолвер 150 мс/имя: GUI не блокируется (elapsed < 250 мс при 3 именах), статус-бар «Резолвим имена хостов… done/total», результат added=3/skipped=0, undo одной пачкой CmdAddRemoveNodeBatch удаляет все узлы; IP-only путь — синхронно без потока; N8/N9 — мёртвый код сайдбара: source-проверка через tokenize (COMMENT-фильтр — сами комментарии упоминают убранные вызовы) + поведение (ForegroundRole None на тегированной строке, DecorationRole комбо None); U1 — все 6 кнопок `_BUTTONS` с text-align: left + padding-left: 12px, иконки не null, высота 34; N10 — msg.confirm_delete_profile × en/ru/zh (перевод через i18n.set_language на каждый язык), ProfileManagerDialog: patched QMessageBox.question → точный текст «Удалить профиль '<alias>'?», удаление происходит; состояние релиза (APP_VERSION == "1.1.4", pyproject-сверка, заголовок requirements v1.1.4, паритет 398 = 377 на v1.1.2 final + 21 sftp.* в v1.1.3) |
| `test_rc3_terminal_window.py` | v1.1.2RC3 окна терминала (тема релиза, 79 проверок): §1–4 U3 (стрелки в mc — DECCKM/SS3; факт pyte 0.8.2: приватные режимы в screen.mode со сдвигом <<5 — DECCKM = 32, а не 1, дефолтный mode {224, 800} = DECAWM+DECTCEM; `application_cursor_keys()` под lock; клавиатура CSI/SS3 в обоих режимах + независимые PageUp/Down/Delete/F-клавиши, цикл smkx/rmkx, thread=None, потокобезопасность feed/чтение); §5 N7 — сброс выделения при авто-возврате скроллбэка к live (окно с фейковым SSH-потоком: 60 строк истории → scroll_page_up → drag-выделение мышью → новый вывод → позиция history сменилась → clear_selection; регрессии: Ctrl+C после сброса → \x03, вывод при live — выделение живёт, Ctrl+C с выделением копирует и в канал ничего, E2E через output_signal); §6 колесо — `terminal_wheel` ("scrollback" дефолт | "off", strip+lower/битое/int → дефолт): виджет "off" — позиция не меняется + event.ignore + в PTY ничего, "scrollback" — prev/next_page + accept, окно: конфиг → widget._wheel_mode; §7 U2 — modules/window_geometry.py (helper round-trip 700×500 против дефолта QMainWindow 640×480, битый base64/не-dict/нет ключа → False + дефолтный размер; E2E терминал: closeEvent → ui_window_geometry_terminal {geometry,state} → новое окно 640×480 вместо 800×600; E2E MainWindow: closeEvent → ui_window_geometry_main → новый MainWindow 700×500); §8 состояние релиза (APP_VERSION == "1.1.4", pyproject-сверка, заголовок requirements v1.1.4) |
| `test_status_parallel.py` | v1.1.2 final параллельные пробы статусов (тема релиза, 51 проверка): §1–4 ThreadPoolExecutor в `_ProbeThread.run()` с фейковыми пробами (monkeypatch `probe_ssh`, без сети) — пик параллельности > 1 и ≤ max_parallel, ровно N вызовов без дублей, раунд короче последовательного (elapsed < baseline); результаты ПО МЕРЕ ГОТОВНОСТИ (быстрая проба прилетела первой, а не первой в списке целей; разбег во времени ≥ 0.15 c); семантика `_busy` не меняется (повторный `start_round()` игнорируется — ни второго потока, ни лишних проб; после round_finished новый раунд стартует); отмена — stop() выводит раунд быстрее полного параллельного цикла, отменённые до начала пробы результата не дают; §5 ключ `status_max_parallel` (нет конфига → дефолт 16, валидное читается, клампы 0→1 / 9999→64, битые str/bool → дефолт; конструктор max_parallel, set_max_parallel на лету с клампом); §6 мягкий авто-интервал для больших карт (N=50 — базовый интервал, N=51 — удвоенный `effective_interval_ms()`; таймер реально переключён после раунда и в set_interval(); ниже порога — возврат к базовому); §7 E2E MainWindow (51 узел → is_large_map True, одноразовая подсказка с числом узлов в статус-баре, повторный sync не сбрасывает флаг, ниже порога — сброс); §8 диалог «Статусы» (спин 1..64, prefill из конфига, retranslate — лейбл переведён, collect() ровно 18 ключей = 17 + status_max_parallel, тип int); §9 i18n (+2 ключа × en/ru/zh не пусты, паритет 398 — было 375→377 в v1.1.2); §10 состояние релиза (APP_VERSION == "1.1.4", pyproject-сверка, заголовок requirements v1.1.4) |

### Новые в v1.1.3

| файл | покрывает |
|---|---|
| `test_sftp_tab.py` | v1.1.3 SFTP-вкладка в окне терминала (тема релиза, 85 проверок): ВСЕ без сети — фейковый SFTPClient с in-memory ФС (поверхность API paramiko: listdir_attr/open/close/get_channel; ошибки IOError "No such file" = SSH_FX_NO_SUCH_FILE); §1–2 worker-очередь: два upload'а СТРОГО последовательно, прогресс-сигналы по порядку (монотонность, финал == total, контент), ошибка пути → error-сигнал БЕЗ падения очереди (list/upload несуществующего каталога, следующие задачи работают); §3 отмена: флаг между операциями — текущая передача прерывается на чанке, очередь пропускается с task_cancelled, worker живёт, флаг автосбрасывается; §4 shutdown: idle и во время передачи (в пределах wait-бюджета), SFTPClient закрыт, queue_* после стопа — None; §5 SftpTab offscreen: листинг/переходы («..», вход в каталог, Refresh, stale-фильтр устаревших ответов), upload/download выбранных (QFileDialog подменён; ожидание по task_done-сигналам, а не по существованию файла — гонка open("wb") до записи чанков), кнопка «Отменить»; §6 SSHTerminalWindow: QTabWidget [Терминал | Файлы], ленивый open_sftp() на том же transport, connected_signal-подхват, ошибка open_sftp → статус-бар, прогресс в статус-баре, closeEvent-teardown; §7 i18n: 21 ключ sftp.* × en/ru/zh, паритет 377→398; §8 состояние релиза (APP_VERSION == "1.1.4", pyproject-сверка, заголовок requirements v1.1.4) |

### Новые в v1.1.4

| файл | покрывает |
|---|---|
| `test_main_window_split.py` | v1.1.4 гигиена main_window.py — разрез на миксины (тема релиза, 29 проверок): §1 структура (MRO MainWindow → ProjectIOMixin → NodeOpsMixin → SshMixin → QMainWindow; все 39 методов плана ROADMAP определены в своих миксинах и отсутствуют в `MainWindow.__dict__`; source-scan: миксины не импортируют main_window — нет цикла; host_attr видит атрибут модуля-фасада И тестовую подмену — шов для offscreen); §2 ProjectIOMixin save/load/restore (`_save_project_as` с подменённым QFileDialog → `_project_file` + сброс dirty, JSON без паролей; `_autosave_tick` → файл автосохранения; `_restore_from_autosave` → содержимое записано в файл проекта + сцена перезагружена; `_load_project_at` во втором окне — узлы восстановлены, dirty сброшен); §3 NodeOpsMixin add/duplicate/delete (`_add_server` с фейковым AddServerDialog через host_attr-шов, включая bool-guard v0.8.1 `_add_server(True)` без падения, по undo-команде на узел; `_duplicate_selected_node` — копия +40/+40 с новым id, выделение перешло к копии; групповое `_delete_selected_nodes` с одним подтверждением → сцена пуста); §4 SshMixin ssh-dialog flow (`_run_ssh_connect` с фейковыми SSHConnectDialog/SSHTerminalWindow: поля через `_apply_ssh_dialog_fields` → `CmdEditNodeData` на undo-стеке, узел в `_ssh_connected_nodes`, терминальное окно создано и зарегистрировано, пароль передан окну и не хранится в модели, автосбор информации (auto=True), `_forget_terminal_window` очищает реестр; без выделения — information без падения) |

### Новые в v1.2

| файл | покрывает |
|---|---|
| `test_terminal_page.py` | v1.2 рефактор TerminalSessionPage «окно → страница» + трекинг по сессиям (тема релиза, 76 проверок; offscreen, ВСЕ без сети — фейковые потоки с тем же API, что у SSHTerminalThread): §1 конструкция страницы (сессия как переиспользуемый виджет: thread+screen+холст+статус+SFTP-вкладка, конфиг terminal_* из config.json, тестовый шов класса потока ST.SSHTerminalThread); §2 ВСЕ teardown-пути через единый `page.shutdown()` (идемпотентен) — штатный путь (PTY-таймер остановлен, сигналы потока/worker'а отвязаны, поздние emit no-op, поток стопнут, реестры орфано пустые), орфано-путь N4 (блокирующийся поток: wait(1500) не дождался → `_orphan_threads`, поздний finished() самочищает реестр), SFTP-worker (ленивый старт на живом transport'е, стоп в бюджете, сигналы отвязаны), error-путь (`error_signal` → QMessageBox.critical + статус-строка + close_terminal без хоста), close_terminal с хост-окном; §3 confirm_close — gate «ask» (Cancel держит / Close закрывает), «close» и завершённая сессия без диалога, `_force_close` (путь лимита); §4 регрессия жизненного цикла окна (режим `windows` = v1.1.x: тонкая обёртка WA_DeleteOnClose/заголовок/геометрия window_geometry.py, compat-свойства live-ссылаются на страницу, ресайз холста → сетка через eventFilter, мост статус-бара sticky+SFTP-прогресс, round-trip ui_window_geometry_terminal, E2E WA_DeleteOnClose — C++-объект уничтожен после close); §5 трекинг по СЕССИЯМ в MainWindow (реестр хранит TerminalSessionPage, а не окна; зелёная точка узла горит пока жива хотя бы одна сессия и гаснет когда все закрыты; лимит «4 терминала» по сессиям: Cancel → None, Close → старейшая `_force_close`+закрыта, реестр обновлён); §6 i18n-паритет (398) + состояние релиза |

### Отдельные смоуки (перенесены на _common.py)

| файл | бывший | покрывает |
|---|---|---|
| `test_collapse.py` | smoke_collapse | сворачивание плашек v0.8.4: toggle_collapsed/boundingRect, JSON round-trip collapsed, legacy без ключа, идемпотентность update_appearance, клик по шеврону |
| `test_drawio_export.py` | smoke_v095_drawio | экспорт drawio v0.9.5: валидный XML, структура (узлы/связи/группы/заметки/слои), координаты членов групп относительно parent, метки узлов |

## Вспомогательные файлы

| файл | роль |
|---|---|
| `_common.py` | обвязка: bootstrap/check/finish/wait_until и т.д. (не тест — run_all его пропускает) |
| `run_all.py` | единый раннер: собирает ровно `test_*.py` + `check_i18n_keys.py` (сам себя и прочие мета-скрипты НЕ включает — иначе рекурсия), параллельно (ThreadPoolExecutor, по умолчанию 4 воркера; `--workers N`), каждый файл — отдельный процесс, таблица + единый exit code |
| `check_i18n_keys.py` | паритет i18n-ключей en/ru/zh (используемые в коде ключи × 3 языка) — входит в run_all |

## Конвенции

1. **Новая версия → новый тематический файл** `test_<тема>.py` (не «regression_vXXX»):
   имя говорит, ЧТО проверяется, а не когда добавлено; провенанс — в докстроке
   («бывш. regression_v098_map_search.py»). Файл самодостаточен: `bootstrap()` →
   проверки → `finish()`.
2. **Мышиный ввод** — только через `PySide6.QtTest.QTest` (widget) или синтетический
   `QGraphicsSceneMouseEvent` для QGraphicsItem (вывод v0.7.3, см. test_collapse.py).
3. **Пины релиза:** при каждом релизе обновить только `tests/_common.py` —
   `EXPECTED_APP_VERSION` (версия) и `EXPECTED_I18N_KEYS` (паритет en/ru/zh);
   release-state-секции тематических файлов вызывают общий
   `check_release_state()`, паритет — `check_i18n_parity()` (ранее: число
   «N ключей» в 12 файлах + версионные пины в 7 секциях). Пропуски самих
   i18n-ключей против кода ловит `check_i18n_keys.py`.
4. **HOME-изоляция обязательна** для всех тестов, пишущих в `~/.sshmap*`
   (bootstrap делает это сам); реальный home пользователя не трогать.
5. **Не трогать:** публичный API MainWindow, undo-стек, keyring-путь паролей,
   i18n-ключи (только добавление) — общие «Не трогать» серии v0.9.9.x.
6. Сьют обязан быть зелёным (`run_all.py` exit 0) в каждом релизе — конвенция
   ROADMAP; offscreen-режим не оставляет фоновых потоков.
