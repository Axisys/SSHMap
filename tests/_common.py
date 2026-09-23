"""The common harness of the SSHMap tests (the scripts without pytest).

The pattern of every file tests/test_*.py:

    from _common import bootstrap, check, finish
    ROOT, WORK = bootstrap()   # FIRST — before the imports of the app modules

...the body of the test with check("name", condition, detail) ...

    finish()   # the summary + the exit code (0 = all the checks passed); prints the time of the file
               # and the "slowest checks" (segments >= 0.1 s — the top-20, see SLOW_REPORT_THRESHOLD)

Run all the tests:  python tests/run_all.py
The map of the files and the conventions:  tests/INDEX.md

What bootstrap() does:
  * UTF-8 stdout/stderr — the cp1251 console (the typical Russian Windows) does not
    drop the run with a UnicodeEncodeError on the "→" in the report;
  * the isolation of HOME/USERPROFILE into a temporary directory BEFORE the imports
    of the app modules: the tests write ~/.sshmap/config.json, ~/.sshmap_settings.json and the like —
    all the I/O goes to the sandbox, the real home is untouched (disabled by
    SSHMAP_TEST_NO_HOME_ISOLATION=1);
  * QT_QPA_PLATFORM=offscreen by default (if the user did not set their own);
  * sys.path: the root of the project; the working folder — a fresh one per run
    (_tmp_testdata, or $SSHMAP_TEST_WORKDIR under the parallel run_all.py);
  * the faulthandler timeout of 180 s: the hung offscreen (the modal) — the dump of the stacks and the exit.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time

PASS = []
FAIL = []

# Suite optimization phase 1: the time measurement. check() records how long it took
# the test segment BEFORE this check (time since the previous check()); finish()
# prints the "slowest checks" (only if there are checks >= SLOW_REPORT_THRESHOLD)
# and the total file time in the ALL PASS/FAILURES line. The check() signature is unchanged.
_T0 = None      # the file run start (sets bootstrap())
_LAST = None    # the moment of the last check()
_SLOW = []      # [(dt, name), …] — the segment time for every check
SLOW_REPORT_THRESHOLD = 0.1   # sec; the "slowest checks" output threshold


def bootstrap(faulthandler_timeout=180):
    """Initialize the test environment. Call before the imports of the app modules."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # an old Python without reconfigure — we live as before

    if os.environ.get("SSHMAP_TEST_NO_HOME_ISOLATION") != "1":
        _home = tempfile.mkdtemp(prefix="sshmap_test_home_")
        os.environ["HOME"] = _home
        os.environ["USERPROFILE"] = _home

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    # A parallel run_all.py passes a per-file unique directory via
    # SSHMAP_TEST_WORKDIR (otherwise the bootstrap() of the neighbouring process would wipe the scratch);
    # a single run — the fixed _tmp_testdata (gitignored).
    work = os.environ.get("SSHMAP_TEST_WORKDIR") or os.path.join(root, "_tmp_testdata")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    if faulthandler_timeout:
        import faulthandler
        faulthandler.dump_traceback_later(faulthandler_timeout, exit=True)

    global _T0, _LAST
    _T0 = time.monotonic()
    _LAST = _T0

    return root, work


