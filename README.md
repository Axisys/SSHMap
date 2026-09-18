# SSH Map (Visual Node Map + SSH Terminal and SFTP manager)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

Where to read what:
- the version — `version.py` (`APP_VERSION`); released versions — `CHANGELOG.md` (the closed lines live in the `CHANGELOG_HISTORY_*.md` files)
- planned features — `ROADMAP.md`; full documentation (architecture, project format, Qt gotchas) — `DOCUMENTATION.md`
- the plugin contract (API v1) — `PLUGINS.md`; **for AI agents** — `AGENTS.md`

---

## 1. Running & Tests

```bash
pip install -r requirements.txt   # dependencies (PySide6, paramiko, keyring, wcwidth; pyte vendored in third_party/pyte)
python main.py                    # run the GUI
pipx install .                    # or pip install . → sshmap command (installable identity, pyproject.toml)
```

Tests — plain Python scripts without pytest: topical `test_*.py` files + a single parallel runner; each file is an isolated process (sandbox HOME, offscreen Qt, UTF-8 stdout — nothing extra needed on cp1251 consoles or in CI):

```bash
python tests/run_all.py               # everything (83 test files + i18n check); auto workers = cores (cap 8, --workers N); exit 0 ⇔ all green
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

Full annotated tree (per file, with the role it plays) — `DOCUMENTATION.md` §2 (version history — `CHANGELOG.md`). Compact overview:

```
main.py                      # Entry point: logging → QApplication → MainWindow → status checks
version.py                   # APP_VERSION / VERSION_FORMAT (JSON format)
pyproject.toml               # Installable identity (entry point sshmap = main:main) — checked by tests/test_pyproject.py
models/                      # server.py — ServerData (password never serialized); profile.py — profiles, passwords in keyring
graphics/                    # MapScene; MapView (zoom 0.1–5.0, panning, multi-selection); ServerNode (status card);
                             # ConnectionArrow (cubic Bezier, 6 types, optional bidirectional heads); StickyNote (pinning to a node); NodeGroup; BackgroundImage
modules/                     # ssh_worker.py — one-shot SSH worker + registry; ssh_terminal.py — terminal thread + tabbed window;
                             # plugin_manager.py — plugin discovery (entry points + ~/.sshmap/plugins/*.py), the plugin registry and the
                             # isolation machinery (managed workers, orphan registry, hook budgets); plugin_context.py — the API v1 plugin
                             # context; plugin_runner.py — "run a command on these nodes" over SSH;
                             # terminal_page.py — session as a reusable widget (single idempotent shutdown()); terminal_dock.py — "tabs" mode dock;
                             # command_library.py — terminal macros: user command/script library panel (~/.sshmap/commands.json);
                             # multi_input.py — multi-input broadcast hub; sftp_worker.py / sftp_tab.py — SFTP over the live transport (listing, upload/download, a file manager: new folder/rename/delete, an overwrite prompt, atomic transfers, drag-out of a path, read-only preview with "no preview" row marks);
                             # terminal_widget.py — cell-based canvas (full keyboard, selection, scrollback); terminal_screen.py — pyte screen + palettes;
                             # window_geometry.py; host_key_policy.py; external_terminal.py; undo_commands.py (14 QUndoCommands); logger.py
storage/                     # project.py — JSON save/load; autosave.py — autosave + backup ring buffer; export_drawio.py — .drawio export (tags + comment included)
services/                    # credential_manager.py (keyring); diagnostics.py (ping / reverse DNS off the GUI thread); host_importer.py (TXT import);
                             # status_checker.py (parallel SSH probes); system_info_collector.py (OS/CPU/RAM/disk)
dialogs/                     # AddServer, SSHConnect (+ external terminal), Connection/EditConnection, ProfileManager, Backups, QuickLaunch
ui/                          # main_window.py — façade over ProjectIOMixin / NodeOpsMixin / SshMixin; sidebar.py; map_search_bar.py (Ctrl+F);
                             # command_palette.py (Ctrl+K); hotkey_registry.py (configurable hotkeys); about_dialog.py (Help → About);
                             # icons.py; mixin_support.py; theme.py (central UI palette, radii, fonts)
