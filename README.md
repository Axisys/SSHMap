# SSH Map (NodeVisualSSH)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

Single source of truth for the version — `version.py` (`APP_VERSION`); released versions — `CHANGELOG.md`; planned features — `ROADMAP.md`; full documentation (architecture, project format, Qt gotchas) — `DOCUMENTATION.md`; **for AI agents** — `AGENTS.md` (condensed, agent-oriented onboarding: run/test, architecture invariants, Qt gotchas, release conventions).

---

## 1. Running & Tests

```bash
pip install -r requirements.txt   # dependencies (PySide6, paramiko, keyring, wcwidth; pyte vendored in third_party/pyte)
python main.py                    # run the GUI
pipx install .                    # or pip install . → sshmap command (installable identity, pyproject.toml)
```

Tests — plain Python scripts without pytest: topical `test_*.py` files + a single parallel runner; each file is an isolated process (sandbox HOME, offscreen Qt, UTF-8 stdout — nothing extra needed on cp1251 consoles or in CI):

```bash
python tests/run_all.py               # everything (72 test files + i18n check); auto workers = cores (cap 8, --workers N); exit 0 ⇔ all green
python tests/run_all.py --fast        # daily profile: skips files tagged slow/network
python tests/run_all.py --tag network # only network-tagged files — real-network sections run ONLY on explicit opt-in (env SSHMAP_TEST_TAGS)
python tests/run_all.py --failed-only # re-run only files that failed in the last run (cache test-results/last_run.json)
python tests/run_all.py --junit       # JUnit XML report → test-results/junit.xml (artifacts dir is gitignored)
python tests/test_tags.py             # a single file (from the project root)
```

- All runs are hermetic by default: `network`-tagged files execute their real-network section only under explicit `--tag network`; `slow` = intentional spec wait budgets.
- Suite map, tags and harness conventions — `tests/INDEX.md`; its "Files" table is auto-generated from module docstrings (`python tests/_gen_index.py`, freshness check `--check`). Shared fakes — `tests/_fakes.py`.

Requirements: Python 3.10+, Windows/Linux/macOS. Logs: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler 5 MB × 3).

---

## 2. Project Structure

Full annotated tree (per file, with version history) — `DOCUMENTATION.md` §2. Compact overview:

```
main.py                      # Entry point: logging → QApplication → MainWindow → status checks
version.py                   # APP_VERSION / VERSION_FORMAT (JSON format)
pyproject.toml               # Installable identity (entry point sshmap = main:main) — checked by tests/test_pyproject.py
models/                      # server.py — ServerData (password never serialized); profile.py — profiles, passwords in keyring
graphics/                    # MapScene; MapView (zoom 0.1–5.0, panning, multi-selection); ServerNode (status card);
                             # ConnectionArrow (cubic Bezier, 6 types, optional bidirectional heads); StickyNote (pinning to a node); NodeGroup; BackgroundImage
modules/                     # ssh_worker.py — one-shot SSH worker + registry; ssh_terminal.py — terminal thread + tabbed window;
                             # terminal_page.py — session as a reusable widget (single idempotent shutdown()); terminal_dock.py — "tabs" mode dock;
                             # command_library.py — terminal macros: user command/script library panel (~/.sshmap/commands.json);
                             # multi_input.py — multi-input broadcast hub; sftp_worker.py / sftp_tab.py — SFTP over the live transport (listing, upload/download, read-only preview with "no preview" row marks);
                             # terminal_widget.py — cell-based canvas (full keyboard, selection, scrollback); terminal_screen.py — pyte screen + palettes;
                             # window_geometry.py; host_key_policy.py; external_terminal.py; undo_commands.py (14 QUndoCommands); logger.py
storage/                     # project.py — JSON save/load; autosave.py — autosave + backup ring buffer; export_drawio.py — .drawio export
services/                    # credential_manager.py (keyring); diagnostics.py (ping / reverse DNS off the GUI thread); host_importer.py (TXT import);
                             # status_checker.py (parallel SSH probes); system_info_collector.py (OS/CPU/RAM/disk)
dialogs/                     # AddServer, SSHConnect (+ external terminal), Connection/EditConnection, ProfileManager, Backups, QuickLaunch
ui/                          # main_window.py — façade over ProjectIOMixin / NodeOpsMixin / SshMixin; sidebar.py; map_search_bar.py (Ctrl+F);
                             # command_palette.py (Ctrl+K); hotkey_registry.py (configurable hotkeys); icons.py; mixin_support.py;
                             # theme.py (central UI palette, radii, fonts)
i18n/                        # t(key, **kwargs); every *.json is a language (file name = code, root "name" = display name);
                             # en/ru/zh/de with identical translation key sets (parity pinned in tests); en is the default for new users
tests/                       # test_*.py without pytest + _common.py harness + run_all.py (parallel runner) + check_i18n_keys.py — map: tests/INDEX.md
third_party/                 # pyte 0.8.2 managed fork (vendored): PyPI sdist + patches 0001–0003; provenance/sha256 — third_party/pyte-patches/MANIFEST.md
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
  "connections": [{"source_id": "...", "target_id": "...", "label": "", "type": "ssh", "bidirectional": true}],
  "notes":  [{"id": "...", "text": "", "x": 0.0, "y": 0.0, "width": 240.0, "height": 160.0, "server_id": "..."}],
  "groups": [{"id": "...", "name": "", "x": 0.0, "y": 0.0, "width": 480.0, "height": 320.0}],
  "background": {"path": "/path/to/background.png", "x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0},
  "zoom": 1.0, "center_x": 0.0, "center_y": 0.0
}
```

