# -*- coding: utf-8 -*-
"""v1.5rc5 — the review batch (hardening): the batch-level checks of the nine defects.

The fifth slot of the 1.5 line is a HARDENING batch, not a theme: the v1.5rc4 review of the
SHIPPED interface (the server card, the floating panels, the first-run screen, the terminal
dock) reproduced nine defects that are independent of the line's contract. The ledger with
the probes is `AUDIT_PENDING.md` (`N1`–`N8`, plus `N4b`); the fixes touch no colour, no
encoding, no panel rule and no i18n key (the 643 pin of that slot stayed).

This file carries the checks that have NO topical home — the ones the ledger assigns to a
new file (`tests/test_audit_v1210.py` is the precedent):

  §1 N4  — a connection failure of the ONE-SHOT worker (`SSHWorker`) is localized:
           `socket.gaierror` / `socket.timeout` / `NoValidConnectionsError` are `OSError`,
           not `SSHException`, so they used to reach the generic handler of `run()` and were
           displayed VERBATIM in English while "Test connection" answered in the user's
           language. Checked under `en` AND `ru`.
  §2 N4b — the SAME mapping in the INTERACTIVE terminal (`SSHTerminalThread`), which had no
           localized branch at all — the primary "Connect" path. Plus the composer
           (`terminal_page._show_error`) that prepends the translated prefix.
  §3 N7  — the first-run hint must not paint OVER its own two buttons. A RENDER-based check:
           `isVisible()` / `geometry()` / `visibleRegion()` cannot see this defect (the card
           sets WA_NoSystemBackground rather than WA_OpaquePaintEvent), so the pixel at each
           button's centre is read from a real `grab()`.
  §4 N8  — a collapsed command-library panel releases its width to the terminal (§36 cap +
           the explicit hand-over), and the cap lives ONLY while collapsed (Qt gotcha #13).
  §5 the release state (version, i18n parity — NO new key) for v1.5rc5.

The regressions with a topical home live there instead: N2 §3 of `tests/test_sftp_ops.py`,
N3 `tests/test_sftp_syntax.py`, N5 `tests/test_tags.py`, N6 §1b/§1c of
`tests/test_map_bigpicture.py`, N1 the about section of `tests/test_actions_keyboard.py`.

Run: python tests/test_audit_v15rc5.py   (from the project root) or python tests/run_all.py
"""
import os
import socket
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
import paramiko  # noqa: E402

RU = "ru"


def t(key, **kw):
    return i18n.t(key, **kw)


class _FakeSSHClient:
    """The `paramiko.SSHClient` seam (the `tests/test_audit_v1210.py` pattern).

    `connect()` raises whatever the class attribute `raise_on_connect` holds — set per case.
    """

    created = []
    raise_on_connect = None

    def __init__(self):
        self.connect_kwargs = None
        _FakeSSHClient.created.append(self)

    def set_missing_host_key_policy(self, policy):
        pass

    def get_host_keys(self):
        return {}

    def connect(self, *args, **kwargs):
        self.connect_kwargs = kwargs
        if _FakeSSHClient.raise_on_connect is not None:
            raise _FakeSSHClient.raise_on_connect

    def close(self):
        pass


# ════════════════════════════════════════════════════════════════════════════
print("== §1 N4: the one-shot worker localizes a connection failure ==")
# ════════════════════════════════════════════════════════════════════════════

import modules.ssh_worker as SW  # noqa: E402

_orig_client_cls = paramiko.SSHClient
paramiko.SSHClient = _FakeSSHClient


def _worker_error(exc, host="bad.invalid", port=22):
    """Run `_run_ssh_connect()` against a client whose connect() raises `exc`.

    Returns the emitted `error` text ("" when the worker reported success).
    """
    captured = []
    _FakeSSHClient.raise_on_connect = exc
    w = SW.SSHWorker(host=host, user="u", port=port, server_id="", password="pw")
    w.error.connect(lambda msg: captured.append(msg))
    try:
        w._run_ssh_connect()
    finally:
        _FakeSSHClient.raise_on_connect = None
    return captured[0] if captured else ""


