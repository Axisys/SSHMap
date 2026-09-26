# -*- coding: utf-8 -*-
"""v1.6.2 — the terminal that stops lying: a dead session, the DEC graphics, the column, the cursor.

(ROADMAP v1.6.2, tasks 1–4. The fork provenance of task 2 stays in `tests/test_pyte_fork.py`;
this file proves the BEHAVIOUR through the application's own seams.)

§1 The session that says it ended (task 1). The recv loop of `modules/ssh_terminal.py` is driven
   against a fake paramiko client/transport/channel (the `paramiko.SSHClient` seam), and the two
   ways a session really ends are BOTH measured: an EOF (`recv()` answering `b""` — the shape the
   report measured at 7 534 475 calls in 1.5 s) and a peer that vanished without a FIN (the
   transport dies under the loop — what OpenSSH's keepalive turns a silently dead TCP into).
   Each ends the loop inside the budget, reaches `closed_signal` (the ONE status line the session
   writes: `terminal.session_closed`) and the EOF path does NOT spin (a bounded `recv()` count).
§2 The DEC graphics charset (task 2) — through `TerminalScreen`, the production seam:
   `ESC ( 0` + the ASCII letters of a frame become box drawing, `ESC ( B` puts the letters back,
   SI/SO really switch G0/G1.
§3 The History tab's Command column (task 3) — the DECLARED default, a stored width that wins,
   the debounced write of a real drag, the SECOND panel that comes back with it, the corrupt
   value and the construction guard that never overwrites what the user stored.
§4 The cursor (task 4) — the three shapes and their geometry, the SHIPPED default (the thin bar),
   the `terminal_cursor_style` key and its validation, the canvas that really receives it, and
   the "Terminal" tab that carries the choice.
§5 The release state.

Run: python tests/test_terminal_truth.py   (from the project root) or python tests/run_all.py
"""
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, wait_for,
                     read_cfg, write_cfg, clear_cfg, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeWidget  # noqa: E402

app = QApplication(sys.argv)

import paramiko  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
import modules.command_history as CH  # noqa: E402
from modules.terminal_screen import TerminalScreen  # noqa: E402
from modules.terminal_widget import (  # noqa: E402
    TerminalWidget, resolve_cursor_style, cursor_shape_rect,
    CURSOR_STYLE_BLOCK, CURSOR_STYLE_BAR, CURSOR_STYLE_UNDERLINE, CURSOR_STYLE_DEFAULT,
    CURSOR_BAR_WIDTH, CURSOR_UNDERLINE_HEIGHT)
from models.server import ServerData  # noqa: E402


# ════════════════════════════════════════════════════════════
# §1 The session that says it ended (task 1)
# ════════════════════════════════════════════════════════════
print("== §1 the session that says it ended ==")


class _FakeTransport:
    """The paramiko `Transport` surface the thread touches: `set_keepalive` (v1.6.2) only."""

    def __init__(self, channel, keepalive_error=None):
        self.channel = channel
        self.active = True
        self.keepalive = None
        self.keepalive_error = keepalive_error

    def set_keepalive(self, interval):
        if self.keepalive_error is not None:
            raise self.keepalive_error
        self.keepalive = interval

    def is_active(self):
        return self.active

    def kill(self, event=None):
        """What paramiko's OWN transport thread does when the socket is gone
        (`Transport.run`'s `finally`): EVERY channel is unlinked and `active` goes False."""
        self.active = False
        self.channel.closed = True