Format invariants:
- `password` is **never** serialized — keyring only (`server_data_to_dict()` excludes it).
- Connection types: `ssh|vpn|http|database|nfs|kubernetes`; unknown/missing type → `ssh`. The `version` field is not validated on load (files 0.6+ are readable).
- `bidirectional` — an **optional** connection field: written only when true; absent = one-way arrow (old files without the key load as-is). A bidirectional arrow draws heads on BOTH ends of the curve (two-way data exchange).
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
- **Architecture** — session = `TerminalSessionPage` (modules/terminal_page.py): thread + pyte screen + canvas + status line + SFTP tab; ALL cleanup logic lives on the page side — every teardown path (tab/window close, session error, MainWindow shutdown, limit reached) goes through the single idempotent `page.shutdown()`, and the "ask" gate is `page.confirm_close()`.
- **Language** — the containers follow a language switch live: the window/dock titles, the tab titles and tooltips, the SFTP buttons and column headers, the command-library panel and its row tooltips are re-texted by a `retranslate()` on every container (MainWindow walks the session registry, exactly like it already did for the terminal font) — no restart.
- **Containers** — `SSHTerminalWindow` (WA_DeleteOnClose) holds a QTabWidget of pages: re-connecting to the same node reuses its live window — new session = new tab (`window.add_session()`), a different node opens a new window; closing a tab cleans up only that page, the last tab closes the window. The status-bar bridge and `win.page` follow the ACTIVE tab (re-bridged on switch). The window itself closes with the standard X button — there is no separate "Close terminal" button.
- **Display mode** — `terminal_mode`: `"windows"` (default) | `"tabs"` — sessions as tabs in a detachable QDockWidget "Terminals" on the map (`modules/terminal_dock.py`; the map remains the central widget): the dock detaches into a window and returns; cleanup is per-page (the last tab hides the dock, does not destroy it); applied without restart — new sessions go to the selected mode, open windows/dock stay as they are. The external terminal is unchanged (always a separate OS process).
- **Pipeline** — raw SSH bytes → `TerminalScreen.feed()` (pyte.HistoryScreen, under lock) → cell-based canvas `TerminalWidget` (QWidget+QPainter: runs, color engine `resolve_color`, blinking block cursor); dirty rendering without a timer (`_on_output` → `widget.update()`, already on the GUI thread).
- **Emulation** — screen is `SshmapHistoryScreen` (subclass of `pyte.HistoryScreen`): bare LF acts as CR+LF (LNM, xterm behavior), private SGR (`CSI ? … m`, sent by Vim 9+) ignored; alternate screen modes 47/1047/1048/1049 implemented — after vim/htop/mc/less the previous screen is restored character-for-character (colors included), TUI lines never enter the scrollback, and wheel/PgUp-PgDn do not scroll history while a TUI owns the grid.
- **Scrollback** — `pyte.HistoryScreen`: mouse wheel + Ctrl+Shift+PageUp/PageDown; auto-return to the live line on new output is batched (one bulk shift in `SshmapHistoryScreen.before_event` instead of ~250 page-by-page calls); **bare PageUp/PageDown remain forwarded to the shell** (`\x1b[5~`/`\x1b[6~` — paging in less/man).
- **PTY resize** — only on an actual grid change + ~150 ms debounce before `channel.resize_pty` (initial 120×32; recomputed on canvas resize via the page's eventFilter).
- **Wheel in TUI** — when a TUI enables mouse tracking (DECSET 1000/1002/1003), the wheel goes to the PTY as an xterm report (SGR `\x1b[<64|65;{col};{row}M` or X10; coordinates clamped to the grid and the protocol limit) via `terminal_thread.send_data()` — NOT through `_send()`, so multi-input never broadcasts session-local coordinates; takes precedence over `terminal_wheel="off"`.
- **pyte fork** — managed fork: `third_party/pyte` = PyPI sdist pyte 0.8.2 + 3 explicit patches (`third_party/pyte-patches/`: private SGR, LNM default, alternate screen; provenance/sha256 — MANIFEST.md); the import seam is one line in `modules/terminal_screen.py`, the subclass adds only the batched auto-return; behavioral change: none. Deep dive: PYTE82_AUDIT.md.
- **Keyboard** — F1–F12, Delete/PageUp/PageDown (always CSI ~); arrows and Home/End follow DECCKM: SS3 (`\x1bO…`) while a TUI owns the grid, CSI otherwise; explicit Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C with a selection copies to the clipboard), bracketed paste Ctrl+V (single block), AltGr guard (Ctrl+Alt is not sent as control codes).
- **Mouse** — selection coordinates are always `(row, col)` (`selection_cells()`); **double-click selects a word, triple-click the whole line** (word = maximal run of non-space cells, CJK wide-glyph placeholders belong to the word); drag after double/triple-click extends from the far end.
- **Context menu** (right click) — Copy (enabled only with a selection), Paste into the PTY (same bracketed-paste path as Ctrl+V), Select All; labels in en/ru/zh (`terminal.menu.*`).
- **Multi-input** — typing in the focused session is broadcast to ALL other open sessions: every user input passes one point (`TerminalWidget.keyPressEvent()` → `_send(bytes)` → `terminal_thread.send_data()`) and the hub (`modules/multi_input.py`, process singleton) duplicates those bytes into every other live session; no echo by definition (bytes come from the keyboard of the focused widget, never from output), Ctrl+V paste included. Toggle: checkable "View" menu item + **F12 = EXIT** (NOT Esc — Esc goes to the shell as `\x1b`); UI: status-bar plaque "MULTI: N sessions" with an exit button, "MULTI · <alias>" tab badges + amber frame on every open container. A session that dies mid-typing leaves the registry through the stock teardown path, so the broadcast keeps working for the rest.
- **Command library (macros)** — user library of commands/scripts in a collapsible panel of the terminal itself (`modules/command_library.py`, both containers: window and "Terminals" dock): search + category→command tree + add/edit/delete; double-click or Enter sends the entry to the ACTIVE session only — single-line macros go raw with a trailing `\n`, multi-line ones as a bracketed-paste block, directly via `terminal_thread.send_data()` (NOT through the multi-input broadcast); storage — `~/.sshmap/commands.json` (5 seed examples on first run, never re-seeded), panel collapse state — `ui_cmdlib_collapsed`.
- Settings — optional `terminal_*` keys in `~/.sshmap/config.json`; full list and defaults below, in "Settings".