_gaierror = socket.gaierror(-2, "Name or service not known")
check("N4: socket.gaierror is an OSError and NOT an SSHException (the root of the leak)",
      isinstance(_gaierror, OSError) and not isinstance(_gaierror, paramiko.SSHException))
check("N4: NoValidConnectionsError is an OSError too",
      issubclass(paramiko.ssh_exception.NoValidConnectionsError, OSError))

try:
    _text = _worker_error(_gaierror)
    _want = t("ssh.connection_failed", host="bad.invalid", port=22)
    check("N4: a gaierror reports the TRANSLATED message, never str(e)",
          _text == _want and str(_gaierror) not in _text,
          f"got={_text!r} want={_want!r}")

    _nvce = paramiko.ssh_exception.NoValidConnectionsError({("bad.invalid", 22): _gaierror})
    _text2 = _worker_error(_nvce)
    check("N4: NoValidConnectionsError is mapped the same way",
          _text2 == _want and str(_nvce) not in _text2, f"got={_text2!r}")

    # socket.timeout — a TimeoutError, i.e. an OSError since Python 3.10.
    _text3 = _worker_error(socket.timeout("timed out"))
    check("N4: socket.timeout is mapped the same way",
          _text3 == _want and "timed out" not in _text3, f"got={_text3!r}")

    # The paramiko branches must still WIN (the OSError branch sits LAST).
    _auth = _worker_error(paramiko.AuthenticationException("Authentication failed."))
    check("N4: AuthenticationException keeps its own branch (ssh.auth_failed)",
          _auth == t("ssh.auth_failed"), f"got={_auth!r}")
    _ssh = _worker_error(paramiko.SSHException("kex failed"))
    check("N4: SSHException keeps its own branch (ssh.ssh_error)",
          _ssh == t("ssh.ssh_error", message="kex failed"), f"got={_ssh!r}")

    # …and the SAME under another language: the leak was "raw English in every language".
    i18n.set_language(RU)
    _ru = _worker_error(_gaierror)
    _ru_want = t("ssh.connection_failed", host="bad.invalid", port=22)
    check("N4: under `ru` the message is the Russian one (not str(e))",
          _ru == _ru_want and _ru != _text and str(_gaierror) not in _ru,
          f"got={_ru!r} want={_ru_want!r}")
finally:
    i18n.set_language("en")
    paramiko.SSHClient = _orig_client_cls


# ════════════════════════════════════════════════════════════════════════════
print("== §2 N4b: the interactive terminal localizes the same failures ==")
# ════════════════════════════════════════════════════════════════════════════

import modules.ssh_terminal as ST  # noqa: E402
import modules.terminal_page as TP  # noqa: E402

_orig_client_cls2 = paramiko.SSHClient
paramiko.SSHClient = _FakeSSHClient


def _terminal_error(exc, host="bad.invalid", port=22):
    """Drive `SSHTerminalThread.run()` against a client whose connect() raises `exc`."""
    captured = []
    _FakeSSHClient.raise_on_connect = exc
    thread = ST.SSHTerminalThread(host=host, user="u", port=port, password="pw")
    thread.error_signal.connect(lambda msg: captured.append(msg))
    try:
        thread.run()
    finally:
        _FakeSSHClient.raise_on_connect = None
    return captured[0] if captured else ""


try:
    _want_conn = t("ssh.connection_failed", host="bad.invalid", port=22)
    _term_os = _terminal_error(_gaierror)
    check("N4b: the terminal maps OSError to ssh.connection_failed (never str(e))",
          _term_os == _want_conn and str(_gaierror) not in _term_os, f"got={_term_os!r}")

    _term_auth = _terminal_error(paramiko.AuthenticationException("Authentication failed."))
    check("N4b: the terminal maps AuthenticationException to ssh.auth_failed",
          _term_auth == t("ssh.auth_failed") and "Authentication failed." not in _term_auth,
          f"got={_term_auth!r}")

    _term_ssh = _terminal_error(paramiko.SSHException("kex failed"))
    check("N4b: the terminal maps SSHException to ssh.ssh_error",
          _term_ssh == t("ssh.ssh_error", message="kex failed"), f"got={_term_ssh!r}")

    # The generic handler stays the LAST resort (a non-OSError/paramiko exception).
    _term_other = _terminal_error(ValueError("weird"))
    check("N4b: an unknown exception still reports str(e) (the generic handler stays last)",
          _term_other == "weird", f"got={_term_other!r}")

    i18n.set_language(RU)
    _term_ru = _terminal_error(_gaierror)
    check("N4b: under `ru` the terminal reports the Russian sentence",
          _term_ru == t("ssh.connection_failed", host="bad.invalid", port=22)
          and _term_ru != _want_conn and str(_gaierror) not in _term_ru,
          f"got={_term_ru!r}")
