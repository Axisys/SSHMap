# -*- coding: utf-8 -*-
"""The reconnect of a session and the `tmux attach` that rides it (v1.9.1) — the ONE re-arm path.

§1 the pure `tmux_attach_command()` and the session rows a container builds; §2 the re-arm — the
SCREEN kept with the boundary marker, a NEW thread from the SAME endpoint and credential, the
session's own command RE-SENT, ONE page and ONE registration, the canvas re-pointed; §3 the
refusals (a live session, no credential, a torn page); §4 the credential order (the keyring first);
§5 the doors — both containers' menus, the state READ at menu-build time, the clicked tab, the name
dialog; §6 the release state.  Run: python tests/test_terminal_reconnect.py"""
import ast as _ast
import os
import sys

from _common import (bootstrap, check, finish, wait_for, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, translation_keys, EXPECTED_I18N_KEYS,
                     EXPECTED_APP_VERSION, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler)

from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
import modules.terminal_dock as TD  # noqa: E402
import modules.terminal_page as TP  # noqa: E402
import services.credential_manager as CM  # noqa: E402
from models.server import ServerData  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
print("== the harness: ONE fake thread the whole file drives ==")
# ════════════════════════════════════════════════════════════════════════════

class _FakeChannel:
    """The channel stub: the bytes a session sent and the resize_pty calls."""

    def __init__(self):
        self.closed = False
        self.sent = []
        self.resizes = []

    def send(self, data):
        self.sent.append(bytes(data))

    def resize_pty(self, width=None, height=None):
        self.resizes.append((width, height))

    def close(self):
        self.closed = True


class _FakeThread(QThread):
    """SSHTerminalThread's surface, idle: every instance is RECORDED with its arguments.

    `created` is the class attribute the scenarios read (the `_fakes.py` pattern): the birth and
    every re-arm append here, which is how the file asserts that a re-arm builds a NEW thread from
    the SAME endpoint and the SAME credential.
    """

    output_signal = Signal(bytes)
    error_signal = Signal(str)
    status_signal = Signal(str)
    closed_signal = Signal()
    connected_signal = Signal()

    created = []

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.client = None
        self.channel = _FakeChannel()
        self.running = True
        self.stop_calls = 0
        _FakeThread.created.append(self)

    def run(self):
        pass  # idle: no SSH is ever opened

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        self.channel.send(data_bytes)


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # the pages of this file are born on the fake


class _FakeCM:
    """A CredentialManager stand-in: `load_password()` answers the one mapped secret."""

    def __init__(self, secrets=None):
        self.secrets = dict(secrets or {})

    def load_password(self, server_id, scope=None):
        return self.secrets.get(server_id)


_orig_gcm = CM.get_credential_manager
_fake_cm = _FakeCM()
CM.get_credential_manager = lambda: _fake_cm


class _FakeInputDialog:
    """`QInputDialog.getText` — a script of answers ([] = the dialog was cancelled)."""

    SCRIPT = []
    CALLS = []

    @staticmethod
    def getText(parent=None, title="", label=""):
        _FakeInputDialog.CALLS.append((title, label))
        if _FakeInputDialog.SCRIPT:
            return _FakeInputDialog.SCRIPT.pop(0), True
        return "", False


_orig_input = ST.QInputDialog
ST.QInputDialog = _FakeInputDialog


def _data(alias="web", node_id="snode001", password="", key_path=""):
    return ServerData(id=node_id, alias=alias, host="10.0.0.1", user="root",
                      password=password, key_path=key_path)


def _page(password="pw", initial_command="", **kwargs):
    """A live page on the fake thread (the container-free case)."""
    page = TP.TerminalSessionPage(_data(password=password), None,
                                  password=password, initial_command=initial_command, **kwargs)
    return page


def _close(page, code=b"OLD OUTPUT\r\n"):
    """A session that really ENDED: some output, then the thread's own closed_signal."""
    if code:
        page._on_output(code)
    page.terminal_thread.closed_signal.emit()
    app.processEvents()
    return page


