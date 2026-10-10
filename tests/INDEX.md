# tests/ — SSHMap test suite map

The suite is plain-python scripts **without pytest**: each file is self-contained,
prints `ok`/`FAIL` per check and exits 0 (all green) or 1.
Shared harness — `_common.py`; a single run of all files — `run_all.py`.

## Running

```
python tests/run_all.py                 # all test_*.py + check_i18n_keys.py, auto workers (cores, <=16), longest file first, table
python tests/run_all.py --workers 8     # number of workers (1 = sequential)
python tests/run_all.py keyring         # only files whose name contains the substring
python tests/run_all.py --fast          # daily profile: without slow/network tags
python tests/run_all.py --tag network   # only files with the given tag (real network mode, see below)
python tests/run_all.py --failed-only   # only files that failed in the previous run
python tests/run_all.py --junit [PATH]  # JUnit XML (default test-results/junit.xml)
python tests/test_tags.py               # a single file (from the project root)
```

File tags: a `# tags: slow network` comment in the header (the first such line
within the first 40 lines; read as text, without importing the file). Known tags:
`slow` — intentionally long wait budgets/teardown (part of the spec),
`network` — the file contains a real network section that runs ONLY under
an explicit `--tag network`: the runner passes the tag to the child process via the
env var `SSHMAP_TEST_TAGS`, the test switches to the real mode (test_diagnostics.py —
a real ping of TEST-NET-1, ~10 s); a regular run of such a file is hermetic and fast.
`--fast` excludes slow+network, `--tag NAME` selects files with the tag.

Run artifacts — in `test-results/` (gitignored): `junit.xml` (the per-file
JUnit report for CI) and `last_run.json` (the status cache for `--failed-only`; updated
after each run).

Each file — a separate process: `bootstrap()` inside performs HOME isolation
(tests write `~/.sshmap/*` into a sandbox), the offscreen Qt platform, UTF-8 stdout
and a faulthandler timeout of 180 s. Disable HOME isolation:
`SSHMAP_TEST_NO_HOME_ISOLATION=1`. During a parallel run the runner gives
each file its own working directory (`SSHMAP_TEST_WORKDIR`, created in
%TEMP% and deleted on exit) — otherwise the `bootstrap()` of a neighboring process
would clobber the shared `_tmp_testdata`.

## Harness (_common.py)

The file pattern (bootstrap — FIRST, before importing the app modules):

```python
from _common import bootstrap, check, finish
ROOT, WORK = bootstrap()          # HOME isolation, offscreen, sys.path, faulthandler
...test body: check("name", condition, detail)...
finish()                          # summary + exit code + file time
```

`check()` measures the time of the segment up to the check (since the previous `check()`);
`finish()` prints "slowest checks" (top-20 segments, only if any is >= 0.1 s)
and the total time in the summary line: `ALL PASS (N) [X.XXs]`.