def check(name, cond, detail=""):
    """One check: prints ok/FAIL and accumulates into PASS/FAIL.

    Additionally measures the time of the segment up to this check (since the previous
    check()) — finish() prints the top-20 of the slowest segments."""
    global _LAST
    dt = time.monotonic() - _LAST if _LAST is not None else 0.0
    _LAST = time.monotonic()
    _SLOW.append((dt, name))
    (PASS if cond else FAIL).append((name, detail))
    print(("  ok  " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


def finish():
    """The summary and the exit code: 0 = all the checks passed."""
    total = len(PASS) + len(FAIL)
    elapsed = time.monotonic() - _T0 if _T0 is not None else 0.0
    print()
    if FAIL:
        print(f"FAILURES ({len(FAIL)}) of {total}:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
        print(f"(file time: {elapsed:.2f} s)")
        sys.exit(1)
    if _SLOW and max(dt for dt, _ in _SLOW) >= SLOW_REPORT_THRESHOLD:
        print("== slowest checks ==")
        for dt, name in sorted(_SLOW, reverse=True)[:20]:
            print(f"  {dt:8.3f}s  {name}")
    print(f"ALL PASS ({total}) [{elapsed:.2f}s]")


def wait_until(cond, timeout_ms=3000, tick_ms=50):
    """The real Qt event loop until cond() or the deadline (the regression_v081 pattern)."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    ticks = {"n": 0}

    def _tick():
        if not cond() and ticks["n"] * tick_ms < timeout_ms:
            ticks["n"] += 1
        elif loop.isRunning():
            loop.quit()

    tmr = QTimer()
    tmr.setInterval(tick_ms)
    tmr.timeout.connect(_tick)
    tmr.start()
    loop.exec()
    tmr.stop()


def wait_for(predicate, timeout_ms=3000, tick_ms=10):
    """Drive `processEvents()` until predicate() is true; return a BOOL (v1.4.1 suite cleanup).

    `wait_until()` above runs a REAL Qt event loop and returns nothing; this poll is for a
    predicate fed by plain Python threads / queued signals (the plugin tests): it returns
    True/False, so `check(..., wait_for(...))` fails honestly on a timeout.

    Do not swap one for the other: `wait_until(...) is not False` against the event-loop
    version is TRUE even on a timeout (`None is not False`), which is a silently passing check.
    """
    import time as _time
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = _time.monotonic() + timeout_ms / 1000.0
    while _time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        _time.sleep(tick_ms / 1000.0)
    if app is not None:
        app.processEvents()
    return bool(predicate())


def viewport_point(view, scene_pos):
    """The scene → a QPoint in the coordinates of the viewport (Qt 6.11: mapFromScene can give a QPoint or a QPointF)."""
    from PySide6.QtCore import QPoint
    q = view.mapFromScene(scene_pos)
    return QPoint(int(q.x()), int(q.y()))


def snapshot_i18n_config():
    """The snapshot of ~/.sshmap/config.json (None, if the file is absent).

    The tests switching the language (set_language) write into the config; under the isolated
    HOME this is the sandbox and the snapshot is not needed, but with SSHMAP_TEST_NO_HOME_ISOLATION=1
    it preserves the real config of the user.
    """
    p = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return (p, f.read())


def restore_i18n_config(snap):
    """The restore of the i18n config from the snapshot of snapshot_i18n_config()."""
    if snap is None:
        return
    try:
        with open(snap[0], "w", encoding="utf-8") as f:
            f.write(snap[1])
    except OSError:
        pass  # sandbox may block writes to ~ — config untouched anyway


# ─────────────────────────────────────────────────────────────────────────────
# config.json — the shared fixture helpers (v1.4.1 suite cleanup).
# The suite re-declared this family 50 times in 21 files under three spellings
# (`_cfg_path`/`write_config`/`clear_config`, `CFG_PATH`/`read_cfg`/`write_cfg`,
# `cfg_path`/`read_config`) — and the variants disagreed on two things: whether a
# missing file reads as {} or None, and whether the write MERGES (the
# `i18n.save_config` semantics) or REPLACES the document. Both are now explicit
# arguments instead of a per-file accident.
# Call them AFTER bootstrap(): the path is resolved from the isolated HOME.
# ─────────────────────────────────────────────────────────────────────────────

def cfg_path() -> str:
    """`~/.sshmap/config.json` of the sandbox HOME."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def read_cfg(default=None):
    """The parsed config.json.

    `default` is what a MISSING or unreadable file yields — `{}` for "no settings
    yet" (the usual test fixture) or `None` for "was the file there at all?".
    A non-object JSON root counts as missing (the app ignores such a file too).
    """
    try:
        with open(cfg_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, dict) else default


def write_cfg(data) -> None:
    """A WHOLE-DOCUMENT write: what is on disk is exactly `data` (the folder is created)."""
    path = cfg_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def merge_cfg(data) -> None:
    """A MERGE write — the `i18n.save_config` semantics: the foreign keys survive.

    This is the behaviour a test needs when it changes ONE setting and then checks
    that the others are still there.
    """
    current = read_cfg({}) or {}
    current.update(data)
    write_cfg(current)


def clear_cfg(*extra_paths: str) -> None:
    """Remove config.json (and any extra path passed — e.g. a legacy settings file).

    No arguments = the ordinary "a clean config for this section" call.
    """
    for path in (cfg_path(),) + tuple(extra_paths):
        try:
            os.remove(path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# The release pins: at every release update ONLY HERE (earlier: the "N keys" number
# in 12 i18n files + the APP_VERSION/requirements pins in 7 release-state sections).
# The misses of the keys themselves against the code are caught by check_i18n_keys.py.
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_APP_VERSION = "1.5.2"   # the current release (a sentinel: it catches "a bump to the wrong version")
EXPECTED_I18N_KEYS = 661        # the parity of the TRANSLATION keys (v1.5.2 — "the activity panel:
                                # the history the interface never kept": the SECOND patch ON the
                                # released 1.5). +13 keys × en/ru/zh/de, ALL of them the chrome of the
                                # new panel: `view.toggle_activity` (the checkable View item — a
                                # registry action with an EMPTY default, so the Hotkeys tab grows
                                # 51 → 52 rows and the empty-default set 28 → 29), its title
                                # (`activity.title`), the Clear button (`activity.clear`), the
                                # empty-state line (`activity.empty`), the FIVE level captions of the
                                # filter (`activity.level.all/.info/.warning/.error/.status`) and the
                                # four column headers (`activity.col.time/.level/.source/.message`).
                                # The event LINES themselves are NOT translated — they are logging
                                # lines (the panel's own rule), which is what keeps a new EVENT KIND
                                # from costing an i18n key; the ring bound, the coalescing window and
                                # the level policy are numbers and a pure function, and the ONE new
                                # config key (`ui_activity_panel`) is UI state written by its owner,
                                # so the hub's `collect()` stays 22. The `_common.py` pins of the
                                # releases before it (the v1.5.1 figure of 648 and the 51/28 of the
                                # registry) move with this line: the release-state sections of the
                                # topical files quote the CURRENT pin, not a historical one.
                                # (v1.5.1 — "map images: copy the render, and a fixed frame for the
                                # documentation": +4 keys × en/ru/zh/de: the two File-menu labels
                                # (`file.copy_map` and `file.docs_frame`) and their two reports
                                # (`status.map_copied`, `status.docs_frame_saved` with {file}); the
                                # two registry actions with an EMPTY default made the Hotkeys tab
                                # grow 49 → 51 and the empty-default set 26 → 28. No config key,
                                # no theme field, no dependency.
                                # (v1.5 — "the release
                                # that closes the 1.5 line": the three features the
                                # interface review left for the closing release — the
                                # floating-panel SNAP, the EMULATED demo statuses and the
                                # environment badge on the card). +1 key × en/ru/zh/de:
                                # `node.status.emulated` ("demo") — the marker a
                                # status the demo DECLARED (instead of measuring) always
                                # carries; the badge, the tooltip line and the suppressed age
                                # all read it, so ONE key is enough for a second channel,
                                # and its value is SHORT enough for a MIN card's band. The other
                                # two features add NO string: the snap is geometry (a
                                # dropped panel re-anchors, the saved position is cleared
                                # with the null sentinel and no new menu entry, key or
                                # config key exists) and the environment badge shows the
                                # USER'S OWN TAG (`graphics/server_node.ENV_TAGS` is a
                                # declared vocabulary, not a translation). `example.note_text`
                                # and `status.example_loaded` were REWORDED (the reversed
                                # "no status is faked" rule) — a value change adds no key.
                                # The hub's `collect()` stays 22 keys.
                                # (v1.5rc5 — the review batch, a HARDENING slot: no new key,
                                # so the v1.5rc4 figure of 643 stood.)
                                # (v1.5rc4 — "Density, focus &
                                # findability: the chrome answers the same questions as the
                                # map": +13 keys × en/ru/zh/de → 643: `settings.search.*`
                                # (the placeholder and the "no hits" line of the new
                                # settings search), the three `settings.hotkeys.filter` /
                                # `.counts` ({with_key} + {assignable}) / `.assign_hint`
                                # keys of the navigable Hotkeys tab, the SIX `settings.
                                # hotkeys.family.*` captions (`FAMILY_ORDER` = File / Edit /
                                # View / Node / Plugins / Help, derived from the action id)
                                # and `toolbar.more` (the "»" overflow menu of the toolbar).
                                # The focus ring is a PAINT (`ui/focus_ring.py` + two
                                # `STYLE_BUILDERS` entries, no string), the keyboard walk and
                                # the panel priority are behaviour, and both overflow
                                # thresholds are measured numbers — none of them is text.
                                # The hub's `collect()` stays 22 keys.)
                                # (v1.5rc3 — "First run &
                                # confidence: how to start, and how old the data is": the
                                # third release of the 1.5 line). +11 keys × en/ru/zh/de:
                                # the two new Help entries and the cheat-sheet window
                                # (`help.cheatsheet`, `hotkeys.sheet_hint`), the two
                                # first-screen pieces (`empty.state.example` — the demo-map
                                # button, reused by the Help item — and
                                # `empty.state.palette_hint` with its {hotkey}) and the
                                # demo map's own text (`example.note_text`; the aliases,
                                # hosts and the group name are infrastructure DATA, not UI
                                # strings), the example marker (`title.example`) and its
                                # load report (`status.example_loaded`), the Undo
                                # affordance's tooltip (`status.undo_hint`; the BUTTON
                                # reuses `edit.undo`), the freshness line
                                # (`node.status.checked_now` / `node.status.checked_ago`
                                # with {minutes}) and the palette's new caption
                                # (`palette.start_here`). The freshness THRESHOLD and the
                                # timestamps are numbers, the stale mark is the existing
                                # idle tone (no new colour) and the undo offer is a widget
                                # — none of them is text. The hub's `collect()` stays 22
                                # keys (nothing was added to config.json). (v1.5rc2 — "Beyond
                                # colour:
                                # patterns, shapes, print": the SECOND channel of the two
                                # encodings + the print-friendly export). +3 keys ×
                                # en/ru/zh/de, all in the new export-options dialog:
                                # `dialog.export_options` (its title), `export.palette_hint`
                                # (what "print-friendly" means: a white page and
                                # high-contrast lines that stay apart in greyscale) and
                                # `export.use_current_theme` (the opt-out checkbox). The two
                                # ENCODINGS are not text: `Theme.arrow_type_styles` (the six
                                # pen styles) and `Theme.status_shapes` (dot/ring/triangle)
                                # are declared data, and the shapes keep the status WORDS in
                                # the tooltips the card already carried. The export palette is
                                # not a config key either — the hub's `collect()` stays 22.
                                # (v1.5rc1 — "Colour: the LIGHT
                                # theme gets its own palette, and a gate that keeps it honest":
                                # +3 keys × en/ru/zh/de, all on the "Appearance" tab —
                                # `settings.appearance.mode.auto` (the third mode: the platform's
                                # own colour scheme decides, and the window follows it live),
                                # `settings.appearance.motion` (the "Reduce motion" switch label)
                                # and `settings.appearance.motion.tooltip` (what it does: every
                                # gesture applies its FINAL state at once). The accent's second
                                # ROLE (`accent_strong` + its hover/selected pair), the retuned
                                # LIGHT palette, the contrast gate and the motion flag of
                                # `config.json` add no other string: a colour and a boolean are not
                                # text, and the gate lives in the suite. The `theme` key stays ONE
                                # nested object, so collect() stays 22 keys.
                                # (v1.4.7 — "Syntax
                                # highlighting in the SFTP viewer": +1 key × en/ru/zh/de,
                                # `sftp.viewer.syntax_heuristic` = "highlighting: {language}
                                # (heuristic)" — the note the read-only preview appends to
                                # its header for the modes NO parser verified (YAML: the
                                # standard library has no YAML parser, so the highlighting
                                # there is a heuristic and says so, the
                                # `sftp.viewer.encoding_note` pattern). The verified modes
                                # (JSON/XML — accepted only after `json.loads` /
                                # `ElementTree.fromstring` really parsed the text) and the
                                # always-truthful `numbers` fallback carry NO note, and the
                                # palette is not text (`ui/theme.py` gained the 8
                                # `Theme.syntax_*` fields, no key).
                                # (v1.4.6 — "List mode:
                                # collapsing the map = server parameters": +9 keys × en/ru/zh/de
                                # (`sidebar.list.alias/.host/.status/.os/.cpu/.ram/.disk/.tags` —
                                # the column headers of the wide LIST layout the sidebar tree
                                # switches to when the map is collapsed; the header set is the
                                # plan's own "alias | host (IP) | status | OS | CPU | RAM | DISK |
                                # tags") and `minimap.title` (the vertical title band of the
                                # minimap — the fold affordance the panel gained in the same
                                # release, the `legend.title` precedent). TWO existing VALUES
                                # changed and no key was added by them:
                                # `view.toggle_map` "Map" → "Map / List" and `view.toggle_sidebar`
                                # "Sidebar" → "Sidebar / Map" — the two splitter panels are named
                                # by their pair of states ("to list / to map") because collapsing
                                # the map now switches the sidebar to the list and collapsing the
                                # sidebar gives the whole width to the map; `minimap.tooltip` was
                                # EXTENDED with the fold gesture (a value change, not a key).
                                # The STATUS words of the table reuse `legend.status.*` (no fourth
                                # spelling of online/warn/offline) and the cell mapping is a pure
                                # function (`ui/sidebar.list_cell_values`) — nothing else became
                                # text.
                                # (v1.4.5 — "UI density &
                                # first run": +17 keys × en/ru/zh/de, and ONE existing VALUE
                                # rewritten. The new keys: 3 `empty.state.*` (the first-run
                                # hint — the title, the button and the import line whose two
                                # placeholders are filled with the REAL File-menu labels
                                # `file.import_servers` / `file.import_ssh_config`, so the hint
                                # can never name a menu item that no longer exists),
                                # 5 `statusbar.filter.*` (the three clickable status counters
                                # `online`/`warn`/`offline` with {count}, their shared tooltip and
                                # the "sidebar filtered by status" status-bar line with {status}),
                                # 8 legend keys (`legend.title`, the two section captions
                                # `legend.connections` / `legend.statuses`, the three status
                                # NAMES `legend.status.online/.warn/.offline` — reused by the
                                # filter's status-bar line — the panel tooltip
                                # `legend.tooltip` and the checkable View/toolbar item
                                # `view.toggle_legend`) and 1 `view.splitter_handle_tooltip`
                                # (the v1.4.5 splitter-handle rule: the divider is available
                                # only while both panels are expanded).
                                # The VALUE change: `status.counts` lost its three status
                                # figures — the counters became three CLICKABLE widgets of
                                # their own (`statusbar.filter.*`), so the single label now
                                # carries only "Servers: {servers} | Connections: {connections}".
                                # A value change adds no key, so this is the only line it
                                # touches here. (v1.4.4 — "Motion: camera
                                # flights, node scale-in, hover focus/dim on arrows": +0 keys
                                # × en/ru/zh/de. The release is BEHAVIOUR only — `ui/motion.py`
                                # holds the durations/easing and the two gestures, and every
                                # user-visible string already exists (the reveal, the fit, the
                                # dimmed cards and the accent frame are the v0.9.6/v0.9.8 ones).
                                # So the pin STAYS 586, the v1.4.3 figure — a release may move
                                # the pin, it is not obliged to.
                                # (v1.4.3 — "Appearance:
                                # light theme + accent color", the `Theme` object):
                                # +16 keys × en/ru/zh/de. 15 under `settings.appearance.*`
                                # — the tab label (`settings.tab.appearance`, the hub grew
                                # 7 → 8 tabs), the mode row (`settings.appearance.mode` +
                                # `.mode.dark` / `.mode.light`), the accent row
                                # (`settings.appearance.accent` + 8 swatch names
                                # `.accent.sky/.cyan/.green/.amber/.orange/.pink/.violet/.slate`
                                # — sky is the DEFAULT hue, so "back to the default look" is
                                # one click), the user's own colour
                                # (`settings.appearance.own_color`), the picker button
                                # (`settings.appearance.pick_color`) and the live-apply hint
                                # (`settings.appearance.hint`) — plus the tab label itself.
                                # The `Theme` object, `LIGHT`, the accent-hue generator, the
                                # QSS builder (`ui/theme_qss.py`) and the live descriptors add
                                # no other string: a theme is not text. The `theme` key of
                                # config.json is ONE nested object (the `hotkeys` precedent),
                                # so the hub's collect() goes 21 → 22 keys, not 24.
                                # (v1.4.2 — the big-picture map
                                # level: +4 keys × en/ru/zh/de. `view.toggle_minimap` (the checkable
                                # View item / the registry action with an EMPTY default),
                                # `minimap.tooltip` (the panel's ONLY text — the minimap draws shapes,
                                # no text, by design) and the group-fold pair `ctx.collapse_group` /
                                # `ctx.expand_group` (the group context menu + the title-band chevron
                                # tooltip, symmetric with `ctx.collapse_server`/`ctx.expand_server`).
                                # The cached shadow pixmap, the `card_rect_scene()` anchors and
                                # `CmdToggleGroupCollapse` add no other string: the fold is a gesture,
                                # the shadow a paint, the anchors geometry.)
                                # (v1.4.1 — import from ~/.ssh/config:
                                # the second release of the 1.4 line and the first one after the base
                                # release, so the chain starts at the v1.4 pin, 545).
                                # +21 keys × en/ru/zh/de: `btn.import` (the picker's confirm button — the
                                # `btn.*` family), `file.import_ssh_config` (the File-menu item / the
                                # registry action, an EMPTY default), `msg.import_ssh_config_result`
                                # ({added} + {skipped} — the end-of-import report), `sshconfig.not_found`
                                # ({path} — the missing ~/.ssh/config hint) and 17 keys of the picker
                                # dialog itself: `sshconfig.title` / `.hint` ({path} + {count}) /
                                # `.skipped` ({count}) / `.notes` ({count}) / `.select_all` /
                                # `.select_none`, the 5 column headers (`sshconfig.col_alias`, `.col_host`,
                                # `.col_port`, `.col_user`, `.col_key` — the dialog is a table, so it gets
                                # its own headers instead of the `server.*` form labels), the 4 skip
                                # reasons (`sshconfig.reason.wildcard`, `.reason.match`,
                                # `.reason.include_missing` with {detail}, `.reason.duplicate`) and the
                                # 2 dropped-directive notes (`sshconfig.note.proxy`,
                                # `sshconfig.note.identity_extra` with {detail}). The parser, the loader
                                # and `MainWindow._import_servers_from_ssh_config()` add no other string:
                                # the parser reports reason CODES and the dialog translates them.
                                # (v1.4.1: the TXT-parser fix in `parse_hosts_file()` — every
                                # whitespace-separated word of a line becomes an entry — is a behaviour
                                # change with NO new UI string: the extra entries already travel through
                                # the existing "skipped" counter of `msg.import_servers_result`.)
                                # (v1.4: the base release of the
                                # 1.4 line: the plugin foundation is COMPLETE, and the release itself
                                # adds NO key — it ships the two example plugins
                                # (`examples/plugins/hello.py`, `examples/plugins/disk_monitor.py`)
                                # and their topical test. The examples are deliberately silent in the
                                # parity policy: a plugin's strings are the AUTHOR's text
                                # (`PLUGINS.md` §7), so the pin STAYS 545 — the number the three rcs
                                # built up. (v1.4rc3: +5 — the UI hooks of
                                # the plugin foundation, ROADMAP tasks 7–9: `plugins.run_on_nodes`
                                # (the "Run on selected servers" menu item / the registry action),
                                # `plugins.run_hint` (the menu row shown while a plugin implements
                                # `run_on_nodes` but the map has no servers yet),
                                # `plugins.no_selection` (the status line of that same case when
                                # the action is triggered), `plugins.status.run_on_nodes` ({count}
                                # — the start report of the action) and `palette.kind_plugin`
                                # (the palette's section label — the `palette.kind_server`
                                # counterpart). The plugin rows go STRAIGHT into the node context
                                # menu (no submenu) and the palette renders the commands as a
                                # section of its own list, so neither a `plugin.node_menu`
                                # nor a `plugin.commands` header exists — two keys written while
                                # implementing rc3 turned out unused and were dropped, keeping
                                # the pinned set honest (`PLUGINS.md` §3 documents the flat
                                # behaviour). `PluginCommand`, the manager's `plugin_commands()` /
                                # `plugin_node_context_menu()` / `plugin_run_on_nodes()` and the
                                # QAction guard add no strings: a plugin's own text is the AUTHOR's
                                # and stays outside the parity policy (PLUGINS.md §7).
                                # (v1.4rc2: +2 — the execution
                                # half of the plugin foundation. `plugins.status.hook_failed`
                                # ({name} + {hook} + {error}) reports a hook that RAISED and
                                # `plugins.status.hook_timeout` ({name} + {hook} + {ms}) reports one
                                # that was ABANDONED after its wait budget — the two outcomes of the
                                # "never throws / never hangs the host" discipline with a user-visible
                                # line. `PluginContext`, `plugin_runner`, the status merge and the
                                # worker/orphan registries add no strings. (v1.4rc1: +8 — the plugin
                                # foundation, part 1. `menu.plugins` (the new top-level menu next
                                # to "Settings"), `plugins.reload` (the re-discovery action, a
                                # registry action with an empty default), `plugins.empty` (the
                                # placeholder naming ~/.sshmap/plugins/) and 5 status-bar reports:
                                # `plugins.status.loaded` / `.error` ({name} + {error}) /
                                # `.enabled` / `.disabled` / `.reloaded` ({count}). The discovery
                                # itself, the `plugins` key of config.json and the module name of a
                                # folder plugin add no strings — plugin strings are the AUTHOR's
                                # text and stay outside the parity policy (PLUGINS.md §7).
                                # (v1.3.3.8: +10 — the
                                # reachable-from-the-UI release. 7 `language.*` for the language
                                # manager (`language.import` / `language.export` — the two buttons
                                # of the "Language" tab; `language.imported` / `language.exported`
                                # — the success reports; `language.import_failed` with the {error}
                                # detail; `language.incomplete_warning` — the English-fallback note
                                # of a file imported with `"partial": true`; `language.name_missing`
                                # — the file carries no "name" meta key) and 3 `settings.terminal.wheel`
                                # (+ `.scrollback` / `.off` — the v1.3.3.8 UI for the last config-only
                                # key). The ROADMAP named 5 + 3; the two extra reports
                                # (`language.exported`, `language.name_missing`) are the deliberate
                                # +2 — the plan listed the minimum key set, and a success line and a
                                # missing-meta warning cannot be expressed by the listed five.
                                # The user language folder itself (`~/.sshmap/languages/`,
                                # the shadowing rule, import/export) adds no other string.
                                # (v1.3.3.7: +2 — the SVG export,
                                # `file.export_svg` + `status.export_svg_ok`. The drawio half of the
                                # release adds NO UI string: the label carries the data and the failure
                                # path reuses `msg.export_failed`.)
                                # (v1.3.3.6: +9 — the project
                                # life cycle: 3 for the Recent submenu (`file.recent`,
                                # `file.recent_clear`, `file.recent_empty`), `msg.drop_project`
                                # (the refused-drop hint) and 5 for the unreadable-file recovery
                                # (`dialog.project_unreadable` + `msg.project_unreadable` with its
                                # restore / backup-list / skip options). Panel widths and the MRU
                                # storage add no strings.
                                # (v1.3.3.5: +2 — terminal.split
                                # ("Split Terminal" — the checkable action of the terminal split:
                                # the toolbar button and the window's context-menu item) and
                                # terminal.split_tooltip (the hint of that action). The split itself
                                # adds no other string: the pane's multi-input badge reuses
                                # terminal.multi_tab_badge / terminal.multi_excluded_badge.
                                # (v1.3.3.4: +17 — the terminal
                                # output theme: 5 terminal.find.* (placeholder / count / next /
                                # prev / close), 3 terminal.menu.* (clear_scrollback /
                                # reset_screen / save_transcript), 5 terminal.cmdlib.seed.*
                                # (the first-run seed names, now i18n keys), 2 multi-input
                                # exclusion keys (terminal.multi_exclude + the tab badge
                                # terminal.multi_excluded_badge), and 2 for the transfer
                                # rate/ETA of the SFTP progress line (sftp.rate / sftp.eta —
                                # ROADMAP task 6, the detachable task 7 of v1.3.3.2).
                                # The ROADMAP's own "490 → 501" figure for this version was
                                # arithmetic slippage: the enumerated key list of the section
                                # already contains 15 keys, plus the 2 of task 6 → 507.
                                # (v1.3.3.3: +13 — view.zoom_in, view.zoom_out,
                                # settings.hotkeys.reset, settings.hotkeys.reset_done,
                                # ctx.check_status, status.check_now, about.open, about.title,
                                # about.license, about.config_path, about.logs_path, about.hotkeys,
                                # about.open_config_dir; the "name"/"partial" meta keys of the language
                                # files are NOT translations and are excluded here and in
                                # check_i18n_keys.py).
                                # v1.3.3.2: +17 — 10 sftp.op.* (new folder / rename / delete / confirm /
                                # copy path / copied / error / name prompt / invalid name / done),
                                # 6 sftp.conflict.* (title / message / overwrite / skip / rename /
                                # apply-to-all) and the sftp.drag_hint drag-out tooltip → 477;
                                # v1.3.3.1: +2 — lang.reload "Rescan the language files" and
                                # status.language_reloaded → 460;
                                # v1.3.3: 458 (no new keys — the "name" meta key is not a translation);
                                # v1.3.2: +5 settings.hotkeys.* / settings.tab.hotkeys → 458;
                                # before, 453 since v1.3.1
VERSION_FORMAT_RE = re.compile(r"^\d+(\.\d+){1,3}([Rr][Cc]\d+)?$")  # "1.1.3", "1.0RC4", "0.9.9.7", "1.2.10rc1" (v1.2.10: + lowercase rc)

# The test-file counter quoted by README.md / ROADMAP.md is checked against the real
# number of tests/test_*.py (v1.3.3.1, ROADMAP task 5): it went stale by one release
# twice (v1.3.2/v1.3.3 dropped the README line). The guard parses the documents and
# asserts every quoted counter equals this number (tests/test_i18n_live.py).
TEST_FILE_COUNTER_RE = re.compile(r"(\d+)\s+(?:test[ _-]?files?|test_\*\.py)")
# The key-count figures a version section quotes: "parity: 458", "parity **458 → 459**",
# "parity baseline (v1.3.3.1): 460". A "~" marks a deliberately approximate figure and
# is skipped (the guard compares EXACT numbers).
I18N_PARITY_FIGURE_RE = re.compile(r"parity[^\n]{0,32}?(?<!~)(\d{3})")

# v1.3.3: the meta keys of a language file — file metadata, not UI strings.
# A language file: {"name": "Русский", "partial": true, "menu.file": "Файл", …}.
# "name" is the language name in its own language; "partial": true (v1.3.3.1) marks a
# DELIBERATELY incomplete file — it loads and works (the en-fallback is unchanged),
# but its missing keys are a WARNING, not a defect. Both are excluded from the key
# parity; a missing "name" only degrades the display to the code.
I18N_META_KEYS = frozenset({"name", "partial"})
I18N_REFERENCE = "en"   # the source language: every other file must cover 100% of its keys
I18N_LANG_ENCODING = "utf-8-sig"   # v1.3.3.1: a Notepad "UTF-8 with BOM" file must load
I18N_PARTIAL_KEY = "partial"       # the meta key of a deliberately incomplete language


def i18n_lang_codes(root):
    """Auto-discovery of the languages: every i18n/*.json is a language, the file name is its code."""
    i18n_dir = os.path.join(root, "i18n")
    if not os.path.isdir(i18n_dir):
        return []
    return sorted(f[:-len(".json")] for f in os.listdir(i18n_dir) if f.endswith(".json"))


def translation_keys(data):
    """The TRANSLATION keys of a loaded language file (the meta keys are dropped)."""
    return {k for k in data if k not in I18N_META_KEYS}


def is_partial_lang(data) -> bool:
    """Is this loaded language file marked `"partial": true` (v1.3.3.1)?

    Only a real JSON `true` counts — a string "true" / 1 / a missing key keeps the
    file under the STRICT parity policy.
    """
    return isinstance(data, dict) and data.get(I18N_PARTIAL_KEY) is True


def load_i18n_langs(root, codes=None, encoding=None):
    """i18n/*.json → {code: dict} (the shared loading for the parity checks).

    v1.3.3: auto-discovery (the file name is the code) — a dropped-in language file is
    picked up by the checks without touching them. codes=… narrows the set.
    v1.3.3.1: read as "utf-8-sig" by default — a BOM saved by Notepad loads exactly
    like a plain UTF-8 file (pass encoding=… to re-read a file as raw UTF-8).
    """
    langs = {}
    for code in (i18n_lang_codes(root) if codes is None else codes):
        path = os.path.join(root, "i18n", f"{code}.json")
        with open(path, encoding=encoding or I18N_LANG_ENCODING) as f:
            langs[code] = json.load(f)
    return langs


# ── v1.3.3.1 (ROADMAP task 4): placeholders and line breaks ──────────────────
# The two defect types the v1.3.3 policy could not see. The helpers live HERE (the
# "one place" rule): both tests/check_i18n_keys.py and tests/test_i18n_languages.py /
# tests/test_i18n_live.py consume them.

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholder_names(value) -> set:
    """The SET of `{placeholder}` names of one translation value (not a string → empty).

    The SET, not the list: the ORDER of the placeholders in a sentence is a language
    matter ("{alias} auf {host}" vs "{host} → {alias}"), their PRESENCE is not.
    """
    if not isinstance(value, str):
        return set()
    return set(PLACEHOLDER_RE.findall(value))


def newline_count(value) -> int:
    """The COUNT of `\\n` line breaks of one translation value (not a string → 0).

    The count (not the positions): word order differs between languages, the number
    of lines a dialog shows does not.
    """
    if not isinstance(value, str):
        return 0
    return value.count("\n")


def i18n_format_problems(langs, reference=I18N_REFERENCE):
    """The placeholder / line-break defects of the discovered languages vs the reference.

    For every translation key present in BOTH the reference and the language:
    the SET of `{placeholder}` names must match, and the COUNT of `\\n` must match.
    A partial language (`"partial": true`) skips the check — its strings are still
    being written. Returns {code: [problem, …]} with only the languages that have any.
    """
    if reference not in langs:
        return {}
    ref = langs[reference]
    out = {}
    for code in sorted(langs):
        if code == reference or is_partial_lang(langs[code]):
            continue
        problems = []
        for key, ref_value in ref.items():
            if key in I18N_META_KEYS or key not in langs[code]:
                continue
            value = langs[code][key]
            ph_ref, ph_got = placeholder_names(ref_value), placeholder_names(value)
            if ph_ref != ph_got:
                problems.append(
                    f"{key}: placeholders {sorted(ph_got)} vs {reference} {sorted(ph_ref)}")
            nl_ref, nl_got = newline_count(ref_value), newline_count(value)
            if nl_ref != nl_got:
                problems.append(
                    f"{key}: {nl_got} line break(s) vs {reference} {nl_ref}")
        if problems:
            out[code] = problems
    return out


def i18n_parity_warnings(langs, reference=I18N_REFERENCE):
    """The parity WARNINGS of the discovered languages: [] = none.

    v1.3.3.1 (ROADMAP task 2): a file with the meta key `"partial": true` is a
    deliberately incomplete translation — it loads and works (the runtime
    en-fallback covers the missing keys), so its MISSING keys and its key COUNT are
    reported here as warnings instead of defects. Everything else stays strict.
    """
    if reference not in langs:
        return []
    ref_keys = translation_keys(langs[reference])
    warnings = []
    for code in sorted(langs):
        data = langs[code]
        if not is_partial_lang(data):
            continue
        keys = translation_keys(data)
        missing = sorted(ref_keys - keys)
        count_note = ""
        if len(keys) != len(ref_keys):
            count_note = f" ({len(keys)} of {len(ref_keys)} {reference} keys)"
        if missing or count_note:
            detail = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
            warnings.append(
                f"{code}: partial language — {len(missing)} key(s) fall back to {reference}"
                + (f": {detail}" if detail else "") + count_note)
    return warnings


def i18n_parity_problems(langs, expected_keys=None, reference=I18N_REFERENCE):
    """The parity defects among the discovered languages: [] = clean.

    The policy (v1.3.3): a built-in language must cover 100% of the reference (en)
    keys — STRICT parity, so an extra key is a defect as well (it would be dead
    weight in one file only) — and the count is pinned by EXPECTED_I18N_KEYS.
    Meta keys are not translations and are ignored here.

    v1.3.3.1: a `"partial": true` file is graded leniently — its MISSING keys and the
    count mismatch are warnings (`i18n_parity_warnings`), not defects. An EXTRA key
    is still a defect: a key that en does not have is dead weight / a typo, in a
    partial file as much as in a strict one.
    """
    expected = EXPECTED_I18N_KEYS if expected_keys is None else expected_keys
    if reference not in langs:
        return [f"the reference language {reference!r} is not among the discovered files"]
    ref_keys = translation_keys(langs[reference])
    problems = []
    for code in sorted(langs):
        keys = translation_keys(langs[code])
        partial = is_partial_lang(langs[code])
        missing = sorted(ref_keys - keys)
        extra = sorted(keys - ref_keys)
        if missing and not partial:
            problems.append(f"{code}: {len(missing)} key(s) missing vs {reference}: "
                            + ", ".join(missing[:5]) + ("…" if len(missing) > 5 else ""))
        if extra:
            problems.append(f"{code}: {len(extra)} key(s) not in {reference}: "
                            + ", ".join(extra[:5]) + ("…" if len(extra) > 5 else ""))
        if expected is not None and len(keys) != expected and not partial:
            problems.append(f"{code}: {len(keys)} translation keys (the pin EXPECTED_I18N_KEYS = {expected})")
    return problems


def check_i18n_parity(langs):
    """The parity over the DISCOVERED languages: identical translation key sets vs en + the pinned count."""
    problems = i18n_parity_problems(langs)
    check(
        f"i18n parity: {len(langs)} language(s) × {EXPECTED_I18N_KEYS} keys "
        f"({', '.join(sorted(langs))})",
        not problems,
        "; ".join(problems) + " | "
        + str({c: len(translation_keys(d)) for c, d in sorted(langs.items())}))


def check_i18n_format(langs):
    """v1.3.3.1: the placeholder / line-break parity of the discovered languages vs en.

    Partial languages are skipped by `i18n_format_problems` (their strings are still
    being written); the warnings of partial languages are reported in the detail so a
    deliberate incompleteness is still visible in the log.
    """
    problems = i18n_format_problems(langs)
    warnings = i18n_parity_warnings(langs)
    check(
        f"i18n format: placeholders + line breaks of {len(langs)} language(s) vs {I18N_REFERENCE}"
        + (f" (+{len(warnings)} partial warning(s))" if warnings else ""),
        not problems,
        "; ".join(f"{c}: {p[0]} (+{len(p) - 1} more)" for c, p in sorted(problems.items()))
        + (" | warnings: " + " | ".join(warnings) if warnings else ""))


def check_release_state(root):
    """The state of the release from version.py (the single source of truth): the sentinel
    EXPECTED_APP_VERSION + the format + the pyproject cross-check + the header of requirements.txt.
    Call AFTER bootstrap() — the version is imported inside the function."""
    try:
        from version import APP_VERSION
    except Exception as e:  # noqa: BLE001
        check("release: version.py is readable", False, repr(e))
        return

    check(f"release: APP_VERSION == '{EXPECTED_APP_VERSION}'",
          APP_VERSION == EXPECTED_APP_VERSION, APP_VERSION)
    check("release: APP_VERSION format (X.Y.Z[.W][RCn])",
          bool(VERSION_FORMAT_RE.match(APP_VERSION)), APP_VERSION)
    try:
        try:
            import tomllib as _toml
        except ModuleNotFoundError:
            import tomli as _toml  # type: ignore
        with open(os.path.join(root, "pyproject.toml"), "rb") as f:
            _pp = _toml.load(f)
        check("release: pyproject version == APP_VERSION",
              _pp["project"]["version"] == APP_VERSION, str(_pp["project"].get("version")))
    except Exception as e:  # noqa: BLE001
        check("release: pyproject version == APP_VERSION", False, repr(e))
    try:
        with open(os.path.join(root, "requirements.txt"), encoding="utf-8") as f:
            _head = f.readline()
        pat = re.compile(rf"v{re.escape(APP_VERSION)}(?![A-Za-z0-9])")
        check(f"release: requirements.txt header carries v{APP_VERSION}",
              pat.search(_head) is not None, _head.strip())
    except Exception as e:  # noqa: BLE001
        check(f"release: requirements.txt header carries v{APP_VERSION}", False, repr(e))
