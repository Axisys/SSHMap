# -*- coding: utf-8 -*-
"""v1.2.10 — Аудит: подтверждённые баги и данные (AUDIT.md): тематический тест релиза.

ROADMAP v1.2.10 (7 задач; все тезисы верифицированы по кодовой базе v1.2.9 2026-09-09 —
см. AUDIT.md, раздел «Верификация тезисов аудита»):
  #1 credential_manager: get_logger() → get_logger("services.credential_manager") —
     warning «Rejected keyring backend» реально пишется в лог;
  #2 AddServerDialog.get_data(): .strip() для host/user/alias;
  #3 SSHWorker key-ветка: final_password (аргумент или keyring) передаётся в connect()
     как fallback вместе с key_filename (паритет с SystemInfoCollector);
  #4 SettingsDialog._on_accept: исключение save_config → видимая ошибка (не тихий return);
  #5 wcwidth в декларациях зависимостей (requirements.txt + pyproject.toml, пин >=0.2.9);
  #6 BackupsDialog: элемент без «path» — без KeyError;
  #7 VERSION_FORMAT_RE принимает нижний регистр rc («1.2.10rc1»).

Запуск: python tests/test_audit_v1210.py   (из корня проекта) или python tests/run_all.py
"""
import logging
import os
import re
import sys

from _common import (
    bootstrap, check, finish,
    load_i18n_langs, check_i18n_parity, check_release_state,
    VERSION_FORMAT_RE,
)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция внутри)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

app = QApplication(sys.argv)

import i18n  # noqa: F401 — состояние языка для _t()/t()


# ─────────────────────────────────────────────────────────────────────────────
# §1. credential_manager: отклонённый бэкенд → is_available False + warning в логе (ручной #2)
# ─────────────────────────────────────────────────────────────────────────────

import keyring as _keyring_mod
from modules.logger import get_logger
from services.credential_manager import CredentialManager

# Якорь корневой причины: get_logger(name) требует позиционный аргумент — старый вызов
# get_logger() бросал TypeError, который глотался окружающим except (стр. 81–82 v1.2.9).
try:
    get_logger()
    check("§1 get_logger() без аргумента бросает TypeError (корень AUDIT ручной #2)", False, "исключения нет")
except TypeError:
    check("§1 get_logger() без аргумента бросает TypeError (корень AUDIT ручной #2)", True)


class _PlaintextKeyring:
    """Фейковый бэкенд, отклоняемый на любой ОС: имя класса содержит «plaintext»
    + модуль keyrings.alt.* (чёрный список) / не в wincred-allowlist (Windows)."""
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

check("§1 отклонённый бэкенд → is_available False", cm.is_available is False, str(cm.is_available))
_warned = [r for r in _records
           if r.levelno == logging.WARNING and "Rejected keyring backend" in r.getMessage()]
check("§1 warning «Rejected keyring backend» реально пишется в лог (AUDIT ручной #2)",
      len(_warned) >= 1, f"всего записей: {len(_records)}")


# ─────────────────────────────────────────────────────────────────────────────
# §2. AddServerDialog.get_data(): .strip() для host/user/alias (ручной #3)
# ─────────────────────────────────────────────────────────────────────────────

from dialogs.add_server_dialog import AddServerDialog

dlg = AddServerDialog()
dlg.alias.setText("  web-1 ")
dlg.host.setText("   192.168.1.5\t")
dlg.user.setText(" root ")
d = dlg.get_data()
check("§2 get_data(): host стрипован", d.host == "192.168.1.5", repr(d.host))
check("§2 get_data(): user стрипован", d.user == "root", repr(d.user))
check("§2 get_data(): alias стрипован", d.alias == "web-1", repr(d.alias))

dlg.alias.setText("    ")
d2 = dlg.get_data()
check("§2 пустой alias → «Server» (поведение не изменилось)", d2.alias == "Server", repr(d2.alias))


# ─────────────────────────────────────────────────────────────────────────────
# §3. SSHWorker key-ветка: пароль как fallback рядом с key_filename (авто #1)
# ─────────────────────────────────────────────────────────────────────────────

import paramiko
import modules.ssh_worker as SW
import services.credential_manager as CM


class _FakeSSHClient:
    """Фейковый paramiko.SSHClient: записывает kwargs connect() (без реальной сети)."""
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
    # Явный пароль + key_path.
    w1 = SW.SSHWorker(host="h1", user="u", port=22, server_id="",
                      password="pw-explicit", key_path="/keys/id_rsa")
    w1._run_ssh_connect()

    # Пароль из keyring (фейковый credential manager) + key_path.
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

    # Чистый key-путь (пароля нигде нет).
    w3 = SW.SSHWorker(host="h1", user="u", port=22, server_id="",
                      password="", key_path="/keys/id_rsa")
    w3._run_ssh_connect()
finally:
    paramiko.SSHClient = _orig_client_cls

kw1 = _FakeSSHClient.created[-3].connect_kwargs
check("§3 key-ветка + явный пароль: connect(key_filename=…, password=…)",
      kw1 is not None and kw1.get("key_filename") == "/keys/id_rsa"
      and kw1.get("password") == "pw-explicit", repr(kw1))
kw2 = _FakeSSHClient.created[-2].connect_kwargs
check("§3 key-ветка + пароль из keyring: connect(key_filename=…, password='ring-pw')",
      kw2 is not None and kw2.get("key_filename") == "/keys/id_rsa"
      and kw2.get("password") == "ring-pw", repr(kw2))
kw3 = _FakeSSHClient.created[-1].connect_kwargs
check("§3 чистый key-путь без изменений: password=None (paramiko пропускает)",
      kw3 is not None and kw3.get("key_filename") == "/keys/id_rsa"
      and kw3.get("password") is None, repr(kw3))


