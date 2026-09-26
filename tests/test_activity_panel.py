# -*- coding: utf-8 -*-
"""v1.5.2 — the activity panel: the history the interface never kept.

The second patch ON the released 1.5, and the release that gives the application a
MEMORY of what happened. A status-bar line lived for a few seconds, and a probe round, an
import, an SFTP failure or a plugin error left nothing behind at all; `sshmap.log` was the
durable record, but it is a file nobody reads while working.

  * **§1 the ring** — `modules/activity_log.py`: the bound (200), the order, the repeat
    counter, the clear, and the "nothing is persisted" rule (memory only).
  * **§2 the two thin taps** — ONE `logging.Handler` (installed by `modules/logger.py`)
    and ONE connection to the status bar (`messageChanged` + `UndoStatusBar.offer_shown`).
    No emitter is rewired for the panel's sake.
  * **§3 the five families** — a probe round, an import, an SFTP task, a plugin error and a
    theme/language fallback each produce at least ONE record (the ROADMAP task 2 acceptance),
    and no secret can enter a record.
  * **§4 the surface** — `ui/activity_panel.py`: newest first, the level filter (the pure
    `matches_level` policy), Clear, the retranslate of the CHROME only, the ONE new
    `config.json` key, and the rule that it is HISTORY and never a second status bar.
  * **§5 the release state** — the pins, the keys, and the "no new contract" audit.

Run: python tests/test_activity_panel.py   (from the project root) or python tests/run_all.py
"""
import json
import logging
import os
import re
import socket
import threading
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, read_cfg, write_cfg,
                     clear_cfg, wait_for, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtWidgets import QApplication, QDialog, QProgressBar  # noqa: E402

app = QApplication.instance() or QApplication([])

import i18n  # noqa: E402
from i18n import t as _t  # noqa: E402
import modules.activity_log as AL  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
from modules.logger import get_logger  # noqa: E402
from modules.sftp_worker import SftpWorker, task_log_line  # noqa: E402
from services.status_checker import StatusChecker, round_summary  # noqa: E402
from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker  # noqa: E402

_langs = load_i18n_langs(ROOT)
_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — for the "it lives in ONE place" audits."""
    key = parts
    if key not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[key] = f.read()
    return _SRC[key]


def messages(buffer=None) -> list:
    """The event texts of the ring, oldest first (the assertion seam)."""
    buf = buffer if buffer is not None else AL.get_activity_buffer()
    return [e.message for e in buf.events()]


def sources(buffer=None) -> list:
    """The sources of the ring, oldest first."""
    buf = buffer if buffer is not None else AL.get_activity_buffer()
    return [e.source for e in buf.events()]


def make_main():
    """An offscreen MainWindow with the timers stopped and NO status checker (hermetic)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1000, 700)
    win.show()
    app.processEvents()
    return win


