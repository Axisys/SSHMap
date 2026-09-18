# -*- coding: utf-8 -*-
"""v1.2.10 — Audit: confirmed bugs and data (AUDIT.md): the release's themed test.

ROADMAP v1.2.10 (7 tasks; all the theses are verified against the codebase of v1.2.9 2026-09-09 —
see AUDIT.md, the section "Verification of the audit theses"):
  #1 credential_manager: get_logger() → get_logger("services.credential_manager") —
     the warning "Rejected keyring backend" is really written to the log;
  #2 AddServerDialog.get_data(): .strip() for the host/user/alias;
  #3 the SSHWorker key branch: the final_password (the argument or the keyring) is passed to connect()
     as the fallback together with key_filename (the parity with SystemInfoCollector);
  #4 SettingsDialog._on_accept: the exception of save_config → a visible error (not a quiet return);
  #5 wcwidth in the dependency declarations (requirements.txt + pyproject.toml, the pin >=0.2.9);
  #6 BackupsDialog: an item without "path" — without a KeyError;
  #7 VERSION_FORMAT_RE accepts the lower-case rc ("1.2.10rc1").

Run: python tests/test_audit_v1210.py   (from the project root) or python tests/run_all.py
"""
import logging
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, VERSION_FORMAT_RE)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

app = QApplication(sys.argv)

import i18n  # noqa: F401 — the language state for _t()/t()


# ─────────────────────────────────────────────────────────────────────────────
# §1. credential_manager: a rejected backend → is_available is False + a warning in the log (manual #2)
# ─────────────────────────────────────────────────────────────────────────────

import keyring as _keyring_mod
from modules.logger import get_logger
from services.credential_manager import CredentialManager

# The anchor of the root cause: get_logger(name) requires a positional argument — the old call
# get_logger() raised a TypeError, which was swallowed by the surrounding except (lines 81–82, v1.2.9).
try:
    get_logger()
    check("§1 get_logger() with no argument raises a TypeError (the root of AUDIT manual #2)", False, "no exception")
except TypeError:
    check("§1 get_logger() with no argument raises a TypeError (the root of AUDIT manual #2)", True)


class _PlaintextKeyring:
    """The fake backend rejected on any OS: the class name contains "plaintext"
    + the module keyrings.alt.* (the blacklist) / not in the wincred allowlist (Windows)."""
    name = "Plaintext (test)"
_PlaintextKeyring.__module__ = "keyrings.alt.file"

_records = []


class _Cap(logging.Handler):
    def emit(self, record):
        _records.append(record)


_lg = logging.getLogger("sshmap.services.credential_manager")
_cap = _Cap()
_old_level, _old_handlers = _lg.level, list(_lg.handlers)
_lg.setLevel(logging.DEBUG)
_lg.addHandler(_cap)

_orig_get_keyring = _keyring_mod.get_keyring
_keyring_mod.get_keyring = lambda: _PlaintextKeyring()
try:
    cm = CredentialManager()
finally:
    _keyring_mod.get_keyring = _orig_get_keyring
    _lg.removeHandler(_cap)
    _lg.setLevel(_old_level)
    _lg.handlers[:] = _old_handlers

check("§1 a rejected backend → is_available False", cm.is_available is False, str(cm.is_available))
_warned = [r for r in _records
           if r.levelno == logging.WARNING and "Rejected keyring backend" in r.getMessage()]
check("§1 the 'Rejected keyring backend' warning is really written to the log (AUDIT manual #2)",
      len(_warned) >= 1, f"total records: {len(_records)}")


# ─────────────────────────────────────────────────────────────────────────────
# §2. AddServerDialog.get_data(): .strip() for host/user/alias (manual #3)
# ─────────────────────────────────────────────────────────────────────────────

from dialogs.add_server_dialog import AddServerDialog

dlg = AddServerDialog()
dlg.alias.setText("  web-1 ")
dlg.host.setText("   192.168.1.5\t")
dlg.user.setText(" root ")
d = dlg.get_data()
check("§2 get_data(): host is stripped", d.host == "192.168.1.5", repr(d.host))
check("§2 get_data(): user is stripped", d.user == "root", repr(d.user))
check("§2 get_data(): alias is stripped", d.alias == "web-1", repr(d.alias))

dlg.alias.setText("    ")
d2 = dlg.get_data()
check("§2 an empty alias → 'Server' (the behaviour is unchanged)", d2.alias == "Server", repr(d2.alias))