class _FakeChannel:
    """A fake channel in one of the two measured end shapes.

    mode "eof":    `recv_ready()` True forever while `recv()` answers `b""` — the hot loop of the
                   report (7 534 475 calls in 1.5 s, zero signals).
    mode "silent": `recv_ready()` False forever — a peer that went away without a FIN. Nothing
                   happens until the TRANSPORT dies (the keepalive's job in production).
    mode "data":   the same always-ready shape with a scripted payload in front of the EOF.
    """

    def __init__(self, mode="eof", payload=()):
        self.mode = mode
        self.closed = False
        self.eof_received = False
        self.timeout = None
        self.sent = []
        self.resizes = []
        self.recv_calls = 0
        self._payload = list(payload)

    def settimeout(self, value):
        self.timeout = value

    def recv_ready(self):
        return self.mode != "silent"

    def recv(self, n=4096):
        self.recv_calls += 1
        if self._payload:
            return self._payload.pop(0)
        return b""

    def exit_status_ready(self):
        return False

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True

    def resize_pty(self, width=None, height=None):
        self.resizes.append((width, height))


class _FakeClient:
    """The paramiko `SSHClient` surface `run()` uses (the `host_key_policy` calls included)."""

    def __init__(self, transport, channel):
        self._transport = transport
        self._channel = channel
        self.closed = False
        self.connect_kwargs = None
        self.shell_kwargs = None
        self.policy = None

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def get_host_keys(self):
        class _Keys:
            def add(self, *a): pass
        return _Keys()

    def connect(self, *args, **kwargs):
        self.connect_kwargs = kwargs

    def invoke_shell(self, **kwargs):
        self.shell_kwargs = kwargs
        return self._channel

    def get_transport(self):
        return self._transport

    def close(self):
        self.closed = True


_ORIG_CLIENT = paramiko.SSHClient


def drive(mode="eof", keepalive_error=None, payload=()):
    """Run the REAL `SSHTerminalThread.run()` against the fake client; return the journal."""
    channel = _FakeChannel(mode, payload)
    transport = _FakeTransport(channel, keepalive_error)
    client = _FakeClient(transport, channel)
    paramiko.SSHClient = lambda *a, **kw: client      # run() resolves it at call time
    thread = ST.SSHTerminalThread(host="10.0.0.1", user="ops", port=22, password="pw")
    events = {"status": [], "out": [], "error": [], "closed": 0, "connected": 0}
    thread.status_signal.connect(events["status"].append)
    thread.output_signal.connect(events["out"].append)
    thread.error_signal.connect(events["error"].append)
    thread.closed_signal.connect(lambda: events.__setitem__("closed", events["closed"] + 1))
    thread.connected_signal.connect(lambda: events.__setitem__("connected", events["connected"] + 1))
    started = time.monotonic()
    thread.run()
    elapsed = time.monotonic() - started
    return thread, client, channel, transport, events, elapsed


# 1.1 The keepalive is really requested — the ONE writer that touches a silent socket.
_thread, _client, _ch, _tr, _ev, _dt = drive("eof")
check(f"the session asks for the SSH keepalive ({ST.TERMINAL_KEEPALIVE_SEC} s — one declared constant)",
      _tr.keepalive == ST.TERMINAL_KEEPALIVE_SEC == 30, f"keepalive={_tr.keepalive}")
check("the session really opened (invoke_shell 120×32 + the connected signal)",
      _ev["connected"] == 1 and _client.shell_kwargs.get("width") == 120
      and _client.shell_kwargs.get("height") == 32, str(_client.shell_kwargs))

# 1.2 EOF: the loop BREAKS instead of calling recv() forever, and the end is announced.
check("EOF (recv() == b''): the loop ends inside the budget", _dt < 1.0, f"{_dt:.3f} s")
check("EOF: it does NOT spin — a bounded recv() count", _ch.recv_calls <= 3, f"recv_calls={_ch.recv_calls}")
check("EOF: `closed_signal` fires exactly once (the session writes ITS status line)",
      _ev["closed"] == 1, f"closed={_ev['closed']}")
check("EOF: no error signal — the end of a stream is not a failure", _ev["error"] == [], str(_ev["error"]))
check("EOF: the channel and the client are closed by the teardown",
      _ch.closed is True and _client.closed is True)

