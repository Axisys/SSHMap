"""External (system) terminal v0.8.2: modules/external_terminal.py (former smoke_test).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * build_ssh_args: the port/key/ConnectTimeout, the known_hosts is not touched, the password is never in argv;
  * build_command for ALL the terminals without a real launch (wt/cmd/gnome/konsole/
    alacritty/kitty + bash -c "; exec bash" — the window survives the exit of ssh), the ValueError on
    an unknown id, the -J jump; v1.1.2RC1 (N2): "conhost" is removed from the presets — build_command
    accepts the old id as an alias of "cmd", detect never returns "conhost";
  * detect_terminal on the current OS (headless-friendly);
  * the settings of the external terminal (v1.1: the single ~/.sshmap/config.json, the migration from the legacy
    ~/.sshmap_settings.json): the round-trip, the merge of the foreign keys, invalid → auto;
  * launch(): the Popen is mocked — the flags of the detach of the console of Windows;
  * the error paths of connect_external: no_ssh_client / no_terminal;
  * the UI integration: external_btn in the SSHConnectDialog + the i18n keys v0.8.2 + the method of MainWindow.

Run: python tests/test_external_terminal.py   (from the project root) or python tests/run_all.py
"""
import json as _json_v082
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from models.server import ServerData

# ══════════════════════════════════════════════════════════
# v0.8.2: the external (system) terminal — modules/external_terminal.py
# build_command() for all terminals (WITHOUT a real launch),
# detect_terminal(), the external terminal settings round-trip (v1.1: a single config.json),
# The UI integration (the ctx menu + the dialog button).
# ══════════════════════════════════════════════════════════
try:
    from modules import external_terminal as _ET
except ImportError:
    from modules.external_terminal import *  # noqa: F401,F403
    import modules.external_terminal as _ET

check("external_terminal module imports", _ET is not None)

# 1) build_ssh_args: port/key/ConnectTimeout, we do not touch known_hosts
_a = _ET.build_ssh_args("h1", "root")
check("build_ssh_args: default port omitted",
      _a == ["ssh", "-o", "ConnectTimeout=10", "root@h1"], str(_a))
_a = _ET.build_ssh_args("h1", "root", port=2222, key_path="C:/k/k.pem")
check("build_ssh_args: -p and -i present",
      "-p" in _a and "2222" in _a and "-i" in _a and "C:/k/k.pem" in _a, str(_a))
check("build_ssh_args: no password ever in argv",
      not any(("pw" == x.lower() or x.startswith("-oPass")) for x in _a))

# 2) build_command for all terminals (without launching)
_c = _ET.build_command("windows_terminal", "h1", "root", port=2222)
check("build_command windows_terminal: wt.exe + ssh args",
      _c[0] == "wt.exe" and "ssh" in _c and "2222" in _c, str(_c))
_c = _ET.build_command("cmd", "h1", "root")
check("build_command cmd: start with empty title",
      _c[1] == "/c" and _c[2] == "start" and _c[3] == "", str(_c))
# v1.1.2RC1 (N2): "conhost" is no longer a preset (conhost.exe is not a launcher) — build_command
# accepts the old id as an alias for "cmd"; the command with conhost.exe is no longer assembled.
_c = _ET.build_command("conhost", "h1", "root")
check("build_command 'conhost' is an alias of 'cmd' (v1.1.2RC1 N2)",
      _c == _ET.build_command("cmd", "h1", "root") and _c[0] == "cmd.exe"
      and "/c" in _c and _c[-1] == "root@h1", str(_c))