Helper utilities: `wait_until(cond)` — a real Qt event loop until the condition;
`wait_for(predicate)` (v1.4.1) — the same wait as a BOOL, driving `processEvents() in a sleep loop
(for a predicate fed by plain threads; `check(..., wait_for(...))` therefore fails honestly on a
timeout — do not swap it for `wait_until`, whose return is `None`);
`viewport_point(view, scene_pos)` — scene → viewport coordinates;
`snapshot_i18n_config()` / `restore_i18n_config()` — a snapshot of the i18n config
(needed only with SSHMAP_TEST_NO_HOME_ISOLATION=1).

**The config.json fixture (v1.4.1):** `cfg_path()` / `read_cfg(default=None)` / `write_cfg(data)` /
`merge_cfg(data)` / `clear_cfg(*extra_paths)` — ONE implementation of what 21 files used to
re-declare under three spellings (`_cfg_path`/`write_config`/`clear_config`,
`CFG_PATH`/`read_cfg`/`write_cfg`, `cfg_path`/`read_config`). Two behaviours were previously a
per-file accident and are now explicit: a MISSING file reads as `{}` or `None` (the `default`
argument), and a write REPLACES the document (`write_cfg`) or MERGES it (`merge_cfg`, the
`i18n.save_config` semantics). Call them after `bootstrap()`.

Shared stubs (`tests/_fakes.py`): `QuestionStub` (v1.4.1) replaces `QMessageBox.question` and
records the calls — `install(module)` / `restore()`, `answer` (settable between the phases),
`replies` (a queue), `calls` and an optional `record(title, text)` journal; it subsumes the 15
hand-written `_fake_question()` copies and their `_orig_question` save/restore pairs.

Release pins and shared checks (at the bottom of the file): the constants
`EXPECTED_APP_VERSION` / `EXPECTED_I18N_KEYS` + the i18n policy constants
`I18N_META_KEYS` (the language-file meta keys, "name") / `I18N_REFERENCE` ("en") —
update at every release ONLY here; `i18n_lang_codes(root)` / `translation_keys(data)` /
`load_i18n_langs(root)` — the auto-discovery of ALL i18n/*.json (v1.3.3: the file name is
the code) and the loading of their TRANSLATION keys; `i18n_parity_problems(langs)` —
the pure defect list (strict parity vs en + the pinned count); `check_i18n_parity(langs)` —
the same as one check; `check_release_state(root)` — APP_VERSION
(sentinel + format X.Y.Z[.W][RCn]) + the pyproject cross-check + the requirements.txt header.

## Suite files

The table below is **auto-generated** by `tests/_gen_index.py` from the files'
docstrings and tags (the same set of test_*.py that run_all.py launches). Do not edit by hand:
after adding/renaming a file or changing its docstring/tags —
`python tests/_gen_index.py` (a freshness check without writing — `--check`, for CI and
the release gate). The full coverage description of each file — in the module docstring
of the file itself.

<!-- AUTOGEN:BEGIN test-files -->

| file | tags | what it checks (first line of the docstring) |
|---|---|---|
| `test_actions_keyboard.py` | — | v1.3.3.3 — The action registry, completed: keyboard, on-demand operations, About. |
| `test_activity_panel.py` | — | v1.5.2 — the activity panel: the history the interface never kept. |
| `test_alt_screen.py` | — | v1.2.12 — Terminal: alternate screen (private modes 47/1047/1048/1049). |
| `test_audit_rc1_threads.py` | slow | v1.2.10rc1 — Audit: threads and teardown (the auto #2 and manual #1 findings plus a verification one). |
| `test_audit_rc2_robustness.py` | — | v1.2.10rc2 — Audit: robustness and code hygiene (the manual #5/#6 and auto #7 findings). |
| `test_audit_v1210.py` | — | v1.2.10 — Audit: confirmed bugs and data (AUDIT.md): the release's themed test. |
| `test_audit_v15rc5.py` | — | v1.5rc5 — the review batch (hardening): the batch-level checks of the nine defects. |
| `test_audit_v161.py` | — | v1.6.1 — the review batch (hardening): the shipped facts, the guards and the leftovers. |
| `test_autosave_backups.py` | — | Regression v0.9.7 — autosave + the project backup ring buffer. |
| `test_bidirectional_arrows.py` | — | Bidirectional arrows (v1.2.6, ROADMAP task 1). |
| `test_bookmarks.py` | — | v1.6.7 — The bookmarks: ONE application-level place for the links the team uses. |
| `test_canvas_truth.py` | — | v1.6.3 — the canvas at the cell: the glyph grid, the mouse the TUI asks for, the Files tab that answers back. |
| `test_chrome.py` | — | v1.5rc4 — Density, focus & findability: the chrome answers the same questions as the map. |
| `test_collapse.py` | — | Server card collapsing v0.8.4 (former DESIGN.md §D) (former tests/smoke_collapse.py). |
| `test_command_guard.py` | — | v1.9.6 — the command guard: the PURE classifier, the policy, the ONE dialog and its doors. |
| `test_command_library.py` | — | Terminal macros: the command/script library of the terminal panel. |
| `test_command_library_file.py` | — | v1.8.2 — the command library as a first-class FILE: the door, the ring and the import/export pair. |
| `test_connections.py` | — | Connections: Bézier arrows, types, edge-to-edge, drag mode (former smoke_test.py §6b "v0.7"). |
| `test_context_menus.py` | — | Node and arrow context menus v0.7.3 (a former smoke-test part). |
| `test_core.py` | — | Suite core (former smoke_test.py §1–5): compile, i18n, models, ANSI, profiles/keyring. |
| `test_diagnostics.py` | network | `services/diagnostics.py`: `PingThread` + `ReverseDnsThread` (v0.9.9.3). |
| `test_docs.py` | — | The documentation-consistency guards (the changelog family, ROADMAP, the counters, INDEX freshness, the code-comment budget). |
| `test_drawio_export.py` | — | Map export to drawio (.drawio) v0.9.5 (a former smoke test). |
| `test_duplicate_multiselect.py` | — | Regression v0.9.3: node duplication + multi-select + group drag. |
| `test_elevated_pane.py` | — | The ELEVATED Files pane (v1.8): the sudo command table and its allowlist, the handshake over a |
| `test_elevated_pane_contract.py` | — | The clause audit of `ELEVATED_PANE.md` (v1.8) against the SHIPPED code — one section per clause |
| `test_encoding.py` | — | v1.5rc2 — the ENCODING gate: "no meaning in a colour alone" + the print-friendly export. |
| `test_export_background.py` | — | Regression v0.9.1: map export to image + background image. |
| `test_export_fidelity.py` | — | v1.3.3.7 — Export fidelity: the drawio vertex keeps the map's data, SVG joins the formats. |
| `test_ext_terminal_dialog.py` | — | Regression v0.9.9.2 — the external terminal UI (presets and reset to defaults). |
| `test_external_terminal.py` | — | External (system) terminal v0.8.2: `modules/external_terminal.py` (a former smoke-test part). |
| `test_facts_on_request.py` | — | v1.6.6 — the measurement you asked for: the status round you start, and the data mount that holds the capacity. |
| `test_files_followup.py` | — | The Files surface's first follow-up (v1.7.5): the listing that SORTS, the preview the user SIZES |
| `test_files_surface.py` | — | The Files surface (v1.7.3): the cross-session send, the per-server memory, the pane drop, the wrapping reader. |
| `test_first_run.py` | — | v1.5rc3 — First run & confidence: the demo map, the undo affordance and the age of a status. |
| `test_freshness.py` | — | v1.5.3 — freshness everywhere: the collected facts get an age, and a red card answers "why". |
| `test_groups.py` | — | Node groups on the map v0.8.1 (the "v0.8.1 groups" part of the old smoke test). |
| `test_hardening_v1751.py` | — | The v1.7.5.1 hardening patch: the nine LOCAL security defects of the shipped ledger. |
| `test_hardening_v1811.py` | — | The hardening patch of the 1.8.1 line (v1.8.1.1): the ONE atomic writer, the send identity, the spool and the two document guards. |
| `test_hotkeys_config.py` | — | v1.3.2 — Configurable hotkeys (QKeySequenceEdit, action registry): the release's test. |
| `test_hotkeys_palette.py` | — | Hotkeys and command palette v0.9.2 (a former smoke-test part). |
| `test_i18n_languages.py` | — | v1.3.3 — Languages without writing code ("name" in JSON + parity policy + documentation): the release's themed test. |
| `test_i18n_live.py` | slow | v1.3.3.1 — Live i18n: the containers follow a language switch + the checks of the policy. |
| `test_inventory.py` | — | v1.5.5 — The inventory: the LIST mode becomes a report (ROADMAP v1.5.5). |
| `test_keyring_fail_backend.py` | — | Regression v0.9.4b: the keyring fail backend + review notes. |
| `test_keyring_validation.py` | — | Regression v0.9.5.5 (security #1): the keyring backend — validation and guard. |
| `test_language_folder.py` | — | v1.3.3.8 — the user language folder, the import/export manager and ONE `terminal_max_open` range. |
| `test_last_mile.py` | — | v1.6.8 — The last mile, closing the line: the gesture the map already had, and the problem set it already knew. |
| `test_list_mode.py` | — | v1.4.6 — List mode: collapsing the map = server parameters (ROADMAP v1.4.6). |
| `test_local_pane.py` | — | The LOCAL pane (v1.7.4rc2): the provider seam, the two path dialects, the OS listing of the |
| `test_local_pane_contract.py` | — | v1.7.4 — the LOCAL pane, the closing release: the CLAUSE AUDIT of the frozen contract |
| `test_main_window_split.py` | — | v1.1.4: main_window.py hygiene — split into mixins (ROADMAP v1.1.4; the v1.8rc1/rc2/rc3 waves add nineteen). |
| `test_map_answers.py` | — | v1.8.4 — the map arranges itself and answers: the whole-map layout, the reverse traversal, the inode fact. |
| `test_map_bigpicture.py` | — | v1.4.2 — The big-picture map level: the minimap, the cached card drop-shadow, the group fold. |
| `test_map_images.py` | — | v1.5.1 — map images: "Copy Map as Image" and the fixed-frame documentation poster. |
| `test_map_scale.py` | — | v1.6 — the map at scale: bulk editing, density, arrangement and the connections out. |
| `test_map_search.py` | — | Regression v0.9.8 — map search (Ctrl+F). |
| `test_menu_actions_regression.py` | — | REGRESSION: the real click path on checkable menu items (`QAction.trigger()`). |
| `test_module_split.py` | — | `1.8rc3` — waves 1–3 of the MainWindow split: the mixins, the facade and the structural pins. |
| `test_motion.py` | — | v1.4.4 — Motion: the standards, the camera flights, the node scale-in, the hover focus/dim. |
| `test_multi_input.py` | — | Multi-input: broadcasting the active session's keystrokes to the other sessions. |
| `test_multi_input_e2e.py` | — | v1.2.4 — Multi-input: E2E on REAL SSH channels (paramiko), no fake threads. |
| `test_node_labels.py` | — | Review fixes v0.8.0: node elide and max width, status markers in the sidebar (a former smoke-test part). |
| `test_note_attach.py` | — | v1.2.4: attaching notes to servers + a special line (the v1.2.4 release theme). |
| `test_notes.py` | — | Sticky notes: drag / resize / edit / delete plus the JSON round trip (a former smoke-test part). |
| `test_pdf_export.py` | — | v0.9.9.7 — Map PDF export (ROADMAP v0.9.9.7); the page geometry is pinned in §6 of this file. |
| `test_plugin_command.py` | — | v1.9.3 — the CORE-owned command dialog: the door, its targets and the rows it produces. |
| `test_plugin_examples.py` | — | v1.4 — the example plugins of `examples/plugins/` (the minimal one and the two monitors). |
| `test_plugin_examples_local.py` | — | v1.9.4 — the two examples whose fact is LOCAL (`examples/plugins/certificates.py`, `watch_command.py`). |
| `test_plugin_examples_monitors.py` | — | v1.9.2 — the two PROVEN examples (`examples/plugins/open_ports.py`, `app_versions.py`). |
| `test_plugin_runtime.py` | — | v1.4rc2 — Plugin foundation, part 2: `PluginContext` and Main Thread isolation |
| `test_plugin_ui.py` | — | v1.4rc3 — Plugin foundation, part 3: the UI hooks and dogfooding (ROADMAP tasks 7–9). |
| `test_plugins.py` | — | v1.4rc1 — Plugin foundation, part 1: discovery and manager (ROADMAP v1.4rc1). |
| `test_plugins_panel.py` | — | v1.8.3 — the Plugins window: the plugin list, the server list and the session event ring. |
| `test_problem_first.py` | — | v1.5.4 — trouble first: the map answers "where is the problem". |
| `test_production_guard.py` | — | v1.9 — the production-tag guard: ONE policy, ONE dialog and the TWO verbs' call sites. |
| `test_project_lifecycle.py` | — | v1.3.3.6 (ROADMAP "Projects: open, recover, remember"): the life cycle of a project file. |
| `test_pyproject.py` | — | v0.9.9.6 — pyproject.toml: installable identity for 1.0 (ROADMAP). |
| `test_pyte_compat.py` | — | v1.2.11 — Terminal: pyte 0.8.2 compatibility (private SGR + LNM). |
| `test_pyte_fork.py` | — | v1.3rc1 — Terminal: the managed pyte fork (vendored 0.8.2 + patch manifest); v1.5.7.1 — the |
| `test_pyte_hardening.py` | — | v1.5.7.1 — Terminal: the pyte fork takes the five defects of the dependency audit. |
| `test_quick_launch.py` | — | v1.0RC4 — Quick launch (server links and commands): the release's themed test. |
| `test_rc2_map_import_sidebar.py` | — | v1.1.2RC2 — Map, import, sidebar (release theme). |
| `test_rc3_terminal_window.py` | — | Terminal windows: the DECCKM arrows, the split pane and the window-level bridges. |
| `test_release_v15.py` | — | v1.5 — the release that closes the 1.5 line: the environment badge, the panel snap, |
| `test_rubber_band_perf.py` | — | v1.2.10rc3 — rubber-band selection performance on large maps (the audit's auto #9). |
| `test_save_load.py` | — | Headless project save/load + keyring passwords (former smoke_test.py §6 "main window"). |
| `test_scrollback_batching.py` | — | v1.2.14 — Scrollback: batching of the auto-return to the live line (PYTE82_AUDIT.md batch D2). |
| `test_selection_sync.py` | — | Regression v0.9.9.1 — selection sync without blockSignals (a reentry guard). |
| `test_settings_dialog.py` | — | v1.1 — Settings dialog (hub): the release's themed test. |
| `test_settings_options.py` | — | v1.1.1 — Small options around the hub: the release's themed test (ROADMAP v1.1.1). |
| `test_sftp_commander.py` | — | The Files Commander, step 2: the copy and the move across the panes. |
| `test_sftp_commander_contract.py` | — | v1.7 — Files Commander, the closing release: the CLAUSE AUDIT of the frozen contract |
| `test_sftp_commander_keys.py` | — | The Files Commander, step 3: the mc/far walk, the hint row and the preview of the other pane. |
| `test_sftp_dnd.py` | — | Drag & drop of files from the desktop into the SFTP tab. |
| `test_sftp_ops.py` | — | SFTP as a file manager: the operations and an atomic (loss-free) transfer. |
| `test_sftp_pane_split.py` | — | The two waves of the `sftp_tab.py` split: `_SftpPane` is a FACADE over six pane mixins. |
| `test_sftp_syntax.py` | — | v1.4.7 — Syntax highlighting in the SFTP viewer (numbers, JSON/XML/YAML, ROADMAP v1.4.7). |
| `test_sftp_tab.py` | — | v1.1.3 — SFTP tab in the terminal window (ROADMAP v1.1.3, tasks 1–5). |
| `test_sftp_viewer.py` | — | v1.3.1 — File viewer in the SFTP tab (text ≤ 1 MB over SFTP, ROADMAP v1.3.1). |
| `test_sidebar_context_menu.py` | — | Regression v0.9.6 — the context menu in the sidebar (the server list). |
| `test_sidebar_panel.py` | — | `ui/sidebar.py`: `SidebarPanel` — a facade of `MainWindow` plus `retranslate` (v0.9.9.4). |
| `test_ssh_config_import.py` | — | v1.4.1 — Import from ~/.ssh/config (ROADMAP v1.4.1, tasks 1–6). |
| `test_ssh_connect.py` | — | `modules/ssh_connect.py` — the ONE connect builder (`N50`'s consolidation, `AGENTS.md` §4.4). |
| `test_ssh_dialogs.py` | — | SSH dialogs: assembly, keyring save v0.9.5.6, the "Connect" button (former smoke_test §6a+§7). |
| `test_ssh_terminal.py` | — | Regression tests v0.8.1 — four fixes. |
| `test_ssh_undo_lifecycle.py` | — | v1.1.2RC1 — the SSH path: undo, paramiko defaults, thread lifecycle (release theme). |
| `test_status_checker.py` | — | Server statuses: probe_ssh, node colors, pulse, StatusChecker (former smoke_test §6d). |
| `test_status_parallel.py` | — | v1.1.2 final — Parallel status probes (release theme, ROADMAP v1.1.2 final). |
| `test_system_info.py` | — | Auto-fill of server data v0.9: `services/system_info_collector.py` (a former smoke-test part). |
| `test_tags.py` | — | Regression v0.9.4: server tags/color labels. |
| `test_terminal_acceptance.py` | — | v1.0 — Terminal v1, final: full acceptance of all RCs + terminal_* config (ROADMAP tasks 9–10). |
| `test_terminal_colors.py` | — | v1.0RC1 — the color engine + per-cell canvas (ROADMAP v1.0RC1). |
| `test_terminal_containers.py` | — | v1.7.2 — Terminal containers: the split in the dock, the single window, the merge and the titles. |
| `test_terminal_dock.py` | — | Terminals docked in the map window (`terminal_mode`: windows/tabs). |
| `test_terminal_ergonomics.py` | — | v1.6.4 — the cheap batch: the thread names, the marked secret, the Ctrl+wheel zoom and the activity dot. |
| `test_terminal_files_panel.py` | — | The Files tree as a right-hand panel of a standalone terminal window. |
| `test_terminal_history.py` | — | v1.5.7 — the command history: the terminal's third tab, one history per server. |
| `test_terminal_input.py` | — | v1.0RC2 — keyboard + selection/copy (ROADMAP v1.0RC2). |
| `test_terminal_links.py` | — | v1.9 — the `OSC 8` link of the canvas: the pure run hit test, the gesture, the allowlist and the underline. |
| `test_terminal_mouse.py` | — | v1.2.13 — the mouse wheel in the full-screen TUI (SGR/X10 passthrough) |
| `test_terminal_output.py` | — | Working with the terminal's output: the find bar, the reset and the transcript. |
| `test_terminal_page.py` | — | TerminalSessionPage — the session as a reusable widget (window → page). |
| `test_terminal_reconnect.py` | — | The reconnect of a session and the `tmux attach` that rides it (v1.9.1) — the ONE re-arm path. |
| `test_terminal_scroll.py` | — | v1.0RC3 — PTY resize + scrollback + dirty rendering (ROADMAP v1.0RC3). |
| `test_terminal_selection_menu.py` | — | v1.2.7 — Terminal: double/triple-click selection + context menu (ROADMAP v1.2.7). |
| `test_terminal_split.py` | — | v1.3.3.5 — Terminal split: a second pane under the sessions (ROADMAP v1.3.3.5). |
| `test_terminal_tabs.py` | — | v1.2.1 — Multiple SSH sessions as tabs in one terminal window (ROADMAP v1.2.1). |
| `test_terminal_truth.py` | — | v1.6.2 — the terminal that stops lying: a dead session, the DEC graphics, the column, the cursor. |
| `test_terminal_widget_split.py` | — | `1.8rc5` — the `terminal_widget.py` split: `TerminalWidget` becomes a facade over five canvas mixins. |
| `test_theme.py` | — | v1.1.5 → v1.4.3 — the central theme `ui/theme.py`: the `Theme` object, LIGHT, the accent hue. |
| `test_theme_contrast.py` | — | v1.5rc1 — the CONTRAST GATE: the LIGHT palette, the two accent roles and the numbers that pin them. |
| `test_trust_surface.py` | — | v1.8.1 — the trust and keys surface: the first connection ASKS, the store is manageable, a credential |
| `test_ui_density.py` | — | v1.4.5 — UI density & first run (ROADMAP v1.4.5): the compact sidebar grid, the first-run |
| `test_ui_entry.py` | — | v1.9.7 — the first ten minutes (ROADMAP v1.9.7): the card that is really compact, the Add |
| `test_ui_polish.py` | — | UI polish: nodes, grid, fit/zoom, status bar, icons, arrow hit zones (a former smoke-test part). |
| `test_ui_requests.py` | — | v1.5.6 — the customer requests: the Export menu, a third first-run button, environment |
| `test_undo_redo.py` | — | Regression tests v0.8.3 — Undo/Redo. |
| `test_unmanaged.py` | — | v1.6.5 — the neighbours on the map: a card for a server you do not administer. |
| `test_view_toggles.py` | — | Collapsing the sidebar and the map into a thin line (buttons + menu). |
| `test_wcwidth_cjk.py` | — | v1.2.9 — full wcwidth(3) for CJK (ROADMAP "Terminal hygiene", task 2). |
| `test_worker_guard.py` | slow | SSHWorker: the active threads registry + the node deletion guard (former smoke_test.py §6c). |

<!-- AUTOGEN:END test-files -->

## Helper files

| file | role |
|---|---|
| `_common.py` | the harness: bootstrap/check/finish/wait_until + the v1.4.1 shared fixtures — `wait_for` (a boolean wait) and the config.json family (`cfg_path`/`read_cfg`/`write_cfg`/`merge_cfg`/`clear_cfg`) (not a test — run_all skips it); check() times the segment, finish() prints "slowest checks" + the file time |
| `_fakes.py` | shared test fakes (suite optimization phase 2): FakeSSHChannel/FakeSSHThread/BlockingFakeSSHThread (the same API as SSHTerminalThread; RECORD — the channel capture mode "list"/"last"/None), CaptureMenu (captures exec/exec_ offscreen, the list — a class attribute captured), a fake SFTP (FakeSftpFS/File/Client + EventLog + wire_worker — the journal of the worker's signals, incl. the v1.3.1 read_ready as the kind "read"), FakeSSHClient/FakeTransport (the paramiko surface for the terminal window), FakeLineEdit/FakeSpinBox/DummySignal/FakeTermWin, FakeWidgetThread (the TerminalWidget level), QuestionStub (v1.4.1: a `QMessageBox.question` replacement — answer/replies/calls/record + install/restore). Not a test — run_all skips it; each test file is a separate process, so class attributes are configured without cross-interference |
| `run_all.py` | the single runner: collects exactly `test_*.py` + `check_i18n_keys.py` (itself and other meta-scripts are NOT included — otherwise recursion), in parallel (ThreadPoolExecutor, auto workers = cores ≤ 16 — v1.4.1, `--workers N`; the LONGEST file first — `order_files()`, the times from the cache of the previous run), each file — a separate process, a table + a single exit code. Flags: `--fast` (without the slow/network tags), `--tag NAME`, `--failed-only` (by the test-results/last_run.json cache), `--junit [PATH]` (JUnit XML into test-results/junit.xml). File tags — a `# tags: …` line in the header |
| `check_i18n_keys.py` | parity of the i18n keys en/ru/zh (the keys used in code × 3 languages) — included in run_all |
| `_gen_index.py` | auto-generation of the "Suite files" table below from the test_*.py docstrings and tags (ast, without importing; the file set and tag parsing — the same functions as in run_all.py). `python tests/_gen_index.py` — rewrites the block between the AUTOGEN markers; `--check` — a freshness check without writing (exit 1 on mismatch, for CI/gate). Not a test — run_all skips it |
| `_comment_budget.py` | the code-comment budget of `AGENTS.md` §12: `HISTORY_MARKERS` (the ONE release-narrative marker list, shared with §5 of test_docs.py) + the ratchet pins + the measurement (`measure()`), `report(check)` — the §6 checks — and `pin_block()`. `python tests/_comment_budget.py` prints the footprint (the narrative hits, the module-header lines, the worst blocks) and a paste-ready pin block; the pins may only go DOWN. Not a test — run_all skips it |
| `_refactor_diff.py` | "a comment cleanup did not touch the CODE": compares the working tree with a snapshot (`--tree <dir>`, a backup taken before, or `--git` for the committed state) by code, not by text — for every `.py` present in both the AST is compared with the docstrings STRIPPED, plus a second comparison with the string literals masked, which separates "a test label changed" from "the structure changed"; the non-`.py` files are compared byte for byte. Exit 0 ⇔ no structure changed and nothing was deleted. Not a test — run_all skips it (a snapshot tree is not part of the repository) |
| `_bench_rubber.py` | the v1.2.10rc3 measurement: a rubber-band drag over a 500-node map, ms before/after the fix (numbers — CHANGELOG.md); NOT part of the suite (files with the _ prefix are skipped by run_all) |
| `_bench_history.py` | the v1.2.12 measurement D1 (PYTE82_AUDIT.md batch D) + since v1.2.14 — a batching regression monitor: the HistoryScreen overhead with deep history — TerminalScreen(120, 32, history_lines=1000), ~1050 lines, the user at the top border (≈242 next_page in one feed), feeding an htop chunk (htop.input, 19 KB) → ms + baselines (the live line, a plain pyte.Screen); numbers — CHANGELOG.md v1.2.12 (the > 50 ms/chunk pain confirmed → v1.2.14) and v1.2.14 (after batching A ≈ B: 42.67 vs 42.42 ms, overhead 0.25 ms); verdict: "A ≈ B — batching works" / "BATCHING REGRESSION" (overhead > 5 ms or A > 50 ms); NOT part of the suite |