# 1.3 A peer that vanished without a FIN: nothing arrives, the transport dies (paramiko's own
#     reaction to the keepalive write that finds a dead socket), the loop ends and says so.
_ch_sil = _FakeChannel("silent")
_tr_sil = _FakeTransport(_ch_sil)
_client_sil = _FakeClient(_tr_sil, _ch_sil)
paramiko.SSHClient = lambda *a, **kw: _client_sil
_thread_sil = ST.SSHTerminalThread(host="10.0.0.1", user="ops", port=22, password="pw")
_ev_sil = {"closed": 0, "error": []}
_thread_sil.closed_signal.connect(lambda: _ev_sil.__setitem__("closed", _ev_sil["closed"] + 1))
_thread_sil.error_signal.connect(_ev_sil["error"].append)
_runner = threading.Thread(target=_thread_sil.run, daemon=True)   # the QThread's run, isolated
_started = time.monotonic()
_runner.start()
time.sleep(0.4)                       # the peer is silent — the loop sleeps, nothing is reported
_closed_while_alive = _ev_sil["closed"]
_recv_while_alive = _ch_sil.recv_calls
_tr_sil.kill()                        # the keepalive write found a dead socket → paramiko unlinks
_runner.join(timeout=3.0)
_elapsed_sil = time.monotonic() - _started
check("a silent peer: recv_ready() False — zero recv() calls (the measured pre-fix state)",
      _recv_while_alive == 0, f"recv_calls={_recv_while_alive}")
check("a silent peer: nothing is announced while the transport is still 'alive'",
      _closed_while_alive == 0, f"closed={_closed_while_alive}")
check("a dead transport: the loop ends inside the budget (it slept forever before)",
      not _runner.is_alive() and _elapsed_sil < 2.0, f"{_elapsed_sil:.3f} s")
# the emit happens on the runner thread — the queued delivery needs one turn of the event loop
check("a dead transport: `closed_signal` fires — the user is TOLD the session ended",
      wait_for(lambda: _ev_sil["closed"] == 1, timeout_ms=1500), f"closed={_ev_sil['closed']}")
check("a dead transport: an ordinary end, not an error dialog", _ev_sil["error"] == [],
      str(_ev_sil["error"]))

# 1.4 A transport that refuses the keepalive must not cost the session (a fake/an older paramiko).
_, _c_ke, _ch_ke, _tr_ke, _ev_ke, _dt_ke = drive("eof", keepalive_error=RuntimeError("no keepalive here"))
check("a transport that cannot take the keepalive: the session still opens and ends normally",
      _ev_ke["connected"] == 1 and _ev_ke["closed"] == 1 and _ev_ke["error"] == []
      and _ch_ke.closed is True, str(_ev_ke))

# 1.5 The output path is untouched: a scripted chunk still reaches output_signal in order.
_, _, _ch_d, _, _ev_d, _ = drive("data", payload=[b"hello ", b"world"])
check("the readable output is unchanged (the chunks reach output_signal in order)",
      _ev_d["out"] == [b"hello ", b"world"], str(_ev_d["out"]))

# 1.6 A user stop is not an end of stream: no error, no "closed by the server" claim.
_ch_usr = _FakeChannel("silent")
_tr_usr = _FakeTransport(_ch_usr)
_client_usr = _FakeClient(_tr_usr, _ch_usr)
paramiko.SSHClient = lambda *a, **kw: _client_usr
_thread_usr = ST.SSHTerminalThread(host="10.0.0.1", user="ops", port=22, password="pw")
_ev_usr = {"error": []}
_thread_usr.error_signal.connect(_ev_usr["error"].append)
_stop_timer = threading.Timer(0.2, _thread_usr.stop)
_stop_timer.daemon = True
_stop_timer.start()
_thread_usr.run()
_stop_timer.cancel()
check("stop() from the user: the loop ends without an error signal", _ev_usr["error"] == [],
      str(_ev_usr["error"]))

paramiko.SSHClient = _ORIG_CLIENT

