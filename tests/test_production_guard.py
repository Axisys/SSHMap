# -*- coding: utf-8 -*-
"""v1.9 — the production-tag guard: ONE policy, ONE dialog and the TWO verbs' call sites.
A node's own `tags` plus the `guard_tags` of `~/.sshmap/config.json` (default EMPTY, `guard_verbs` may narrow
the pair) decide whether a gesture that reaches MORE THAN ONE session — the multi-input broadcast — or that
pushes a whole BLOCK into one — a MULTI-LINE paste — asks first. The policy is PURE; `confirm()` is the ONE
dialog and the module attribute is its seam, so a GUI that cannot answer REFUSES rather than passing. The
paste is the canvas gesture reaching the page's `guard_hook`; the broadcast asks about the WHOLE registry in
ONE dialog and puts the QAction back when the user says no. Rule — `AGENTS.md` §4.28, mechanism — §72.
"""
import sys
import types

from _common import (bootstrap, check, finish, check_release_state, load_i18n_langs,
                     check_i18n_parity)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.production_guard as PG
from models.server import ServerData
from modules.terminal_page import TerminalSessionPage
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from ui.main_window_ssh import SshMixin


class FakeBox:
    """The `QMessageBox` seam: records the ONE question and answers what the test wants."""

    answer = 2                      # == StandardButton.No
    asked = []
    defaults = []
    titles = []

    class Icon:                     # noqa: N801 — the Qt spelling
        Warning = "warning"

    class StandardButton:           # noqa: N801
        Yes = 1
        No = 2

    def __init__(self, parent=None):
        self.parent = parent
        self.text = ""
        self.title = ""

    def setIcon(self, icon):        # noqa: N802
        pass

    def setWindowTitle(self, text):  # noqa: N802
        self.title = text
        FakeBox.titles.append(text)

    def setText(self, text):        # noqa: N802
        self.text = text
        FakeBox.asked.append(text)

    def setStandardButtons(self, buttons):  # noqa: N802
        pass

    def setDefaultButton(self, button):     # noqa: N802
        FakeBox.defaults.append(button)

    def exec(self):                 # noqa: N802
        return FakeBox.answer


class FakeThread:
    """The fake `SSHTerminalThread`: the recorded sends (the pattern of `test_terminal_mouse.py`)."""

    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


# ════════════════════════════════════════════════════════════
# 1. The PURE policy (no window, no dialog)
# ════════════════════════════════════════════════════════════
print("== the pure policy ==")

check("no config → NO tags and BOTH verbs (the declared default)",
      PG.guard_tags({}) == () and PG.guard_verbs({}) == ("broadcast", "paste"),
      str(PG.guard_tags({})))
check("`guard_tags` accepts a string and a list, drops junk and duplicates",
      PG.guard_tags({"guard_tags": "prod"}) == ("prod",)
      and PG.guard_tags({"guard_tags": ["prod", "", "prod", " live ", 7]}) == ("prod", "live", "7"),
      str(PG.guard_tags({"guard_tags": ["prod", "", "prod", " live ", 7]})))
check("a foreign type is no policy (never an exception)",
      PG.guard_tags({"guard_tags": {"a": 1}}) == () and PG.guard_tags(None) == ())
check("`guard_verbs` narrows to the KNOWN names only, and never to nothing",
      PG.guard_verbs({"guard_verbs": ["paste"]}) == ("paste",)
      and PG.guard_verbs({"guard_verbs": ["nope"]}) == ("broadcast", "paste"))
check("the node's tag MATCHES case-insensitively and is answered in the node's own spelling",
      PG.guard_tag(["production", "PROD"], {"guard_tags": ["prod"]}) == "PROD",
      str(PG.guard_tag(["production", "PROD"], {"guard_tags": ["prod"]})))
check("an unguarded node and an empty tag list answer \"\"",
      PG.guard_tag(["dev"], {"guard_tags": ["prod"]}) == "" and PG.guard_tag([], {}) == "")
check("`node_tags` reads a `ServerData`, a dict and a broken record",
      PG.node_tags(ServerData(id="x", alias="a", host="h", user="u", tags=["prod", "eu"]))
      == ["prod", "eu"]
      and PG.node_tags({"tags": ["p"]}) == ["p"] and PG.node_tags(None) == []
      and PG.node_tags(object()) == [])
check("`needs_confirmation` is the ONE decision both verbs ask",
      PG.needs_confirmation(PG.VERB_BROADCAST, ["prod"], {"guard_tags": ["prod"]}) == "prod"
      and PG.needs_confirmation(PG.VERB_PASTE, ["prod"], {"guard_tags": ["prod"]}) == "prod"
      and PG.needs_confirmation(PG.VERB_PASTE, ["prod"],
                                {"guard_tags": ["prod"], "guard_verbs": ["broadcast"]}) == ""
      and PG.needs_confirmation(PG.VERB_BROADCAST, ["dev"], {"guard_tags": ["prod"]}) == "")