# ─────────────────────────────────────────────────────────────────────────────
# §3. The SSHWorker key branch: the password as a fallback next to key_filename (auto #1)
# ─────────────────────────────────────────────────────────────────────────────

import paramiko
import modules.ssh_worker as SW
import services.credential_manager as CM


class _FakeSSHClient:
    """The fake paramiko.SSHClient: it records the kwargs of connect() (without the real network)."""
    created = []

    def __init__(self):
        self.connect_kwargs = None
        _FakeSSHClient.created.append(self)

    def set_missing_host_key_policy(self, policy):
        pass

    def get_host_keys(self):
        return {}

    def connect(self, *args, **kwargs):
        self.connect_kwargs = kwargs

    def close(self):
        pass


_orig_client_cls = paramiko.SSHClient
paramiko.SSHClient = _FakeSSHClient
try:
    # An explicit password + key_path.
    w1 = SW.SSHWorker(host="h1", user="u", port=22, server_id="",
                      password="pw-explicit", key_path="/keys/id_rsa")
    w1._run_ssh_connect()

    # The password from the keyring (a fake credential manager) + key_path.
    class _FakeCM:
        def load_password(self, server_id):
            return "ring-pw"

    _orig_gcm = CM.get_credential_manager
    CM.get_credential_manager = lambda: _FakeCM()
    try:
        w2 = SW.SSHWorker(host="h1", user="u", port=22, server_id="auditv1210",
                          password="", key_path="/keys/id_rsa")
        w2._run_ssh_connect()
    finally:
        CM.get_credential_manager = _orig_gcm
        SW._active_workers.pop("auditv1210", None)

    # The clean key path (no password anywhere).
    w3 = SW.SSHWorker(host="h1", user="u", port=22, server_id="",
                      password="", key_path="/keys/id_rsa")
    w3._run_ssh_connect()
finally:
    paramiko.SSHClient = _orig_client_cls

kw1 = _FakeSSHClient.created[-3].connect_kwargs
check("§3 the key branch + an explicit password: connect(key_filename=…, password=…)",
      kw1 is not None and kw1.get("key_filename") == "/keys/id_rsa"
      and kw1.get("password") == "pw-explicit", repr(kw1))
kw2 = _FakeSSHClient.created[-2].connect_kwargs
check("§3 the key branch + the password from the keyring: connect(key_filename=…, password='ring-pw')",
      kw2 is not None and kw2.get("key_filename") == "/keys/id_rsa"
      and kw2.get("password") == "ring-pw", repr(kw2))
kw3 = _FakeSSHClient.created[-1].connect_kwargs
check("§3 the clean key path is unchanged: password=None (paramiko skips it)",
      kw3 is not None and kw3.get("key_filename") == "/keys/id_rsa"
      and kw3.get("password") is None, repr(kw3))


# ─────────────────────────────────────────────────────────────────────────────
# §4. SettingsDialog._on_accept: a save_config exception → a visible error (auto #3)
# ─────────────────────────────────────────────────────────────────────────────

import ui.settings_dialog as SD_mod
from ui.settings_dialog import SettingsDialog


class _FakeMB:
    """The test seam: the module global QMessageBox in ui.settings_dialog is replaced
    (the pattern of the ST.QMessageBox from v1.2.9 — the class attribute of PySide6 is not polluted)."""
    warnings = []

    @staticmethod
    def warning(parent, title, text):
        _FakeMB.warnings.append((title, text))


sd = SettingsDialog()
_applied_fired = []
sd.applied.connect(lambda: _applied_fired.append(1))

_orig_mb = SD_mod.QMessageBox
SD_mod.QMessageBox = _FakeMB
try:
    # The error path: save_config raises — a visible error is needed, not a silent return.
    def _boom(data):
        raise OSError("simulated config failure")

    _orig_save = i18n.save_config
    i18n.save_config = _boom
    try:
        sd._on_accept()
    finally:
        i18n.save_config = _orig_save

    check("§4 a save_config exception → QMessageBox.warning (not a silent return)",
          len(_FakeMB.warnings) == 1, f"warnings={_FakeMB.warnings}")
    if _FakeMB.warnings:
        _title, _text = _FakeMB.warnings[0]
        check("§4 the warning is on the existing keys msg.error_title/msg.save_failed (no new i18n)",
              bool(_title) and "config.json" in _text, f"title={_title!r} text={_text!r}")
    check("§4 applied() is NOT emitted on the error", not _applied_fired, str(_applied_fired))
    check("§4 the dialog is not closed (result != Accepted)", sd.result() != QDialog.Accepted, str(sd.result()))

    # The success path: save_config is True → applied + accept, no new warnings.
    i18n.save_config = lambda data: True
    try:
        sd._on_accept()
    finally:
        i18n.save_config = _orig_save
    check("§4 the success path: applied() is emitted", len(_applied_fired) == 1, str(_applied_fired))
    check("§4 the success path: no new warnings", len(_FakeMB.warnings) == 1, f"warnings={_FakeMB.warnings}")
    check("§4 the success path: the dialog is closed (Accepted)", sd.result() == QDialog.Accepted, str(sd.result()))