# 1.7 The line the session writes when the stream ends exists in EVERY language (the task
#     REUSES `terminal.session_closed` — the one key the session's `_on_closed` already writes).
import i18n  # noqa: E402
check("the end-of-session line is the shipped `terminal.session_closed` (no new key for task 1)",
      i18n.t("terminal.session_closed") not in ("terminal.session_closed", ""),
      i18n.t("terminal.session_closed"))


# ════════════════════════════════════════════════════════════
# §2 The DEC graphics charset (task 2) — the application's own seam
# ════════════════════════════════════════════════════════════
print("== §2 the DEC graphics charset ==")

BOX_H, BOX_TL, BOX_TR = "\u2500", "\u250c", "\u2510"


def line(scr, row=0):
    return "".join(ch.data for ch in scr.snapshot()[0][row]).rstrip()


_acs = TerminalScreen(columns=20, lines=3)
_acs.feed(b"\x1b(0q\x1b(B")
check("`ESC ( 0` + `q` → the horizontal line (the pre-fix grid held the letter 'q')",
      line(_acs) == BOX_H, repr(line(_acs)))
_acs.feed(b"q")
check("`ESC ( B` puts the identity map back → a literal `q`", line(_acs) == BOX_H + "q",
      repr(line(_acs)))

_acs_frame = TerminalScreen(columns=20, lines=3)
_acs_frame.feed(b"\x1b(0lqqqk\x1b(B\r\nx   x")
_rows_frame, _cx_f, _cy_f, _hidden_f = _acs_frame.snapshot()
check("a whole ACS frame draws (the mc panel separator is a frame, not four letters)",
      "".join(ch.data for ch in _rows_frame[0]).rstrip() == BOX_TL + BOX_H * 3 + BOX_TR,
      repr("".join(ch.data for ch in _rows_frame[0])))
check("the ACS map is scoped to the frame: the text after `ESC ( B` is literal",
      "".join(ch.data for ch in _rows_frame[1]).rstrip() == "x   x",
      repr("".join(ch.data for ch in _rows_frame[1])))

_acs_g1 = TerminalScreen(columns=20, lines=3)
_acs_g1.feed(b"\x1b)0\x0eq")        # designate G1 + SO
check("G1 (`ESC ) 0` + SO) draws the box character too", line(_acs_g1) == BOX_H, repr(line(_acs_g1)))
_acs_g1.feed(b"\x0fq")              # SI — back to G0
check("SI selects G0 again → a literal `q`", line(_acs_g1) == BOX_H + "q", repr(line(_acs_g1)))

_acs_utf8 = TerminalScreen(columns=20, lines=3)
_acs_utf8.feed("Ж\u2500".encode("utf-8"))   # UTF-8 text around the designation is untouched
check("the UTF-8 decoding itself is untouched (a Cyrillic glyph + a box character survive)",
      line(_acs_utf8) == "Ж" + BOX_H, repr(line(_acs_utf8)))

check("the DEC patch is in the manifest (provenance is `tests/test_pyte_fork.py`'s subject)",
      __import__("os").path.isfile(
          __import__("os").path.join(ROOT, "third_party", "pyte-patches",
                                     "0010-honour-charset-designation.patch")))


# ════════════════════════════════════════════════════════════
# §3 The History tab's Command column (task 3)
# ════════════════════════════════════════════════════════════
print("== §3 the History tab's Command column ==")


def _cfg():
    """The live test config as a dict (the harness reader answers None for a missing file)."""
    return read_cfg({}) or {}


clear_cfg()
_qt_tree = QTreeWidget()          # kept alive: the temporary wrapper would die with its header
_qt_default = _qt_tree.header().defaultSectionSize()
check("the DECLARED default is 4 × Qt's own default section size (400 against 100)",
      CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT == 400
      and CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT == 4 * _qt_default,
      f"declared={CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT} qt_default={_qt_default}")

