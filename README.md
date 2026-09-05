# SSH Map (NodeVisualSSH) — v1.2.2

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

Single source of truth for the version — `version.py` (`APP_VERSION`); released versions — `CHANGELOG.md`; planned features — `ROADMAP.md`.

---

## 1. Running & Tests

```bash
pip install -r requirements.txt        # all dependencies (PySide6, paramiko, keyring, pyte)
python main.py                         # run the GUI

# Installable identity (pyproject.toml) — install as a package:
pipx install .                         # or pip install . → sshmap command (entry point main:main)

# Tests without pytest: topical test_*.py files + a single parallel runner.
# Tests are isolated: they write to a temporary HOME and set UTF-8 stdout
# themselves — no extra environment needed on cp1251 consoles or in CI:
python tests/run_all.py              # everything (49 files): parallel (4 workers), results table + single exit code (0 ⇔ all green)
python tests/run_all.py --workers 8  # worker count (1 = sequential, as before)
python tests/run_all.py keyring      # filter by substring in file name
python tests/test_tags.py            # a single file (from the project root)
```

Suite map — what each `test_*.py` covers and where it came from, plus conventions: `tests/INDEX.md`.
Test harness `tests/_common.py`: HOME isolation (sandbox for `~/.sshmap/*`), offscreen platform,
faulthandler timeout of 180 s; each file exits with exit 0 = ALL PASS.
Release pins are centralized at the bottom of `_common.py` (`EXPECTED_APP_VERSION`, `EXPECTED_I18N_KEYS`
+ shared checks): one place to update per release.

Requirements: Python 3.10+, Windows/Linux/macOS. Logs: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler 5 MB × 3).

---

## 2. Project Structure