def _screen_text(page):
    return "\n".join(page.tscreen.text_lines())


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the pure pieces and the session rows ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 a plain name becomes ONE single-quoted shell word",
      TP.tmux_attach_command("work") == "tmux attach -t 'work'",
      TP.tmux_attach_command("work"))
check("§1 a space in the name cannot become a second word",
      TP.tmux_attach_command("my work") == "tmux attach -t 'my work'",
      TP.tmux_attach_command("my work"))
check("§1 a quote in the name is escaped the POSIX way, not passed through",
      TP.tmux_attach_command("a'b") == "tmux attach -t 'a'\\''b'",
      TP.tmux_attach_command("a'b"))
check("§1 a shell substitution in the name is LITERAL (the quoted word never expands)",
      TP.tmux_attach_command("x$(id)") == "tmux attach -t 'x$(id)'",
      TP.tmux_attach_command("x$(id)"))
check("§1 surrounding whitespace is stripped before quoting",
      TP.tmux_attach_command("  work  ") == "tmux attach -t 'work'",
      TP.tmux_attach_command("  work  "))
check("§1 an empty / whitespace-only / None name is REFUSED with \"\"",
      TP.tmux_attach_command("") == "" and TP.tmux_attach_command("   ") == ""
      and TP.tmux_attach_command(None) == "")
check("§1 the quoted form is the SHIPPED sh_quote (one rule, not a second one)",
      TP.tmux_attach_command("a b") == "tmux attach -t " + __import__(
          "services.system_info_collector", fromlist=["sh_quote"]).sh_quote("a b"))

_menu_actions = {}


class _FakeMenu:
    """The menu surface `add_session_actions()` needs (addAction returns a stub action)."""

    class _Signal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args):
            for slot in list(self._slots):
                slot(*args)

    class _Action:
        def __init__(self, text):
            self._text = text
            self._enabled = True
            self.tooltip = ""
            self.triggered = _FakeMenu._Signal()

        def text(self):
            return self._text

        def setToolTip(self, value):
            self.tooltip = value

        def setEnabled(self, value):
            self._enabled = bool(value)

        def isEnabled(self):
            return self._enabled

        def trigger(self):
            self.triggered.emit(False)
    def __init__(self):
        self.actions = []

    def addAction(self, text):
        action = _FakeMenu._Action(text)
        self.actions.append(action)
        return action


_dead = _page()
_dead._on_closed()
_menu = _FakeMenu()
_rows = TP.add_session_actions(_menu, _dead, lambda page: None, lambda page: None)
check("§1 the builder appends exactly TWO rows: Reconnect and the tmux door",
      [a.text() for a in _menu.actions] == [i18n.t("terminal.reconnect"),
                                           i18n.t("terminal.attach_tmux")],
      [a.text() for a in _menu.actions])
check("§1 every row carries its own tooltip (the key exists)",
      all(a.tooltip for a in _menu.actions))
check("§1 an ENDED session enables Reconnect (`can_reconnect()` read at build time)",
      _menu.actions[0].isEnabled() is True)
check("§1 the tmux door stays enabled for any live page",
      _menu.actions[1].isEnabled() is True and _rows[0] is _menu.actions[0])

_live_menu = _FakeMenu()
TP.add_session_actions(_live_menu, _page(), lambda page: None, lambda page: None)
check("§1 a LIVE session leaves Reconnect DISABLED (the state is never cached)",
      _live_menu.actions[0].isEnabled() is False and _live_menu.actions[1].isEnabled() is True)

_none_menu = _FakeMenu()
TP.add_session_actions(_none_menu, None, lambda page: None, lambda page: None)
check("§1 a page-less menu disables both rows instead of raising",
      [a.isEnabled() for a in _none_menu.actions] == [False, False])

_clicked = []
_t_menu = _FakeMenu()
TP.add_session_actions(_t_menu, _dead, lambda page: _clicked.append(page), lambda page: None)
_t_menu.actions[0].trigger()
check("§1 a row hands its OWN page to the handler (the clicked tab, not the active one)",
      _clicked == [_dead])


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the ONE re-arm path: the screen, the thread, the command ==")
# ════════════════════════════════════════════════════════════════════════════