finally:
    i18n.set_language("en")
    paramiko.SSHClient = _orig_client_cls2

# The composer: `_show_error()` prepends the TRANSLATED prefix to the already translated body.
_boxes = []


class _FakeMessageBox:
    @staticmethod
    def critical(parent, title, text):
        _boxes.append((title, text))


class _FakePage:
    """The duck-typed page for the composer (one method, three collaborators)."""
    _host_window = None

    def __init__(self):
        self.status_writes = []
        self.closed = 0

    def _set_status_text(self, text):
        self.status_writes.append(text)

    def close_terminal(self):
        self.closed += 1


_orig_mb = ST.QMessageBox
ST.QMessageBox = _FakeMessageBox
try:
    _page = _FakePage()
    TP.TerminalSessionPage._show_error(
        _page, t("ssh.connection_failed", host="h", port=22))
    check("N4b: _show_error() writes the translated prefix + the translated body",
          _page.status_writes and _page.status_writes[0]
          == f"{t('terminal.error_prefix')} {t('ssh.connection_failed', host='h', port=22)}",
          f"status={_page.status_writes}")
    check("N4b: _show_error() shows the same text in a QMessageBox and closes the session",
          len(_boxes) == 1 and _boxes[0][1] == _page.status_writes[0] and _page.closed == 1,
          f"boxes={_boxes} closed={_page.closed}")
finally:
    ST.QMessageBox = _orig_mb


# ════════════════════════════════════════════════════════════════════════════
print("== §3 N7: the first-run hint does not paint over its own buttons ==")
# ════════════════════════════════════════════════════════════════════════════

import ui.main_window as MW  # noqa: E402
from ui import theme  # noqa: E402

_win = MW.MainWindow()
_win._autosave_timer.stop()
_win._freshness_timer.stop()
_win._status_checker = None
_win.resize(1100, 760)
_win.show()
app.processEvents()

_overlay = _win.empty_state
check("N7: the first screen is the empty state (0 servers)",
      _overlay.is_state_visible() and _overlay.isVisible())
check("N7: the two action buttons are SIBLINGS of the card (children of the view)",
      _overlay.btn_add_first.parentWidget() is _win.view
      and _overlay.btn_example.parentWidget() is _win.view)

_bg = QColor(theme.WINDOW_BG).name()
_frame = _win.grab().toImage()
_painted = {}
for _name, _btn in (("add_first", _overlay.btn_add_first), ("example", _overlay.btn_example)):
    _pt = _btn.mapTo(_win, _btn.rect().center())
    _painted[_name] = QColor(_frame.pixel(_pt)).name()
    check(f"N7: the pixel at the CENTRE of '{_name}' is the button's own chrome, not WINDOW_BG",
          _painted[_name] != _bg, f"pixel={_painted[_name]} WINDOW_BG={_bg} geom={_btn.geometry()}")

# The two buttons do not paint the SAME colour either (the primary keeps the accent fill).
check("N7: the two buttons keep their own chrome (the primary is not the secondary)",
      _painted["add_first"] != _painted["example"], str(_painted))

# The stacking order that caused the cover: the card must not be the TOPMOST sibling.
_children = [c for c in _win.view.children() if c in (_overlay, _overlay.btn_add_first,
                                                      _overlay.btn_example)]
check("N7: the card is NOT the topmost of the three (the buttons are raised above it)",
      _children and _children[-1] is not _overlay
      and set(_children[-2:]) == {_overlay.btn_add_first, _overlay.btn_example},
      str([type(c).__name__ for c in _children]))