i18n/                        # t(key, **kwargs); every *.json is a language (file name = code, root "name" = display name);
                             # en/ru/zh/de with identical translation key sets (parity pinned in tests); en is the default for new users;
                             # ~/.sshmap/languages/*.json is the USER folder — it shadows the built-in file of the same code
                             # (import/export in "Settings → Language") and needs no change to the installed package
tests/                       # test_*.py without pytest + _common.py harness + run_all.py (parallel runner) + check_i18n_keys.py — map: tests/INDEX.md
examples/                    # two working example plugins (hello.py — the minimal one; disk_monitor.py — the Disk Space Monitor) +
                             # examples/README.md: copy a file into ~/.sshmap/plugins/ and use Plugins → Reload; not installed, never auto-discovered
third_party/                 # pyte 0.8.2 managed fork (vendored): PyPI sdist + patches 0001–0003; provenance/sha256 — third_party/pyte-patches/MANIFEST.md
PLUGINS.md                   # the plugin contract: API v1 (manifest, hooks, context, isolation rules) + the examples of examples/
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
`probe_ssh(host, port)`: TCP open + SSH banner → `online`; port open without a banner → `warn`; otherwise → `offline`.

- **Off the GUI thread, in parallel** — the probes run on `_ProbeThread` (`ThreadPoolExecutor`, cap `status_max_parallel`, default 16), so a round costs `ceil(N/max_parallel) × timeout` instead of `N × timeout`; results arrive as they complete, and cancellation (stop/shutdown) prevents probes that have not started from reporting.
- **Soft auto-interval** — N > 50 nodes → the round interval doubles (`effective_interval_ms()`) with a one-time hint in the status bar; there is no hard limit on the server count.
- `start_status_checks()` is called once from `main.py` after `show()`.

### Terminal
- **Architecture** — session = `TerminalSessionPage` (modules/terminal_page.py): thread + pyte screen + canvas + status line + SFTP tab; ALL cleanup logic lives on the page side — every teardown path (tab/window close, session error, MainWindow shutdown, limit reached) goes through the single idempotent `page.shutdown()`, and the "ask" gate is `page.confirm_close()`.
- **Language** — the containers follow a language switch live: the window/dock titles, the tab titles and tooltips, the SFTP buttons and column headers, the command-library panel and its row tooltips are re-texted by a `retranslate()` on every container (MainWindow walks the session registry, exactly like it already did for the terminal font) — no restart.
- **Containers** —
  `SSHTerminalWindow` (WA_DeleteOnClose) holds a QTabWidget of pages: re-connecting to the same node reuses its live window —
  new session = new tab (`window.add_session()`), a different node opens a new window;
  closing a tab cleans up only that page, the last tab closes the window. The status-bar bridge and `win.page` follow the ACTIVE tab —
  and, with a split, the FOCUSED pane. The window itself closes with the standard X button —
  there is no separate "Close terminal" button.