_FakeThread.created = []
page = _page(initial_command="k9s")
first_thread = page.terminal_thread
check("§2 the session is born on the fake thread recorded with its endpoint",
      len(_FakeThread.created) == 1 and first_thread.host == "10.0.0.1"
      and first_thread.user == "root" and first_thread.port == 22
      and first_thread.password == "pw")
check("§2 a fresh session is NOT reconnectable (a live one has nothing to re-arm)",
      page.can_reconnect() is False and page.reconnect() is False)
check("§2 ...and the refusal is ONE sentence, not silence",
      page.session_status == i18n.t("terminal.reconnect_live"), page.session_status)

_close(page)
check("§2 `closed_signal` is the ONE fact that arms the re-arm", page.can_reconnect() is True)

_registry = [page]           # the MainWindow._terminal_windows shape (the page OBJECT is the unit)
page.destroyed.connect(lambda *_a, s=page: _registry.remove(s))
_before_thread = page.terminal_thread
check("§2 the re-arm answers True", page.reconnect() is True)
check("§2 a NEW thread object was built (the re-arm is not a restart of the dead one)",
      page.terminal_thread is not _before_thread and len(_FakeThread.created) == 2)
check("§2 ...from the SAME endpoint and the SAME credential",
      page.terminal_thread.host == _before_thread.host
      and page.terminal_thread.user == _before_thread.user
      and page.terminal_thread.port == _before_thread.port
      and page.terminal_thread.password == "pw" and page.terminal_thread.key_path == "")
check("§2 the dead thread left through the shipped path (stop() — no second teardown)",
      _before_thread.stop_calls == 1)
check("§2 the page OBJECT is the very same session (the registrations are REUSED)",
      _registry == [page] and len(_registry) == 1)
check("§2 ...and the screen, the canvas and the SFTP tab are the session's own",
      page.tscreen is not None and page.widget is not None and page.sftp_tab is not None)
check("§2 the CANVAS was handed the new thread (the ONE input point follows the re-arm)",
      page.widget.terminal_thread is page.terminal_thread)
_screen = _screen_text(page)
check("§2 the dead output is KEPT as scrollback (the screen was not reset)",
      "OLD OUTPUT" in _screen, _screen[:120])
check("§2 the boundary line is on the screen (ONE marker between the two lives)",
      i18n.t("terminal.reconnect_marker") in _screen, _screen[-160:])
check("§2 the re-arm is no longer offered while the second life is live",
      page.can_reconnect() is False)
check("§2 the old channel is NOT the new one (a fresh transport per life)",
      _before_thread.channel is not page.terminal_thread.channel)

check("§2 the session's own command is re-armed (a `tmux attach` comes back)",
      page._initial_command == "k9s")
page.terminal_thread.connected_signal.emit()
check("§2 ...and goes out on the NEW channel behind the shipped delay",
      wait_for(lambda: page.terminal_thread.channel.sent == [b"k9s\n"], timeout_ms=3000),
      page.terminal_thread.channel.sent)
check("§2 ...and the re-sent command is recorded in the history like the first launch",
      any(entry.get("cmd") == "k9s" for entry in page.command_history.load()),
      page.command_history.load())
check("§2 a second connected_signal does not send it twice (the one-shot guard holds)",
      page._initial_command == "")
page.terminal_thread.connected_signal.emit()
app.processEvents()
check("§2 ...and the second emit leaves the wire alone",
      page.terminal_thread.channel.sent == [b"k9s\n"], page.terminal_thread.channel.sent)

page._pending_pty = (100, 30)
page.terminal_thread.channel.resizes = []
page.terminal_thread.connected_signal.emit()
check("§2 the PTY grid is re-flushed on the new life's connected_signal",
      page.terminal_thread.channel.resizes == [(100, 30)],
      page.terminal_thread.channel.resizes)