# ════════════════════════════════════════════════════════════
# 2. The ONE dialog and its refusal by default
# ════════════════════════════════════════════════════════════
print("== the dialog seam ==")

_orig_box = PG.QMessageBox
PG.QMessageBox = FakeBox
try:
    FakeBox.answer = FakeBox.StandardButton.No
    FakeBox.asked.clear()
    FakeBox.defaults.clear()
    check("a REFUSED dialog answers False (and the sentence names the session, the tag and the lines)",
          PG.confirm(PG.VERB_PASTE, "prod", alias="web-1", lines=3) is False
          and "web-1" in FakeBox.asked[-1] and "prod" in FakeBox.asked[-1]
          and "3" in FakeBox.asked[-1], FakeBox.asked[-1])
    check("the DEFAULT button is No — Enter on the dialog never green-lights the gesture",
          FakeBox.defaults == [FakeBox.StandardButton.No], str(FakeBox.defaults))
    FakeBox.answer = FakeBox.StandardButton.Yes
    check("a confirmed dialog answers True",
          PG.confirm(PG.VERB_PASTE, "prod", alias="w", lines=2) is True)
    FakeBox.asked.clear()
    FakeBox.titles.clear()
    PG.confirm(PG.VERB_BROADCAST, "prod", names="web-1 (prod), db-1 (prod)")
    check("the broadcast sentence carries the WHOLE names list",
          "web-1 (prod), db-1 (prod)" in FakeBox.asked[-1], FakeBox.asked[-1])
    check("the title is the `guard.title` key of the ACTIVE language (never a code literal)",
          FakeBox.titles[-1] == i18n.t("guard.title"), repr(FakeBox.titles[-1]))
finally:
    PG.QMessageBox = _orig_box

check("without Qt the guard REFUSES (never a silent pass)",
      (lambda: (setattr(PG, "QMessageBox", None), PG.confirm(PG.VERB_PASTE, "prod"),
                setattr(PG, "QMessageBox", _orig_box))[1])() is False)


# ════════════════════════════════════════════════════════════
# 3. The broadcast: the WHOLE registry in ONE dialog
# ════════════════════════════════════════════════════════════
print("== the multi-input broadcast (the whole registry, ONE question) ==")


def session(alias, tags, host="10.0.0.1"):
    """One registry entry: the broadcast reader reaches `page.server_data` (the page owns the node)."""
    return types.SimpleNamespace(
        server_data=ServerData(id=alias, alias=alias, host=host, user="root", tags=list(tags)))


class _Window:
    """The `SshMixin` seam: the mixin duck-types the instance, so the registry is all it needs."""

    def __init__(self, sessions):
        self._terminal_windows = list(sessions)
        self.act_multi_input = None


_asked = []
_orig_confirm = PG.confirm
PG.confirm = lambda verb, tag, **kw: (_asked.append((verb, tag, kw.get("names"))), False)[1]
i18n.save_config({"guard_tags": ["prod"]})
try:
    _asked.clear()
    check("a registry with NO guarded session passes without asking",
          SshMixin._confirm_guard_broadcast(_Window([session("dev-1", ["dev"]),
                                                     session("lab", [])])) is True
          and _asked == [], str(_asked))

    _asked.clear()
    refused = SshMixin._confirm_guard_broadcast(
        _Window([session("web-1", ["prod", "eu"]), session("dev-1", ["dev"]),
                 session("db-1", ["PROD"])]))
    check("a guarded session makes the broadcast ask (a refusal answers False)",
          refused is False and len(_asked) == 1, str(_asked))
    check("…the ONE question is the BROADCAST verb and names EVERY guarded session (once, one dialog)",
          _asked and _asked[0][0] == PG.VERB_BROADCAST
          and _asked[0][2] == "web-1 (prod), db-1 (PROD)", str(_asked))
    check("…the unguarded session is NOT named in it", "dev-1" not in str(_asked[0][2]), str(_asked))

    i18n.save_config({"guard_tags": ["prod"], "guard_verbs": ["paste"]})
    _asked.clear()
    check('…and `guard_verbs: ["paste"]` SILENCES the broadcast (the narrowed pair is really asked)',
          SshMixin._confirm_guard_broadcast(_Window([session("web-1", ["prod"])])) is True
          and _asked == [], str(_asked))
    i18n.save_config({"guard_tags": ["prod"]})

    PG.confirm = lambda verb, tag, **kw: True
    check("…and a confirmed dialog lets the mode through",
          SshMixin._confirm_guard_broadcast(_Window([session("web-1", ["prod"])])) is True)
    PG.confirm = _orig_confirm

    act = QAction("multi")
    act.setCheckable(True)
    act.setChecked(True)
    win = _Window([])
    win.act_multi_input = act
    SshMixin._reset_multi_action(win)
    check("a REFUSED broadcast puts the checkable QAction back (the checkmark never lies)",
          act.isChecked() is False, str(act.isChecked()))
    SshMixin._reset_multi_action(_Window([]))       # no QAction at all
    check("…and a window without the action is a quiet no-op (never a raise)", True)