- **Split (v1.3.3.5)** —
  the "Split Terminal" button at the right end of the session tab bar (or the window's right-click menu) puts a SECOND shell of the same node in a pane below the tabs (25% of the height by default, the divider is draggable): watch `htop` above and type below, in one window. Both panes are full sessions —
  their own channel, their own screen, so a TUI in each is fine;
  the small pane is a command line (no SFTP tab there), its state (on/off + ratio) is remembered, it does not count towards `terminal_max_open`, and multi-input reaches it like any other session. Off by default —
  nothing changes until you ask for it.
- **Display mode** — `terminal_mode`: `"windows"` (default) | `"tabs"` — sessions as tabs in a detachable QDockWidget "Terminals" on the map (`modules/terminal_dock.py`;
  the map remains the central widget): the dock detaches into a window and returns;
  cleanup is per-page (the last tab hides the dock, does not destroy it);
  applied without restart — new sessions go to the selected mode, open windows/dock stay as they are. The external terminal is unchanged (always a separate OS process).
- **Pipeline** — raw SSH bytes → `TerminalScreen.feed()` (pyte.HistoryScreen, under lock) → cell-based canvas `TerminalWidget` (QWidget+QPainter: runs, color engine `resolve_color`, blinking block cursor); dirty rendering without a timer (`_on_output` → `widget.update()`, already on the GUI thread).
- **Emulation** —
  screen is `SshmapHistoryScreen` (subclass of `pyte.HistoryScreen`): bare LF acts as CR+LF (LNM, xterm behavior), private SGR (`CSI ? … m`, sent by Vim 9+) ignored;
  alternate screen modes 47/1047/1048/1049 implemented —
  after vim/htop/mc/less the previous screen is restored character-for-character (colors included), TUI lines never enter the scrollback, and wheel/PgUp-PgDn do not scroll history while a TUI owns the grid.
- **Scrollback** — `pyte.HistoryScreen`: mouse wheel + Ctrl+Shift+PageUp/PageDown; auto-return to the live line on new output is batched (one bulk shift in `SshmapHistoryScreen.before_event` instead of ~250 page-by-page calls); **bare PageUp/PageDown remain forwarded to the shell** (`\x1b[5~`/`\x1b[6~` — paging in less/man).
- **PTY resize** — only on an actual grid change + ~150 ms debounce before `channel.resize_pty` (initial 120×32; recomputed on canvas resize via the page's eventFilter).
- **Wheel in TUI** — when a TUI enables mouse tracking (DECSET 1000/1002/1003), the wheel goes to the PTY as an xterm report (SGR `\x1b[<64|65;{col};{row}M` or X10; coordinates clamped to the grid and the protocol limit) via `terminal_thread.send_data()` — NOT through `_send()`, so multi-input never broadcasts session-local coordinates; takes precedence over `terminal_wheel="off"`.
- **pyte fork** — managed fork: `third_party/pyte` = PyPI sdist pyte 0.8.2 + 3 explicit patches (`third_party/pyte-patches/`: private SGR, LNM default, alternate screen; provenance/sha256 — MANIFEST.md); the import seam is one line in `modules/terminal_screen.py`, the subclass adds only the batched auto-return; behavioral change: none. Deep dive: PYTE82_AUDIT.md.
- **Keyboard** — F1–F12, Delete/PageUp/PageDown (always CSI ~);
  arrows and Home/End follow DECCKM: SS3 (`\x1bO…`) while a TUI owns the grid, CSI otherwise;
  explicit Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C with a selection copies to the clipboard), bracketed paste Ctrl+V (single block), AltGr guard (Ctrl+Alt is not sent as control codes). **The focused session owns its keys in both display modes:** the canvas claims the Ctrl+… family, the function keys and Delete from the window-level shortcuts, so Ctrl+D / Ctrl+Z / Delete reach the shell in the dock exactly as they do in a separate terminal window (Ctrl+F stays `\x06` for the shell — the find bar is on Ctrl+Shift+F).
- **Mouse** — selection coordinates are always `(row, col)` (`selection_cells()`); **double-click selects a word, triple-click the whole line** (word = maximal run of non-space cells, CJK wide-glyph placeholders belong to the word); drag after double/triple-click extends from the far end.
- **Working with the output** (v1.3.3.4) —
  **Ctrl+Shift+F** opens a floating find bar over the canvas: a case-insensitive search over the history AND the live grid, "k / N" counter, Enter/Shift+Enter walk the matches (the viewport scrolls to them, the match is highlighted), Esc closes the panel and returns to the view you started from —
  the key belongs to the canvas (the terminal's own keys are the xterm protocol), and nothing typed into the panel can reach the PTY. The context menu adds **Clear scrollback** (drop the history, keep the screen), **Reset screen** (re-local re-init + repaint —
  the "the screen is a mess" case) and **Save transcript…** (a tee of the session output into a local file, the raw stream;
  the checkmark is the on/off state, the file is closed with the session).
- **Context menu** (right click) — Find…, Copy (enabled only with a selection), Paste into the PTY (same bracketed-paste path as Ctrl+V), Select All, Clear scrollback, Reset screen, Save transcript…, Exclude from multi-input; labels in en/ru/zh/de (`terminal.menu.*` / `terminal.find.*`).
- **Multi-input** — typing in the focused session is broadcast to ALL other open sessions: every user input passes one point (`TerminalWidget.keyPressEvent()` → `_send(bytes)` → `terminal_thread.send_data()`) and the hub (`modules/multi_input.py`, process singleton) duplicates those bytes into every other live session;
  no echo by definition (bytes come from the keyboard of the focused widget, never from output), Ctrl+V paste included. Toggle: checkable "View" menu item + **F12 = EXIT** (NOT Esc — Esc goes to the shell as `\x1b`);
  UI: status-bar plaque "MULTI: N sessions" with an exit button, "MULTI · <alias>" tab badges + amber frame on every open container. A session that dies mid-typing leaves the registry through the stock teardown path, so the broadcast keeps working for the rest. **Excluding a session** (v1.3.3.4): "Exclude from multi-input" in the terminal's context menu keeps that session out of the broadcast (its own typing still works, its tab is badged "NO MULTI · <alias>", the plaque counts only the participants) — in memory, per session, not persisted.
- **Command library (macros)** — user library of commands/scripts in a collapsible panel of the terminal itself (`modules/command_library.py`, both containers: window and "Terminals" dock): search + category→command tree + add/edit/delete;
  double-click or Enter sends the entry to the ACTIVE session only — single-line macros go raw with a trailing `\n`, multi-line ones as a bracketed-paste block, directly via `terminal_thread.send_data()` (NOT through the multi-input broadcast);
  storage — `~/.sshmap/commands.json` (5 seed examples on first run — their names are i18n keys written in the language active at that first run, and an existing file is never re-translated — never re-seeded), panel collapse state — `ui_cmdlib_collapsed`.
- Settings — optional `terminal_*` keys in `~/.sshmap/config.json`; full list and defaults below, in "Settings".

### Settings
- Dialog (hub, `ui/settings_dialog.py`) — QTabWidget "General / Terminal / Statuses / Autosave / Map / Hotkeys / Language"; entry points: the "Settings" menu between "View" and "Help" + a button at the bottom of the sidebar (vector gear from `ui/icons.py`); the Ctrl+K command palette picks up the item automatically.
- Storage — a SINGLE `~/.sshmap/config.json` (`i18n.save_config`, atomic merge write): all keys are optional, defaults = behavior. Statuses, autosave, the UI options and the hotkeys apply live; terminal and external terminal read the config on next window creation/launch.
- Keys:
  - `external_terminal` (moved from a separate `~/.sshmap_settings.json`, with migration on read — the old file is deleted);
  - `terminal_palette` (`default|nord|dracula|tokyo_night`, unknown → default), `terminal_font` (family; empty → system monospace; live for open windows), `terminal_font_size` (pt 6–72, otherwise 10);
  - `terminal_history_lines` (scrollback depth; default 1000, explicit 0 — disabled), `terminal_close_behavior` (`"close"` | `"ask"` — confirm via `page.confirm_close()`; an already-finished session closes without a dialog);
  - `terminal_max_open` (default 4, range **1..32** — counts SESSIONS in the registry across all containers, SPLIT PANES excluded; when reached — a suggestion to close the oldest, not a refusal), `terminal_mode` (`"windows"` | `"tabs"` — see "Terminal"; broken value → default; applied to new sessions only);
  - `terminal_wheel` (`"scrollback"` | `"off"` — the local scrollback or the application; its combo lives in "Settings → Terminal"), `ui_terminal_split` (`true` — open a terminal window with the bottom pane already on) and `ui_terminal_split_ratio` (the pane's share of the height, default 0.25, clamped 0.10–0.75) — written with the window geometry on close;
  - `status_interval_sec`/`status_probe_timeout_sec`/`status_max_parallel` (defaults 30 s / 3.0 s / 16 parallel probes; live via `StatusChecker.set_interval/set_probe_timeout/set_max_parallel`);
  - `autosave_enabled/autosave_interval_sec/backup_count` (live — the autosave QTimer);
  - `language` (applied immediately, before OK);
  - `hotkeys` (a dict action_id → sequence, e.g. `"file.save": "Ctrl+S"`;
    the whole set is edited in the "Hotkeys" tab from the action registry `ui/hotkey_registry.py` —
    every one of the 43 global actions has a row, an empty string means "no hotkey" (the value the actions without a shortcut ship with) and "Reset to defaults" restores the whole map, a missing/broken value falls back to the default;
    applied live after OK;
    the terminal's own keys —
    F1–F12, Ctrl+C/D/Z, arrows —
    are the xterm protocol and are NOT configurable);
  - `ui_font_family/ui_font_size` (UI font, live via `QApplication.setFont`, 0 = system), `ui_node_double_click` (`"properties"` by default | `"connect"` —
    double-clicking a node opens SSHConnectDialog directly), `ui_show_sidebar_buttons` (the sidebar button block;
    the whole sidebar is hidden via the "View → Sidebar" menu item), `ui_show_connection_type` (type on the connection badge: "SSH · <label>", handy for PNG/PDF export) + 20-character limit on the connection label (input only —
    old projects with long labels load unchanged);
  - `plugins` (`{plugin id: true|false}` — which plugins are switched off; written by the "Plugins" menu, a missing id means enabled).

### Undo/Redo
- Any scene change goes through `MainWindow._push_command(cmd)`; the scene is modified **only** inside a command's `redo()/undo()` — `QUndoStack.push()` calls redo itself.
- Dirty marker: `self._dirty = undo_stack.canUndo() or self._undo_baseline_dirty`; `_do_save()` calls `_reset_undo_stack()` (new baseline). `_undo_baseline_dirty` covers non-undo dirty causes (statuses, background).
- NOT in undo: node statuses, coordinates on load, background geometry. Groups (move/resize/rename) — ARE included (CmdMoveGroup/CmdResizeGroup/CmdEditGroupName).
- Node drag: MapView catches the release and emits `node_drag_committed(node, old, new)` → CmdMoveNode.
- Group drag: if an already-selected node is dragged and >1 are selected — ALL selected move; one CmdMoveNodes command per gesture.
- Note pinning: `CmdAttachNote` — attaching/detaching a note to/from a node is undoable; undo of attach restores the note's pre-attach position; when deleting a node that has attached notes, the detach commands are pushed **before** the removal command (LIFO: undo first restores the node, then re-attaches the notes).

### Hotkeys + Command Palette
- Hotkeys: Ctrl+N/O/S — project;
  **Ctrl+Shift+S** — Save As…;
  Ctrl+Z/Y(+Shift) — undo/redo;
  Ctrl+Shift+A/G/C — server/group/connection;
  Ctrl+I — properties;
  **Ctrl+Enter** — SSH to the selected node;
  **Ctrl+E** — edit node;
  **Ctrl+D** — duplicate node;
  **Ctrl+Shift+N** — note in the center of the visible area;
  Delete — delete selection;
  **Ctrl+0 / Ctrl+= / Ctrl+-** — reset zoom / zoom in / zoom out;
  Ctrl+Shift+F — fit map;
  **Ctrl+F** — map search (search bar over the canvas, Enter/Shift+Enter — jump between matches with centering and an accent frame, Esc — close).
- **Every action is assignable** ("Settings → Hotkeys", v1.3.3.3): the tab lists **all 43 global actions**, not only the ones that happen to have a shortcut — so `File → Save As…`, the exports, the backups, "Check statuses now", "Reload plugins", "Run on selected servers", the About window and the rest can get a key of your own, on top of the zoom family this release gave real keys to. One row per action with a key recorder;
  a duplicate combination marks both rows and warns, but still saves;
  a row left empty means "no hotkey" (the menu item keeps working);
  **"Reset to defaults"** puts every row back at once. Stored in `~/.sshmap/config.json` and applied instantly — no restart. Multi-input keeps its own rule: whatever key you pick works only while the mode is on, so it never steals a key from your shell.
- The terminal canvas keeps its own keys (F1–F12, Ctrl+C/D/Z, arrows) — they are the xterm protocol, deliberately not configurable.
- Multi-selection: Ctrl+click on a node adds to the selection (native Qt), **Ctrl+drag on empty space** — rubber-band selection (Shift+Ctrl adds to current); group drag moves all selected; right-click during multi-selection → "Connect selected" / "Delete selected" (one confirmation, guarded per item).
- **Ctrl+K** — command palette (`ui/command_palette.py`): fuzzy search (subsequence scoring, no dependencies) over all menu QActions + project servers + the commands contributed by plugins (their own section, after the servers, so a plugin can never shadow a built-in command; the text is the plugin author's); selecting a server → select node + centerOn. Enter/Up/Down/Esc.

### Security
Passwords: keyring only (profiles `"profile:{id}"`, servers by server_id). If the keyring is unavailable, the app works but passwords do not survive a restart. External terminal: the password is entered by the OS ssh client, never in argv.

**Limitations:**
- **TOFU on first connect:** a host key that is not in `~/.sshmap/known_hosts` is accepted automatically (the fingerprint is shown in the log). This is standard paramiko-client behavior, but it is **not** full MITM protection on the very first connection: protection kicks in on a *change* of an already-recorded key. For critical hosts, verify the first-connect fingerprint over a trusted channel.
- **Windows / keyring:** only the Windows Credential Manager system backend (`keyrings.win.*`, i.e., requires pywin32 —
  uncomment it in requirements.txt) is accepted. Plaintext file fallback backends (`keyrings.alt.file`) are rejected: passwords would not be saved rather than leak into a plaintext file. On Linux/macOS, `keyrings.alt.*` backends are rejected. If no secure backend is available —
  the app works, but passwords are not saved between runs.

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
| `QPdfWriter` coordinates | Paints in device pixels at `resolution()` (1200 dpi by default) while a page layout is in points → set the resolution and draw into `device.width()/height()`; `QPageLayout` also transposes a custom size for `Landscape` (pass the portrait form) — the v1.3.3.7 PDF-export fix |

---

## 6. i18n

```python
from i18n import t, set_language, get_available_languages
t("btn.add_server", alias="web-1")   # {alias} formatting
```
en (default) / ru / zh / de — and any language you drop in, without touching the installed package:

- **Adding a language takes one JSON file.** Every `i18n/*.json` is a language (the file name is the code, the root key `"name"` is the name shown in the menus, a BOM is fine): drop it into `~/.sshmap/languages/` and `Help → Language` rescans the folder on every open — no code change, no restart.
- **A file in `~/.sshmap/languages/` shadows the built-in language of the same code**; a new code adds a language, and the folder appears only when you use it.
- **"Settings → Language"** imports a file after checking it (an object root, at least one translation key, a `"name"`; an incomplete file is imported with a note and the rest falls back to English) and exports the active language — or the English template to start a new one. A file that cannot be used is refused and the folder stays clean.
- **The rule for contributors:** a new key goes into all the files at once and a built-in language must cover 100% of en — in keys, in `{placeholders}` and in line breaks. A deliberately incomplete translation may declare itself with `"partial": true`, which turns its missing keys into a warning instead of a defect. Check — `python tests/check_i18n_keys.py`.
- Hot-path modules (`ssh_worker`, `ssh_terminal`) use a cached `get_translator()`.

---

## 7. State & Roadmap

**Implemented features** (details in sections 3–4):
- interactive map: nodes, Bezier connections of 6 types (one-way or bidirectional), notes, groups, background image with drag/resize
- node statuses online/warn/offline — parallel SSH probes, auto-interval for large maps; "Check statuses now" for a selection
- note pinning: a note pinned to a server follows it on any movement; undoable, survives save/load
- multi-selection: Ctrl+click, rubber band, group drag, "connect/delete selected"; tags with a sidebar filter
- map search (Ctrl+F): match highlighting, Enter/Shift+Enter navigation, dimming of non-matches
- quick launch per server: URLs (open in the default browser) and commands (first terminal command)
- collapsible sidebar and map panels — at most one at a time; the collapse state, the divider and the panel widths persist
- context menus for all objects, fit/zoom/centering; zoom as actions (Ctrl+0 / Ctrl+= / Ctrl+-) next to the wheel
- the project always close at hand: File → Recent (the last 10 maps), a `.json`/`.sshmap` dropped onto the window, and an unreadable file offering its autosave or a backup instead of a dead end
- built-in SSH terminal on pyte (scrollback, full keyboard, mouse selection with word/line clicks, context menu) + external system terminal
- terminal output tools: search the screen and the scrollback (Ctrl+Shift+F), clear the scrollback, reset a mangled screen, save a transcript
- SFTP tab over the same SSH connection — navigation, upload/download incl. drag & drop, and a read-only text preview (≤ 1 MB) with non-previewable rows marked
- SFTP file manager: new folder / rename / delete, an overwrite prompt, transfers that never truncate the destination, rate and ETA, a row dragged out as its remote path
- multiple sessions as tabs; separate windows or a detachable "Terminals" dock on the map — switch without restart
- terminal split: a second shell of the same node in a pane below (draggable, remembered, not counted by the session limit)
- multi-input: typing of the focused session is broadcast to all other open sessions (F12 exits), with per-session exclusions
- terminal command library (macros): one click sends a saved command/script to the active terminal (single-line raw, multi-line bracketed paste)
- undo/redo of scene operations (incl. groups and note pinning)
- automatic info collection for Linux servers (OS/CPU/RAM/disk); profiles and passwords in the OS keyring — never written to JSON
- autosave + ring buffer of backups with rollback ("File → Backups…")
- export to PNG/JPEG/PDF, SVG and draw.io `.drawio` (tags and the comment included); bulk server import from TXT
- i18n: en (default) / ru / zh / de — plus any language as one dropped-in JSON file, no code changes; the UI follows a switch live
- your own languages live in `~/.sshmap/languages/` (a file there shadows the built-in one of the same code); `Help → Language` rescans, "Settings → Language" imports and exports
- settings hub — single `~/.sshmap/config.json`, live application without restart, every user-facing key in one place
- hotkeys + command palette (Ctrl+K) — the full action registry is editable in "Settings → Hotkeys" (reset to defaults, duplicates flagged) and applied without restart
- Help → About — the version, the license, the `~/.sshmap` paths and a hotkey cheat-sheet built from the registry
- plugins: an installed package (`pip install sshmap-<name>-plugin`) or one file dropped into `~/.sshmap/plugins/`
- the "Plugins" menu switches them and re-scans without a restart; a broken plugin is reported, never fatal — the contract is `PLUGINS.md`
- what a plugin can do: run a command on selected servers (one result each, credentials resolved by the app)
- a plugin can also contribute a status to a node (the worse of the two wins, shown in the card tooltip) and add Ctrl+K commands and node-menu rows
- nothing a plugin does can freeze the window: UI hooks are timed, background hooks run on managed threads, a hung hook is abandoned
- two working examples in `examples/plugins/`: `hello.py` and `disk_monitor.py` (`df -hP` on the servers you select → a `warn` card with the mount point in the tooltip)

**Known limitations:**
- undo/redo does not cover node statuses or background geometry (§4 "Undo/Redo");
- the background image is stored by path — move the file together with the project;
- TOFU on first connect and keyring backend restrictions (§4 "Security");
- plugins run inside the application's process (v1.4): a plugin with a broken C extension can take it down — install plugins you trust.

**Roadmap** (tasks, order, acceptance — in ROADMAP.md):
- **v1.4 line** — the plugin foundation, released at **v1.4**: discovery + the "Plugins" menu and the frozen API (`PLUGINS.md`), commands on selected servers, a plugin status on the card, palette commands, node-menu rows, "Run on selected servers", two working example plugins.
- **Next (v1.4.1 → v1.4.7):** import from `~/.ssh/config`; minimap and a cached card drop-shadow; light theme + accent color; motion standards; a denser UI with first-run hints; list mode; syntax highlighting in the SFTP viewer.

---

## 8. License & Security

- MIT License (LICENSE).
- Security model and its limitations: see §4 "Security".