# ─────────────────────────────────────────────────────────────────────────────
# §4. SettingsDialog._on_accept: исключение save_config → видимая ошибка (авто #3)
# ─────────────────────────────────────────────────────────────────────────────

import ui.settings_dialog as SD_mod
from ui.settings_dialog import SettingsDialog


class _FakeMB:
    """Тестовый шов: модульный глобал QMessageBox в ui.settings_dialog подменяется
    (паттерн ST.QMessageBox из v1.2.9 — класс-атрибут PySide6 не пачается)."""
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
    # Ошибочный путь: save_config бросает — нужна видимая ошибка, а не тихий return.
    def _boom(data):
        raise OSError("simulated config failure")

    _orig_save = i18n.save_config
    i18n.save_config = _boom
    try:
        sd._on_accept()
    finally:
        i18n.save_config = _orig_save

    check("§4 исключение save_config → QMessageBox.warning (не тихий return)",
          len(_FakeMB.warnings) == 1, f"warnings={_FakeMB.warnings}")
    if _FakeMB.warnings:
        _title, _text = _FakeMB.warnings[0]
        check("§4 warning на существующих ключах msg.error_title/msg.save_failed (без новых i18n)",
              bool(_title) and "config.json" in _text, f"title={_title!r} text={_text!r}")
    check("§4 applied() НЕ эмитится при ошибке", not _applied_fired, str(_applied_fired))
    check("§4 диалог не закрыт (result != Accepted)", sd.result() != QDialog.Accepted, str(sd.result()))

    # Успешный путь: save_config True → applied + accept, без новых warning.
    i18n.save_config = lambda data: True
    try:
        sd._on_accept()
    finally:
        i18n.save_config = _orig_save
    check("§4 успешный путь: applied() эмитится", len(_applied_fired) == 1, str(_applied_fired))
    check("§4 успешный путь: новых warning нет", len(_FakeMB.warnings) == 1, f"warnings={_FakeMB.warnings}")
    check("§4 успешный путь: диалог закрыт (Accepted)", sd.result() == QDialog.Accepted, str(sd.result()))
finally:
    SD_mod.QMessageBox = _orig_mb


# ─────────────────────────────────────────────────────────────────────────────
# §5. wcwidth в декларациях зависимостей (ручной #4)
# ─────────────────────────────────────────────────────────────────────────────

from importlib.metadata import version as _pkg_version

import wcwidth  # noqa: F401 — прямой импорт, как modules/terminal_widget.py:82


def _ver_tuple(v):
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", v)
    if not m:
        return (0,)
    return tuple(int(g) for g in m.groups() if g is not None)


_wv = _pkg_version("wcwidth")
check("§5 wcwidth импортируется (прямая зависимость с v1.2.10)", True)
check("§5 установленный wcwidth >= 0.2.9", _ver_tuple(_wv) >= (0, 2, 9), f"установлен {_wv}")

with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
    _req_lines = [re.sub(r"\s+#.*$", "", l).strip() for l in f]
_req_wc = [l for l in _req_lines if l.lower().startswith("wcwidth")]
check("§5 requirements.txt декларирует wcwidth>=0.2.9", _req_wc == ["wcwidth>=0.2.9"], repr(_req_wc))

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
check("§5 pyproject.toml декларирует wcwidth>=0.2.9 (тот же пин, что requirements.txt)",
      _deps.get("wcwidth") == "wcwidth>=0.2.9", repr(_deps.get("wcwidth")))


# ─────────────────────────────────────────────────────────────────────────────
# §6. BackupsDialog: элемент без «path» — без KeyError (авто #4)
# ─────────────────────────────────────────────────────────────────────────────

from dialogs.backups_dialog import BackupsDialog

_bd_path = os.path.join(WORK, "a.json")
bd = BackupsDialog([
    {"label": "slot-1", "path": _bd_path, "mtime": 0.0, "size": 10},
    {"label": "no-path"},   # до фикса v1.2.10 — KeyError: 'path' здесь
])
check("§6 BackupsDialog с элементом без «path»: без KeyError", bd.item_count() == 2, str(bd.item_count()))
_row0 = bd.tree.topLevelItem(0)
_row1 = bd.tree.topLevelItem(1)
check("§6 строка с path: данные сохранены", _row0.data(0, Qt.UserRole) == (_bd_path, "slot-1"),
      repr(_row0.data(0, Qt.UserRole)))
check("§6 строка без path: («», label)", _row1.data(0, Qt.UserRole) == ("", "no-path"),
      repr(_row1.data(0, Qt.UserRole)))


# ─────────────────────────────────────────────────────────────────────────────
# §7. VERSION_FORMAT_RE: нижний регистр rc (задача 7)
# ─────────────────────────────────────────────────────────────────────────────

for _good in ("1.2.10", "1.2.10rc1", "1.2.10RC1", "1.2.10rc3", "1.1.3", "1.0RC4", "0.9.9.7"):
    check(f"§7 VERSION_FORMAT_RE принимает {_good}", bool(VERSION_FORMAT_RE.match(_good)))
for _bad in ("1.2.10rc", "1.2.10rcx1", "1.2.10 1", "", "abc"):
    check(f"§7 VERSION_FORMAT_RE отклоняет {_bad!r}", not VERSION_FORMAT_RE.match(_bad))


# ─────────────────────────────────────────────────────────────────────────────
# §8. Состояние релиза + i18n-паритет (конвенция: пин 427 — новых ключей нет)
# ─────────────────────────────────────────────────────────────────────────────

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