```
main.py                      # Entry point: setup_logging() → QApplication → MainWindow → start_status_checks()
pyproject.toml               # Installable identity (name/version/deps from version.py and requirements.txt, entry point sshmap = main:main) — checked by tests/test_pyproject.py
models/
├── server.py                # ServerData dataclass; server_data_from_dict/to_dict (password excluded);
│                            #   quick_launch — list of Quick Launch items + sanitize_quick_launch
└── profile.py               # Profile; CRUD; JSON ~/.sshmap_profiles.json (passwords in keyring, "profile:{id}" prefix)
graphics/
├── map_scene.py             # MapScene: _nodes/_arrows/_notes/_groups; resync_group_members (geometric membership)
├── map_view.py              # MapView: zoom 0.1–5.0, panning, Shift+drag connections, context menus,
│                            #   node_drag_committed, multi-selection Ctrl+click/rubber band + nodes_drag_committed
├── server_node.py           # ServerNode: card with online/warn/offline status (#22c55e/#facc15/#ef4444)
├── connection_arrow.py      # ConnectionArrow: cubic Bezier, 6 connection types, ~10 px hit zone via contains()
├── sticky_note.py           # StickyNote: QGraphicsProxyWidget+QTextEdit, manual drag/resize/edit
├── node_group.py            # NodeGroup: cluster frame z=-5; membership = node center inside the topmost group
└── background_image.py      # BackgroundImage: map background image z=-10, drag/resize by corner
modules/
├── ssh_worker.py            # SSHWorker (one-shot QThread); get_active_worker/wait_for_worker registry
├── ssh_terminal.py          # SSHTerminalThread (connected_signal after invoke_shell) + SSHTerminalWindow — a window with a QTabWidget of TerminalSessionPage sessions (tab title = node alias; WA_DeleteOnClose, geometry via window_geometry.py); load_terminal_settings() — terminal_* keys from ~/.sshmap/config.json (defaults = behavior, see §4 "Settings"); _orphan_threads registry. Details: §4 "Terminal"
├── terminal_page.py         # TerminalSessionPage: an SSH session as a reusable widget — thread + pyte screen + canvas + status line + SFTP tab; single idempotent teardown shutdown() on every path, confirm_close() gate ("ask"); close_terminal() closes only its own tab. Details: §4 "Terminal"
├── terminal_dock.py         # TerminalDockContent + TerminalsDock: "tabs" mode (terminal_mode) — a detachable "Terminals" QDockWidget in MainWindow. Details: §4 "Terminal"
├── sftp_worker.py           # SftpWorker: one worker thread with a list/upload/download task queue over the live transport; cancellation via a flag between operations, clean shutdown, orphan-worker registry
├── sftp_tab.py              # SftpTab: "Files" tab — current-directory listing + ".." navigation, upload/download of selected items, "Cancel" button; GUI never blocks (all SFTP in the worker thread)
├── terminal_widget.py       # TerminalWidget — cell-based QWidget+QPainter canvas: runs, format cache, block cursor (+cursor.hidden), wide glyphs; full keyboard (F1–F12/PgUp/PgDn/Home/End/Delete, Ctrl+C/D/Z, bracketed paste, AltGr guard) + mouse selection (selection_cells, (row,col) coordinates) and copy; scrollback via wheel/Ctrl+Shift+PgUp/PgDn (bare PgUp/PgDn go to the shell) + QTimer cursor blink
├── terminal_screen.py       # TerminalScreen: pyte.HistoryScreen(120x32)+ByteStream, feed under a threading.Lock; PALETTES+resolve_color, snapshot(); scrollback scroll_up/scroll_down/at_bottom (auto-return to live is built into pyte); render() — deprecated
├── window_geometry.py       # Window size save/restore — saveGeometry()/saveState() → base64 → config.json (ui_window_geometry_main/terminal); never raises
├── host_key_policy.py       # SshKnownHostsPolicy: ~/.sshmap/known_hosts; changed key → BadHostKeyException (MITM)
├── external_terminal.py     # OS system terminal; settings in ~/.sshmap/config.json (migrated from legacy ~/.sshmap_settings.json); password never in argv
├── undo_commands.py         # 13 QUndoCommands: MoveNode(merge), MoveNodes(group drag),
│                            #   MoveGroup, ResizeGroup, EditGroupName, AddRemoveNode(+arrows),
│                            #   AddRemoveNodeBatch(TXT import — one undo), AddRemoveConnection,
│                            #   ConnectSelected, AddRemoveNote, EditTextNote(600 ms debounce),
│                            #   EditConnection, EditNodeData
└── logger.py                # setup_logging()/get_logger(__name__)
storage/project.py           # save_project/load_project + serialize_scene()/write_project_json() — JSON version (VERSION_FORMAT from version.py; + "background" key)
storage/autosave.py          # Autosave ~/.sshmap/autosave/<key>.json + ring buffer of backups ~/.sshmap/backups/<key>_NNN.json (no Qt, atomic writes)
storage/export_drawio.py     # Map export to .drawio (mxGraph XML, ElementTree, no new dependencies)
services/
├── credential_manager.py    # keyring abstraction (get_credential_manager() singleton): only the verified backend (Windows — wincred, otherwise refuse to write)
├── diagnostics.py           # PingThread + ReverseDnsThread — ping and reverse DNS off the GUI thread (moved from ui/main_window.py)
├── host_importer.py         # Bulk server import from TXT: parse_hosts_file, is_ip_address, resolve_host
├── status_checker.py        # StatusChecker: QTimer schedules rounds, probes run in parallel on _ProbeThread (ThreadPoolExecutor); probe_ssh() → online/warn/offline
└── system_info_collector.py # SystemInfoCollector: auto-collection of OS/CPU/RAM/disk from a Linux server in one exec_command session
version.py                   # Single version point: APP_VERSION="1.2.2", VERSION_FORMAT="0.9"
dialogs/                     # AddServerDialog (+ "Quick Launch…" button), SSHConnectDialog (+ external terminal button),
                             #   ConnectionDialog/EditConnectionDialog, ProfileManagerDialog,
                             #   BackupsDialog (backups + autosave, restore), QuickLaunchDialog (Quick Launch)
ui/main_window.py            # MainWindow: façade: class MainWindow(ProjectIOMixin, NodeOpsMixin, SshMixin, QMainWindow);
                             #   UI wiring __init__/toolbar/menus/closeEvent + thread shutdown (including terminal sessions), undo_stack (QUndoStack), dirty via canUndo()+baseline;
                             #   notes, groups, background, PNG/JPEG/PDF/drawio export, "Collect information", map search Ctrl+F, tag filter;
                             #   _qaction_guard — guard for QActions with an attached QMenu; public API unchanged (method names/call sites untouched)
ui/main_window_project_io.py # ProjectIOMixin: project new/open/load/save/autosave/backups/restore; owns _project_file/_dirty/_autosave_timer
ui/main_window_node_ops.py   # NodeOpsMixin: node/connection operations + TXT import; _is_scene_point (bool guard)
ui/main_window_ssh.py        # SshMixin: SSH dialog, terminal windows, info auto-collection, quick launch; owns _terminal_windows/_terminals_dock/_ssh_connected_nodes/_info_collectors;
                             #   the _terminal_windows registry stores SESSIONS (TerminalSessionPage) — the node's green dot and the "4 terminals" limit are counted per session;
                             #   reconnecting to a node reuses its live window — new session = new tab (window.add_session());
                             #   "tabs" mode (terminal_mode) — sessions as tabs in the "Terminals" dock (_ensure_terminals_dock, lazy creation);
                             #   applied without restart: new sessions go to the selected mode, open windows/dock stay as they are
ui/mixin_support.py          # host_attr(self, name) — access to façade module globals at call time (mixins do not import main_window — no cycle; test seam for substituting MW.<name>)
ui/sidebar.py                # SidebarPanel(QWidget) — buttons, header, search, tag filter, tree with status markers,
                             #   row context menu; i18n via callback + retranslate
ui/map_search_bar.py         # MapSearchBar — floating search bar over the canvas (Enter/Shift+Enter/Esc, k/N counter)
ui/command_palette.py        # CommandPalette: Ctrl+K, fuzzy search over menu actions and servers
i18n/                        # t(key,**kwargs); en.json/ru.json/zh.json — 404 keys, identical sets; en is the default for new users
tests/                       # Topical suite without pytest: 48 × test_*.py + _common.py (harness), run_all.py (parallel runner, 4 workers), check_i18n_keys.py; map — tests/INDEX.md
```