finally:
    PG.confirm = _orig_confirm


# ════════════════════════════════════════════════════════════
# 4. The paste: the page's hook and the canvas gesture
# ════════════════════════════════════════════════════════════
print("== the multi-line paste ==")

_page_mod = sys.modules["modules.terminal_page"]
_orig_page_confirm = _page_mod.guard_confirm
import modules.ssh_terminal as ST
from _fakes import FakeSSHThread as _FakeThread

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # the shipped seam: every page built here is built on the fake
i18n.save_config({"guard_tags": ["prod"]})
try:
    page = TerminalSessionPage(ServerData(id="g1", alias="prod-web", host="10.0.0.9", user="root",
                                          tags=["prod"]))
    check("the page installs its hook on the canvas (the canvas owns the gesture, the page the node)",
          callable(page.widget.guard_hook), str(page.widget.guard_hook))
    calls = []
    _page_mod.guard_confirm = lambda verb, tag, **kw: (calls.append((verb, tag, kw)), False)[1]
    check("a 3-line paste into a `prod` session is REFUSED (the ONE dialog is asked with the words)",
          page.widget._guard_allows(3) is False and calls and calls[0][0] == PG.VERB_PASTE
          and calls[0][1] == "prod" and calls[0][2]["lines"] == 3
          and calls[0][2]["alias"] == "prod-web", str(calls))
    _page_mod.guard_confirm = lambda *a, **kw: True
    check("…and it goes ahead when the user confirms", page.widget._guard_allows(3) is True)
    _page_mod.guard_confirm = lambda verb, tag, **kw: (calls.append((verb, tag, kw)), True)[1]
    i18n.save_config({"guard_tags": ["prod"], "guard_verbs": ["broadcast"]})
    calls.clear()
    check('…and `guard_verbs: ["broadcast"]` SILENCES the paste (the narrowed pair is really asked)',
          page.widget._guard_allows(3) is True and calls == [], str(calls))
    i18n.save_config({"guard_tags": ["prod"], "guard_verbs": ["paste"]})
    calls.clear()
    check('…while `guard_verbs: ["paste"]` still asks for the paste (the pair is not dead)',
          page.widget._guard_allows(3) is True and len(calls) == 1, str(calls))
    i18n.save_config({"guard_tags": ["prod"]})
    page.shutdown()

    page2 = TerminalSessionPage(ServerData(id="g2", alias="dev", host="10.0.0.8", user="root",
                                           tags=["dev"]))
    check("a session WITHOUT a guard tag never asks", page2.widget._guard_allows(5) is True)
    page2.shutdown()
finally:
    _page_mod.guard_confirm = _orig_page_confirm
    ST.SSHTerminalThread = _orig_thread_cls
    i18n.save_config({})

scr = TerminalScreen(columns=40, lines=6)
canvas = TerminalWidget(scr, FakeThread())
canvas.resize(40 * canvas.cell_size[0], 6 * canvas.cell_size[1])
seen = []

check("a canvas with NO hook (a page that installed none) allows the block",
      canvas._guard_allows(3) is True)

canvas.guard_hook = lambda lines: (seen.append(lines), False)[1]
QApplication.clipboard().setText("one line only")
canvas._bracketed_paste()
check("a SINGLE-line paste never asks the guard", seen == [], str(seen))
canvas.terminal_thread.sent.clear()          # the single-line block above already went out
QApplication.clipboard().setText("one\ntwo\nthree")
canvas._bracketed_paste()
check("a MULTI-line paste asks with its line count and a refusal stops it at the canvas",
      seen == [3] and canvas.terminal_thread.sent == [], f"{seen} {canvas.terminal_thread.sent}")
canvas.guard_hook = lambda lines: True
canvas._bracketed_paste()
check("a confirmed paste reaches the session (the block is not swallowed by the guard)",
      len(canvas.terminal_thread.sent) == 1 and b"one\ntwo\nthree" in canvas.terminal_thread.sent[0],
      str(canvas.terminal_thread.sent))


def _broken(lines):
    """A guard that cannot answer: the canvas must REFUSE, never wave a block into a guarded session."""
    raise RuntimeError("the policy store is gone")


canvas.guard_hook = _broken
check("a hook that RAISES refuses the block (never a silent pass)",
      canvas._guard_allows(3) is False)


# ════════════════════════════════════════════════════════════
# 5. Release state + i18n parity
# ════════════════════════════════════════════════════════════
print("== release state + i18n parity ==")

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