# Re-showing keeps the order (the raise lives in ONE place — `set_state_visible`).
_overlay.set_state_visible(False)
_overlay.set_state_visible(True)
app.processEvents()
_after = _win.grab().toImage()
_still = {}
for _name, _btn in (("add_first", _overlay.btn_add_first), ("example", _overlay.btn_example)):
    _pt = _btn.mapTo(_win, _btn.rect().center())
    _still[_name] = QColor(_after.pixel(_pt)).name()
check("N7: a hide/show cycle re-raises the buttons (the cover cannot come back)",
      _still == _painted, f"before={_painted} after={_still}")

_win._dirty = False
_win.close()
_win.destroy()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 N8: a collapsed command panel hands its width to the terminal ==")
# ════════════════════════════════════════════════════════════════════════════

_win2 = MW.MainWindow()
_win2._autosave_timer.stop()
_win2._freshness_timer.stop()
_win2._status_checker = None
_win2.resize(1150, 640)
_win2.show()
app.processEvents()

_dock = _win2._ensure_terminals_dock()
app.processEvents()
_dc = _dock.content
_panel = _dc.cmdlib_panel
_splitter = _panel.parentWidget()
_strip_w = _panel._strip.STRIP_WIDTH

check("N8: the panel is the first member of a two-member splitter",
      _splitter.widget(0) is _panel and _splitter.count() == 2,
      f"{type(_splitter).__name__} count={_splitter.count()}")

_panel.set_collapsed(False, persist=False)
app.processEvents()
_expanded_panel_w = _panel.width()
_expanded_tabs_w = _dc.session_tabs.width()
check("N8: expanded, the panel is wide and the terminal keeps the rest",
      _expanded_panel_w > _strip_w and _expanded_tabs_w > 0,
      f"panel={_expanded_panel_w} tabs={_expanded_tabs_w} sizes={_splitter.sizes()}")

_panel.set_collapsed(True, persist=False)
app.processEvents()
check("N8: collapsed, the panel IS the strip (the §36 width cap)",
      _panel.width() <= _strip_w + 1 and _panel.maximumWidth() <= _strip_w,
      f"w={_panel.width()} maxW={_panel.maximumWidth()} strip={_strip_w}")
check("N8: ...and the TERMINAL received the freed space",
      _dc.session_tabs.width() >= _expanded_tabs_w + (_expanded_panel_w - _strip_w) - 2,
      f"tabs {_expanded_tabs_w} -> {_dc.session_tabs.width()} "
      f"freed={_expanded_panel_w - _strip_w} sizes={_splitter.sizes()}")
check("N8: a re-layout does not give the width back to the collapsed strip",
      (_splitter.setSizes([_expanded_panel_w, _expanded_tabs_w]),
       app.processEvents(),
       _panel.width() <= _strip_w + 1)[-1],
      f"w={_panel.width()} sizes={_splitter.sizes()}")

_panel.set_collapsed(False, persist=False)
app.processEvents()
check("N8: expanding RELEASES the cap (Qt gotcha #13 — it lives only while collapsed)",
      _panel.maximumWidth() > _strip_w and _panel.width() > _strip_w,
      f"maxW={_panel.maximumWidth()} w={_panel.width()}")
check("N8: the round trip restores the terminal's width",
      abs(_dc.session_tabs.width() - _expanded_tabs_w) <= 2,
      f"tabs={_dc.session_tabs.width()} was={_expanded_tabs_w} sizes={_splitter.sizes()}")

_win2._dirty = False
_win2.close()
_win2.destroy()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state — v1.5rc5 added NO i18n key ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 the batch itself added no key (the pin is the SHIPPED one — v1.5 +1, v1.5.1 +4,"
      " v1.5.2 +13, v1.5.3 +20, v1.5.4 +11, v1.5.5 +14 and v1.5.6 +2)",
      EXPECTED_I18N_KEYS == 708, str(EXPECTED_I18N_KEYS))
check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)

check("§5 no language file was edited by the batch (the four built-in codes)",
      sorted(_langs) == ["de", "en", "ru", "zh"], str(sorted(_langs)))

finish()