---

## 3. Project Format (JSON `.json` / `.sshmap`)

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

Format invariants:
- `password` is **never** serialized — keyring only (`server_data_to_dict()` excludes it).
- Connection types: `ssh|vpn|http|database|nfs|kubernetes`; unknown/missing type → `ssh`. The `version` field is not validated on load (files 0.6+ are readable).
- Group membership is **not stored** — computed from geometry (card center inside the topmost group, exclusive).
- `tags` — an array of strings in the server record; missing or non-array in old JSON → empty list (`server_data_from_dict` normalizes it).
- `quick_launch` — an array of Quick Launch items `{"type": "url"|"command", "name", "value"}`; missing in old JSON → empty list, broken records are dropped (`sanitize_quick_launch`). URLs open in the default browser, commands become the first command in the SSH terminal.
- `background` stores a **path** to the image (the file is NOT embedded in the JSON); a missing file on load is ignored with a warning. Background geometry is not part of undo.

---

## 4. Key Behaviors (important for code changes)

### Statuses
`probe_ssh(host, port)`: TCP open + SSH banner → `online`; port open without a banner → `warn`; otherwise → `offline`. Probes run only on `_ProbeThread` (never the GUI thread); within a round — **in parallel** (`ThreadPoolExecutor`, cap `status_max_parallel`, default 16): worst-case round time is `ceil(N/max_parallel) × timeout` instead of `N × timeout`; results arrive as they complete; cancellation (stop/shutdown) prevents probes that have not started yet from producing results. Soft auto-interval: N > 50 nodes → the round interval doubles (`effective_interval_ms()`) + a one-time hint in the status bar; there is no hard limit on server count. `start_status_checks()` is called once from main.py after `show()`.