## Conventions

1. **New version → new themed file** `test_<topic>.py` (not "regression_vXXX"):
   the name says WHAT is checked, not when it was added; the provenance — in the docstring
   ("former regression_v098_map_search.py"). The file is self-contained: `bootstrap()` →
   checks → `finish()`.
2. **Mouse input** — only via `PySide6.QtTest.QTest` (widget) or a synthetic
   `QGraphicsSceneMouseEvent` for a QGraphicsItem (the v0.7.3 conclusion, see test_collapse.py).
3. **Release pins:** at each release update only `tests/_common.py` —
   `EXPECTED_APP_VERSION` (the version) and `EXPECTED_I18N_KEYS` (the parity of the
   TRANSLATION keys over all the discovered languages — en/ru/zh today; the meta key
   `"name"` is not counted, v1.3.3);
   the release-state sections of themed files call the shared
   `check_release_state()`, parity — `i18n_parity_problems()` / `check_i18n_parity()`
   (earlier: the "N keys" count in 12 files + version pins in 7 sections). Missing
   i18n keys against the code are caught by `check_i18n_keys.py` (which also enforces
   the parity over every `i18n/*.json`).
4. **HOME isolation is mandatory** for all tests writing to `~/.sshmap*`
   (bootstrap does it itself); do not touch the user's real home.
