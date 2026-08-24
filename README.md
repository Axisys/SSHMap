# SSH Map (NodeVisualSSH) — v0.9.1

Десктопное приложение (Python + PySide6): интерактивная карта IT-инфраструктуры с прямым SSH-подключением к узлам. Slogan: *"Draw your infrastructure. Organize it. Connect to it."*

Единственный источник актуальной версии — этот README и код. Подробная история изменений — в DOCUMENTATION.md (при расхождениях приоритет у кода).

---

## 1. Запуск и тесты

```bash
cd F:/PythonAI/sshmap
pip install PySide6 paramiko keyring pyte   # все зависимости из requirements.txt
python main.py                              # запуск GUI

# Тесты без pytest (все должны завершаться EXIT=0):
QT_QPA_PLATFORM=offscreen python tests/smoke_test.py        # 256 проверок
QT_QPA_PLATFORM=offscreen python tests/regression_v083.py   # 34 проверки (undo/redo)
QT_QPA_PLATFORM=offscreen python tests/regression_v081.py   # 22 проверки
QT_QPA_PLATFORM=offscreen python tests/regression_v091.py   # 28 проверок (экспорт + фон)
QT_QPA_PLATFORM=offscreen python tests/check_i18n_keys.py   # паритет i18n-ключей (exit 0 = ок)
```

Требования: Python 3.10+, Windows/Linux/macOS. Логи: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler 5MB × 3).

---

## 2. Структура проекта

```
main.py                      # точка входа: setup_logging() → QApplication → MainWindow → start_status_checks()
models/
├── server.py                # ServerData dataclass; server_data_from_dict/to_dict (password исключается)
└── profile.py               # Profile; CRUD; JSON ~/.sshmap_profiles.json (пароли в keyring, префикс "profile:{id}")
graphics/
├── map_scene.py             # MapScene: _nodes/_arrows/_notes/_groups; resync_group_members (геометрическое членство)
├── map_view.py              # MapView: зум 0.1–5.0, панорамирование, Shift+drag связи, ctx-меню, node_drag_committed (v0.8.3)
├── server_node.py           # ServerNode: карточка со статусом online/warn/offline (#22c55e/#facc15/#ef4444)
├── connection_arrow.py      # ConnectionArrow: кубическая Безье, 6 типов связей, hit-зона ~10px через contains()
├── sticky_note.py           # StickyNote: QGraphicsProxyWidget+QTextEdit, ручной drag/resize/edit
├── node_group.py            # NodeGroup (v0.8.1): рамка кластера z=-5; членство = центр узла внутри верхней группы
└── background_image.py      # BackgroundImage (v0.9.1): фон-изображение z=-10, drag/resize за угол
modules/
├── ssh_worker.py            # SSHWorker (одноразовый QThread); реестр get_active_worker/wait_for_worker
├── ssh_terminal.py          # SSHTerminalThread + SSHTerminalWindow + TextEdit; QTimer 33мс HTML-рендер
├── terminal_screen.py       # TerminalScreen: pyte.Screen(120x32)+ByteStream, feed под threading.Lock
├── host_key_policy.py       # SshKnownHostsPolicy: ~/.sshmap/known_hosts; изменённый ключ → BadHostKeyException (MITM)
├── external_terminal.py     # (v0.8.2) системный терминал ОС; настройки ~/.sshmap_settings.json; пароль НЕ в argv
├── undo_commands.py         # (v0.8.3) 7 QUndoCommand: MoveNode(merge), AddRemoveNode(+стрелки), AddRemoveConnection,
│                            #   AddRemoveNote, EditTextNote(дебаунс 600мс), EditConnection, EditNodeData
└── logger.py                # setup_logging()/get_logger(__name__)
storage/project.py           # save_project/load_project — JSON версии "0.9" (+ ключ "background")
services/
├── credential_manager.py    # keyring-абстракция (синглтон get_credential_manager()); graceful fallback без keyring
└── status_checker.py        # StatusChecker: QTimer разводит раунды, пробы в _ProbeThread; probe_ssh() → online/warn/offline
dialogs/                     # AddServerDialog, SSHConnectDialog (+кнопка внешнего терминала),
                             # ConnectionDialog/EditConnectionDialog, ProfileManagerDialog
ui/main_window.py            # MainWindow (~1950 строк): контроллер; undo_stack (QUndoStack), dirty по canUndo()+baseline;
                             #   экспорт карты в PNG/JPEG (v0.9.1), установка/удаление фона
i18n/                        # t(key,**kwargs); en.json/ru.json/zh.json — 241 ключ, наборы идентичны; ru — дефолт
tests/                       # smoke_test.py, regression_v081/v083/v091.py, check_i18n_keys.py
```

---

## 3. Формат проекта (JSON `.json` / `.sshmap`)