def free_port() -> int:
    """A port nothing listens on (the "offline" probe target)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the ring: bounded, newest-first, memory only ==")
# ════════════════════════════════════════════════════════════════════════════

buffer = AL.reset_activity_buffer()
check("§1 the bound is DECLARED once (the ROADMAP acceptance names 200)",
      AL.MAX_EVENTS == 200 and buffer.max_events == 200, str(buffer.max_events))
check("§1 a fresh ring is empty", len(buffer) == 0 and buffer.events() == []
      and buffer.newest_first() == [] and buffer.last() is None)

for _i in range(250):
    buffer.append(f"event {_i}", source="tests.ring")
check("§1 the ring never grows past the bound", len(buffer) == 200, str(len(buffer)))
check("§1 ...and the OLDEST events are the ones that left",
      buffer.events()[0].message == "event 50" and buffer.events()[-1].message == "event 249",
      f"{buffer.events()[0].message} … {buffer.events()[-1].message}")
check("§1 newest_first is the display order (the reverse of the ring)",
      buffer.newest_first()[0].message == "event 249"
      and buffer.newest_first()[-1].message == "event 50"
      and len(buffer.newest_first()) == 200)
check("§1 the sequence numbers are monotonic and unique (the repeat seam keys on them)",
      [e.seq for e in buffer.events()] == sorted({e.seq for e in buffer.events()})
      and buffer.last().seq - buffer.events()[0].seq == 199,
      f"{buffer.events()[0].seq} … {buffer.last().seq}")
check("§1 an EMPTY message is not a fact",
      buffer.append("") is None and buffer.append("   ") is None and len(buffer) == 200)
check("§1 events() hands out a COPY (a reader cannot mutate the ring)",
      buffer.events() is not buffer.events()
      and (buffer.events().clear() or len(buffer) == 200), str(len(buffer)))

buffer = AL.reset_activity_buffer()
buffer.append("Ready.", source="status bar")
check("§1 the same fact twice in a burst is ONE event with a counter",
      buffer.append("Ready.", source="status bar") is not None
      and len(buffer) == 1 and buffer.last().repeats == 2, str(len(buffer)))
check("§1 ...and the time is the FIRST occurrence (a row answers \"when did this start\")",
      abs(buffer.last().timestamp - time.time()) < 5.0 and buffer.last().repeats == 2)
buffer.last().timestamp -= (AL.REPEAT_WINDOW_S + 1.0)   # an event older than the window
buffer.append("Ready.", source="status bar")
check("§1 a repeat OUTSIDE the coalescing window is a NEW event (the window is not eternity)",
      len(buffer) == 2 and buffer.last().message == "Ready."
      and buffer.last().repeats == 1, str(len(buffer)))
buffer.append("Another fact", source="status bar")
check("§1 a DIFFERENT fact never coalesces",
      len(buffer) == 3 and buffer.last().message == "Another fact" and buffer.last().repeats == 1)

before = len(buffer)
buffer.clear()
check("§1 clear() empties the ring", len(buffer) == 0 and before == 3, str(len(buffer)))

# "Nothing is persisted": the ring lives in the process and nowhere else.
_needle = "secret-activity-probe-9f3a"
AL.record_status_message(_needle)
_hits = []
for _root_dir, _dirs, _files in os.walk(os.path.expanduser("~")):
    for _name in _files:
        _path = os.path.join(_root_dir, _name)
        try:
            with open(_path, "r", encoding="utf-8", errors="ignore") as _f:
                if _needle in _f.read():
                    _hits.append(_path)
        except OSError:
            continue
check("§1 the history is MEMORY-ONLY (no file under ~ carries an event)",
      not _hits, str(_hits))
_activity_src = _src("modules", "activity_log.py")
check("§1 ...and the module has no writer at all (the one home per fact rule)",
      "open(" not in _activity_src and "json" not in _activity_src
      and "save_config" not in _activity_src and "logging.Handler" in _activity_src)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the two thin taps ==")
# ════════════════════════════════════════════════════════════════════════════

buffer = AL.reset_activity_buffer()
AL.install_activity_handler()
L = logging.getLogger("sshmap")
_old_level = L.level
get_logger("services.somewhere").info("a fact from a module")
check("§2 a record of ANY module reaches the ring (its logger is under `sshmap`)",
      "a fact from a module" in messages(), str(messages()))
check("§2 ...with its SHORT source (the `sshmap.` prefix is not part of the row)",
      sources()[-1] == "services.somewhere", str(sources()))
check("§2 ...and the first tap is installed by modules/logger.py beside the file handler",
      "install_activity_handler" in _src("modules", "logger.py")
      and "RotatingFileHandler" in _src("modules", "logger.py")
      and "ActivityLogHandler" in _activity_src)
check("§2 installing it twice is a no-op (one tap per process, not one per call)",
      AL.install_activity_handler() is AL.install_activity_handler())

# The handler honours the level policy: DEBUG stays in the file.
get_logger("services.somewhere").debug("a debug line nobody asked for")
check("§2 ...and DEBUG is NOT a fact for the panel (the tap records INFO and above)",
      "a debug line nobody asked for" not in messages()
      and AL.ACTIVITY_LEVEL == logging.INFO, str(AL.ACTIVITY_LEVEL))

# The status-bar tap: the ordinary path (messageChanged) and the offer path.
buffer = AL.reset_activity_buffer()
win = make_main()
win.statusBar().showMessage("status tap probe")
check("§2 a status-bar message reaches the ring",
      messages()[-1] == "status tap probe" and AL.get_activity_buffer().last().is_status()
      and AL.get_activity_buffer().last().level == AL.LEVEL_STATUS, str(messages()))
before = len(AL.get_activity_buffer())
win.statusBar().clearMessage()
app.processEvents()
check("§2 ...and the CLEAR is not a fact (Qt emits messageChanged(\"\") on every clear)",
      len(AL.get_activity_buffer()) == before, str(len(AL.get_activity_buffer())))
win.statusBar().arm_undo()
win.statusBar().showMessage("Server deleted: web-01")
check("§2 the UNDO OFFER's sentence reaches the ring too (it never travels through "
      "messageChanged — that is why `offer_shown` exists)",
      "Server deleted: web-01" in messages() and win.statusBar().is_offer_visible(),
      str(messages()))
check("§2 the tap is ONE connection per surface (the window owns it, not the panel)",
      "_record_activity_message" in _src("ui", "main_window.py")
      and "offer_shown" in _src("ui", "status_bar.py")
      and "offer_shown = Signal(str)" in _src("ui", "status_bar.py"))
check("§2 the panel is not the owner of the taps (it renders, the window wires)",
      "messageChanged" not in _src("ui", "activity_panel.py"))

# The pure level policy of the filter (§4 renders it).
AL.reset_activity_buffer()
AL.get_activity_buffer().append("plain", source="m")
AL.get_activity_buffer().append("careful", level="WARNING", source="m")
AL.get_activity_buffer().append("broken", level="ERROR", source="m")
AL.record_status_message("ui said so")
_ev = {e.message: e for e in AL.get_activity_buffer().events()}
check("§2 matches_level: `all` matches everything and an unknown key does not hide a row",
      all(AL.matches_level(e, "all") for e in _ev.values())
      and all(AL.matches_level(e, "nonsense") for e in _ev.values()))
check("§2 matches_level: the three logging keys select their own level only",
      AL.matches_level(_ev["plain"], "info") and not AL.matches_level(_ev["careful"], "info")
      and AL.matches_level(_ev["careful"], "warning")
      and AL.matches_level(_ev["broken"], "error")
      and not AL.matches_level(_ev["broken"], "warning"))
check("§2 matches_level: `status` is the SECOND family, not a level",
      AL.matches_level(_ev["ui said so"], "status")
      and not AL.matches_level(_ev["plain"], "status")
      and not AL.matches_level(_ev["ui said so"], "info"))
check("§2 the filter keys are the declared vocabulary (the combo renders them)",
      AL.LEVEL_KEYS == ("all", "info", "warning", "error", "status"), str(AL.LEVEL_KEYS))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the five families produce a record ==")
# ════════════════════════════════════════════════════════════════════════════

# ── (1) the probe round: a REAL round against a local banner server and a closed port ──
buffer = AL.reset_activity_buffer()
_port_on = free_port()
_srv = socket.socket()
_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_srv.bind(("127.0.0.1", _port_on))
_srv.listen(1)
_srv.settimeout(5)


def _serve_banner():
    try:
        conn, _ = _srv.accept()
        conn.sendall(b"SSH-2.0-ActivityTest\r\n")
        time.sleep(0.3)
        conn.close()
    except OSError:
        pass


threading.Thread(target=_serve_banner, daemon=True).start()
checker = StatusChecker(interval_ms=5000, probe_timeout=1.0)
checker.set_servers([("act-on", "127.0.0.1", _port_on), ("act-off", "127.0.0.1", free_port())])
_done = []
checker.round_finished.connect(lambda r: _done.append(r))
checker.start_round()
wait_for(lambda: bool(_done), timeout_ms=8000)
checker.shutdown()
check("§3 a probe round wrote ONE summary record (the per-node answers stay on the cards)",
      len(_done) == 1 and len([m for m in messages() if m.startswith("Status round:")]) == 1,
      str(messages()))
_summary = [m for m in messages() if m.startswith("Status round:")]
check("§3 ...that names the counts by status",
      _summary and "online 1" in _summary[0] and "offline 1" in _summary[0], str(_summary))
check("§3 ...and it comes from the checker itself (the module had NO log call before v1.5.2)",
      _summary and sources()[-1] == "services.status_checker", str(sources()))
check("§3 the summary line is PURE and pinned (the topical-test seam)",
      round_summary([("a", "online"), ("b", "warn"), ("c", "offline")])
      == "Status round: 3 probed — online 1, warn 1, offline 1"
      and round_summary([]) == "Status round: 0 probed — online 0, warn 0, offline 0"
      and "other 1" in round_summary([("a", "weird")]),
      round_summary([("a", "online"), ("b", "warn"), ("c", "offline")]))

# ── (2) an import: the ~/.ssh/config loader and the TXT DNS stage ─────────────
buffer = AL.reset_activity_buffer()
_cfg_path = os.path.join(WORK, "ssh_config")
with open(_cfg_path, "w", encoding="utf-8") as f:
    f.write("Host web-1\n    HostName 192.0.2.10\n    User root\n\n"
            "Host db-1\n    HostName 192.0.2.20\n    Port 2222\n")
from services.ssh_config_importer import SshConfigError, load_ssh_config  # noqa: E402

_result = load_ssh_config(_cfg_path)
check("§3 an SSH-config import wrote its result (it logged NOTHING before v1.5.2)",
      any(m.startswith("SSH config import: 2 host(s)") for m in messages()), str(messages()))
check("§3 ...naming the file and the skip/note counts",
      messages() and _cfg_path in messages()[-1] and "skipped" in messages()[-1],
      str(messages()[-1:]))
try:
    load_ssh_config(os.path.join(WORK, "nope_config"))
    _raised = False
except SshConfigError:
    _raised = True
check("§3 an import that cannot read its file leaves the REASON behind (a WARNING)",
      _raised and any("no file at" in m for m in messages())
      and AL.get_activity_buffer().last().level == "WARNING", str(messages()))

from services.host_importer import HostResolverThread  # noqa: E402

check("§3 the TXT import's DNS stage resolves localhost in a thread",
      isinstance(HostResolverThread(["localhost"]), HostResolverThread))
_resolved = []
_rt = HostResolverThread(["localhost"])
_rt.resolved_map.connect(lambda m: _resolved.append(dict(m)))
_rt.start()
wait_for(lambda: bool(_resolved), timeout_ms=8000)
check("§3 ...and writes its own summary record",
      any(m.startswith("TXT import: 1 of 1 name(s) resolved") for m in messages()),
      str(messages()[-2:]))

# ── (3) an SFTP task: a REAL worker over the in-memory fake server ────────────
buffer = AL.reset_activity_buffer()
fs = FakeSftpFS()
fs.add_dir("/home")
_fs_worker = SftpWorker(FakeSftpClient(fs))
_log = EventLog()
wire_worker(_fs_worker, _log)
_fs_worker.start()
_tid = _fs_worker.queue_mkdir("/home", "fresh")
wait_for(lambda: _log.of_kind("done", _tid), timeout_ms=5000)
wait_for(lambda: any(m.startswith("SFTP mkdir finished") for m in messages()), timeout_ms=5000)
_fs_worker.shutdown()
check("§3 an SFTP task that finished wrote its record (the worker logged NOTHING before)",
      any(m == "SFTP mkdir finished: /home/fresh" for m in messages()), str(messages()))
check("§3 ...from the worker thread, i.e. the ring really is thread-safe",
      "sftp_worker" in sources()[-1] if sources() else False, str(sources()[-1:]))
buffer = AL.reset_activity_buffer()
fs2 = FakeSftpFS()
fs2.add_dir("/home")
_fs_worker2 = SftpWorker(FakeSftpClient(fs2))
_log2 = EventLog()
wire_worker(_fs_worker2, _log2)
_fs_worker2.start()
_tid2 = _fs_worker2.queue_mkdir("/home", "sub/deep")   # no parent -> task_error
wait_for(lambda: _log2.of_kind("error", _tid2), timeout_ms=5000)
wait_for(lambda: any(m.startswith("SFTP mkdir failed") for m in messages()), timeout_ms=5000)
_fs_worker2.shutdown()
check("§3 a FAILED task writes an ERROR record with the reason",
      any(m.startswith("SFTP mkdir failed: /home/sub/deep") for m in messages())
      and AL.get_activity_buffer().last().level == "ERROR", str(messages()))
check("§3 the line builder is PURE (kind/label/outcome in, one line out)",
      task_log_line("upload", "/tmp/a.bin", "done")[0] == "SFTP upload finished: /tmp/a.bin"
      and task_log_line("download", "/tmp/b", "failed", "denied")[0]
      == "SFTP download failed: /tmp/b — denied"
      and task_log_line("upload", "/x", "done")[1] == logging.INFO
      and task_log_line("download", "/x", "failed", "e")[1] == logging.ERROR)
check("§3 NAVIGATION is deliberately not logged: a listing / a viewer read is not history",
      task_log_line("list", "/home", "done")[0] == ""
      and task_log_line("read", "/home/a.txt", "done")[0] == ""
      and task_log_line("read", "/home/a.txt", "failed", "binary")[0] == "")

# ── (4) a plugin error ───────────────────────────────────────────────────────
buffer = AL.reset_activity_buffer()
PLUGIN_DIR = PM.user_plugin_dir()
os.makedirs(PLUGIN_DIR, exist_ok=True)
_plugin_path = os.path.join(PLUGIN_DIR, "activity_broken.py")
with open(_plugin_path, "w", encoding="utf-8") as f:
    f.write("def broken(:\n")
try:
    _records = PM.PluginManager(None).discover()
finally:
    try:
        os.remove(_plugin_path)
    except OSError:
        pass
_broken = [r for r in _records if r.plugin_id == "activity_broken"]
check("§3 a broken plugin is an ERROR record (never a crash) and reaches the ring",
      bool(_broken) and _broken[0].state == PM.STATE_ERROR
      and any("activity_broken" in m and "failed to load" in m for m in messages()),
      str(messages()[-2:]))
check("§3 ...at ERROR level, so the panel's \"Errors\" filter finds it",
      any(e.level == "ERROR" and "activity_broken" in e.message
          for e in AL.get_activity_buffer().events()), str(messages()[-2:]))

# ── (5) a theme / language fallback ──────────────────────────────────────────
buffer = AL.reset_activity_buffer()
clear_cfg()
write_cfg({"theme": {"mode": "bogus", "accent": "not-a-colour", "motion": "yes"}})
from ui.settings_dialog import load_theme_settings  # noqa: E402

_theme = load_theme_settings()
check("§3 a broken theme value falls back AND says so (the record the panel shows)",
      _theme == {"mode": "dark", "accent": "#38bdf8", "motion": True, "density": "normal"}
      and sum(1 for m in messages() if "theme" in m) >= 3, str(messages()))
clear_cfg()
check("§3 a language that cannot be loaded is a WARNING record (it was a DEBUG line before)",
      i18n.set_language("definitely-not-a-language") is False
      and any("not loaded (no usable file)" in m for m in messages())
      and AL.get_activity_buffer().last().level == "WARNING", str(messages()[-1:]))
_udir = i18n.user_language_dir()
os.makedirs(_udir, exist_ok=True)
_bad_lang = os.path.join(_udir, "activitybroken.json")
with open(_bad_lang, "w", encoding="utf-8") as f:
    f.write("{ this is not json")
check("§3 a user language file that is not one is skipped WITH a record (the built-in wins)",
      i18n.language_file_path("activitybroken") is None
      and any("activitybroken" in m and "not a language file" in m for m in messages()),
      str(messages()[-1:]))
os.remove(_bad_lang)
check("§3 no secret can enter a record — the call sites of the five families are scanned",
      not any(re.search(r"log\.\w+\([^\n]*(password|passphrase|secret|credential)",
                        _src(*parts), re.I)
              for parts in (("services", "status_checker.py"), ("modules", "sftp_worker.py"),
                            ("services", "ssh_config_importer.py"),
                            ("services", "host_importer.py"),
                            ("ui", "main_window_node_ops.py")))
      and "getMessage()" in _activity_src)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the surface: history, never a second status bar ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
buffer = AL.reset_activity_buffer()
win = make_main()
panel = win.activity_panel
check("§4 the window builds the panel (the surface is not lazily forgotten)",
      panel is not None and panel.parent() is win)
check("§4 it is a NON-MODAL window — never a fifth floating panel (the placement decision)",
      panel.isModal() is False and isinstance(panel, QDialog) and panel.parent() is win)
_resolver = _src("ui", "main_window.py")
_open = _resolver.index("def _overlay_panel_rects")
check("§4 ...so it never joins the floating-panel priority resolver (only the VIEW children)",
      'for name in ("empty_state", "map_search", "minimap", "legend", "filter_plaque")'
      in _resolver[_open:_open + 900] and panel.parent() is not win.view)
check("§4 it owns retranslate() (the v1.3.3.1 container invariant)",
      callable(getattr(panel, "retranslate", None)))
check("§4 the activity switch JOINS the toolbar's view cluster (v1.6, ROADMAP task 7: the "
      "cluster is the deliverable, and every panel toggle is a member of it)",
      MW._VIEW_TOOLBAR_ACTIONS.get("view.toggle_activity") == "act_show_activity"
      and "view.toggle_activity" in win._view_toolbar_buttons)
check("§4 it is hidden by default and the config key is read, not assumed",
      win.act_show_activity.isChecked() is False and panel.is_shown() is False
      and read_cfg({}).get("ui_activity_panel") in (None, False))

# The rows: newest first, filtered by the pure policy.
AL.get_activity_buffer().append("an info line", level="INFO", source="tests.panel")
AL.get_activity_buffer().append("a warning line", level="WARNING", source="tests.panel")
AL.get_activity_buffer().append("an error line", level="ERROR", source="tests.panel")
AL.record_status_message("the interface said so")
win.act_show_activity.setChecked(True)
wait_for(lambda: panel.is_shown() and panel.row_count() > 0)
check("§4 the View item shows the window and the state is PERSISTED under ONE key",
      panel.is_shown() and win._activity_enabled is True
      and read_cfg({}).get("ui_activity_panel") is True
      and [k for k in read_cfg({}) if k.startswith("ui_activity")]
      == ["ui_activity_panel"], str(sorted(read_cfg({}))))
_rows = panel.rows_text()
check("§4 the panel lists the ring NEWEST first",
      [r[3] for r in _rows][:2] == ["the interface said so", "an error line"], str(_rows))
check("§4 every row carries time, level, source and message (four columns)",
      all(len(r) == 4 and r[0] and r[1] and r[2] and r[3] for r in _rows)
      and panel.tree.columnCount() == 4, str(_rows[:1]))
check("§4 the rows are the buffer's own count (nothing is invented or dropped)",
      panel.row_count() == len(AL.get_activity_buffer()) == len(messages()),
      str(panel.row_count()))

panel.set_level("warning")
app.processEvents()
check("§4 the level filter renders the PURE policy (it decides nothing itself)",
      [r[3] for r in panel.rows_text()] == ["a warning line"], str(panel.rows_text()))
panel.set_level("status")
app.processEvents()
check("§4 ...and the \"Interface\" filter is the status family",
      [r[3] for r in panel.rows_text()] == ["the interface said so"], str(panel.rows_text()))
panel.set_level("all")
app.processEvents()

# The history survives what the status bar forgets (one fact, two ROLES).
win.statusBar().clearMessage()
app.processEvents()
check("§4 the bar forgets, the panel REMEMBERS (the bar is the \"now\", the panel the history)",
      panel.row_count() == len(AL.get_activity_buffer())
      and "the interface said so" in [r[3] for r in panel.rows_text()])
check("§4 ...and it is not a second status bar: no progress bar, no current-status widget",
      panel.has_live_surface() is False and panel.findChildren(QProgressBar) == []
      and not isinstance(panel, type(win.statusBar())))

# Clear: the ring itself, not only the view.
panel.clear()
check("§4 Clear empties the HISTORY (the ring), not only the rows",
      len(AL.get_activity_buffer()) == 0 and panel.row_count() == 0)

# The retranslate: the CHROME follows the language, the event LINES do not.
AL.get_activity_buffer().append("a line that stays English", level="INFO", source="tests.panel")
panel.refresh()
_en_title = panel.windowTitle()
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("§4 retranslate() re-texts the chrome (title, buttons, captions, columns)",
      panel.windowTitle() == _t("activity.title") == _langs["ru"]["activity.title"]
      and panel.windowTitle() != _en_title
      and panel.clear_btn.text() == _langs["ru"]["activity.clear"]
      and panel.tree.headerItem().text(3) == _langs["ru"]["activity.col.message"]
      and panel.level_combo.itemText(0) == _langs["ru"]["activity.level.all"],
      f"{panel.windowTitle()!r} / {panel.clear_btn.text()!r}")
check("§4 ...and the event LINES stay English (the logging convention — no key per event kind)",
      panel.rows_text()[0][3] == "a line that stays English", str(panel.rows_text()[:1]))
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()

# The user closes the window with its X: the OWNER (the menu item) must follow.
panel.close()
app.processEvents()
check("§4 closing the window hides it (the history survives) and unchecks the View item",
      panel.is_shown() is False and win.act_show_activity.isChecked() is False
      and win._activity_enabled is False
      and read_cfg({}).get("ui_activity_panel") is False, str(read_cfg({})))
check("§4 ...and the same instance comes back with the history intact",
      (win.act_show_activity.setChecked(True), app.processEvents(),
       panel.is_shown()
       and "a line that stays English" in [r[3] for r in panel.rows_text()])[-1],
      str(panel.rows_text()[:2]))
win.act_show_activity.setChecked(False)
win._dirty = False
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state and the 'no new contract' audit ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
check("§5 EXPECTED_APP_VERSION is the shipped release (v1.5.2 was the second patch on 1.5;"
      " the pin quotes the CURRENT one — v1.6.4 — like every topical file)",
      EXPECTED_APP_VERSION == "1.6.4"
      and re.fullmatch(r"1\.6(\.\d+)?", EXPECTED_APP_VERSION) is not None)
check("§5 the i18n pin counts the shipped release (v1.5.2's 661 + v1.5.3's twenty"
      " + v1.5.4's eleven + v1.5.5's fourteen + v1.5.6's two + v1.5.7's twenty-nine"
      " + v1.6's forty-one + v1.6.2's four + v1.6.3's four + v1.6.4's three)",
      EXPECTED_I18N_KEYS == 789, str(EXPECTED_I18N_KEYS))
check_i18n_parity(_langs)
check_i18n_format(_langs)

_NEW_KEYS = ("view.toggle_activity", "activity.title", "activity.clear", "activity.empty",
             "activity.level.all", "activity.level.info", "activity.level.warning",
             "activity.level.error", "activity.level.status",
             "activity.col.time", "activity.col.level", "activity.col.source",
             "activity.col.message")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in _langs.items()}
check(f"§5 the {len(_NEW_KEYS)} keys of v1.5.2 are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§5 ...and they are the keys the CODE really asks for (the panel's own vocabulary)",
      all(part in _src("ui", "activity_panel.py") for part in
          ('"activity.title"', '"activity.clear"', '"activity.empty"',
           "activity.level.{key}", "activity.col.time", "activity.col.level",
           "activity.col.source", "activity.col.message")))

check("§5 the ONE new action is registered with an EMPTY default (assignable, no key taken)",
      "view.toggle_activity" in HR.action_ids()
      and HR.default_sequence("view.toggle_activity") == ""
      and "view.toggle_activity" in HR.empty_default_action_ids()
      and HR.action_family("view.toggle_activity") == "view")
check("§5 the registry grew 51 -> 52 in v1.5.2 (and 52 -> 54 with the v1.5.3 pair,"
      " 54 -> 56 with the v1.5.5 inventory pair, -> 59 with the v1.6 trio) and the empty-default "
      "set 28 -> 29 (-> 31, -> 33, -> 36)",
      len(HR.HOTKEY_ACTIONS) == 59 and len(HR.empty_default_action_ids()) == 36,
      f"{len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")

_win = make_main()
check("§5 the new action is bound to a real object in a live window",
      len(_win._hotkey_targets.get("view.toggle_activity") or []) == 1
      and all(len(t) > 0 for t in _win._hotkey_targets.values()))
_activity_action = _win._hotkey_targets["view.toggle_activity"][0]
check("§5 ...and it is a CHECKABLE View item (the owner of the persisted state)",
      _activity_action.isCheckable() and _activity_action.text() == _t("view.toggle_activity"),
      _activity_action.text())

from ui.settings_dialog import SettingsDialog  # noqa: E402

_hub = SettingsDialog(None)
check("§5 the new config key is UI STATE, not a preference (the hub collects 23)",
      len(_hub.collect()) == 23 and "ui_activity_panel" not in _hub.collect(),
      str(sorted(_hub.collect()))[:120])
_hub.close()
import dataclasses  # noqa: E402
from ui import theme  # noqa: E402

check("§5 no new theme field (the palette is the v1.5rc1 one)",
      len(dataclasses.fields(theme.Theme)) == 60)
_deps = {"PySide6", "paramiko", "keyring", "wcwidth"}
_req = _src("requirements.txt")
check("§5 no new dependency (the four pinned ones and nothing else)",
      all(f"{d}>=" in _req for d in _deps)
      and not re.search(r"^\s*(?!PySide6|paramiko|keyring|wcwidth|#)[A-Za-z][\w.-]*\s*[><=]",
                        _req, re.M))
check("§5 VERSION_FORMAT did NOT move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9"
      and __import__("version").APP_VERSION == "1.6.4")
check("§5 the durable record stays the FILE — the ring is the second, memory-only home",
      "LOG_FILE" in _src("modules", "logger.py")
      and "MAX_LOG_SIZE_MB" in _src("modules", "logger.py")
      and "max_events" in _activity_src)
check("§5 the topical file is listed by the suite map (tests/INDEX.md regenerated)",
      "test_activity_panel" in open(os.path.join(ROOT, "tests", "INDEX.md"),
                                    encoding="utf-8").read())
_win._dirty = False
_win.close()

finish()