5. **Do not touch:** the MainWindow public API, the undo stack, the keyring password path,
   i18n keys (additions only) — the shared "Do not touch" of the v0.9.9.x series.
6. The suite must be green (`run_all.py` exit 0) at every release — a ROADMAP
   convention; the offscreen mode leaves no background threads.
7. **File tags:** `# tags: slow network` — a comment in the header (the first such
   line within the first 40 lines; in it — only tag names, the explanation — a separate
   comment nearby: everything after `# tags:` is parsed as tags).
   `slow` = intentionally long wait budgets/teardown,
   `network` = the file contains a real network section. The section runs only under
   an explicit `run_all.py --tag network` (the runner passes the tag into the env `SSHMAP_TEST_TAGS`,
   the test switches to the real mode by it); a regular run — hermetic/fast.
   `--fast` skips the slow/network files (daily profile), `--tag NAME` selects
   by tag. New slow/network tests are marked at creation; the network section
   of a new test must have a hermetic branch by default.
8. **Shared fakes — in `_fakes.py`:** a fake needed by a second test file
   is moved to `_fakes.py` (import with an alias: `from _fakes import FakeSSHThread
   as _FakeThread`) — duplicating class bodies across files is not allowed.
   File-specific values (passwords/paths/capture lists) stay in the test;
   configurable class attributes (CaptureMenu.captured, FakeTermWin.spawned,
   FakeWidgetThread.sent) are assigned before the scenario.
   The same rule covers the fixture HELPERS (v1.4.1): a local `_cfg_path`/`write_config`/
   `_fake_question`/`wait_until` copy is a defect — `_common.py` (config.json + waits) and
   `_fakes.py` (QuestionStub) own them, and the `record=`/`default=`/`answer` arguments
   carry the per-file differences that used to justify the copies.
9. **INDEX.md is auto-generated:** the "Suite files" table between the AUTOGEN markers —
   the output of `tests/_gen_index.py` (each file's first docstring line + tags);
   the module docstring is the single source of truth about coverage. After adding/
   renaming a test file or changing its docstring/tags run the generator;
   CI can keep `--check` (exit 1 if INDEX.md is stale). The first line of the module
   docstring must be a self-contained summary — it lands in the table as-is.