_p1 = CH.CommandHistoryPanel(store=CH.CommandHistoryStore("truth-width"))
check("a fresh panel's Command section is the DECLARED default, not Qt's 100 px",
      _p1.command_width() == CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT and _p1.command_width() != _qt_default,
      f"width={_p1.command_width()}")
check("the fresh panel did NOT write anything into the config (the construction guard)",
      CH.HISTORY_COL_COMMAND_WIDTH_KEY not in _cfg(), str(sorted(_cfg())))

# A stored width WINS over the default, and the construction never overwrites it.
write_cfg({CH.HISTORY_COL_COMMAND_WIDTH_KEY: 650})
_p2 = CH.CommandHistoryPanel(store=CH.CommandHistoryStore("truth-width"))
check("a STORED width wins over the default", _p2.command_width() == 650, f"width={_p2.command_width()}")
app.processEvents()
check("the construction does not write the default over the stored value",
      _cfg().get(CH.HISTORY_COL_COMMAND_WIDTH_KEY) == 650,
      str(_cfg().get(CH.HISTORY_COL_COMMAND_WIDTH_KEY)))

# A real drag: Qt's own signal (per pixel) → ONE debounced write.
_p2.tree.setColumnWidth(CH.CommandHistoryPanel.COL_COMMAND, 512)
check("the drag really resized the section", _p2.command_width() == 512, f"width={_p2.command_width()}")
check("the drag is persisted through the debounce (one write, not one per pixel)",
      wait_for(lambda: _cfg().get(CH.HISTORY_COL_COMMAND_WIDTH_KEY) == 512, timeout_ms=2500),
      str(_cfg().get(CH.HISTORY_COL_COMMAND_WIDTH_KEY)))

# ...and a SECOND panel — the next session — comes back with the dragged width.
_p3 = CH.CommandHistoryPanel(store=CH.CommandHistoryStore("truth-width"))
check("a SECOND panel (the next session) comes back with the DRAGGED width",
      _p3.command_width() == 512, f"width={_p3.command_width()}")

# The corrupt / foreign values are the declared default (the pure validator + a real panel).
for _bad, _what in ((None, "absent"), ("700", "a string"), (True, "a bool"), (12.5, "a float"),
                    (5, "below the floor"), (999999, "above the ceiling")):
    _cfg = {} if _bad is None else {CH.HISTORY_COL_COMMAND_WIDTH_KEY: _bad}
    check(f"a corrupt stored width ({_what}) → the declared default",
          CH.command_width_from_config(_cfg) == CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT,
          str(CH.command_width_from_config(_cfg)))
check("a valid stored width passes the validator unchanged",
      CH.command_width_from_config({CH.HISTORY_COL_COMMAND_WIDTH_KEY: 812}) == 812)
check("an unreadable config object is the default (the reader never raises)",
      CH.command_width_from_config(None) == CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT)

write_cfg({CH.HISTORY_COL_COMMAND_WIDTH_KEY: "garbage"})
_p4 = CH.CommandHistoryPanel(store=CH.CommandHistoryStore("truth-width"))
check("a panel built over a corrupt stored value opens on the default",
      _p4.command_width() == CH.HISTORY_COL_COMMAND_WIDTH_DEFAULT, f"width={_p4.command_width()}")

# The width is UI STATE: it adds NO i18n key and NO settings-hub row.
_i18n_hits = [k for k in load_i18n_langs(ROOT)["en"] if "column" in k and "width" in k]
check("the width adds NO i18n key (a number in the config, a column in a table)", _i18n_hits == [],
      str(_i18n_hits))
check("the width key is a UI-state key of its owner (a `ui_*` name, the split-ratio precedent)",
      CH.HISTORY_COL_COMMAND_WIDTH_KEY.startswith("ui_terminal_"), CH.HISTORY_COL_COMMAND_WIDTH_KEY)
for _panel in (_p1, _p2, _p3, _p4):
    _panel.deleteLater()
_qt_tree.deleteLater()
app.processEvents()
clear_cfg()