# ════════════════════════════════════════════════════════════════════════════
print("== §2b the structural pins: no second connection, no second question ==")
# ════════════════════════════════════════════════════════════════════════════

with open(os.path.join(ROOT, "modules", "terminal_page.py"), encoding="utf-8") as _fh:
    _PAGE_SRC = _fh.read()
_py_imports = set()
for _node in _ast.walk(_ast.parse(_PAGE_SRC)):
    if isinstance(_node, _ast.Import):
        _py_imports.update(_alias.name.split(".")[0] for _alias in _node.names)
    elif isinstance(_node, _ast.ImportFrom) and _node.module:
        _py_imports.add(_node.module.split(".")[0])
check("§2b the page opens no connection of its own (the thread's ONE `ssh_connect` call stays the door)",
      "paramiko" not in _py_imports and "ssh_connect" not in _py_imports, sorted(_py_imports))
check("§2b ...and asks no host-key / passphrase question (a key the store pinned is never re-asked)",
      "host_key_policy" not in _py_imports and "interactive_ask" not in _py_imports,
      sorted(_py_imports))
check("§2b the dead thread leaves through the SHIPPED registry, not a private path",
      "register_orphan_thread" in _PAGE_SRC and "orphan" in _PAGE_SRC)

_close(page)
_second = page.terminal_thread
check("§2 a page can be re-armed twice (the third life is a normal re-arm)",
      page.reconnect() is True and page.terminal_thread is not _second
      and len(_FakeThread.created) == 3)
check("§2 the second re-arm added a SECOND marker line (one per life)",
      _screen_text(page).count(i18n.t("terminal.reconnect_marker")) == 2,
      _screen_text(page).count(i18n.t("terminal.reconnect_marker")))
page.shutdown()
check("§2 a torn-down page never re-arms again", page.can_reconnect() is False)
check("§2 ...and `reconnect()` on it answers False", page.reconnect() is False)


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the refusals and the credential order ==")
# ════════════════════════════════════════════════════════════════════════════

_orphan = _page(password="")
_orphan.server_data.key_path = ""
_close(_orphan)
_fake_cm.secrets = {}
_before_refusal = len(_FakeThread.created)
check("§3 an ended session with NO credential and NO key is refused",
      _orphan.reconnect() is False)
check("§3 ...with ONE sentence that names the reason",
      _orphan.session_status == i18n.t("terminal.reconnect_no_credential"),
      _orphan.session_status)
check("§3 ...and no thread was created for the refused re-arm",
      len(_FakeThread.created) == _before_refusal, len(_FakeThread.created))
_orphan.shutdown()

_keyed = _page(password="")
_keyed.server_data.key_path = "C:/keys/id_ed25519"
_close(_keyed)
check("§3 a key path needs NO secret: the re-arm goes ahead", _keyed.reconnect() is True)
check("§3 ...and the new thread carries the same key path",
      _keyed.terminal_thread.key_path == "C:/keys/id_ed25519")
_keyed.shutdown()

_fake_cm.secrets = {}
_own = _page(password="FromTheSession")
_close(_own)
check("§4 a keyring with nothing reuses the credential the session was opened with",
      _own.reconnect() is True
      and _own.terminal_thread.password == "FromTheSession")
_own.shutdown()

_fake_cm.secrets = {"snode001": "FromTheKeyring"}
_stored = _page(password="FromTheSession")
_close(_stored)
check("§4 the STORED credential wins when the keyring has one",
      _stored.reconnect() is True
      and _stored.terminal_thread.password == "FromTheKeyring",
      _stored.terminal_thread.password)
check("§4 ...and the page's own copy follows it (the next re-arm starts from the store)",
      _stored._session_password == "FromTheKeyring")
_stored.shutdown()
_fake_cm.secrets = {}

_broken = _page(password="kept")
_close(_broken)


def _raising_cm():
    raise RuntimeError("keyring unavailable")


CM.get_credential_manager = _raising_cm
check("§4 an unusable keyring is the shipped \"no stored credential\" path (never an exception)",
      _broken.reconnect() is True and _broken.terminal_thread.password == "kept")
