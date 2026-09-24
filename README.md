# SSH Map (Visual Node Map + SSH Terminal and SFTP manager)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

![The example map in SSH Map](docs/map-example.png)

*The example map (Help → Open the example map): five servers, one connection of every type, a group, a note — all on
documentation addresses (`192.0.2.0/24`), and the statuses it declares are marked as emulated. Taken with
**File → Save Documentation Image…** (a fixed 1600×900 frame at 2×) — the refresh rule is in
DOCUMENTATION.md §5: re-run `python tests/_gen_docs_image.py` after a change that alters the
cards, the theme or the demo map, and commit `docs/map-example.png`.*

---

## 1. Running & Tests

```bash
pip install -r requirements.txt   # dependencies (PySide6, paramiko, keyring, wcwidth; pyte vendored in third_party/pyte)
python main.py                    # run the GUI
pipx install .                    # or pip install . → sshmap command (installable identity, pyproject.toml)
```

Tests are plain Python scripts without pytest: one topical `test_*.py` file per area plus a single parallel runner. Each file is an isolated process (sandbox HOME, offscreen Qt, UTF-8 stdout), so nothing extra is needed on cp1251 consoles or in CI:

```bash
python tests/run_all.py               # everything (100 test files + i18n check); auto workers = cores (cap 16), longest file first; exit 0 ⇔ all green
python tests/run_all.py --fast        # daily profile: skips files tagged slow/network
python tests/run_all.py --tag network # only network-tagged files - real-network sections run ONLY on explicit opt-in (env SSHMAP_TEST_TAGS)
python tests/run_all.py --failed-only # re-run only files that failed in the last run (cache test-results/last_run.json)
python tests/run_all.py --junit       # JUnit XML report → test-results/junit.xml (artifacts dir is gitignored)
python tests/test_tags.py             # a single file (from the project root)
```

- All runs are hermetic by default: `network`-tagged files run their real-network section only under explicit `--tag network`; `slow` = intentional long wait budgets.
- Suite map, tags and harness conventions: `tests/INDEX.md`. Its "Files" table is auto-generated from module docstrings (`python tests/_gen_index.py`, freshness check with `--check`). Shared fakes: `tests/_fakes.py`.

Requirements: Python 3.10+, Windows/Linux/macOS. Logs: `~/.sshmap/logs/sshmap.log` (RotatingFileHandler, 5 MB × 3).

---

## 2. Project Structure

Compact overview:

```
main.py                      # Entry point: logging → QApplication → MainWindow → status checks
version.py                   # APP_VERSION / VERSION_FORMAT (JSON format)
pyproject.toml               # Installable identity (entry point sshmap = main:main) - checked by tests/test_pyproject.py
models/                      # server.py - ServerData (password never serialized); profile.py - profiles, passwords in keyring
graphics/                    # MapScene; MapView (zoom 0.1–5.0, panning, multi-selection); ServerNode (status card);
                             # ConnectionArrow (cubic Bezier, 6 types, optional bidirectional heads); StickyNote (pinning to a node); NodeGroup; BackgroundImage
modules/                     # ssh_worker.py - one-shot SSH worker + registry; ssh_terminal.py - terminal thread + tabbed window;
                             # plugin_manager.py - plugin discovery (entry points + ~/.sshmap/plugins/*.py), the plugin registry and the
                             # isolation machinery (managed workers, orphan registry, hook budgets); plugin_context.py - the API v1 plugin
                             # context; plugin_runner.py - "run a command on these nodes" over SSH;
                             # terminal_page.py - session as a reusable widget (single idempotent shutdown()); terminal_dock.py - "tabs" mode dock;
                             # command_library.py - terminal macros: user command/script library panel (~/.sshmap/commands.json);
                             # multi_input.py - multi-input broadcast hub; sftp_worker.py / sftp_tab.py - SFTP over the live transport (listing, upload/download, a file manager: new folder/rename/delete, an overwrite prompt, atomic transfers, drag-out of a path, read-only preview with "no preview" row marks and syntax highlighting);
                             # syntax_highlight.py - the viewer's grammars (number-only, verified JSON/XML, heuristic YAML) and its one highlighter;
                             # terminal_widget.py - cell-based canvas (full keyboard, selection, scrollback); terminal_screen.py - pyte screen + palettes;
                             # window_geometry.py; host_key_policy.py; external_terminal.py; undo_commands.py (15 QUndoCommands);
                             # logger.py (the file/console handlers + the activity tap); activity_log.py (the bounded, memory-only history ring)
storage/                     # project.py - JSON save/load; example_project.py - the DEMO map built in code (five nodes, six connections, RFC 5737 addresses only);
                             # autosave.py - autosave + backup ring buffer; export_drawio.py - .drawio export (tags + comment included; the print-friendly palette by default)
services/                    # credential_manager.py (keyring); diagnostics.py (ping / reverse DNS off the GUI thread + the v1.5.3 reachability report: DNS → TCP → banner → ICMP);
                             # info_batch.py (the bounded queue behind "gather information for many nodes"); host_importer.py (TXT import);
                             # ssh_config_importer.py (~/.ssh/config import); status_checker.py (parallel SSH probes); system_info_collector.py (OS/CPU/RAM/disk)
dialogs/                     # AddServer, SSHConnect (+ external terminal), Connection/EditConnection, ProfileManager, Backups, QuickLaunch,
                             # SshConfigImport (the checkbox picker of the ~/.ssh/config import), ExportOptions (print-friendly or current theme)
ui/                          # main_window.py - façade over ProjectIOMixin / NodeOpsMixin / SshMixin; sidebar.py (the server list - adaptive columns: the narrow view, or the LIST table when the map is collapsed); map_search_bar.py (Ctrl+F);
                             # minimap.py (the big-picture panel: the scheme at fit scale + a viewport frame);
                             # legend.py (the collapsible legend: the 6 connection types + the 3 statuses, each with a sample of its line style or shape);
                             # status_shape.py (the status marks: a filled dot / a ring / a triangle);
                             # empty_state.py (first-run hint over an empty map: add a server, open the example map, the palette hotkey); motion.py (animation standards: camera flights, the node scale-in);
                             # status_bar.py (the status bar with the Undo affordance of the last destructive action); activity_panel.py (the activity history window); hotkey_sheet_dialog.py (the shortcut list, rendered from the registry);
                             # command_palette.py (Ctrl+K); hotkey_registry.py (configurable hotkeys); about_dialog.py (Help → About);
                             # icons.py; mixin_support.py; theme.py (the `Theme` object - DARK/LIGHT, the accent hue; pure data);
                             # theme_qss.py (the palette + the ONE QSS builder + the live switch)
i18n/                        # t(key, **kwargs); every *.json is a language (file name = code, root "name" = display name);
                             # en/ru/zh/de with identical translation key sets (parity pinned in tests); en is the default for new users;
                             # ~/.sshmap/languages/*.json is the USER folder - it shadows the built-in file of the same code
                             # (import/export in "Settings → Language") and needs no change to the installed package
tests/                       # test_*.py without pytest + _common.py harness + run_all.py (parallel runner) + check_i18n_keys.py - map: tests/INDEX.md
docs/                        # the README's documentation image (docs/map-example.png) - rendered from the EXAMPLE map by tests/_gen_docs_image.py
examples/                    # two working example plugins (hello.py - the minimal one; disk_monitor.py - the Disk Space Monitor) +
                             # examples/README.md: copy a file into ~/.sshmap/plugins/ and use Plugins → Reload; not installed, never auto-discovered
third_party/                 # pyte 0.8.2 managed fork (vendored): PyPI sdist + patches 0001–0003; provenance/sha256 - third_party/pyte-patches/MANIFEST.md
PLUGINS.md                   # the plugin contract: API v1 (manifest, hooks, context, isolation rules) + the examples of examples/
```