### Terminal
- Architecture: session = `TerminalSessionPage` (modules/terminal_page.py) — a reusable widget (thread + pyte screen + canvas + status line + SFTP tab); ALL cleanup logic lives on the page side: every teardown path (tab/window close, session error, MainWindow shutdown, limit reached) goes through the single idempotent `page.shutdown()`; the "ask" gate is `page.confirm_close()`.
- Sessions as tabs in one window: `SSHTerminalWindow` (WA_DeleteOnClose, title, geometry) holds a QTabWidget of pages (`session_tabs`, closable tabs, tab title = node alias); re-"connecting to a node" reuses that node's live window — new session = new tab (`window.add_session()`, status message `terminal.session_new_tab`), a different node opens a new window. Closing a tab (the X / `close_page`) is cleanup of the LOCAL page only: neighboring tabs are unaffected; closing the LAST tab closes the window (`WA_DeleteOnClose`). The "status bar → window status bar" bridge bridges ONLY the active tab (re-bridged on switch). Window compat attributes are live references to the ACTIVE tab (`win.page` = current one).
- Second display mode `terminal_mode`: `"windows"` (default, behavior above) | `"tabs"` — sessions as tabs in a detachable QDockWidget "Terminals" on the map (`modules/terminal_dock.py`; the map remains the central widget). From one mechanism come both "tabs" and "windows": the dock detaches into a separate window (float) and returns. Cleanup is per-page (closing a tab = session cleanup; the last tab hides the dock, does not destroy it); green dot/limit — per SESSION regardless of container. Applied without restart: new sessions go to the selected mode, open windows/dock stay as they are; UI — "Terminal" tab of the settings dialog. The external terminal is unchanged (always a separate OS process).
- Pipeline: raw SSH bytes → `TerminalScreen.feed()` (pyte.HistoryScreen, under lock) → cell-based canvas `TerminalWidget` (QWidget+QPainter: runs, color engine `resolve_color`, blinking block cursor).
- Dirty rendering without a timer: `_on_output` → `widget.update()` directly (the queued signal is already on the GUI thread).
- PTY resize — only on an actual grid change + ~150 ms debounce before `channel.resize_pty` (initial `invoke_shell` 120×32; recomputed on canvas resize via the page's eventFilter, previously the window's resizeEvent).
- Scrollback — stock `pyte.HistoryScreen`: mouse wheel and Ctrl+Shift+PageUp/PageDown, auto-return to the live line on new output; **bare PageUp/PageDown remain forwarded to the shell** (`\x1b[5~`/`\x1b[6~` — paging in less/man).
- Keyboard — full table: F1–F12, Delete/PageUp/PageDown (always CSI ~), arrows and Home/End per DECCKM state: TUIs send smkx `\x1b[?1h` and wait for SS3 — `_cursor_key_seq()` sends `\x1bOA/B/C/D`, `\x1bOH/\x1bOF`; normal mode — CSI; state is `tscreen.application_cursor_keys()`, in pyte 0.8.2 DECCKM = 32 in `screen.mode`. Explicit Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C with a selection copies to the clipboard), bracketed paste Ctrl+V (single block), AltGr guard (Ctrl+Alt is not sent as control codes).
- Mouse selection — coordinates are always `(row, col)` (`selection_cells()`), multi-line text copy.
- The window closes with the standard X button (there is no separate "Close terminal" button); known hosts are pinned in `~/.sshmap/known_hosts`.
- Settings — optional `terminal_*` keys in `~/.sshmap/config.json`; full list and defaults below, in "Settings".

### Settings
- Dialog (hub, `ui/settings_dialog.py`) — QTabWidget "General / Terminal / Statuses / Autosave / Map / Language"; entry points: the "Settings" menu between "View" and "Help" + a ⚙ button at the bottom of the sidebar (vector gear from `ui/icons.py`); the Ctrl+K command palette picks up the item automatically.
- Storage — a SINGLE `~/.sshmap/config.json` (`i18n.save_config`, atomic merge write): all keys are optional, defaults = behavior. Statuses and autosave apply live; terminal and external terminal read the config on next window creation/launch.
- Keys:
  - `external_terminal` (moved from a separate `~/.sshmap_settings.json`, with migration on read — the old file is deleted);
  - `terminal_palette` (`default|nord|dracula|tokyo_night`, unknown → default), `terminal_font` (family, empty → system monospace; live for open windows), `terminal_font_size` (pt 6–72, otherwise 10), `terminal_history_lines` (HistoryScreen scrollback depth; default 1000 — enabled, explicit 0 — disabled), `terminal_close_behavior` (`"close"` by default | `"ask"` — confirm closing the active session in `page.confirm_close()`; an already-finished session closes without a dialog), `terminal_max_open` (limit on own terminals, default 4 — when reached, not a refusal but a suggestion to close the oldest session / cancel; the limit counts SESSIONS in the registry, not windows; per session across ALL windows — tabs of one window are counted separately), `terminal_mode` (`"windows"` by default | `"tabs"` — sessions as tabs in the "Terminals" dock on the map; broken value/wrong type → default; applied without restart — to new sessions), `terminal_wheel` (`"scrollback"` by default | `"off"` — the wheel is not intercepted for scrollback; config-only key, no UI);
  - `status_interval_sec`/`status_probe_timeout_sec`/`status_max_parallel` (defaults 30 s / 3.0 s / 16 parallel probes; live via `StatusChecker.set_interval/set_probe_timeout/set_max_parallel`);
  - `autosave_enabled/autosave_interval_sec/backup_count` (live — the autosave QTimer);
  - `language` (applied immediately, before OK);
  - `ui_font_family/ui_font_size` (UI font, live via `QApplication.setFont`, 0 = system), `ui_node_double_click` (`"properties"` by default | `"connect"` — double-clicking a node opens SSHConnectDialog directly), `ui_show_sidebar_buttons` (the sidebar button block; the whole sidebar is hidden via the "View → Sidebar" menu item), `ui_show_connection_type` (type on the connection badge: "SSH · <label>", handy for PNG/PDF export) + 20-character limit on the connection label (input only — old projects with long labels load unchanged).

