"""Внешний (системный) терминал v0.8.2: modules/external_terminal.py (бывш. smoke_test).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * build_ssh_args: порт/ключ/ConnectTimeout, known_hosts не трогаем, пароль никогда в argv;
  * build_command для ВСЕХ терминалов без реального запуска (wt/cmd/conhost/gnome/konsole/
    alacritty/kitty + bash -c «; exec bash» — окно переживает выход ssh), ValueError на
    неизвестный id, -J jump;
  * detect_terminal на текущей ОС (headless-friendly);
  * настройки внешнего терминала (v1.1: единый ~/.sshmap/config.json, миграция из legacy
    ~/.sshmap_settings.json): round-trip, merge чужих ключей, invalid → auto;
  * launch(): Popen мокается — флаги детача консоли Windows;
  * connect_external error paths: no_ssh_client / no_terminal;
  * UI-интеграция: external_btn в SSHConnectDialog + i18n-ключи v0.8.2 + метод MainWindow.

Запуск: python tests/test_external_terminal.py   (из корня проекта) или python tests/run_all.py
"""
import json as _json_v082
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from models.server import ServerData

# ══════════════════════════════════════════════════════════
# v0.8.2: внешний (системный) терминал — modules/external_terminal.py
# build_command() для всех терминалов (БЕЗ реального запуска),
# detect_terminal(), настройки внешнего терминала round-trip (v1.1: единый config.json),
# UI-интеграция (ctx-меню + кнопка диалога).
# ══════════════════════════════════════════════════════════
try:
    from modules import external_terminal as _ET
except ImportError:
    from modules.external_terminal import *  # noqa: F401,F403
    import modules.external_terminal as _ET

check("external_terminal module imports", _ET is not None)

# 1) build_ssh_args: порт/ключ/ConnectTimeout, known_hosts не трогаем
_a = _ET.build_ssh_args("h1", "root")
check("build_ssh_args: default port omitted",
      _a == ["ssh", "-o", "ConnectTimeout=10", "root@h1"], str(_a))
_a = _ET.build_ssh_args("h1", "root", port=2222, key_path="C:/k/k.pem")
check("build_ssh_args: -p and -i present",
      "-p" in _a and "2222" in _a and "-i" in _a and "C:/k/k.pem" in _a, str(_a))
check("build_ssh_args: no password ever in argv",
      not any(("pw" == x.lower() or x.startswith("-oPass")) for x in _a))

# 2) build_command для всех терминалов (без запуска)
_c = _ET.build_command("windows_terminal", "h1", "root", port=2222)
check("build_command windows_terminal: wt.exe + ssh args",
      _c[0] == "wt.exe" and "ssh" in _c and "2222" in _c, str(_c))
_c = _ET.build_command("cmd", "h1", "root")
check("build_command cmd: start with empty title",
      _c[1] == "/c" and _c[2] == "start" and _c[3] == "", str(_c))
_c = _ET.build_command("conhost", "h1", "root")
# v0.9.3 fix: conhost требует команду через cmd /c — голый `conhost ssh` не работает
check("build_command conhost",
      _c[0] == "conhost.exe" and _c[1].lower().endswith("cmd.exe")
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

# пароль никогда не попадает в команду даже при jump
_c = _ET.build_command("windows_terminal", "h1", "root", jump="jump@bastion")
check("build_command supports -J jump", "-J" in _c and "jump@bastion" in _c, str(_c))

# 3) detect_terminal на текущей ОС (headless-friendly)
_dt = _ET.detect_terminal()
if sys.platform == "win32":
    check("detect_terminal on Windows returns wt/cmd/conhost/open_terminal",
          _dt in ("windows_terminal", "cmd", "conhost"), str(_dt))
else:
    check("detect_terminal returns known id or None", _dt is None or isinstance(_dt, str), str(_dt))

# 4) настройки: JSON round-trip с merge существующих ключей
_orig_settings = None
_sp = _ET._settings_path()
try:
    with open(_sp, "r", encoding="utf-8") as f:
        _orig_settings = f.read()
except OSError:
    pass
def _read_json_or_none(path):
    """v0.9.3 fix: чтение settings-файла, устойчивое к read-only home.

    На песочнице/read-only профиле запись могла не состояться — тогда вместо
    FileNotFoundError со stacktrace'ом (срывающего все последующие проверки) тест
    честно доложит FAIL по затронутым чекам.
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
    # merge: другой ключ файла не теряется
    d = _read_json_or_none(_sp) or {}
    d["some_other_key"] = 42
    try:
        with open(_sp, "w", encoding="utf-8") as f:
            _json_v082.dump(d, f)
    except OSError:
        pass  # read-only home: чек ниже честно задокументирует потерю ключа
    _ET.save_external_terminal_setting("auto")
    d2 = _read_json_or_none(_sp) or {}
    check("settings merge keeps unrelated keys",
          d2.get("some_other_key") == 42 and d2.get("external_terminal") == "auto", str(d2))
    # невалидное значение → auto
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

# 5) launch(): Popen мокается — проверяем флаги Windows и отсутствие исключений
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

# connect_external error paths (без GUI): ssh отсутствует → no_ssh_client
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

# 6) UI-интеграция: SSHConnectDialog имеет external_btn; ctx-ключ i18n присутствует
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD_ext
_nd_ext = ServerData(id="extsrv", alias="ExtSrv", host="10.0.0.9", user="root")
_dlg_ext = _SCD_ext(_nd_ext, None)
check("SSHConnectDialog has external terminal button",
      hasattr(_dlg_ext, "external_btn") and bool(_dlg_ext.external_btn.text())
      and not _dlg_ext.external_btn.text().startswith("ssh_ext."),
      _dlg_ext.external_btn.text())
_dlg_ext.deleteLater()

# i18n: все три языка содержат новые ключи v0.8.2
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

# MainWindow method presence (класс, без инстанса)
from ui.main_window import MainWindow as _MW_v082
check("MainWindow has _connect_ssh_external",
      callable(getattr(_MW_v082, "_connect_ssh_external", None)))

finish()