### Settings
- Dialog (hub, `ui/settings_dialog.py`) — QTabWidget "General / Terminal / Statuses / Autosave / Map / Hotkeys / Language"; entry points: the "Settings" menu between "View" and "Help" + a button at the bottom of the sidebar (vector gear from `ui/icons.py`); the Ctrl+K command palette picks up the item automatically.
- Storage — a SINGLE `~/.sshmap/config.json` (`i18n.save_config`, atomic merge write): all keys are optional, defaults = behavior. Statuses, autosave, the UI options and the hotkeys apply live; terminal and external terminal read the config on next window creation/launch.
- Keys:
  - `external_terminal` (moved from a separate `~/.sshmap_settings.json`, with migration on read — the old file is deleted);
  - `terminal_palette` (`default|nord|dracula|tokyo_night`, unknown → default), `terminal_font` (family; empty → system monospace; live for open windows), `terminal_font_size` (pt 6–72, otherwise 10), `terminal_history_lines` (scrollback depth; default 1000, explicit 0 — disabled), `terminal_close_behavior` (`"close"` | `"ask"` — confirm via `page.confirm_close()`; an already-finished session closes without a dialog), `terminal_max_open` (default 4 — counts SESSIONS in the registry across all containers; when reached — a suggestion to close the oldest, not a refusal), `terminal_mode` (`"windows"` | `"tabs"` — see "Terminal"; broken value → default; applied to new sessions only), `terminal_wheel` (`"scrollback"` | `"off"` — config-only key, no UI);
  - `status_interval_sec`/`status_probe_timeout_sec`/`status_max_parallel` (defaults 30 s / 3.0 s / 16 parallel probes; live via `StatusChecker.set_interval/set_probe_timeout/set_max_parallel`);
  - `autosave_enabled/autosave_interval_sec/backup_count` (live — the autosave QTimer);
  - `language` (applied immediately, before OK);
  - `hotkeys` (a dict action_id → sequence, e.g. `"file.save": "Ctrl+S"`; the whole set is edited in the "Hotkeys" tab from the action registry `ui/hotkey_registry.py` — an empty string disables a hotkey, a missing/broken value falls back to the default; applied live after OK; the terminal's own keys — F1–F12, Ctrl+C/D/Z, arrows — are the xterm protocol and are NOT configurable);
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
- **All of them are configurable** ("Settings → Hotkeys", v1.3.2): one row per action with a key recorder — record your own combination, or clear the field to switch that hotkey off (the action stays in the menu). A duplicate combination marks both rows and warns, but still saves. Stored in `~/.sshmap/config.json` and applied instantly — no restart. Multi-input keeps its own rule: whatever key you pick works only while the mode is on, so it never steals a key from your shell.
- The terminal canvas keeps its own keys (F1–F12, Ctrl+C/D/Z, arrows) — they are the xterm protocol, deliberately not configurable.
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
en (default) / ru / zh / de — plus any language you drop in: every `i18n/*.json` is a language (the file name is the code, the root key `"name"` is the name shown in the menus, a file saved with a BOM loads fine), so adding one takes no code changes and needs no restart — `Help → Language` rescans the folder (and re-reads your file) on every open. Rule: a new key goes into all the files at once and a built-in language must cover 100% of en — in keys, in `{placeholders}` and in line breaks; a deliberately incomplete translation may declare itself with the root key `"partial": true`, which turns its missing keys into a warning instead of a defect. Check — `python tests/check_i18n_keys.py`. Modules on the hot path (ssh_worker, ssh_terminal) use a cached `get_translator()`.

---

## 7. State & Roadmap

**Implemented features** (details in sections 3–4):
- interactive map: nodes, Bezier connections of 6 types (one-way or bidirectional), notes, groups, background image with drag/resize
- node statuses online/warn/offline — parallel SSH probes, auto-interval for large maps
- note pinning: a note pinned to a server follows it on any movement; undoable, survives save/load
- multi-selection: Ctrl+click, rubber band, group drag, "connect/delete selected"
- map search (Ctrl+F): match highlighting, Enter/Shift+Enter navigation, dimming of non-matches
- tags: color strip on the card + sidebar filter with dimming of non-matching nodes
- quick launch per server: URLs (open in the default browser) and commands (first terminal command)
- collapsible sidebar and map panels — at most one at a time, state persists across restarts
- context menus for all objects, fit/zoom/centering
- built-in SSH terminal on pyte (scrollback, full keyboard, mouse selection with word/line clicks, context menu) + external system terminal
- SFTP tab in the terminal window over the same SSH connection — listing/navigation, upload/download incl. drag & drop, read-only text preview (≤ 1 MB) with non-previewable files marked in the tree
- multiple sessions as tabs; separate windows or a detachable "Terminals" dock on the map — switch without restart
- multi-input: typing of the focused session is broadcast to all other open sessions (F12 exits)
- terminal command library (macros): one click sends a saved command/script to the active terminal (single-line raw, multi-line bracketed paste)
- undo/redo of scene operations (incl. groups and note pinning)
- automatic info collection for Linux servers (OS/CPU/RAM/disk)
- profiles and passwords in the OS keyring — never written to JSON
- autosave + ring buffer of backups with rollback ("File → Backups…")
- export to PNG/JPEG/PDF and draw.io `.drawio`; bulk server import from TXT
- i18n: en (default) / ru / zh / de — and any language as one dropped-in JSON file, no code changes; the interface follows a language switch everywhere, terminals and SFTP tabs included; `Help → Language` rescans the folder without a restart
- settings hub — single `~/.sshmap/config.json`, live application without restart
- hotkeys + command palette (Ctrl+K) — every shortcut editable in "Settings → Hotkeys", duplicates flagged, applied without restart

**Known limitations:**
- undo/redo does not cover node statuses or background geometry (§4 "Undo/Redo");
- the background image is stored by path — move the file together with the project;
- TOFU on first connect and keyring backend restrictions (§4 "Security").

**Roadmap** (tasks, order, acceptance — in ROADMAP.md):
- **v1.3.x series**: lightweight plugins (entry points + a local scripts folder); import from `~/.ssh/config`.
- **v1.4**: syntax highlighting in the SFTP viewer (numbers, JSON/XML/YAML) — opens the 1.4 line.

---

## 8. License & Security

- MIT License (LICENSE).
- Security model and its limitations: see §4 "Security".
