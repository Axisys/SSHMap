# -*- coding: utf-8 -*-
"""Регрессия v0.9.5.5 (безопасность #1): keyring-бэкенд — валидация и гард.

Запуск: python tests/test_keyring_validation.py или python tests/run_all.py

Проверяет:
  1. plaintext-бэкенд (keyrings.alt.*) отклоняется на Windows И на Linux —
     save/load/delete не пишут/не читают в него;
  2. fail-бэкенд (keyring.backends.fail) отклоняется на Linux;
  3. при отклонённом бэкенде: save→False, load→None, delete→True
     (semantics v094b: «ничего не хранилось — удалять нечего»);
  4. реальный бэкенд этой машины (если принят): round-trip save/load/delete
     и delete отсутствующей записи → True (keyring 25.x бросает
     PasswordDeleteError — перехватывается).
"""
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

import keyring

from services import credential_manager as CM_MOD
from services.credential_manager import CredentialManager


def _make_fake(module_name, cls_name="FakeKeyring"):
    """Бэкенд-заглушка с заданным __module__/именем класса (для валидации).

    Методы — страховка: при правильной работе гарда они не должны вызываться.
    """

    def _forbidden_write(self, service, username, password):
        raise AssertionError("insecure backend must NOT be used for writes")

    def _forbidden_read(self, service, username):
        raise AssertionError("insecure backend must NOT be used for reads")

    cls = type(cls_name, (), {
        "name": cls_name,
        "set_password": _forbidden_write,
        "get_password": _forbidden_read,
        "delete_password": lambda self, service, username: None,
    })
    cls.__module__ = module_name
    return cls()


def _with_backend(fake, platform_name):
    """CredentialManager, инициализированный под заданный бэкенд и ОС."""
    orig_system = CM_MOD._platform_mod.system
    orig_get = keyring.get_keyring
    try:
        CM_MOD._platform_mod.system = staticmethod(lambda: platform_name)
        keyring.get_keyring = staticmethod(lambda *a, **k: fake)
        return CredentialManager()
    finally:
        CM_MOD._platform_mod.system = orig_system
        keyring.get_keyring = orig_get


def main():
    print("== v0.9.5.5: keyring backend validation + guard ==")

    # ── 1. Plaintext-бэкенд (keyrings.alt.file) отклоняется на любой ОС ──
    plaintext = _make_fake("keyrings.alt.file", "PlaintextKeyring")
    for plat in ("Windows", "Linux"):
        cm = _with_backend(plaintext, plat)
        check(f"plaintext backend REJECTED on {plat}", cm.is_available is False)
        check(f"save refused on {plat}", cm.save_password("sid1", "pw") is False)
        check(f"load None on {plat}", cm.load_password("sid1") is None)
        check(f"delete True (nothing stored) on {plat}", cm.delete_password("sid1") is True)

    # ── 2. Fail-бэкенд (keyring.backends.fail) отклоняется на Linux ──
    fail_be = _make_fake("keyring.backends.fail", "FailKeyring")
    cm = _with_backend(fail_be, "Linux")
    check("fail backend REJECTED on Linux", cm.is_available is False)
    check("save refused (fail backend)", cm.save_password("sid2", "pw") is False)

    # ── 3. Реальный бэкенд этой машины: round-trip (если принят валидацией) ──
    cm_real = CredentialManager()
    if cm_real.is_available:
        print(f"  (real backend: {type(cm_real._keyring_backend).__module__}"
              f".{type(cm_real._keyring_backend).__name__})")
        sid = "v0955keyring"
        check("real backend: save -> True",
              cm_real.save_password(sid, "VerifyPw123") is True)
        check("real backend: load round-trip",
              cm_real.load_password(sid) == "VerifyPw123")
        check("real backend: delete existing -> True",
              cm_real.delete_password(sid) is True)
        check("real backend: load after delete -> None",
              cm_real.load_password(sid) is None)
        check("real backend: delete missing -> True (PasswordDeleteError handled)",
              cm_real.delete_password(sid) is True)
    else:
        print("  (real backend rejected on this host — round-trip skipped)")

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