---

## 3. Project Format (JSON files, `.json` / `.sshmap`)

```json
{
  "version": "0.9",
  "servers":  [{"id": "710602ee", "alias": "...", "host": "...", "user": "...",
                "x": 0.0, "y": 0.0, "cpu": "", "ram": "", "disk": "", "ip": "",
                "comment": "", "ssh_port": 22, "key_path": "",
                "os_name": "", "cpu_model": "", "tags": ["prod", "dev"],
                "info_collected_at": 1750000000.0,
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
- `password` is never serialized; it lives only in the OS keyring (`server_data_to_dict()` excludes the field).
- Connection types: `ssh|vpn|http|database|nfs|kubernetes`; an unknown or missing type loads as `ssh`. The `version` field is not validated on load (files from 0.6+ are readable).
- `bidirectional` is optional on a connection record: written only when true, absent means a one-way arrow (old files without the key load unchanged). A bidirectional arrow draws heads at both ends of the curve (two-way data exchange).
- Group membership is not stored; it is computed from geometry. Each card joins exactly the topmost group whose rect contains its center.
- `tags`: an array of strings on the server record; missing or non-array in old JSON becomes an empty list (`server_data_from_dict` normalizes it).
- `info_collected_at` (v1.5.3): when the collected facts (`os_name`/`cpu_model`/`cpu`/`ram`/`disk`/`ip`) were measured, as epoch seconds. Written ONLY when the server has one, so an undated map keeps the file it had; a missing key, `null`, a non-numeric value or a negative epoch loads as "not dated" and the card stays unmarked. The key holds an age, never a status, and `VERSION_FORMAT` stays `"0.9"` — an optional field with a default is not a schema change.
- `quick_launch`: an array of items `{"type": "url"|"command", "name", "value"}`; missing in old JSON is an empty list, broken records are dropped (`sanitize_quick_launch`). A URL opens in the default browser; a command becomes the first command sent to the SSH terminal.
- `server_id` on a note is optional (the same pattern as `groups`/`background`): written only when set, absent means a free note. A broken reference (missing node or not a string) logs a warning and leaves the note free at its saved position; on load an attached note keeps its SAVED position (`attach_note_to_node(..., keep_position=True)` derives the anchor offset from the stored x/y relative to the node's card anchor), so a note that was moved by hand stays where it was left instead of jumping into the corner. `VERSION_FORMAT` stays `"0.9"`.
- `background` stores a path to the image, not the file itself (nothing is embedded in the JSON); a missing file on load logs a warning and is ignored. Background geometry is not part of undo.

---

## 4. Key Behaviors (important for code changes)

### Map cards, groups and the minimap
- Shadow vs. card: `ServerNode.boundingRect()` returns the card plus its cached shadow halo (`_shadow_pixmap()`, one shared pixmap per card size, never a `QGraphicsDropShadowEffect`). Every anchor (arrow tips, pinned notes, group membership, the connect-drag band) goes through `card_rect_scene()`: the card without the halo. Route new consumers of a node's edge through that API rather than `sceneBoundingRect()`, or they will sit 9 px off the card. The SVG export hides the halos while it renders (a pixmap would land in the file as base64); PNG and PDF keep them.
- Group fold: folding a group is a real, undoable change (`NodeGroup.collapse()/expand()`, `CmdToggleGroupCollapse`). Members become badges in a grid inside a re-fitted frame; the pre-fold arrangement is snapshotted as local offsets and restored on unfold; members are not draggable while folded. The state persists in the project file as optional group fields (`collapsed`, `expanded_width/height`); a group restored folded from a file unfolds in place (no previous card layout is stored).
- Minimap: `ui/minimap.py` is a floating child of `MapView`, never a scene item, so it stays out of every export. It keeps one cached layer of `(rect, colour)` pairs in scene coordinates, rebuilt on a debounced `scene.changed`, and asks the window for a camera move with `center_requested` (the window owns `centerOn`).
- Card header (tag badge): the card shows its **primary tag as text** in the free band above the alias, on a tint of the same colour the left-edge tag strip uses. The declared vocabulary wins the pick (`prod` > `staging`/`stage` > `dev` > `test`, whatever order you typed the tags in); any other tag is shown as your first one, elided to the band, and a card without tags shows nothing at all. It is a second channel on purpose: `prod` used to be readable only as the red of "offline".

### Motion
- One module owns the timing: `ui/motion.py` fixes 150 / 250 / 300 ms and one easing (OutQuad); nothing invents its own numbers at a call site.
- Smooth camera: "Show on map" from the sidebar and Fit map (Ctrl+Shift+F) fly the camera in 250 ms instead of jumping, and a newly added card scales in (0.9 → 1.0 over 200 ms, its own opacity property, never an opacity effect). A flight interpolates zoom and centre together; the status-bar percentage follows.
- Everything is interruptible: the wheel, a mouse drag or any instant navigation (the palette, a search step, the minimap drag) stops a running flight where it is; a second flight starts from the current camera, never from an abandoned target. A cancelled or undone scale-in settles the card back to unit, so `boundingRect()`/`edge_point` are never left shifted.
- Arrow hover focus: hovering a connection lights its two nodes with the accent frame while every other card dims to 25%; leaving restores the map. The dim has one owner (`MainWindow._apply_map_dimming`), so hover, tag filter and map search merge instead of stacking.

### Theme
- One `Theme` object is the whole look: `ui/theme.py` holds `DARK` (the default) and `LIGHT`, the same field set with colours only; the accent is a hue that generates its shades. The module is pure data (no PySide6); the Qt half (`QPalette`, application QSS, the switch) lives in `ui/theme_qss.py`.
- Two accent roles, one hue: the DECORATIVE tone (`accent`) draws borders, focus outlines and the floating panels' frames; the STRONG tone (`accent_strong`, with its own hover/selected pair) is the ink for accent text and the fill under text (a selected menu row, an item-view selection, the clickable status counters, the first-run button). In the dark theme both resolve to the same value, so nothing moves; in the light theme the strong tone is generated deeper so it stays readable.
- The light palette is measured, not eyeballed: every arrow, status, tag and note tone was re-tuned against the surface it is really drawn on (a status dot sits on the CARD, not on the canvas), and `tests/test_theme_contrast.py` is the gate — a declared table of pairs with WCAG thresholds (4.5 for text, 3.0 for a graphic) checked in both themes, plus a completeness audit: a colour that enters the theme without a pair or a written-down exemption fails the suite.
- Read the theme at access time, never capture it: module constants resolve live (`theme.NODE_BG` follows a switch), class-level colours are `ThemeColor`/`ThemeMap` descriptors, and anything built in `__init__` (a `QBrush`, a QSS string) is rebuilt by its owner's `refresh_theme()`. `MainWindow.refresh_theme()` and `MapScene.refresh_theme()` are the two walks that ask every owner; `QApplication.setStyleSheet` re-polishes standard controls on its own. A new widget with a stylesheet adds one entry to `theme_qss.STYLE_BUILDERS` instead of an f-string.
- Vector icons follow the switch as well (cached per name, re-painted in the new tone).
- Three modes: dark, light and Auto (system), which follows the operating system's own colour scheme live (a platform without the hint stays dark). The accent is stored as the colour you picked (`theme.accent` in `config.json`) and read back as a hue; terminal output palettes are deliberately outside this system.
- Reduce motion: one switch in the same tab turns the animations off — every gesture then applies its final state at once instead of gliding.

### Density & first run
- Compact sidebar: its six action buttons sit in a 2-column × 3-row grid (icon + text, tooltips carry the full label) instead of six full-width rows; the panel's public attributes and signals are unchanged.
- Empty map explains itself: at 0 servers a hint appears over the canvas ("Add your first server" opens the AddServer dialog, plus a line naming the two real import menu items); it disappears with the first server. The card is click-through (only its button takes the mouse) and is a widget over the scene, never a scene item, so it stays out of the exports.
- Start from an example: the empty map offers **Open the example map** (Help → the same item): a small demo project built in code — five servers, one connection of every type, a group, a note and tags, all on RFC 5737 documentation addresses (`192.0.2.0/24`), so no real host is ever probed. Its first screen looks alive: the statuses are declared in code and every card says "demo (emulated)" next to the mark (and carries no age, because nothing was measured). Save it and it is yours — the copy is an ordinary project and gets checked for real.
- Undo is visible when it matters: after a delete, a disconnect or a bulk import the status bar shows the action's own message next to an **Undo** button (gone with the next message or after a few seconds). A move, an edit or a view change offers nothing, because nothing was lost.
- Live status bar: the Online / Warn / Offline counters are clickable; one click filters the sidebar by that status (AND-combined with the tag filter and the search), a second click resets it. The filter is transient (never saved); the counters keep showing the totals.
- Legend: a small collapsible panel (View → Legend, plus a toolbar button) listing the 6 connection types and the 3 statuses; drag it anywhere (position, folded state and visibility persist in `config.json`). Every row shows a sample of the mark itself — the line style of a connection type, the shape of a status — so the legend explains the second channel too.
- Panel divider obeys the collapse state: enabled only while both panels are expanded, and a collapsed panel is capped at its 18 px strip for every resize source (handle, window, dock), so the strip can no longer drift into empty space.

### Meaning beyond colour, and printing
- Six connection types, six line styles: SSH is a solid line, VPN dashed, HTTP dotted, Database dash-dot, NFS a double line and Kubernetes long-dashed. A type is now readable without its colour — in greyscale, in print and for colour-vision deficiencies.
- Three statuses, three shapes: Online is a filled dot, Warn a ring, Offline a triangle — on the card, in the sidebar row and in the legend. The words stay in the tooltips.
- Exports are print-friendly by default: PNG, PDF, SVG and drawio all leave a light page with high-contrast lines (whatever theme you are working in), and the six types stay apart by their line style. The export dialog has one checkbox — "use the current theme colours" — if you want the screen look instead; a `.drawio` export carries the same palette and the same line styles.
- The suite keeps it honest (`tests/test_encoding.py`): the samples, the greyscale separations of all six types in both themes, the measured dash rhythms and rails in a real desaturated render, the three shapes and the export palette of every format.

### Map images (v1.5.1)
- **Copy the map** (File → Copy Map as Image, or the empty map's right-click menu): the same 2× render as the PNG export goes straight to the clipboard — no file dialog, and deliberately no palette question. An export is a document (light page by default), a copy is *what you are looking at* (your current theme). Paste it into a chat, a ticket or a slide.
- **A documentation image in a fixed frame** (File → Save Documentation Image…): the map rendered inside 1600×900 at 2× (3200×1800 px), content fitted and centred on a 40 px margin, so the picture has the same size for every map. It is a **poster of the map**: the floating panels and the whole chrome are children of the view, never scene items, so they stay out of the image — no window resizing, no screenshots.
- The README picture above is that action's output on the example map. It is regenerated in one command and only ever from the **example map** — real projects (`server_map*.json`) are gitignored and must never be published.

### Activity history (v1.5.2)
- **View → Activity panel** opens a window with what just happened: probe rounds, imports, SFTP transfers, plugin errors, theme and language fallbacks — newest first, four columns (time, level, source, message), a level filter (Info / Warnings / Errors / Interface) and **Clear**. The status bar still shows the *now*; this window keeps the history the interface never had, and it is **memory only** — the last 200 events, never written to disk (`~/.sshmap/logs/sshmap.log` stays the durable record, and it got the missing lines: a round summary, every transfer's outcome, every import's result).
- The event lines are English, like the log file; the window's own chrome (title, columns, level names, Clear) is translated. It opens again where you left it (one `config.json` flag, off by default) and there is nothing else to configure.

### List mode
- Collapsing the map turns the sidebar into a server table: the panel already stretches to the whole window width, and the tree now uses it (alias, host (IP), status, OS, CPU, RAM, disk and tags taken straight from the server data; an empty field is an empty cell; columns are draggable). Expand the map and the compact one-column list is back.
- It is the same sidebar, only wider: search and tag/status filters narrow the table, the row context menu is unchanged, and a double click on a row does what a double click on a card does (`Settings → Map`: properties or connect).
- The two splitter items name their states: `Map / List` and `Sidebar / Map` (same config keys, same behaviour). The mode is the ordinary "map collapsed" state, so nothing new is stored and the 18 px strips still work as the way back.
- Minimap folds sideways and moves: a vertical title band on its right edge; click it to fold the panel into a thin strip (click again to bring it back). Hold the left button on the map area and drag to detach the panel from the corner and place it anywhere on the map; a plain click or drag still pans the view, and the spot is remembered.
- Panels re-attach when you drop them at an edge: a floating panel (the minimap and the legend) dropped within 24 px of the map edge it hangs from snaps back to its documented corner and forgets the dragged position, so the "below the search bar" placement, the fold and the corner rules come back on their own. Drop it anywhere else and it stays where you put it.
- All four view toggles sit next to each other on the toolbar (Sidebar / Map, Minimap and Legend), so a panel can be shown, hidden, folded or collapsed without opening the View menu; the menu items stay the owners (hotkeys and state live there).

### SFTP viewer
- The preview is no longer monochrome: numbers in any text file plus a real grammar for JSON, XML and YAML. Same read-only panel, same 1 MB limit, no new dependency.
- A hint must not lie: the extension only proposes, the content decides. A `.json`/`.xml` file gets its grammar only after it really parses; otherwise it falls back to number-only mode. YAML has no standard-library parser, so its highlighting is a heuristic and the header says so.
- Colours, never bold; and only the lines you can see are painted, so even a 1 MB file opens as fast as its first screen (a minified one is capped instead of freezing).

### Statuses
`probe_ssh(host, port)`: TCP open + SSH banner → `online`; port open without a banner → `warn`; otherwise → `offline`.

- Statuses carry their age: the card tooltip says "checked just now" / "checked N min ago", and once a result is older than `max(2 × interval, 90 s)` its mark turns grey **while keeping the shape of its status**. Freshness never changes a status and never starts a check of its own.
- The example map's statuses are **emulated and always marked**: the demo network does not exist (a probe can only answer `offline` there), so the demo declares green/amber/red in code and every one of those cards carries a "demo (emulated)" badge, names the emulation in its tooltip and shows **no age** — nothing was measured. Those nodes are never probed while the demo is open, the file keeps no status field, and saving the map as your own project drops the emulation so the copy is checked for real.

- Off the GUI thread, in parallel: probes run on `_ProbeThread` (`ThreadPoolExecutor`, cap `status_max_parallel`, default 16), so a round costs ceil(N/max_parallel) × timeout instead of N × timeout; results arrive as they complete, and cancellation (stop/shutdown) prevents not-yet-started probes from reporting.
- Soft auto-interval: above 50 nodes the round interval doubles (`effective_interval_ms()`) with a one-time hint in the status bar; there is no hard limit on the server count.
- `start_status_checks()` is called once from `main.py` after `show()`.

### Fresh facts and "why is it red?" (v1.5.3)
- **The collected facts carry their age too.** OS / CPU / RAM / disk / IP are written together with the moment they were measured, so the info plaque on a card says "collected just now" / "{days} days ago" in its tooltip, and a fact older than a week is painted in the grey "not current" tone **without changing a single value**. A project saved before this release loads unchanged and simply shows no age; a card can honestly have a fresh status above year-old hardware lines, because the two ages are separate.
- **Gather information for many servers at once** ("Collect system info" in the Edit menu and in both context menus): the selection when there is one, the clicked server from a context menu, the whole map when nothing is selected. The collections run in a bounded queue — at most `info_max_parallel` at a time (default 4, a performance key in `config.json`), a server that is already being collected is skipped, and one failure never stops the rest. The status bar shows progress and the final line **names the failures**; the full list goes to the activity panel.
- **"Why is it offline?"** asks the red card a direct question and answers it with the steps the app already takes, in order: DNS resolve → TCP connect → SSH banner → ICMP ping. The first failing step is named in its own words, so a wrong name, a refused port, a filtered port and a server that answers with something that is not SSH produce four different sentences. When the port is unreachable the ping says which of the two it is ("host down" vs "firewall"). The answer appears in the card's tooltip, the status bar and the activity history — and **the status itself is never changed by it**, because a report explains, it does not decide. One report per server at a time; no new dependency, and every step keeps the 3 s probe budget.

### Where is the problem? (v1.5.4)
- **A group answers for its members.** Its frame (and its folded badge grid) carries the worst member status as a
  shape plus the counts — `Offline 2 · Warn 1`, `Online 5`, "No members" for an empty group, "Not checked" for one
  nobody probed. The worst status also colours the frame while it is a problem, and a probe round updates it. A
  group's status is a VIEW fact: it is never written into the project file.
- **The "problems only" lens**: one click on the chip next to the status counters dims everything that is not warn,
  offline or stale (a result older than its freshness budget counts as trouble too). It composes with the tag filter,
  the map search and the hover focus instead of replacing them, the counters keep showing the totals, and nothing is
  saved — a restart never leaves the map dimmed for no visible reason.
- **The filter plaque** names what the map is showing: the search query, the tag, the status filter and the lens, each
  with its own ×. It appears only while a filter is active, it never enters an export, and it stays clear of the
  collapse diamond (and of the search bar on a narrow window).
- The words are the ones the app already uses (the legend's status names), the shape comes from the same declaration
  the cards and the legend draw from, and the suite (`tests/test_problem_first.py`) measures the aggregate, the
  composition of the filters and the plaque.

### Terminal
- Architecture: session = `TerminalSessionPage` (`modules/terminal_page.py`: thread + pyte screen + canvas + SFTP tab). All cleanup logic lives on the page; every teardown path (tab/window close, session error, MainWindow shutdown, limit reached) goes through the single idempotent `page.shutdown()`, and the "ask" gate is `page.confirm_close()`.
- Status bar: a session does not draw a status line of its own (it would repeat one row above the tabs text the window's status bar already shows). Every state (connecting, opened, closed, error) goes to that one bar.
- Language: containers follow a language switch live. Window/dock titles, tab titles and tooltips, SFTP buttons and column headers, and the command-library panel with its row tooltips are re-texted by `retranslate()` on every container (MainWindow walks the session registry, exactly as it already does for the terminal font); no restart.
- Containers: `SSHTerminalWindow` (`WA_DeleteOnClose`) holds a QTabWidget of pages. Re-connecting to the same node reuses its live window (new session = new tab via `window.add_session()`); a different node opens a new window. Closing a tab cleans up only that page; the last tab closes the window. The status-bar bridge and `win.page` follow the active tab, or with a split the focused pane. The window itself closes with the standard X button; there is no separate "Close terminal" button.
- Split: the "Split Terminal" button at the right end of the session tab bar (or in the window's right-click menu) puts a second shell of the same node in a pane below the tabs, 25% of the height by default with a draggable divider; watch `htop` above and type below in one window. Both panes are full sessions (their own channel, their own screen), so a TUI in each is fine. The small pane stays compact: no SFTP tab, no tab strip, no status line there, just the canvas in its frame; its state (on/off + ratio) is remembered; it does not count towards `terminal_max_open`; multi-input reaches it like any other session (the amber frame is the mark). Its live state goes to the window's status bar as a second text (`Split Terminal  SSH session opened`), which disappears when the pane does. Off by default: nothing changes until you ask for it.
- Display mode: `terminal_mode`: `"windows"` (default) or `"tabs"`. In tabs mode sessions live as tabs in a detachable "Terminals" QDockWidget on the map (`modules/terminal_dock.py`); the map remains the central widget, and the dock detaches into a window and returns. Cleanup is per-page (the last tab hides the dock without destroying it). The setting applies without restart: new sessions go to the selected mode, open windows/dock stay as they are. The external terminal is unchanged (always a separate OS process).
- Pipeline: raw SSH bytes → `TerminalScreen.feed()` (the pyte history screen under lock) → cell-based canvas `TerminalWidget` (`QWidget` + `QPainter`: runs, colour engine `resolve_color`, blinking block cursor). Dirty rendering without a timer: `_on_output` → `widget.update()`, already on the GUI thread.
- Emulation: the screen is `SshmapHistoryScreen` (a subclass of `pyte.HistoryScreen`). Bare LF acts as CR+LF (LNM, xterm behaviour); private SGR (`CSI ? … m`, sent by Vim 9+) is ignored; alternate screen modes 47/1047/1048/1049 are implemented, so after vim/htop/mc/less the previous screen is restored character-for-character (colours included); TUI lines never enter the scrollback, and wheel/PgUp-PgDn do not scroll history while a TUI owns the grid.
- Scrollback: `pyte.HistoryScreen` depth; mouse wheel + Ctrl+Shift+PageUp/PageDown. Auto-return to the live line on new output is batched (one bulk shift in `SshmapHistoryScreen.before_event` instead of ~250 page-by-page calls). Bare PageUp/PageDown stay forwarded to the shell (`\x1b[5~`/`\x1b[6~`, paging in less/man).
- PTY resize: only on an actual grid change, with a ~150 ms debounce before `channel.resize_pty` (initial 120×32; recomputed on canvas resize via the page's eventFilter).
- Wheel in TUI: when a TUI enables mouse tracking (DECSET 1000/1002/1003) the wheel goes to the PTY as an xterm report (SGR `\x1b[<64|65;{col};{row}M` or X10, coordinates clamped to the grid and protocol limits) via `terminal_thread.send_data()`, not through `_send()`, so multi-input never broadcasts session-local coordinates. This takes precedence over `terminal_wheel="off"`.
- pyte fork: a managed fork in `third_party/pyte` (the PyPI sdist of pyte 0.8.2 + 3 explicit patches under `third_party/pyte-patches/`: private SGR, LNM default, alternate screen; provenance and sha256 in MANIFEST.md). The import seam is one line in `modules/terminal_screen.py`; the subclass adds only the batched auto-return. No other behavioral change. Deep dive: PYTE82_AUDIT.md.
- Keyboard: F1–F12, Delete/PageUp/PageDown always reach the shell as CSI ~ sequences; arrows and Home/End follow DECCKM (SS3 `\x1bO…` while a TUI owns the grid, CSI otherwise); explicit Ctrl+C→`\x03` / Ctrl+D→`\x04` (Ctrl+C with a selection copies to the clipboard), bracketed paste on Ctrl+V (single block), AltGr guard (Ctrl+Alt is not sent as control codes). The focused session owns its keys in both display modes: the canvas claims the Ctrl+… family, function keys and Delete from window-level shortcuts, so Ctrl+D / Ctrl+Z / Delete reach the shell in the dock exactly as they do in a separate terminal window. (Ctrl+F stays `\x06` for the shell; the find bar is on Ctrl+Shift+F.)
- Mouse: selection coordinates are always `(row, col)` (`selection_cells()`); double-click selects a word, triple-click the whole line (a word = maximal run of non-space cells; CJK wide-glyph placeholders belong to the word); drag after double/triple-click extends from the far end.
- Working with the output: Ctrl+Shift+F opens a floating find bar over the canvas: case-insensitive search over history and live grid, a "k / N" counter, Enter/Shift+Enter walk the matches (the viewport scrolls to them, the match is highlighted), Esc closes the panel and returns to the view you started from. The key belongs to the canvas (terminal keys are xterm protocol) and nothing typed into the panel can reach the PTY. The context menu adds Clear scrollback (drop the history, keep the screen), Reset screen (re-local re-init + repaint, for when "the screen is a mess") and Save transcript… (a tee of the session output into a local file, raw stream; the checkmark is on/off, the file closes with the session).
- Context menu (right click): Find…, Copy (enabled only with a selection), Paste into the PTY (same bracketed-paste path as Ctrl+V), Select All, Clear scrollback, Reset screen, Save transcript…, Exclude from multi-input. Labels in en/ru/zh/de (`terminal.menu.*` / `terminal.find.*`).
- Multi-input: typing in the focused session is broadcast to all other open sessions. Every user input passes one point (`TerminalWidget.keyPressEvent()` → `_send(bytes)` → `terminal_thread.send_data()`) and the hub (`modules/multi_input.py`, process singleton) duplicates those bytes into every other live session; no echo by definition (bytes come from the keyboard of the focused widget, never from output), Ctrl+V paste included. Toggle: a checkable "View" menu item; F12 exits the mode (not Esc, which goes to the shell as `\x1b`). UI: status-bar plaque "MULTI: N sessions" with an exit button, "MULTI · <alias>" tab badges and an amber frame on every open container. A session that dies mid-typing leaves the registry through the stock teardown path, so the broadcast keeps working for the rest. Excluding a session: "Exclude from multi-input" in the terminal's context menu keeps that session out of the broadcast; its own typing still works, its tab is badged "NO MULTI · <alias>", and the plaque counts only participants. The exclusion lives in memory per session, not persisted.
- Command library (macros): a user library of commands/scripts in a collapsible panel inside the terminal (`modules/command_library.py`, both containers: window and dock). Search + category→command tree + add/edit/delete; double-click or Enter sends the entry to the active session only: single-line macros go raw with a trailing `\n`, multi-line ones as a bracketed-paste block, directly via `terminal_thread.send_data()` (not through the multi-input broadcast). Storage: `~/.sshmap/commands.json` (5 seed examples on first run; their names are i18n keys written in the language active at that first run, and an existing file is never re-translated or re-seeded); panel collapse state: `ui_cmdlib_collapsed`.
- Settings: optional `terminal_*` keys in `~/.sshmap/config.json`; the full list and defaults are below, under "Settings".

### Settings
- Dialog (hub, `ui/settings_dialog.py`) with tabs General / Appearance / Terminal / Statuses / Autosave / Map / Hotkeys / Language. Entry points: the Settings menu between View and Help + a button at the bottom of the sidebar (vector gear from `ui/icons.py`); the Ctrl+K command palette picks up the item automatically.
- Storage: a single `~/.sshmap/config.json` (`i18n.save_config`, atomic merge write). All keys are optional; defaults = behaviour. Statuses, autosave, UI options, theme and hotkeys apply live; terminal and external terminal read the config on next window creation/launch.
- Keys:
  - `external_terminal` (moved from a separate `~/.sshmap_settings.json`, migrated on read; the old file is deleted);
  - `terminal_palette` (`default|nord|dracula|tokyo_night`; unknown → default), `terminal_font` (family; empty → system monospace; live for open windows), `terminal_font_size` (pt 6–72, otherwise 10);
  - `terminal_history_lines` (scrollback depth; default 1000, explicit 0 disables it), `terminal_close_behavior` (`"close"` | `"ask"`; confirm via `page.confirm_close()`; an already-finished session closes without a dialog);
  - `terminal_max_open` (default 4, range 1..32): counts sessions in the registry across all containers, split panes excluded; when reached it offers to close the oldest instead of refusing.
  - `terminal_mode` (`"windows"` | `"tabs"`, see the Terminal section; broken value → default; applied to new sessions only);
  - `terminal_wheel` (`"scrollback"` | `"off"`: local scrollback or the application's; its combo lives in Settings → Terminal), `ui_terminal_split` (true opens a terminal window with the bottom pane already on) and `ui_terminal_split_ratio` (the pane's share of height, default 0.25, clamped 0.10–0.75); both split keys are written with the window geometry on close;
  - `status_interval_sec` / `status_probe_timeout_sec` / `status_max_parallel` (defaults 30 s / 3.0 s / 16 parallel probes; live via `StatusChecker.set_interval/set_probe_timeout/set_max_parallel`); `info_max_parallel` (v1.5.3: how many system-info collections "Gather information" runs at once, default 4, clamped 1..16 — read by the batch owner, not a settings-hub row);
  - `autosave_enabled` / `autosave_interval_sec` / `backup_count` (live, drive the autosave QTimer);
  - `language` (applied immediately, before OK);
  - `theme` (`{"mode": "dark"|"light"|"auto", "accent": "#rrggbb", "motion": true}`). The Appearance tab: dark theme is the default, `auto` follows the operating system's colour scheme live, the accent is one hue (8 swatches or your own colour), and the "Reduce motion" box turns the animations off. A broken value falls back to dark + the default sky + the motion on. Applied live before OK; Cancel restores the previous theme and the previous motion flag.
  - `hotkeys` (dict action_id → sequence, e.g. `"file.save": "Ctrl+S"`). The whole set is edited in the Hotkeys tab from the action registry `ui/hotkey_registry.py`: every one of the 54 global actions has a row; an empty string means no hotkey (the value the actions without a shortcut ship with); "Reset to defaults" restores the whole map; missing or broken values fall back to the default. Applied live after OK. The terminal's own keys (F1–F12, Ctrl+C/D/Z, arrows) are xterm protocol and not configurable.
  - `ui_font_family` / `ui_font_size` (UI font, live via `QApplication.setFont`, 0 = system), `ui_node_double_click` (`"properties"` default | `"connect"`; double-clicking a node opens the SSHConnectDialog directly), `ui_show_sidebar_buttons` (the sidebar button block; hide the whole sidebar via View → Sidebar), `ui_show_connection_type` (type on the connection badge, "SSH · <label>", handy for PNG/PDF export) + 20-character limit on the connection label (input only; old projects with long labels load unchanged);
  - `plugins` (`{plugin id: true|false}`, which plugins are switched off; written by the Plugins menu; a missing id means enabled).

### Undo/Redo
- The affordance: `_push_command()` is the ONE place that offers a way back. A destructive command (delete a node/connection/note, detach a note, a bulk import) arms an **Undo** button in the status bar, which the action's own message then carries; a later message, the next save/load/new or a timeout clears it. Nothing outside the stack — the terminal, SFTP, a view state — can offer one.
- Any scene change goes through `MainWindow._push_command(cmd)`; the scene is modified only inside a command's `redo()/undo()` (`QUndoStack.push()` calls redo itself).
- Dirty marker: `self._dirty = undo_stack.canUndo() or self._undo_baseline_dirty`; `_do_save()` calls `_reset_undo_stack()` (new baseline). `_undo_baseline_dirty` covers non-undo dirty causes (statuses, background).
- Not in undo: node statuses, coordinates applied on load, background geometry, collapsing a single card (a view state). Groups (move/resize/rename) are undoable (`CmdMoveGroup`/`CmdResizeGroup`/`CmdEditGroupName`), and so is the group fold (`CmdToggleGroupCollapse`; it moves the member cards).
- Node drag: MapView catches the release and emits `node_drag_committed(node, old, new)` → CmdMoveNode.
- Group drag: dragging an already-selected node while more than one is selected moves all of them; one `CmdMoveNodes` command per gesture.
- Note pinning (`CmdAttachNote`): attaching or detaching a note to/from a node is undoable; undo of attach restores the note's pre-attach position. When deleting a node with attached notes, the detach commands are pushed before the removal command (LIFO: undo first restores the node, then re-attaches the notes).

### Hotkeys + Command Palette
- Default hotkeys: Ctrl+N/O/S for projects; Ctrl+Shift+S Save As…; Ctrl+Z / Y(+Shift) undo/redo; Ctrl+Shift+A/G/C add server/group/connection; Ctrl+I properties; Ctrl+Enter SSH to the selected node; Ctrl+E edit node; Ctrl+D duplicate node; Ctrl+Shift+N a note in the centre of the visible area; Delete delete selection; Ctrl+0 / Ctrl+= / Ctrl+- reset zoom / zoom in / zoom out; Ctrl+Shift+F fit map; Ctrl+F map search (search bar over the canvas, Enter/Shift+Enter jump between matches with centering and an accent frame, Esc close).
- Every global action is assignable (Settings → Hotkeys): the tab lists all 54 global actions (grouped by family: File / Edit / View / Node / Plugins / Help) with a filter box, so it is not only the ones that happen to have a shortcut, so File → Save As…, the exports, the map images, the backups, "Check statuses now", "Gather information", "Why is it offline?", "Reload plugins", "Run on selected servers", the minimap and the About window can get keys of your own, on top of the zoom family this release gave real keys. One row per action with a key recorder; a duplicate combination marks both rows and warns but still saves; an empty row means no hotkey (the menu item keeps working); "Reset to defaults" puts every row back at once. Stored in `~/.sshmap/config.json` and applied instantly, no restart. Multi-input keeps its own rule: whatever key you pick works only while the mode is on, so it never steals a key from your shell.
- The terminal canvas keeps its own keys (F1–F12, Ctrl+C/D/Z, arrows): they are xterm protocol and deliberately not configurable.
- Multi-selection: Ctrl+click on a node adds to the selection (native Qt); Ctrl+drag on empty space is rubber-band selection (Shift+Ctrl adds to current). Group drag moves all selected; right-click during multi-selection offers "Connect selected" / "Delete selected" (one confirmation, guarded per item).
- Ctrl+K opens the command palette (`ui/command_palette.py`): fuzzy search (subsequence scoring, no dependencies) over all menu QActions + project servers + commands contributed by plugins (their own section after the servers, so a plugin can never shadow a built-in command; the text is the plugin author's). Selecting a server selects the node and centers on it. Enter/Up/Down/Esc navigate. With an EMPTY query it opens on a bounded "Start here" list (the actions you already ran in this session, then the frequent ones) instead of a wall of rows.
- The shortcut list: `?` on the map or F1 (Help → Keyboard shortcuts) opens a window with every action and the key you gave it — the same list Help → About renders, straight from the registry, so it can never go stale.
- **The map works from the keyboard** (v1.5rc4): Tab/Shift+Tab walk the cards in reading order, the arrow keys move the selection to the nearest card in that direction, Enter (or Space) opens it exactly as a double click does (properties or SSH, per the Map setting) and Esc clears the selection. Ctrl+Tab hands the keyboard to the next domain — and the map, the sidebar and the terminal canvas each show a thin accent frame while they own the keys, so "where do my keys go" has a visible answer.
- **The chrome adapts to a narrow window** (v1.5rc4): the toolbar keeps its essential buttons and moves the rest into a "»" menu instead of squeezing them, and the status bar drops the "Servers / Connections" totals while keeping the clickable status counters and the zoom; Settings gained a search box above its tabs, so a setting is one word away.
- **Reliability fixes** (v1.5rc5): a remote upload can no longer lose both copies when the publish step fails after the destination was cleared (the `.part` file is kept, with its path in the error), a collapsed command panel gives its width back to the terminal, a connection failure is reported in the user's language on both connect paths, the first-run buttons are visible again, the tag strip no longer paints over the card's status frame, a folded minimap keeps its right edge, and a stray `|` in a YAML value no longer colours the lines below it.

### Security
Passwords: keyring only (profiles as `"profile:{id}"`, servers by server_id). If the keyring is unavailable, the app works but passwords do not survive a restart. External terminal: the password is entered by the OS ssh client, never in argv.

**Limitations:**
- TOFU on first connect: a host key that is not in `~/.sshmap/known_hosts` is accepted automatically (the fingerprint is shown in the log). That is standard paramiko-client behaviour, but it is not full MITM protection on the very first connection; protection kicks in when an already-recorded key changes. For critical hosts, verify the first-connect fingerprint over a trusted channel.
- Windows / keyring: only the Windows Credential Manager system backend (`keyrings.win.*`, requires pywin32; uncomment it in requirements.txt) is accepted. Plaintext file fallback backends (`keyrings.alt.file`) are rejected; better not to save passwords than leak them into a plaintext file. On Linux/macOS, `keyrings.alt.*` backends are also rejected. If no secure backend is available, the app works but passwords are not saved between runs.

---

## 5. PySide6 / Qt 6.11 Gotchas (required knowledge)

| Issue | Solution |
|---|---|
| Mouse input in QGraphicsView tests | Only `PySide6.QtTest.QTest.mousePress/Move/Release/DClick` works; hand-crafted QMouseEvents are ignored by the core |
| Monkey-patching C++ slots with return values (`itemChange`, `eventFilter`) | FORBIDDEN: infinite recursion or Access Violation 0xC0000005. Only subclass overrides |
| `QPropertyAnimation(target=QGraphicsItem)` | Does not work ("non-existing property opacity") → use QVariantAnimation |
| `QGraphicsItemGroup.boundingRect()` | Not recomputed from children (zero rect) → explicit override (see ServerNode) |
| `itemChange(ItemPositionChange)` | Called BEFORE the position is applied → pass target rects explicitly (the resync_group_members pattern) |
| QGraphicsProxyWidget "eats" the mouse | StickyNote/NodeGroup dragging is handled manually; MapView temporarily switches dragMode to NoDrag |
| strokeToFill/strokedPath QPainterPath | Not bound in PySide6 → arrow hit zone via a custom contains() with curve sampling |
| QWidget focusIn/focusOut signals | Do not exist in Qt6 → eventFilter |
| Death of the Python QAction wrapper with an attached QMenu | PySide6 6.11 destroys the C++ QMenu along with it (verified offscreen and native); temporary wrappers from `menubar.actions()`/`act.menu()` were killing ALL menus except the last one, e.g. when opening the Ctrl+K palette and switching language. Cure: keep such QActions permanently (`MainWindow._qaction_guard`) + avoid `action.menu()` where a direct path exists (the `_menu_i18n` registry) |
| `QPdfWriter` coordinates | Paints in device pixels at `resolution()` (1200 dpi by default) while the page layout is in points → set the resolution and draw into `device.width()/height()`. `QPageLayout` also transposes a custom size for Landscape (pass the portrait form). The PDF-export fix |

---

## 6. i18n

```python
from i18n import t, set_language, get_available_languages
t("btn.add_server", alias="web-1")   # {alias} formatting
```

Built-in languages: en (default), ru, zh, de; any other language joins by dropping one JSON file into `~/.sshmap/languages/`, without touching the installed package.

- Adding a language takes one JSON file. Every `i18n/*.json` is a language: the file name is the code, the root key `"name"` is the display name in the menus, and a BOM is fine. Drop it into `~/.sshmap/languages/`; Help → Language rescans the folder on every open (no code change, no restart).
- A file in `~/.sshmap/languages/` shadows the built-in language of the same code; a new code adds a language. The folder appears only when you use it.
- Settings → Language imports a file after checking it (object root, at least one translation key, a `"name"`); an incomplete file is imported with a note and the rest falls back to English. It also exports the active language, or the English template to start a new one. A file that cannot be used is refused; the folder stays clean.
- The rule for contributors: a new key goes into all files at once, and each built-in language must cover 100% of en in keys, `{placeholders}` and line breaks. A deliberately incomplete translation may declare itself with `"partial": true`, which turns its missing keys into warnings instead of defects. Check: `python tests/check_i18n_keys.py`.
- Hot-path modules (`ssh_worker`, `ssh_terminal`) use a cached `get_translator()`.

---

## 7. State & Roadmap

**Implemented features** (details in sections 3–4):
- a first run that explains itself: an **example map built in code** (five nodes, six connections covering every type, a group, a note, tags — all on documentation addresses, with clearly **marked emulated statuses**), and a status bar that offers **Undo** right where a delete, a disconnect or an import happened
- statuses with an age: the tooltip says when a result was taken, and an old one turns grey (keeping its shape) instead of pretending to be current — an emulated demo status never claims one
- collected facts with an age (v1.5.3): the info plaque says when the OS/CPU/RAM/disk data was measured and turns grey after a week — the values never change, and an old project simply shows no age
- one click gathers the system info of the selection (or the whole map): a bounded queue, a per-server guard, live progress and a closing line that names the failures
- **"why is it offline?"** (v1.5.3): one on-demand report per server — DNS → TCP → SSH banner → ICMP ping — names the first failing step in its own words and lands in the tooltip, the status bar and the activity history; the status itself is never changed
- **trouble first** (v1.5.4): a group answers for its members — the worst status as its own shape plus the
  counts (`Offline 2 · Warn 1`) on the frame (the fold keeps it, an empty group says so, and nothing of it is
  ever written to the project file), one click on the status bar dims everything that is not warn / offline /
  stale while the counters keep their totals, and a floating plaque names every active filter (the search, the
  tag, the status, the lens) with one × each — so a forgotten filter can no longer look like deleted servers
- the card names its environment: the primary tag (`prod` / `staging` / `dev` / …) as text above the alias, so an environment is never just the colour of a status
- floating panels that come back: drop the legend or the minimap at the edge it hangs from and it re-anchors to its corner (the dragged position is forgotten)
- the command palette on the first screen: an empty Ctrl+K opens a short "Start here" list, the empty map names the key, and `?` / F1 open the shortcut list built from the registry
- interactive map: nodes, Bezier connections of 6 types (one-way or bidirectional), notes, groups, background image with drag/resize
- big-picture level: a minimap panel (the whole scheme at fit scale + viewport frame; click or drag it to move the view, View → Minimap), a soft drop-shadow on every card (one cached pixmap per card size) and the group fold: one click turns a cluster into a grid of badges, Ctrl+Z brings the cards back
- node statuses online/warn/offline: parallel SSH probes with auto-interval for large maps; "Check statuses now" for a selection
- note pinning: a pinned note follows its server on any movement; undoable, survives save/load
- multi-selection: Ctrl+click, rubber band, group drag, connect/delete selected; tags with sidebar filter
- map search (Ctrl+F): match highlighting, Enter/Shift+Enter navigation, dimming of non-matches
- quick launch per server: URLs (default browser) and commands (first terminal command)
- collapsible sidebar and map panels, at most one collapsed at a time; collapse state, divider and panel widths persist. Collapsing the map is list mode (below)
- context menus for all objects; fit/zoom/centering, with zoom as actions (Ctrl+0 / Ctrl+= / Ctrl+-) next to the wheel
- the project always within reach: File → Recent (last 10 maps), a `.json`/`.sshmap` dropped onto the window, and an unreadable file offers its autosave or backup instead of a dead end
- built-in SSH terminal on pyte (scrollback, full keyboard, mouse selection with word/line clicks, context menu) + external system terminal
- terminal output tools: search the screen and scrollback (Ctrl+Shift+F), clear the scrollback, reset a mangled screen, save a transcript
- SFTP tab over the same SSH connection: navigation, upload/download including drag & drop, read-only text preview (≤ 1 MB) with non-previewable rows marked
- SFTP file manager: new folder / rename / delete, overwrite prompt, transfers that never truncate the destination, rate and ETA, a row dragged out as its remote path
- multiple sessions as tabs in separate windows or a detachable "Terminals" dock on the map; switch without restart
- terminal split: a second shell of the same node in a pane below (draggable, remembered, not counted by the session limit)
- multi-input: typing in the focused session is broadcast to all other open sessions (F12 exits), with per-session exclusions
- command library (macros): one click sends a saved command/script to the active terminal (single-line raw, multi-line bracketed paste)
- undo/redo of scene operations including groups and note pinning
- automatic info collection for Linux servers (OS/CPU/RAM/disk) — one server from a context menu, a whole selection or the whole map through the bounded batch, each measurement dated so the card can show its age; profiles with passwords in the OS keyring, never written to JSON
- autosave + ring buffer of backups with rollback (File → Backups…)
- export to PNG/JPEG/PDF, SVG and draw.io `.drawio` (tags and comment included) — print-friendly by default: a light page with high-contrast lines, the six connection types kept apart by their line style; one checkbox switches to the current theme; bulk server import from TXT and from `~/.ssh/config` (alias, host, user, port and key file; checkbox picker; one undo for the whole batch)
- i18n: en (default), ru, zh, de plus any language as one dropped-in JSON file; no code changes, the UI follows a switch live
- your own languages in `~/.sshmap/languages/` (a file there shadows the built-in of the same code); Help → Language rescans, Settings → Language imports and exports
- settings hub: single `~/.sshmap/config.json`, live application without restart, every user-facing key in one place
- dark or light theme with your own accent colour: Settings → Appearance; the dark theme stays default, the light one is a slate palette on the same Theme object, and the accent is one hue (eight presets or any colour) that generates its shades; a third mode follows the system's light/dark setting; it applies live before you press OK, Cancel puts the previous look back
- readable in both themes: the accent has a decorative and a strong role (borders vs. text and fills), the light palette was re-tuned against the surface each tone is drawn on, and a contrast gate in the suite keeps it honest — a colour without a threshold or a written exemption fails the tests
- the interface no longer explains itself in colour alone: each connection type has its own line style (solid / dashed / dotted / dash-dot / double / long dash) and each status its own shape (dot / ring / triangle), the legend shows a sample of both, and a second gate keeps the two channels honest
- print-friendly exports: a light page with high-contrast lines by default, with "use the current theme" as a one-click opt-out in the export dialog
- map images without a screenshot tool: **Copy the map as an image** puts the 2× render of your current theme on the clipboard (no dialog), and **Save Documentation Image…** writes a fixed 1600×900 @2× poster of the map for a README, an issue or a slide
- an activity history (View → **Activity panel**): what just happened — probe rounds, imports, transfers, plugin errors, theme and language fallbacks — newest first, with a level filter and Clear. It is memory only (the last 200 events) and never a second status bar; the log file gains the same facts
- motion: the map glides instead of jumping (Show on map, Fit map), a new server scales in, hovering a connection dims everything but its two ends; every animation is interruptible, so the wheel or a drag always wins, and one switch turns the motion off entirely
- three theme modes: dark, light and Auto (system), which follows the operating system's colour scheme without a restart
- denser interface and friendlier first run: sidebar buttons became a compact grid, an empty map shows how to start, status counters filter the sidebar with one click, and a small legend explains arrow colours and statuses (hide it, fold it or drag it; it remembers where it was)
- list mode: collapse the map and the sidebar becomes the server table its width always allowed: alias, host, status, OS, CPU, RAM, disk and tags with the same search, filters and row menu
- syntax highlighting in the SFTP viewer: numbers in any text file; JSON and XML coloured only when they really parse; YAML marked as the heuristic it is; only visible lines painted so a 1 MB file opens immediately
- hotkeys + command palette (Ctrl+K): the full action registry is editable in Settings → Hotkeys (reset to defaults, duplicates flagged), applied without restart
- Help → About: version, license, `~/.sshmap` paths and a hotkey cheat-sheet built from the registry
- plugins: an installed package (`pip install sshmap-<name>-plugin`) or one file dropped into `~/.sshmap/plugins/`; the Plugins menu switches them and re-scans without restart; a broken plugin is reported, never fatal (contract in PLUGINS.md)
- what a plugin can do: run a command on selected servers (one result each, credentials resolved by the app)
- a plugin can also contribute a status to a node (the worse of the two wins, shown in the card tooltip) and add Ctrl+K commands and node-menu rows
- nothing a plugin does can freeze the window: UI hooks are timed, background hooks run on managed threads, a hung hook is abandoned
- two working examples in `examples/plugins/`: hello.py and disk_monitor.py (df -hP on the servers you select → warn card with the mount point in the tooltip)

**Known limitations:**
- undo/redo does not cover node statuses or background geometry (§4 "Undo/Redo")
- the background image is stored by path: move the file together with the project
- TOFU on first connect and keyring backend restrictions (§4 "Security")
- plugins run inside the application's process: a plugin with a broken C extension can take it down; install plugins you trust

**Roadmap** (tasks, order, acceptance in ROADMAP.md):
- next: the inventory export (sorting, CSV/TSV, more columns for the list mode). The trouble-first release shipped in v1.5.4

---

## 8. License & Security
- MIT License (LICENSE).
- Security model and its limitations: see §4 "Security".