### Undo/Redo
- Any scene change goes through `MainWindow._push_command(cmd)`; the scene is modified **only** inside a command's `redo()/undo()` — `QUndoStack.push()` calls redo itself.
- Dirty marker: `self._dirty = undo_stack.canUndo() or self._undo_baseline_dirty`; `_do_save()` calls `_reset_undo_stack()` (new baseline). `_undo_baseline_dirty` covers non-undo dirty causes (statuses, background).
- NOT in undo: node statuses, coordinates on load, background geometry. Groups (move/resize/rename) — ARE included (CmdMoveGroup/CmdResizeGroup/CmdEditGroupName).
- Node drag: MapView catches the release and emits `node_drag_committed(node, old, new)` → CmdMoveNode.
- Group drag: if an already-selected node is dragged and >1 are selected — ALL selected move; one CmdMoveNodes command per gesture.

### Hotkeys + Command Palette
- Hotkeys: Ctrl+N/O/S — project; Ctrl+Z/Y(+Shift) — undo/redo; Ctrl+Shift+A/G/C — server/group/connection; Ctrl+I — properties; **Ctrl+Enter** — SSH to the selected node; **Ctrl+E** — edit node; **Ctrl+D** — duplicate node; **Ctrl+Shift+N** — note in the center of the visible area; Delete — delete selection; Ctrl+Shift+F — fit map; **Ctrl+F** — map search (search bar over the canvas, Enter/Shift+Enter — jump between matches with centering and an accent frame, Esc — close).
- Multi-selection: Ctrl+click on a node adds to the selection (native Qt), **Ctrl+drag on empty space** — rubber-band selection (Shift+Ctrl adds to current); group drag moves all selected; right-click during multi-selection → "Connect selected" / "Delete selected" (one confirmation, guarded per item).
- **Ctrl+K** — command palette (`ui/command_palette.py`): fuzzy search (subsequence scoring, no dependencies) over all menu QActions + project servers; selecting a server → select node + centerOn. Enter/Up/Down/Esc.

### Security
Passwords: keyring only (profiles `"profile:{id}"`, servers by server_id). If the keyring is unavailable, the app works but passwords do not survive a restart. External terminal: the password is entered by the OS ssh client, never in argv.

**Limitations:**
- **TOFU on first connect:** a host key that is not in `~/.sshmap/known_hosts` is accepted automatically (the fingerprint is shown in the log). This is standard paramiko-client behavior, but it is **not** full MITM protection on the very first connection: protection kicks in on a *change* of an already-recorded key. For critical hosts, verify the first-connect fingerprint over a trusted channel.
- **Windows / keyring:** only the Windows Credential Manager system backend (`keyrings.win.*`, i.e., requires pywin32 — uncomment it in requirements.txt) is accepted. Plaintext file fallback backends (`keyrings.alt.file`) are rejected: passwords would not be saved rather than leak into a plaintext file. On Linux/macOS, `keyrings.alt.*` backends are rejected. If no secure backend is available — the app works, but passwords are not saved between runs.

---

## 5. PySide6 / Qt 6.11 Gotchas (required knowledge)

