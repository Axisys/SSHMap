# -*- coding: utf-8 -*-
"""v1.9.6 — the command guard: the PURE classifier, the policy, the ONE dialog and its doors.
The token table (reboot, `rm` with BOTH flags, a package `remove`, `mkfs`, `dd` onto a device, `wipefs`,
the partitioners, `userdel`, a fatal `kill`, the fork-bomb shape) is driven without a window and the
module NEVER raises. §3 the policy (`guard_commands`, ON by default); §4 the dialog seam and its
refusal by default; §5 the ONE gate of the run boundary in `PluginManager`; §6 the multi-input
submission at the canvas's `Enter`; §7 the release state. Rule — `AGENTS.md` §4.30, mechanism — §74.
"""
import os
import sys
import threading
import types

from _common import (EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, bootstrap, check, check_i18n_parity,
                     check_release_state, clear_cfg, finish, load_i18n_langs, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + offscreen inside)

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
import modules.command_guard as CG  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import modules.terminal_widget_input as TWI  # noqa: E402
from modules.multi_input import MultiInputHub  # noqa: E402
from modules.terminal_screen import TerminalScreen  # noqa: E402
from modules.terminal_widget import TerminalWidget  # noqa: E402

_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — the "it lives in ONE place" audits."""
    if parts not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[parts] = f.read()
    return _SRC[parts]


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the PURE classifier: the declared token table ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the declared families are the table this file drives",
      CG.FAMILIES == ("reboot", "rm", "remove", "mkfs", "dd", "wipefs", "partition", "userdel",
                      "kill", "fork_bomb"), str(CG.FAMILIES))
check("§1 the reboot family matches, with a wrapper and a foreign path",
      [CG.dangerous_token(c) for c in ("reboot", "shutdown -h now", "/sbin/poweroff",
                                       "sudo halt", "doas -u root reboot")]
      == ["reboot", "shutdown", "poweroff", "halt", "reboot"],
      str([CG.dangerous_token(c) for c in ("reboot", "shutdown -h now", "/sbin/poweroff",
                                           "sudo halt", "doas -u root reboot")]))
check("§1 `rm` needs BOTH flags — one alone is not the family",
      [CG.dangerous_token(c) for c in ("rm -rf /", "rm -fr x", "rm -r -f y", "rm -rfv build",
                                       "rm --recursive --force z", "sudo rm -rf /tmp")]
      == ["rm -rf"] * 6,
      str([CG.dangerous_token(c) for c in ("rm -rf /", "rm -fr x", "rm -r -f y", "rm -rfv build",
                                           "rm --recursive --force z", "sudo rm -rf /tmp")]))
check("§1 ...while a lone `-f`, a lone `-r` and an UNRELATED command stay out of it",
      [CG.dangerous_token(c) for c in ("rm -f x", "rm -r x", "rm x", "mv -rf a b", "chmod -R 777 /")]
      == [""] * 5,
      str([CG.dangerous_token(c) for c in ("rm -f x", "rm -r x", "rm x", "mv -rf a b",
                                           "chmod -R 777 /")]))
check("§1 a subcommand prefix does not HIDE the family (the declared generosity)",
      CG.dangerous_token("git rm -rf .") == "rm -rf"
      and CG.dangerous_token("docker rm -rf container") == "rm -rf"
      and CG.dangerous_token("xargs rm -rf < list") == "rm -rf")
check("§1 the package managers' own `remove` is the family's second spelling",
      CG.dangerous_token("apt remove nano") == "remove"
      and CG.dangerous_token("apt-get remove -y nginx") == "remove"
      and CG.dangerous_token("dnf remove kernel") == "remove")
check("§1 the filesystem family matches mkfs and every `mkfs.<fs>` spelling",
      [CG.dangerous_token(c) for c in ("mkfs /dev/sdb", "mkfs.ext4 /dev/sda1",
                                       "sudo mkfs.xfs -f /dev/sdc", "mke2fs /dev/sdd")]
      == ["mkfs", "mkfs.ext4", "mkfs.xfs", ""],
      str([CG.dangerous_token(c) for c in ("mkfs /dev/sdb", "mkfs.ext4 /dev/sda1",
                                           "sudo mkfs.xfs -f /dev/sdc", "mke2fs /dev/sdd")]))
check("§1 `dd` fires on an `of=/dev/…` operand and NOT on `of=/dev/null`",
      CG.dangerous_token("dd if=/dev/zero of=/dev/sda bs=1M") == "dd"
      and CG.dangerous_token("dd of=/dev/sdb") == "dd"
      and CG.dangerous_token("dd if=/dev/sda of=/dev/null") == ""
      and CG.dangerous_token("dd if=/dev/sda of=backup.img") == "")
check("§1 wipefs / the partitioners / userdel are matched by their words",
      [CG.dangerous_token(c) for c in ("wipefs -a /dev/sdb", "fdisk /dev/sda",
                                       "sudo parted /dev/sdb mklabel gpt", "diskpart")]
      == ["wipefs", "fdisk", "parted", "diskpart"]
      and CG.dangerous_token("userdel -r bob") == "userdel"
      and CG.dangerous_token("/usr/sbin/userdel bob") == "userdel")
check("§1 the fatal `kill` family names its two shapes and NOT a plain signal",
      [CG.dangerous_token(c) for c in ("kill -9 1234", "pkill -KILL nginx",
                                       "kill -s 9 5", "kill -1 1", "kill -s HUP 5")]
      == ["kill -9", "kill -9", "kill -9", "kill -1", "kill -1"]
      and CG.dangerous_token("kill -15 1234") == "" and CG.dangerous_token("kill 1234") == "")
check("§1 the fork bomb is a WHITESPACE-NORMALISED shape and its re-spellings match",
      [CG.dangerous_token(c) for c in (":(){ :|:& };:", ":(){:|:&};:", "  : ( ) { : | : & } ; :  ",
                                       "bomb(){ bomb|bomb& };bomb")]
      == ["fork bomb"] * 4,
      str([CG.dangerous_token(c) for c in (":(){ :|:& };:", ":(){:|:&};:",
                                           "  : ( ) { : | : & } ; :  ",
                                           "bomb(){ bomb|bomb& };bomb")]))
check("§1 an ordinary fleet command never matches (the everyday case stays quiet)",
      [CG.dangerous_token(c) for c in ("uptime", "ls -la /var/log", "systemctl restart nginx",
                                       "docker ps", "df -h", "grep -rf pattern file")]
      == [""] * 6,
      str([CG.dangerous_token(c) for c in ("uptime", "ls -la /var/log",
                                           "systemctl restart nginx", "docker ps", "df -h",
                                           "grep -rf pattern file")]))
check("§1 a QUOTED word is an argument, not a command (the quote-aware word split)",
      CG.dangerous_token('echo "rm -rf /"') == ""
      and CG.dangerous_token("echo reboot") == "reboot")
check("§1 a separator never hides the family that follows it",
      CG.dangerous_token("cd /tmp && rm -rf x") == "rm -rf"
      and CG.dangerous_token("true; shutdown -h now") == "shutdown"
      and CG.dangerous_token("cat list | xargs -n1 kill -9") == "kill -9")
check("§1 the classifier answers the FIRST match, so the dialog names ONE token",
      CG.dangerous_token("reboot && rm -rf /") == "reboot"
      and CG.dangerous_token("rm -rf / && reboot") == "rm -rf")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the classifier NEVER raises and prints a bounded excerpt ==")
# ════════════════════════════════════════════════════════════════════════════

check("§2 a foreign value, an empty command and a broken quote are 'no match' (never a raise)",
      CG.dangerous_token(None) == "" and CG.dangerous_token(5) == ""
      and CG.dangerous_token(object()) == "" and CG.dangerous_token("   ") == ""
      and CG.dangerous_token("echo 'unclosed") == "")
check("§2 a huge command is CLASSIFIED under the bound and never blows up",
      CG.dangerous_token("x" * 200000) == ""
      and CG.dangerous_token("rm -rf / " + "y" * 100000) == "rm -rf"
      and CG.MAX_COMMAND_CHARS > 0 and CG.SHOWN_CHARS > 0)
check("§2 the excerpt is ONE line and is capped (the dialog never prints a wall of text)",
      CG.excerpt("a\nb\tc") == "a b c" and "\n" not in CG.excerpt("a\nb")
      and len(CG.excerpt("z" * 5000)) == CG.SHOWN_CHARS + 1
      and CG.excerpt(None) == "")


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the policy: `guard_commands`, ON by default ==")
# ════════════════════════════════════════════════════════════════════════════

check("§3 the guard is ARMED by default — a missing key, a foreign value and a broken store",
      CG.guard_enabled({}) is True and CG.guard_enabled(None) is True
      and CG.guard_enabled({"guard_commands": "no"}) is True
      and CG.guard_enabled(object()) is True)
check("§3 only an explicit `false` turns it off (the INERT escape)",
      CG.guard_enabled({"guard_commands": False}) is False
      and CG.needs_confirmation("rm -rf /", {"guard_commands": False}) == "")
check("§3 `needs_confirmation` is the ONE decision every door asks",
      CG.needs_confirmation("rm -rf /", {}) == "rm -rf"
      and CG.needs_confirmation("uptime", {}) == ""
      and CG.needs_confirmation("rm -rf /", {"guard_commands": True}) == "rm -rf")
check("§3 the policy is CONFIG and never the project (the key is the module's own constant)",
      CG.GUARD_COMMANDS_KEY == "guard_commands")

clear_cfg()
i18n.save_config({"guard_commands": False})
try:
    check("§3 the shipped reader reads ~/.sshmap/config.json (the real store, not a fake)",
          CG.guard_enabled() is False and CG.needs_confirmation("reboot") == "")
finally:
    clear_cfg()
check("§3 the store is back to the declared default after the probe", CG.guard_enabled() is True)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the ONE dialog and its refusal by default ==")
# ════════════════════════════════════════════════════════════════════════════


class FakeBox:
    """The `QMessageBox` seam: records the ONE question and answers what the test wants."""

    answer = 2                      # == StandardButton.No
    asked = []
    defaults = []
    titles = []
    parents = []

    class Icon:                     # noqa: N801 — the Qt spelling
        Warning = "warning"

    class StandardButton:           # noqa: N801
        Yes = 1
        No = 2

    def __init__(self, parent=None):
        self.parent = parent
        self.text = ""
        self.title = ""
        FakeBox.parents.append(parent)

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


_orig_box = CG.QMessageBox
CG.QMessageBox = FakeBox
try:
    FakeBox.answer = FakeBox.StandardButton.No
    FakeBox.asked.clear()
    FakeBox.defaults.clear()
    FakeBox.titles.clear()
    check("§4 a REFUSED run answers False and the sentence NAMES the token, the command and the count",
          CG.confirm("rm -rf /var", "rm -rf", count=7) is False
          and "rm -rf" in FakeBox.asked[-1] and "rm -rf /var" in FakeBox.asked[-1]
          and "7" in FakeBox.asked[-1], FakeBox.asked[-1])
    check("§4 the DEFAULT button is No — Enter on the dialog never green-lights a run",
          FakeBox.defaults == [FakeBox.StandardButton.No], str(FakeBox.defaults))
    check("§4 the title is the shared `guard.title` key of the ACTIVE language",
          FakeBox.titles[-1] == i18n.t("guard.title"), repr(FakeBox.titles[-1]))
    FakeBox.answer = FakeBox.StandardButton.Yes
    check("§4 a confirmed run answers True and the WIDGET parent is handed to the box",
          CG.confirm("reboot", "reboot", count=30, parent="W") is True and FakeBox.parents[-1] == "W")
    check("§4 the BROADCAST question is the second sentence and names the line and the count",
          CG.confirm_broadcast("rm -rf /", "rm -rf", count=3) is True
          and "rm -rf /" in FakeBox.asked[-1] and "3" in FakeBox.asked[-1]
          and CG.broadcast_text("a b", "rm -rf", 2)
          == i18n.t("guard.command.broadcast", command="a b", token="rm -rf", count=2))
    check("§4 the run's sentence is built from the i18n key (never a code literal)",
          CG.confirmation_text("x", "reboot", 4)
          == i18n.t("guard.command.text", command="x", token="reboot", count=4))
finally:
    CG.QMessageBox = _orig_box

check("§4 without Qt the guard REFUSES (never a silent pass)",
      (lambda: (setattr(CG, "QMessageBox", None), CG.confirm("reboot", "reboot"),
                CG.confirm_broadcast("reboot", "reboot"),
                setattr(CG, "QMessageBox", _orig_box))[1])() is False)


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the ONE gate of the run boundary (PluginManager) ==")
# ════════════════════════════════════════════════════════════════════════════

_NODES = [PM.PluginNode(id="n1", alias="web-1", host="192.0.2.11", port=22, user="root"),
          PM.PluginNode(id="n2", alias="db-1", host="192.0.2.12", port=2222, user="deploy")]


class _FakeRunner(QObject):
    """The runner seam: what the gate must NOT build on a refusal and what it builds on a yes."""

    node_result = Signal(str, dict)
    all_finished = Signal(list)
    finished = Signal()
    built = []

    def __init__(self, nodes, command, plugin_id="", timeout=0.0, node_facts=None, parent=None):
        super().__init__(parent)
        _FakeRunner.built.append(([n.id for n in nodes], command, plugin_id))

    def start(self):
        pass


_ask_calls = []
_orig_confirm = PM.command_confirm
_orig_runner = None


def _refuse(command, token, **kw):
    _ask_calls.append((command, token, kw.get("count")))
    return False


def _accept(command, token, **kw):
    _ask_calls.append((command, token, kw.get("count")))
    return True


try:
    import modules.plugin_runner as PR
    _orig_runner = PR.PluginCommandRunner
    PR.PluginCommandRunner = _FakeRunner

    mgr = PM.PluginManager()
    _refused = []
    _finished = []
    mgr.command_refused.connect(lambda *a: _refused.append(a))
    mgr.command_finished.connect(lambda *a: _finished.append(a))

    clear_cfg()                       # the default policy: the guard is ARMED
    PM.command_confirm = _refuse
    _ask_calls.clear()
    _FakeRunner.built.clear()
    check("§5 a destructive command is REFUSED at the boundary (a direct caller hears False)",
          mgr.plugin_run_command("demo", _NODES, "rm -rf /var") is False, str(_refused))
    check("§5 ...after exactly ONE question per RUN, naming the token and the node count",
          len(_ask_calls) == 1 and _ask_calls[0][1] == "rm -rf" and _ask_calls[0][2] == 2,
          str(_ask_calls))
    check("§5 ...with NO runner built and nothing registered (no connection is opened at all)",
          _FakeRunner.built == [] and mgr.active_workers() == [] and mgr.running_commands() == 0
          and mgr._workers == [],
          f"{_FakeRunner.built} {mgr.active_workers()} {mgr._workers}")
    check("§5 `command_refused` carries (plugin_id, token, node count)",
          _refused == [("demo", "rm -rf", 2)], str(_refused))
    check("§5 `command_finished` fires with an EMPTY list (a refusal is a RESULT, not a silence)",
          _finished == [("demo", [])], str(_finished))
    check("§5 `last_command_refusal()` is the honest synchronous answer the core door reads",
          mgr.last_command_refusal() == ("rm -rf", 2), str(mgr.last_command_refusal()))

    _refused.clear()
    _finished.clear()
    mgr.plugin_run_command("demo", _NODES, "reboot")
    check("§5 the guard reads the FINAL string — a second run asks its OWN question",
          len(_ask_calls) == 2 and _refused == [("demo", "reboot", 2)], str(_refused))

    _cb = []
    _ask_calls.clear()
    mgr.plugin_run_command("demo", _NODES, "shutdown -h now", on_finished=lambda rs: _cb.append(rs))
    check("§5 a refused run still calls the plugin's own `on_finished` with the empty list",
          _cb == [[]], str(_cb))

    PM.command_confirm = _accept
    _ask_calls.clear()
    _FakeRunner.built.clear()
    _finished.clear()
    check("§5 a CONFIRMED run builds the runner and reports True (the guard is not a lock)",
          mgr.plugin_run_command("demo", _NODES, "rm -rf /tmp/x") is True
          and _FakeRunner.built == [(["n1", "n2"], "rm -rf /tmp/x", "demo")]
          and mgr.last_command_refusal() == () and _finished == [],
          f"{_FakeRunner.built} {mgr.last_command_refusal()}")

    _ask_calls.clear()
    _FakeRunner.built.clear()
    check("§5 an ORDINARY command never asks at all (no dialog, no token)",
          mgr.plugin_run_command("demo", _NODES, "uptime") is True
          and _ask_calls == [] and _FakeRunner.built == [(["n1", "n2"], "uptime", "demo")],
          f"{_ask_calls} {_FakeRunner.built}")

    i18n.save_config({"guard_commands": False})
    _ask_calls.clear()
    _FakeRunner.built.clear()
    check("§5 the INERT escape really disarms the gate (the run starts without a question)",
          mgr.plugin_run_command("demo", _NODES, "rm -rf /var") is True and _ask_calls == []
          and len(_FakeRunner.built) == 1, f"{_ask_calls} {_FakeRunner.built}")
    i18n.save_config({})

    PM.command_confirm = _refuse
    _worker_answer = []
    _thread = threading.Thread(target=lambda: _worker_answer.append(
        mgr.plugin_run_command("demo", _NODES, "reboot")))
    _thread.start()
    _thread.join(5)
    check("§5 a call from a plugin WORKER still answers True — the outcome travels by signal "
          "(the DECLARED asymmetry of PLUGINS.md §5)",
          _worker_answer == [True], str(_worker_answer))

    check("§5 the gate lives in the ONE slot the hop reaches (never in a second place)",
          "_start_command_run" in _src("modules", "plugin_manager.py")
          and "command_requested.connect(self._start_command_run)"
          in _src("modules", "plugin_manager.py"))
finally:
    PM.command_confirm = _orig_confirm
    if _orig_runner is not None:
        PR.PluginCommandRunner = _orig_runner
    i18n.save_config({})


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the multi-input submission door (the canvas at Enter) ==")
# ════════════════════════════════════════════════════════════════════════════


class FakeThread:
    """The fake `SSHTerminalThread`: the recorded sends (the `test_production_guard.py` pattern)."""

    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


def type_line(widget, text):
    for ch in text:
        widget.keyPressEvent(key_event(ord(ch.upper()), ch))


scr = TerminalScreen(columns=40, lines=6)
hub = MultiInputHub()
_PAGES = [types.SimpleNamespace(widget=None), types.SimpleNamespace(widget=None)]
hub.set_session_provider(lambda: _PAGES)
widget = TerminalWidget(scr, FakeThread(), multi_hub=hub)
widget.resize(40 * widget.cell_size[0], 6 * widget.cell_size[1])

_asked = []
_orig_broadcast = TWI._guard_confirm_broadcast
_orig_needs = TWI._guard_needs_confirmation
clear_cfg()


def _refuse_broadcast(line, token, count=1, parent=None):
    _asked.append((line, token, count))
    return False


def _accept_broadcast(line, token, count=1, parent=None):
    _asked.append((line, token, count))
    return True


def _last_sent(widget):
    return b"".join(widget.terminal_thread.sent)


try:
    check("§6 the canvas carries the forward-only line buffer (the facade owns the state)",
          widget._guard_line == "" and widget._guard_line_ok is True
          and TWI.GUARD_LINE_MAX_CHARS > 0)

    hub.set_active(True)
    TWI._guard_confirm_broadcast = _refuse_broadcast
    _asked.clear()
    widget.terminal_thread.sent.clear()
    type_line(widget, "rm -rf /")
    check("§6 printable text is APPENDED to the buffer and still reaches the shell (the guard is late)",
          widget._guard_line == "rm -rf /" and _last_sent(widget) == b"rm -rf /",
          f"{widget._guard_line!r} {widget.terminal_thread.sent}")
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 ...and the Enter of a destructive line is SWALLOWED after ONE question naming the "
          "hub's own participant count",
          _asked == [("rm -rf /", "rm -rf", 2)] and b"\r" not in widget.terminal_thread.sent,
          f"{_asked} {widget.terminal_thread.sent}")
    check("§6 NOTHING else is injected on a refusal (no Ctrl+C on the user's behalf)",
          _last_sent(widget) == b"rm -rf /", str(widget.terminal_thread.sent))

    _asked.clear()
    widget.terminal_thread.sent.clear()
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 the buffer SURVIVES a refusal, so a second Enter asks again (no slip-through)",
          _asked == [("rm -rf /", "rm -rf", 2)] and b"\r" not in widget.terminal_thread.sent,
          f"{_asked} {widget.terminal_thread.sent}")

    TWI._guard_confirm_broadcast = _accept_broadcast
    _asked.clear()
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 a confirmed submission sends the Enter and starts a NEW line",
          _asked == [("rm -rf /", "rm -rf", 2)] and widget.terminal_thread.sent[-1] == b"\r"
          and widget._guard_line == "", f"{_asked} {widget.terminal_thread.sent}")

    TWI._guard_confirm_broadcast = _refuse_broadcast
    _asked.clear()
    widget.terminal_thread.sent.clear()
    type_line(widget, "uptime")
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 an ORDINARY line is never questioned and the Enter goes out",
          _asked == [] and widget.terminal_thread.sent[-1] == b"\r")

    widget._guard_line_reset()
    type_line(widget, "reboot")
    widget.keyPressEvent(key_event(Qt.Key.Key_Backspace, ""))
    type_line(widget, "x")
    check("§6 Backspace pops the buffer (an erasure stays forward-only)",
          widget._guard_line == "reboox", repr(widget._guard_line))

    _asked.clear()
    widget._guard_line_reset()
    type_line(widget, "rm -rf")
    widget.keyPressEvent(key_event(Qt.Key.Key_Left, ""))      # a cursor move: readline territory
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 a line EDITED by a cursor move is invalidated and NOT guarded (the declared false "
          "negative — the Enter still goes out)",
          _asked == [] and widget.terminal_thread.sent[-1] == b"\r"
          and widget._guard_line_ok is True, f"{_asked} {widget._guard_line!r}")

    _asked.clear()
    widget._guard_line_reset()
    type_line(widget, "rm -rf")
    widget.keyPressEvent(key_event(Qt.Key.Key_Escape, ""))
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 ...and a control key kills it the same way", _asked == [])

    _asked.clear()
    widget._guard_line_reset()
    type_line(widget, "rm -rf")
    widget._send_mouse(widget.MOUSE_BUTTON_LEFT, 1, 1, True)
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 a mouse report invalidates the line too (it is not text this canvas typed)",
          _asked == [] and widget.terminal_thread.sent[-1] == b"\r")

    _asked.clear()
    hub.set_active(False)
    widget._guard_line_reset()
    type_line(widget, "rm -rf /")
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 with the multi-input mode OFF the Enter is never questioned (one session, one line)",
          _asked == [] and widget.terminal_thread.sent[-1] == b"\r")
    hub.set_active(True)

    TWI._guard_needs_confirmation = lambda command, cfg=None: "rm -rf"
    TWI._guard_confirm_broadcast = _accept_broadcast
    _asked.clear()
    widget._guard_line_reset()
    type_line(widget, "hello")
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 the door really calls the classifier (a token lets the confirmed line through)",
          _asked and _asked[-1][:2] == ("hello", "rm -rf"), str(_asked))

    TWI._guard_confirm_broadcast = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    _asked.clear()
    widget._guard_line_reset()
    type_line(widget, "rm -rf")
    widget.terminal_thread.sent.clear()
    widget.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
    check("§6 a guard that RAISES refuses the submission (never a silent pass)",
          b"\r" not in widget.terminal_thread.sent and widget._guard_line == "rm -rf")
finally:
    TWI._guard_confirm_broadcast = _orig_broadcast
    TWI._guard_needs_confirmation = _orig_needs
    hub.set_active(False)
    hub.reset()


# ════════════════════════════════════════════════════════════════════════════
print("== §7 release state + i18n parity ==")
# ════════════════════════════════════════════════════════════════════════════

_NEW_KEYS = ("guard.command.text", "guard.command.broadcast", "plugins.command.guard_refused")
check("§7 the release moved past v1.9.6 and the pin counts the guard's THREE new keys "
      "plus v1.9.7's TWELVE",
      releases_at_least(EXPECTED_APP_VERSION, "1.9.6") and EXPECTED_I18N_KEYS == 1064 + 3 + 12,
      f"{EXPECTED_APP_VERSION} {EXPECTED_I18N_KEYS}")
langs = load_i18n_langs(ROOT)
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in langs.items()}
check(f"§7 the {len(_NEW_KEYS)} new keys are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§7 ...and they are the keys the CODE really asks for (the guard's own vocabulary)",
      all(f'"{key}"' in _src("modules", "command_guard.py") for key in _NEW_KEYS[:2])
      and f'"plugins.command.guard_refused"' in _src("ui", "main_window_plugins.py"))
check("§7 every sentence keeps its placeholders in every language (the words are the guard's)",
      all(all(name in langs[code]["guard.command.text"]
              for name in ("{command}", "{token}", "{count}"))
          and all(name in langs[code]["guard.command.broadcast"]
                  for name in ("{command}", "{token}", "{count}"))
          and all(name in langs[code]["plugins.command.guard_refused"]
                  for name in ("{token}", "{count}"))
          for code in langs), str(sorted(langs)))
check_i18n_parity(langs)
check_release_state(ROOT)
check("§7 the topical file is listed by the suite map (tests/INDEX.md regenerated)",
      "test_command_guard" in open(os.path.join(ROOT, "tests", "INDEX.md"), encoding="utf-8").read())

i18n.save_config({})
finish()
