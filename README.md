# SSH Map (NodeVisualSSH)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

Single source of truth for the version — `version.py` (`APP_VERSION`); released versions — `CHANGELOG.md`; planned features — `ROADMAP.md`; full documentation (architecture, project format, Qt gotchas) — `DOCUMENTATION.md`.

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
python tests/run_all.py              # everything (52 test files + i18n check): parallel (4 workers), results table + single exit code (0 ⇔ all green)
python tests/run_all.py --workers 8  # worker count (1 = sequential, as before)
python tests/run_all.py keyring      # filter by substring in file name
python tests/test_tags.py            # a single file (from the project root)
```

Suite map — what each `test_*.py` covers and where it came from, plus harness conventions (HOME isolation, offscreen platform, release pins): `tests/INDEX.md`.

Requirements: Python 3.10+, Windows/Linux/macOS. Logs: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler 5 MB × 3).

---

## 2. Project Structure

Full annotated tree (per file, with version history) — `DOCUMENTATION.md` §2. Compact overview:

```
main.py                      # Entry point: logging → QApplication → MainWindow → status checks
version.py                   # Single source of truth for APP_VERSION / VERSION_FORMAT (JSON format)
pyproject.toml               # Installable identity (entry point sshmap = main:main) — checked by tests/test_pyproject.py
models/                      # server.py — ServerData (password never serialized); profile.py — profiles, passwords in keyring
graphics/                    # MapScene; MapView (zoom 0.1–5.0, panning, multi-selection); ServerNode (status card);
                             # ConnectionArrow (cubic Bezier, 6 types); StickyNote (pinning to a node); NodeGroup; BackgroundImage
modules/                     # ssh_worker.py — one-shot SSH worker + registry; ssh_terminal.py — terminal thread + tabbed window;
                             # terminal_page.py — session as a reusable widget (single idempotent shutdown()); terminal_dock.py — "tabs" mode dock;
                             # multi_input.py — multi-input broadcast hub; sftp_worker.py / sftp_tab.py — SFTP over the live transport;
                             # terminal_widget.py — cell-based canvas (full keyboard, selection, scrollback); terminal_screen.py — pyte screen + palettes;
                             # window_geometry.py; host_key_policy.py; external_terminal.py; undo_commands.py (14 QUndoCommands); logger.py
storage/                     # project.py — JSON save/load; autosave.py — autosave + backup ring buffer; export_drawio.py — .drawio export
services/                    # credential_manager.py (keyring); diagnostics.py (ping / reverse DNS off the GUI thread); host_importer.py (TXT import);
                             # status_checker.py (parallel SSH probes); system_info_collector.py (OS/CPU/RAM/disk)
dialogs/                     # AddServer, SSHConnect (+ external terminal), Connection/EditConnection, ProfileManager, Backups, QuickLaunch
ui/                          # main_window.py — façade over ProjectIOMixin / NodeOpsMixin / SshMixin; sidebar.py; map_search_bar.py (Ctrl+F);
                             # command_palette.py (Ctrl+K); icons.py; mixin_support.py
i18n/                        # t(key, **kwargs); en/ru/zh JSON with identical key sets (parity pinned in tests); en is the default for new users
tests/                       # 52 × test_*.py without pytest + _common.py harness + run_all.py (parallel runner) + check_i18n_keys.py — map: tests/INDEX.md
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
  "notes":  [{"id": "...", "text": "", "x": 0.0, "y": 0.0, "width": 240.0, "height": 160.0, "server_id": "..."}],
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
- `server_id` — an **optional** note field (pattern of `"groups"`/`"background"`): written only when set; absent = free note (old files without the key load as-is). Broken reference (missing node / not a string) → log warning + the note stays free at its saved position; on load an attached note's position is recomputed from the node's CURRENT geometry. `VERSION_FORMAT` stays `"0.9"`.
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
- Multi-input: typing in the focused session is broadcast to ALL other open sessions — every user input passes one point (`TerminalWidget.keyPressEvent()` → `_send(bytes)` → `terminal_thread.send_data()`), and the hub (`modules/multi_input.py`, process singleton) hangs on exactly that point: when the mode is on, `_send` duplicates the same bytes into `send_data()` of every other live session from the registry. No echo by definition — bytes come from the keyboard of the focused widget, never from output; the source session is skipped by the broadcast (it already got them via its own `send_data`). Ctrl+V (bracketed paste) goes through the same point and is duplicated too. Toggle: checkable "View" menu item + **F12 = EXIT** (NOT Esc — Esc goes to the shell as `\x1b`!); while the mode is on the RC2 F12→`\x1b[24~` mapping is suspended (the key never reaches the shell), when off it works as before. UI: status-bar plaque "MULTI: N sessions" with an exit button, "MULTI · <alias>" tab badges + amber frame on every open container (window and dock) + window title prefix; a session that dies mid-typing (error → close) leaves the registry through the stock path (`destroyed` → `_forget_terminal_window`) and dead threads are additionally filtered by liveness, so the broadcast keeps working for the rest.
- Settings — optional `terminal_*` keys in `~/.sshmap/config.json`; full list and defaults below, in "Settings".

### Settings
- Dialog (hub, `ui/settings_dialog.py`) — QTabWidget "General / Terminal / Statuses / Autosave / Map / Language"; entry points: the "Settings" menu between "View" and "Help" + a button at the bottom of the sidebar (vector gear from `ui/icons.py`); the Ctrl+K command palette picks up the item automatically.
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
- Note pinning: `CmdAttachNote` — attaching/detaching a note to/from a node is undoable; undo of attach restores the note's pre-attach position; when deleting a node that has attached notes, the detach commands are pushed **before** the removal command (LIFO: undo first restores the node, then re-attaches the notes).

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
- multiple SSH sessions as tabs in one terminal window (reconnect = new tab) + `terminal_mode`: separate windows (default) or a detachable "Terminals" dock on the map, switching without restart — details in §4 "Terminal"
- multi-input: typing of the focused session is broadcast to all other open sessions; F12 exits the mode — details in §4 "Terminal"
- note pinning: a note can be pinned to a server and follows it on any movement (dashed anchor line); undoable, survives save/load via the optional `server_id` field — details in §3 and §4 "Undo/Redo"
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
- **v1.2.x series** (the "window → page" refactor `TerminalSessionPage` — v1.2, sessions as tabs in a window — v1.2.1, terminals dock of the map window — v1.2.2, multi-input broadcast — v1.2.3, note pinning to servers — v1.2.4): central theme `ui/theme.py` + map animations; terminal selection and context menu; D&D into the SFTP tab; dead code removal + full wcwidth CJK; log highlighting (opt-in).
- **v1.3.x series**: terminal command library (macros) — one click sends a saved command/script to the active terminal; text viewer in the SFTP tab; configurable hotkeys; languages without writing code; lightweight plugins.

---

## 8. License & Security

- MIT License (LICENSE).
- Security model and its limitations: see §4 "Security".