_broken.shutdown()
CM.get_credential_manager = lambda: _fake_cm


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the doors: the two containers and the name dialog ==")
# ════════════════════════════════════════════════════════════════════════════

_win = ST.SSHTerminalWindow(_data(), None, password="pw", initial_command="k9s")
_win_page = _win.page
_live_thread = _win_page.terminal_thread
check("§5 the window's tab bar really takes the custom context menu (the real path)",
      _win.session_tabs.tabBar().contextMenuPolicy().name == "CustomContextMenu")
_tab_menu = _win._build_tab_context_menu(0)
check("§5 the TAB's menu carries the two session rows",
      [a.text() for a in _tab_menu.actions()] == [i18n.t("terminal.reconnect"),
                                                  i18n.t("terminal.attach_tmux")],
      [a.text() for a in _tab_menu.actions()])
check("§5 ...and Reconnect is DISABLED while the session is live",
      _tab_menu.actions()[0].isEnabled() is False)
check("§5 the window's own menu carries them for the session on screen",
      i18n.t("terminal.reconnect") in [a.text() for a in _win._build_context_menu().actions()])
check("§5 a stale tab index answers None instead of a menu",
      _win._build_tab_context_menu(99) is None)

_tab_menu.actions()[0].trigger()
check("§5 the disabled row does nothing (a live session is not re-armed)",
      _win_page.terminal_thread is _live_thread and _win_page.can_reconnect() is False)
_win_page.terminal_thread.closed_signal.emit()
app.processEvents()
check("§5 once `closed_signal` arrived the very same menu ENABLES the row",
      _win._build_tab_context_menu(0).actions()[0].isEnabled() is True)
check("§5 the delegate re-arms through the session and answers True",
      _win.reconnect_session(_win_page) is True)
check("§5 ...and the re-arm did NOT open a second session anywhere",
      _win.session_tabs.count() == 1 and not _win_page.can_reconnect())
_win_page.terminal_thread.connected_signal.emit()
check("§5 the window's re-arm re-sent the session's command too",
      wait_for(lambda: _win_page.terminal_thread.channel.sent == [b"k9s\n"], timeout_ms=3000),
      _win_page.terminal_thread.channel.sent)

_FakeInputDialog.SCRIPT = []
_FakeInputDialog.CALLS = []
check("§5 a cancelled name field attaches nothing",
      _win.attach_tmux_session(_win_page) is False and len(_FakeInputDialog.CALLS) == 1)
check("§5 the field asks with its own title and prompt",
      _FakeInputDialog.CALLS[0] == (i18n.t("terminal.attach_tmux_title"),
                                    i18n.t("terminal.attach_tmux_prompt")),
      _FakeInputDialog.CALLS[0])

_FakeInputDialog.SCRIPT = ["  my work  "]
_win_page.terminal_thread.channel.sent = []
check("§5 a named session is attached on the LIVE session at once",
      _win.attach_tmux_session(_win_page) is True)
check("§5 ...with the quoted command on the wire",
      _win_page.terminal_thread.channel.sent == [b"tmux attach -t 'my work'\n"],
      _win_page.terminal_thread.channel.sent)
check("§5 ...recorded in the command history like any explicit send",
      any(entry.get("cmd") == "tmux attach -t 'my work'"
          for entry in _win_page.command_history.load()),
      _win_page.command_history.load())
check("§5 ...and it became the session's OWN command (a re-arm attaches again)",
      _win_page._session_command == "tmux attach -t 'my work'")
check("§5 the attach is reported on the status surface",
      _win_page.session_status == i18n.t("terminal.attach_tmux_sent", name="my work"),
      _win_page.session_status)
check("§5 an empty name returns False without touching the wire",
      _win_page.attach_tmux("") is False)

_win_page.terminal_thread.closed_signal.emit()
app.processEvents()
_win_page.terminal_thread.channel.sent = []
_FakeInputDialog.SCRIPT = ["work"]
check("§5 on an ENDED session the same door rides the re-arm",
      _win.attach_tmux_session(_win_page) is True and _win_page.can_reconnect() is False)