# ════════════════════════════════════════════════════════════
# §4 The cursor (task 4)
# ════════════════════════════════════════════════════════════
print("== §4 the cursor ==")

# 4.1 The pure geometry — the topical test reads the shape HERE, the canvas only paints it.
check("the three shapes are DECLARED and the shipped default is the thin bar",
      (CURSOR_STYLE_BLOCK, CURSOR_STYLE_BAR, CURSOR_STYLE_UNDERLINE) == ("block", "bar", "underline")
      and CURSOR_STYLE_DEFAULT == CURSOR_STYLE_BAR, CURSOR_STYLE_DEFAULT)
check("block: the whole cell (13×30 at (10, 20))",
      cursor_shape_rect("block", 10, 20, 13, 30) == (10, 20, 13, 30),
      str(cursor_shape_rect("block", 10, 20, 13, 30)))
check(f"bar: {CURSOR_BAR_WIDTH} px at the LEFT edge, the full cell height",
      cursor_shape_rect("bar", 10, 20, 13, 30) == (10, 20, CURSOR_BAR_WIDTH, 30),
      str(cursor_shape_rect("bar", 10, 20, 13, 30)))
check(f"underline: {CURSOR_UNDERLINE_HEIGHT} px at the BOTTOM edge, the full cell width",
      cursor_shape_rect("underline", 10, 20, 13, 30) == (10, 48, 13, CURSOR_UNDERLINE_HEIGHT),
      str(cursor_shape_rect("underline", 10, 20, 13, 30)))
check("an unknown shape is the DECLARED default (never a missing cursor)",
      cursor_shape_rect("nope", 0, 0, 13, 30) == cursor_shape_rect(CURSOR_STYLE_DEFAULT, 0, 0, 13, 30))
check("the line shapes clamp to the cell (a 1 px cell still shows a 1 px mark)",
      cursor_shape_rect("bar", 0, 0, 1, 5) == (0, 0, 1, 5)
      and cursor_shape_rect("underline", 0, 0, 4, 1) == (0, 0, 4, 1),
      str(cursor_shape_rect("bar", 0, 0, 1, 5)))
for _raw, _want in ((None, "bar"), ("", "bar"), (" BAR ", "bar"), ("Block", "block"),
                    ("underline", "underline"), (5, "bar"), ("weird", "bar")):
    check(f"resolve_cursor_style({_raw!r}) → {_want!r}", resolve_cursor_style(_raw) == _want,
          resolve_cursor_style(_raw))

# 4.2 The rendering: the bar paints a thin line INSIDE the cursor cell and changes NOTHING
#     else — the honest check in this environment (the offscreen box has no real font, so the
#     RUN of a text may spill into the neighbouring cell; the baseline is the SAME screen with
#     the cursor hidden, and only the DIFFERENCE between the two renders is asserted).
import modules.terminal_widget as TW  # noqa: E402


def _render(screen, style):
    w = TerminalWidget(screen, cursor_style=style)
    cw, chh = w.cell_size
    w.resize(cw * 20, chh * 5)
    return w, w.grab().toImage(), cw, chh