finally:
    SD_mod.QMessageBox = _orig_mb


# ─────────────────────────────────────────────────────────────────────────────
# §5. wcwidth in the dependency declarations (manual #4)
# ─────────────────────────────────────────────────────────────────────────────

from importlib.metadata import version as _pkg_version

import wcwidth  # noqa: F401 — a direct import, as modules/terminal_widget.py:82


def _ver_tuple(v):
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", v)
    if not m:
        return (0,)
    return tuple(int(g) for g in m.groups() if g is not None)


_wv = _pkg_version("wcwidth")
check("§5 wcwidth is importable (a direct dependency since v1.2.10)", True)
check("§5 the installed wcwidth >= 0.2.9", _ver_tuple(_wv) >= (0, 2, 9), f"installed {_wv}")

with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
    _req_lines = [re.sub(r"\s+#.*$", "", l).strip() for l in f]
_req_wc = [l for l in _req_lines if l.lower().startswith("wcwidth")]
check("§5 requirements.txt declares wcwidth>=0.2.9", _req_wc == ["wcwidth>=0.2.9"], repr(_req_wc))

try:
    import tomllib as _toml
except ModuleNotFoundError:
    import tomli as _toml  # type: ignore
with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
    _pp = _toml.load(f)
_deps = {}
for _dep in _pp["project"]["dependencies"]:
    _name, _, _spec = _dep.partition(">=")
    _deps[re.sub(r"[-_.]+", "-", _name.strip()).lower()] = _dep.strip()
check("§5 pyproject.toml declares wcwidth>=0.2.9 (the same pin as requirements.txt)",
      _deps.get("wcwidth") == "wcwidth>=0.2.9", repr(_deps.get("wcwidth")))


# ─────────────────────────────────────────────────────────────────────────────
# §6. BackupsDialog: an element without a "path" — no KeyError (auto #4)
# ─────────────────────────────────────────────────────────────────────────────

from dialogs.backups_dialog import BackupsDialog

_bd_path = os.path.join(WORK, "a.json")
bd = BackupsDialog([
    {"label": "slot-1", "path": _bd_path, "mtime": 0.0, "size": 10},
    {"label": "no-path"},   # before the v1.2.10 fix — a KeyError: 'path' here
])
check("§6 BackupsDialog with an element without 'path': no KeyError", bd.item_count() == 2, str(bd.item_count()))
_row0 = bd.tree.topLevelItem(0)
_row1 = bd.tree.topLevelItem(1)
check("§6 the row with a path: the data is kept", _row0.data(0, Qt.UserRole) == (_bd_path, "slot-1"),
      repr(_row0.data(0, Qt.UserRole)))
check("§6 the row without a path: ('', the label)", _row1.data(0, Qt.UserRole) == ("", "no-path"),
      repr(_row1.data(0, Qt.UserRole)))


# ─────────────────────────────────────────────────────────────────────────────
# §7. VERSION_FORMAT_RE: lowercase rc (task 7)
# ─────────────────────────────────────────────────────────────────────────────

for _good in ("1.2.10", "1.2.10rc1", "1.2.10RC1", "1.2.10rc3", "1.1.3", "1.0RC4", "0.9.9.7"):
    check(f"§7 VERSION_FORMAT_RE accepts {_good}", bool(VERSION_FORMAT_RE.match(_good)))
for _bad in ("1.2.10rc", "1.2.10rcx1", "1.2.10 1", "", "abc"):
    check(f"§7 VERSION_FORMAT_RE rejects {_bad!r}", not VERSION_FORMAT_RE.match(_bad))


# ─────────────────────────────────────────────────────────────────────────────
# §8. Release state + i18n parity (convention: the pin 427 — no new keys)
# ─────────────────────────────────────────────────────────────────────────────

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