_win_page.terminal_thread.connected_signal.emit()
check("§5 ...and the attach command is what goes out (not the original one)",
      wait_for(lambda: _win_page.terminal_thread.channel.sent == [b"tmux attach -t 'work'\n"],
               timeout_ms=3000),
      _win_page.terminal_thread.channel.sent)
_win_page.shutdown()

_dock = TD.TerminalDockContent()
_dock_page = _dock.add_session(_data(alias="db"), password="pw")
check("§5 the dock's tab bar takes the same custom context menu",
      _dock.session_tabs.tabBar().contextMenuPolicy().name == "CustomContextMenu")
check("§5 the dock's tab menu carries the pair and reads the LIVE state",
      [a.text() for a in _dock._build_tab_context_menu(0).actions()]
      == [i18n.t("terminal.reconnect"), i18n.t("terminal.attach_tmux")]
      and _dock._build_tab_context_menu(0).actions()[0].isEnabled() is False)
check("§5 the dock's own menu carries them for the session in front",
      i18n.t("terminal.reconnect") in [a.text() for a in _dock._build_context_menu().actions()])
check("§5 a stale dock tab index answers None", _dock._build_tab_context_menu(-1) is None)
_dock_page.terminal_thread.closed_signal.emit()
app.processEvents()
check("§5 the dock's tab menu enables the row once the session ended",
      _dock._build_tab_context_menu(0).actions()[0].isEnabled() is True)
check("§5 the dock's delegate re-arms the session", _dock.reconnect_session(_dock_page) is True)
check("§5 ...and the dock still holds exactly ONE tab", _dock.session_tabs.count() == 1)
_dock_page.shutdown()

_FakeInputDialog.SCRIPT = ["attached"]
check("§5 the name field is the SHIPPED seam (`ssh_terminal.QInputDialog`, read at call time)",
      TP.ask_tmux_name(None) == "attached" and TD._st_module() is ST)
_FakeInputDialog.SCRIPT = []
check("§5 a cancelled field answers an empty name", TP.ask_tmux_name(None) == "")


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
LANGS = load_i18n_langs(ROOT)
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check("§6 the pin counts the shipped keys (the v1.9 line's 1040 + ELEVEN of v1.9.1 "
      "+ THIRTEEN of v1.9.3: the command dialog and the reader's encoding)",
      EXPECTED_I18N_KEYS == 1040 + 11 + 13, f"{EXPECTED_I18N_KEYS}")
check("§6 the pin names this release or a LATER one (the file describes v1.9.1)",
      releases_at_least("1.9.1"), EXPECTED_APP_VERSION)
_NEW_KEYS = ("terminal.reconnect", "terminal.reconnect_tooltip", "terminal.reconnecting",
             "terminal.reconnect_marker", "terminal.reconnect_live",
             "terminal.reconnect_no_credential", "terminal.attach_tmux",
             "terminal.attach_tmux_tooltip", "terminal.attach_tmux_title",
             "terminal.attach_tmux_prompt", "terminal.attach_tmux_sent")
check("§6 every new key is in EVERY language file",
      all(all(k in translation_keys(d) for d in LANGS.values()) for k in _NEW_KEYS),
      [k for k in _NEW_KEYS
       if not all(k in translation_keys(d) for d in LANGS.values())])
check("§6 the reconnect keys are really TRANSLATED, not left as the English copy",
      all(len({str(d.get(k, "")) for d in LANGS.values()}) > 1
          for k in ("terminal.reconnect", "terminal.attach_tmux")),
      [k for k in ("terminal.reconnect", "terminal.attach_tmux")
       if len({str(d.get(k, "")) for d in LANGS.values()}) <= 1])


# ════════════════════════════════════════════════════════════════════════════
ST.QInputDialog = _orig_input
ST.SSHTerminalThread = _orig_thread_cls
CM.get_credential_manager = _orig_gcm
finish()