| Issue | Solution |
|---|---|
| Mouse input in QGraphicsView tests | Only `PySide6.QtTest.QTest.mousePress/Move/Release/DClick` — hand-crafted QMouseEvents are ignored by the core |
| Monkey-patching C++ slots with return values (`itemChange`, `eventFilter`) | FORBIDDEN: infinite recursion or Access Violation 0xC0000005. Only subclass overrides |
| `QPropertyAnimation(target=QGraphicsItem)` | Does not work ("non-existing property opacity") → use QVariantAnimation |
| `QGraphicsItemGroup.boundingRect()` | Not recomputed from children (zero rect) → explicit override (see ServerNode) |
| `itemChange(ItemPositionChange)` | Called BEFORE the position is applied → pass target rects explicitly (the resync_group_members pattern) |
| QGraphicsProxyWidget "eats" the mouse | StickyNote/NodeGroup dragging is handled manually; MapView temporarily switches dragMode to NoDrag |
| strokeToFill/strokedPath QPainterPath | Not bound in PySide6 → arrow hit zone via a custom contains() with curve sampling |
| QWidget focusIn/focusOut signals | Do not exist in Qt6 → eventFilter |
| Death of the Python QAction wrapper with an attached QMenu | PySide6 6.11 destroys the C++ QMenu along with it (verified offscreen AND native): temporary wrappers from `menubar.actions()`/`act.menu()` were killing ALL menus except the last one — when opening the Ctrl+K palette and switching language. Cure: keep such QActions permanently (`MainWindow._qaction_guard`) + do not go through `action.menu()` where a direct path exists (the `_menu_i18n` registry) |

---

## 6. i18n

```python
from i18n import t, set_language, get_available_languages
t("btn.add_server", alias="web-1")   # {alias} formatting
```
en (default) / ru / zh. Rule: a new key is added to all 3 files at once; check — `python tests/check_i18n_keys.py`. Modules on the hot path (ssh_worker, ssh_terminal) use a cached `get_translator()`.

---

## 7. State & Roadmap

**Implemented features** (details in sections 3–4):
- interactive map: nodes, Bezier connections of 6 types, notes, groups, background image with drag/resize
- node statuses online/warn/offline: parallel probes, auto-interval for large maps
- built-in SSH terminal on pyte (scrollback, mouse selection, full keyboard) + external system terminal — details in §4 "Terminal"
- SFTP tab in the terminal window: files over the same SSH connection — listing/".." navigation, upload/download with progress in the status bar and cancel
- multiple SSH sessions as tabs in one terminal window (reconnect = new tab, title = alias; closing a tab does not affect its neighbors; the last tab closes the window) + `terminal_mode`: separate windows (default) or a detachable "Terminals" dock on the map; switching without restart — details in §4 "Terminal"
- undo/redo of scene operations
- automatic info collection for Linux servers (OS/CPU/RAM/disk)
- profiles and passwords in the OS keyring — password is never written to JSON
- i18n: en (default) / ru / zh
- context menus for all objects, fit/zoom/centering
- multi-selection: Ctrl+click, rubber band, group drag, "connect/delete selected"
- tags: color strip on the card + tag filter in the sidebar with dimming of non-matching nodes
- map search (Ctrl+F): match highlighting, Enter/Shift+Enter navigation, dimming of non-matches
- quick launch on a server: list of URLs/commands (URL — browser, command — first terminal command)
- settings dialog (hub): single `~/.sshmap/config.json`, live application without restart
- autosave + ring buffer of backups with rollback ("File → Backups…")
- export to PNG/JPEG/PDF and draw.io `.drawio`; bulk server import from TXT
- hotkeys and command palette (Ctrl+K)

**Known limitations:**
- undo does not cover node statuses and background geometry — details in "Undo/Redo";
- the background image is stored in JSON by path: when moving a project to another machine, move the file together with the map;
- TOFU on first connect (a new host key is accepted automatically) and keyring limitations — details in "Security".

**Roadmap** (tasks, order, acceptance — in ROADMAP.md):
- **v1.2.x series** (the "window → page" refactor `TerminalSessionPage` — v1.2, sessions as tabs in a window — v1.2.1, terminals dock of the map window — v1.2.2): multi-typing; note pinning to servers; central theme `ui/theme.py` + map animations; terminal selection and context menu; D&D into the SFTP tab; dead code removal + full wcwidth CJK; log highlighting (opt-in).
- **v1.3.x series**: file panel at the bottom of the map window + text viewer; configurable hotkeys; languages without writing code; lightweight plugins.

---

## 8. License & Security

- MIT License (LICENSE).
- Security model: passwords only in the OS keyring (never in project JSON), known_hosts pinning with TOFU on first connect, external terminal without a password in argv — details and limitations: §4 "Security".