for tid in ("gnome-terminal", "x-terminal-emulator", "xfce4-terminal"):
    _c = _ET.build_command(tid, "h1", "root")
    check(f"build_command {tid}: bash -c with exec bash (window survives)",
          _c[-3] == "bash" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("konsole", "h1", "root")
check("build_command konsole: -e bash -c",
      _c[-4] == "-e" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("alacritty", "h1", "root")
check("build_command alacritty: -e bash -c",
      _c[-4] == "-e" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("kitty", "h1", "root")
check("build_command kitty: bash -c",
      _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
try:
    _ET.build_command("bogus-term", "h1", "root")
    check("build_command unknown id raises ValueError", False)
except ValueError:
    check("build_command unknown id raises ValueError", True)

# the password never enters the command even on a jump
_c = _ET.build_command("windows_terminal", "h1", "root", jump="jump@bastion")
check("build_command supports -J jump", "-J" in _c and "jump@bastion" in _c, str(_c))

# 3) detect_terminal on the current OS (headless-friendly)
_dt = _ET.detect_terminal()
if sys.platform == "win32":
    # v1.1.2RC1 (N2): "conhost" is removed from the fallback chain — wt → cmd remain.
    check("detect_terminal on Windows returns wt/cmd",
          _dt in ("windows_terminal", "cmd"), str(_dt))
else:
    check("detect_terminal returns known id or None", _dt is None or isinstance(_dt, str), str(_dt))

# 4) settings: a JSON round-trip with a merge of the existing keys
_orig_settings = None
_sp = _ET._settings_path()
try:
    with open(_sp, "r", encoding="utf-8") as f:
        _orig_settings = f.read()
except OSError:
    pass
def _read_json_or_none(path):
    """v0.9.3 fix: reading the settings file, robust to a read-only home.

    On a sandbox/read-only profile the write could fail — then instead of
    a FileNotFoundError with a stacktrace (crashing all the following checks) the test
    will honestly report FAIL for the affected checks.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json_v082.load(f)
    except (OSError, ValueError):
        return None

try:
    check("load default setting is 'auto'", _ET.load_external_terminal_setting() == "auto")
    ok_w = _ET.save_external_terminal_setting("cmd" if sys.platform == "win32" else "kitty")
    check("save_external_terminal_setting writes file", ok_w)
    want = "cmd" if sys.platform == "win32" else "kitty"
    check("round-trip reads saved value back",
          _ET.load_external_terminal_setting() == want)
    # merge: the other key of the file is not lost
    d = _read_json_or_none(_sp) or {}
    d["some_other_key"] = 42
    try:
        with open(_sp, "w", encoding="utf-8") as f:
            _json_v082.dump(d, f)
    except OSError:
        pass  # a read-only home: the check below will honestly document the lost key
    _ET.save_external_terminal_setting("auto")
    d2 = _read_json_or_none(_sp) or {}
    check("settings merge keeps unrelated keys",
          d2.get("some_other_key") == 42 and d2.get("external_terminal") == "auto", str(d2))
    # an invalid value → auto
    try:
        with open(_sp, "w", encoding="utf-8") as f:
            _json_v082.dump({"external_terminal": "not-a-terminal"}, f)
    except OSError:
        pass
    check("invalid setting falls back to 'auto'",
          _ET.load_external_terminal_setting() == "auto")
finally:
    try:
        if _orig_settings is not None:
            with open(_sp, "w", encoding="utf-8") as f:
                f.write(_orig_settings)
        else:
            os.remove(_sp)
    except OSError:
        pass

# 5) launch(): Popen is mocked — we check the Windows flags and the absence of exceptions
_launched = {}
class _FakePopenV082:
    def __init__(self, cmd, **kw):
        _launched["cmd"] = cmd
        _launched["kw"] = kw
_orig_popen = _ET.subprocess.Popen
_ET.subprocess.Popen = _FakePopenV082
try:
    ok_l = _ET.launch(["fake-term.exe", "ssh", "root@h1"])
    check("launch returns True via Popen", ok_l is True)
    check("launch detaches console on Windows",
          (sys.platform != "win32") or (_launched["kw"].get("creationflags", 0) != 0),
          str(_launched.get("kw")))
finally:
    _ET.subprocess.Popen = _orig_popen

# the connect_external error paths (no GUI): ssh is missing → no_ssh_client
_orig_which = _ET._which
try:
    _ET._which = lambda name: None
    ok_e, err_e = _ET.connect_external("h1", "root")
    check("connect_external without ssh client → no_ssh_client",
          ok_e is False and err_e == "no_ssh_client", str((ok_e, err_e)))
    def _which_no_term(name):
        return "C:/fake/ssh.exe" if name == "ssh" else None
    _ET._which = _which_no_term
    ok_e, err_e = _ET.connect_external("h1", "root")
    check("connect_external without terminal → no_terminal",
          ok_e is False and err_e == "no_terminal", str((ok_e, err_e)))
finally:
    _ET._which = _orig_which

# 6) UI integration: SSHConnectDialog has external_btn; the i18n ctx key is present
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD_ext
_nd_ext = ServerData(id="extsrv", alias="ExtSrv", host="10.0.0.9", user="root")
_dlg_ext = _SCD_ext(_nd_ext, None)
check("SSHConnectDialog has external terminal button",
      hasattr(_dlg_ext, "external_btn") and bool(_dlg_ext.external_btn.text())
      and not _dlg_ext.external_btn.text().startswith("ssh_ext."),
      _dlg_ext.external_btn.text())
_dlg_ext.deleteLater()

# i18n: all three languages contain the new v0.8.2 keys
for _lang_k in ("en", "ru", "zh"):
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "i18n", f"{_lang_k}.json")
    with open(_p, encoding="utf-8") as f:
        _d = _json_v082.load(f)
    _missing = [k for k in ("ctx.ssh_external", "ssh_ext.open_button",
                            "ssh_ext.no_ssh_client", "ssh_ext.no_terminal",
                            "ssh_ext.launch_failed", "ssh_ext.launched")
                if k not in _d]
    check(f"i18n v0.8.2 keys present ({_lang_k})", not _missing, str(_missing))

# MainWindow method presence (the class, no instance)
from ui.main_window import MainWindow as _MW_v082
check("MainWindow has _connect_ssh_external",
      callable(getattr(_MW_v082, "_connect_ssh_external", None)))

finish()