```json
{
  "version": "0.9",
  "servers":  [{"id": "710602ee", "alias": "...", "host": "...", "user": "...",
                "x": 0.0, "y": 0.0, "cpu": "", "ram": "", "disk": "", "ip": "",
                "comment": "", "ssh_port": 22, "key_path": ""}],
  "connections": [{"source_id": "...", "target_id": "...", "label": "", "type": "ssh"}],
  "notes":  [{"id": "...", "text": "", "x": 0.0, "y": 0.0, "width": 240.0, "height": 160.0}],
  "groups": [{"id": "...", "name": "", "x": 0.0, "y": 0.0, "width": 480.0, "height": 320.0}],
  "background": {"path": "C:/schemes/dc.png", "x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0},
  "zoom": 1.0, "center_x": 0.0, "center_y": 0.0
}
```

Инварианты формата:
- `password` **никогда** не сериализуется — только keyring (`server_data_to_dict()` исключает).
- Типы связей: `ssh|vpn|http|database|nfs|kubernetes`; неизвестный/отсутствующий тип → `ssh`. Поле `version` при загрузке не валидируется (файлы 0.6+ читаются).
- Членство в группах **не хранится** — вычисляется из геометрии (центр карточки внутри верхней группы, эксклюзивно).
- `background` хранит **путь** к изображению (файл НЕ встраивается в JSON); отсутствующий файл при загрузке игнорируется с warning. Геометрия фона в undo не входит.

---

## 4. Ключевые поведения (важно для модификации кода)

### Undo/Redo (v0.8.3)
- Любое изменение сцены делается через `MainWindow._push_command(cmd)`; сцена меняется **только** внутри `redo()/undo()` команды — `QUndoStack.push()` сам вызывает redo.
- Dirty-маркер: `self._dirty = undo_stack.canUndo() or self._undo_baseline_dirty`; `_do_save()` вызывает `_reset_undo_stack()` (новая baseline). `_undo_baseline_dirty` покрывает dirty-причины вне undo (статусы, группы).
- В undo НЕ входят: статусы узлов, перемещение/resize групп, координаты при загрузке.
- Перетаскивание узла: MapView ловит release, эмитит `node_drag_committed(node, old, new)` → CmdMoveNode.

### Статусы (v0.7.1)
`probe_ssh(host, port)`: TCP открыт + SSH-баннер → `online`; порт открыт без баннера → `warn`; иначе `offline`. Пробы только в `_ProbeThread` (не на GUI-потоке). `start_status_checks()` вызывается из main.py один раз после `show()`.

### Терминал (v0.8)
Сырые байты SSH → `TerminalScreen.feed()` (pyte, под lock) → QTimer ~30 FPS → HTML в QPlainTextEdit. Известный хост пиннится в `~/.sshmap/known_hosts`.

### Безопасность
Пароли: только keyring (профили `"profile:{id}"`, серверы по server_id). При недоступном keyring приложение работает, но пароли не переживают перезапуск. Внешний терминал: пароль вводит ssh-клиент ОС, никогда не argv.

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

---

## 6. i18n

```python
from i18n import t, set_language, get_available_languages
t("btn.add_server", alias="web-1")   # форматирование {alias}
```
ru (дефолт) / en / zh. Правило: новый ключ добавляется во все 3 файла сразу; проверка — `python tests/check_i18n_keys.py`. Модули с горячим путём (ssh_worker, ssh_terminal) используют кэшированный `get_translator()`.

---

## 7. Состояние и roadmap

**Реализовано полностью:** карта (узлы/Безье-связи 6 типов/заметки/группы), статусы online/warn/offline, терминал на pyte (vim/htop работают), внешний системный терминал, undo/redo, автосбор информации о Linux-сервере (v0.9), профили + keyring, i18n ru/en/zh, контекстные меню всех объектов, fit/zoom/центрирование, экспорт карты в PNG/JPEG и фоновое изображение с drag/resize (v0.9.1).

**Известные ограничения:** undo не покрывает группы и геометрию фона; фоновое изображение хранится путём (при переносе проекта на другую машину файл нужно переносить вместе с картой).

**Roadmap (по приоритету):**
1. **v0.9.2**: горячие клавиши + палитра команд Ctrl+K (fuzzy-поиск по действиям и серверам).
2. **v0.9.3**: дублирование узла (Ctrl+D) + мультивыделение + групповые операции.
3. **v0.9.4**: теги/цветные метки серверов (prod/staging/dev) + фильтр.
4. **v0.9.5**: экспорт карты в draw.io (`.drawio`, mxGraph XML через ElementTree, без новых зависимостей); фон отдельным слоем; импорт — опционально, только своих файлов. Предусловие: модель данных после v0.9.4.
5. **v0.10**: jump host (ProxyJump) + agent forwarding; импорт из ~/.ssh/config; поиск Ctrl+F.
6. **v1.0**: доработки дизайна (DESIGN.md). **v1.x**: SFTP-браузер. **v2.0**: Prometheus-метрики.

---