def _px(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


def _cell_diff(img_a, img_b, cell, cw, chh):
    """(the differing columns, the differing rows) of ONE cell between two renders."""
    cols, rows = set(), set()
    for y in range(chh):
        for x in range(cell * cw, (cell + 1) * cw):
            if _px(img_a, x, y) != _px(img_b, x, y):
                cols.add(x - cell * cw)
                rows.add(y)
    return cols, rows


_CUR = (0xE2, 0xE8, 0xF0)
_seed = TerminalScreen(columns=20, lines=5)
_seed.feed(b"abc")                     # the cursor sits on the empty cell (3, 0)
_seed_off = TerminalScreen(columns=20, lines=5)
_seed_off.feed(b"abc\x1b[?25l")        # the SAME screen with the cursor hidden — the baseline
_hid = _seed_off.snapshot()
check("the baseline really hides the cursor (the comparison below means something)",
      _hid[3] is True and (_hid[1], _hid[2]) == (3, 0),
      f"hidden={_hid[3]} cursor=({_hid[1]},{_hid[2]})")

_, _img_off, _cw, _chh = _render(_seed_off, "bar")
_, _img_bar, _cw, _chh = _render(_seed, "bar")
_cols, _rows = _cell_diff(_img_bar, _img_off, 3, _cw, _chh)
check(f"the bar: only the first {CURSOR_BAR_WIDTH} pixel columns of the cell change",
      _cols == set(range(CURSOR_BAR_WIDTH)), str(sorted(_cols)))
check("the bar: the mark runs the FULL height of the cell (a line, not a dot)",
      all(_px(_img_bar, 3 * _cw + k, y) == _CUR
          for k in range(CURSOR_BAR_WIDTH) for y in range(_chh)),
      f"differing rows={len(_rows)} of {_chh}")
check("the bar is the cursor colour",
      _px(_img_bar, 3 * _cw, _chh // 2) == _CUR, str(_px(_img_bar, 3 * _cw, _chh // 2)))
_span = [x for x in range(_img_bar.width())
         if any(_px(_img_bar, x, y) != _px(_img_off, x, y) for y in range(_chh))]
check("the bar draws inside ONE cell (nothing else on the row is repainted)",
      bool(_span) and min(_span) == 3 * _cw and max(_span) == 3 * _cw + CURSOR_BAR_WIDTH - 1,
      f"span={min(_span) if _span else None}..{max(_span) if _span else None}")

_, _img_ul, _cw, _chh = _render(_seed, "underline")
_cols_ul, _rows_ul = _cell_diff(_img_ul, _img_off, 3, _cw, _chh)
check(f"the underline: the BOTTOM {CURSOR_UNDERLINE_HEIGHT} rows change, over the full cell width",
      _rows_ul == set(range(_chh - CURSOR_UNDERLINE_HEIGHT, _chh)) and _cols_ul == set(range(_cw)),
      f"rows={sorted(_rows_ul)} cols={len(_cols_ul)}")

_, _img_block, _cw, _chh = _render(_seed, "block")
check("the block still fills the cell completely (the historical painting)",
      all(_px(_img_block, 3 * _cw + k, y) == _CUR for k in range(_cw) for y in range(_chh)),
      "a pixel of the block cell is not the cursor colour")

# The bar must NOT repaint a glyph — the shape only adds its own line.
_glyph = TerminalScreen(columns=20, lines=5)
_glyph.feed(b"a\x1b[1;1H")             # the cursor over the glyph 'a'
_glyph_off = TerminalScreen(columns=20, lines=5)
_glyph_off.feed(b"a\x1b[1;1H\x1b[?25l")
_, _img_g_bar, _cw, _chh = _render(_glyph, "bar")
_, _img_g_off, _cw, _chh = _render(_glyph_off, "bar")
_cols_g, _ = _cell_diff(_img_g_bar, _img_g_off, 0, _cw, _chh)
check("the bar does NOT touch the glyph (only its own line is added)",
      _cols_g == set(range(CURSOR_BAR_WIDTH)), str(sorted(_cols_g)))
_, _img_g_block, _cw, _chh = _render(_glyph, "block")
_BG = tuple(QColor(TW.PALETTES["default"]["default_bg"]).getRgb()[:3])
_glyph_cell = {_px(_img_g_block, k, y) for k in range(_cw) for y in range(_chh)}
check("the block swaps the glyph out (the cell is the cursor colour + the background only)",
      _glyph_cell <= {_CUR, _BG}, str(sorted(_glyph_cell)))

# 4.3 The blink phase and the hide rule apply to EVERY shape.
_phase = TerminalWidget(_seed, cursor_style="bar")
_phase._cursor_visible = False
_phase.resize(_phase.cell_size[0] * 20, _phase.cell_size[1] * 5)
_img_phase = _phase.grab().toImage()
_phase_cols, _phase_rows = _cell_diff(_img_phase, _img_off, 3, _cw, _chh)
check("the blink phase silences the bar too (the timer is untouched by the shape)",
      (_phase_cols, _phase_rows) == (set(), set()),
      f"cols={sorted(_phase_cols)} rows={sorted(_phase_rows)}")
check("set_cursor_style(): the live switch answers the shape it applied",
      _phase.set_cursor_style("underline") == "underline"
      and _phase.cursor_style() == "underline"
      and _phase.set_cursor_style("garbage") == CURSOR_STYLE_DEFAULT)

# 4.4 The config key: the shipped default, the three values, the foreign value.
clear_cfg()
check("no key → the SHIPPED default is the thin bar",
      ST.load_terminal_settings()["cursor"] == "bar", ST.load_terminal_settings()["cursor"])
for _raw, _want in (("block", "block"), (" BAR ", "bar"), ("underline", "underline"),
                    ("garbage", "bar"), (123, "bar")):
    write_cfg({"terminal_cursor_style": _raw})
    check(f"terminal_cursor_style={_raw!r} → {_want!r}",
          ST.load_terminal_settings()["cursor"] == _want, ST.load_terminal_settings()["cursor"])

# 4.5 The canvas of a session really receives it (the page plumbing, the page seam).
from _fakes import FakeSSHThread as _FakeThread  # noqa: E402

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread
from modules.terminal_page import TerminalSessionPage  # noqa: E402

write_cfg({"terminal_cursor_style": "block"})
_page = TerminalSessionPage(ServerData(id="truth-cursor", alias="cursor", host="10.99.0.9",
                                       user="root"), None)
check("the session canvas takes the shape from the config (block)",
      _page.widget.cursor_style() == "block", _page.widget.cursor_style())
_page.shutdown()
write_cfg({"terminal_cursor_style": "underline"})
_page2 = TerminalSessionPage(ServerData(id="truth-cursor2", alias="cursor2", host="10.99.0.9",
                                        user="root"), None)
check("the next session takes the NEW shape (the key is read per session)",
      _page2.widget.cursor_style() == "underline", _page2.widget.cursor_style())
_page2.shutdown()
ST.SSHTerminalThread = _orig_thread_cls

# 4.6 The "Terminal" tab carries the choice, and the four keys exist in EVERY language.
from ui.settings_dialog import SettingsDialog  # noqa: E402

write_cfg({"terminal_cursor_style": "underline"})
_dlg = SettingsDialog(None)
_ids = [_dlg.cursor_combo.itemData(i) for i in range(_dlg.cursor_combo.count())]
check("the 'Terminal' tab offers the three shapes (block / bar / underline)",
      _ids == ["bar", "block", "underline"], str(_ids))
check("the combo opens on the STORED shape", _dlg.cursor_combo.currentData() == "underline",
      str(_dlg.cursor_combo.currentData()))
check("collect() carries terminal_cursor_style (the 23rd UI-facing key)",
      _dlg.collect().get("terminal_cursor_style") == "underline"
      and len(_dlg.collect()) == 23, str(len(_dlg.collect())))
check("the tab's label and its three values are translated (not the raw key)",
      _dlg._lbl_cursor.text() not in ("", "settings.terminal.cursor"),
      _dlg._lbl_cursor.text())
_langs = load_i18n_langs(ROOT)
_missing = {c: [k for k in ("settings.terminal.cursor", "settings.terminal.cursor.bar",
                            "settings.terminal.cursor.block", "settings.terminal.cursor.underline")
                if k not in _langs[c]] for c in _langs}
check("the four cursor keys are in EVERY discovered language",
      all(not v for v in _missing.values()), str(_missing))
_dlg.close()
clear_cfg()


# ════════════════════════════════════════════════════════════
# §5 The release state
# ════════════════════════════════════════════════════════════
print("== §5 the release state ==")

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
