# -*- coding: utf-8 -*-
"""Regression v0.9.5.5 (security #1): the keyring backend — validation and guard.

Run: python tests/test_keyring_validation.py or python tests/run_all.py

Checks:
  1. the plaintext backend (keyrings.alt.*) is rejected on Windows AND on Linux —
     save/load/delete do not write/read into it;
  2. the fail-backend (keyring.backends.fail) is rejected on Linux;
  3. with the rejected backend: save→False, load→None, delete→True
     (the semantics v094b: "nothing was stored — there is nothing to delete");
  4. the real backend of this machine (if accepted): the round-trip save/load/delete
     and the delete of the missing entry → True (keyring 25.x raises
     PasswordDeleteError — it is caught).
"""
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

import keyring

from services import credential_manager as CM_MOD
from services.credential_manager import CredentialManager


def _make_fake(module_name, cls_name="FakeKeyring"):
    """A backend stub with a given __module__/the class name (for the validation).

    The methods — a safety net: with the guard working correctly they must not be called.
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
    """A CredentialManager initialized for a given backend and OS."""
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

    # ── 1. The Plaintext backend (keyrings.alt.file) is rejected on any OS ──
    plaintext = _make_fake("keyrings.alt.file", "PlaintextKeyring")
    for plat in ("Windows", "Linux"):
        cm = _with_backend(plaintext, plat)
        check(f"plaintext backend REJECTED on {plat}", cm.is_available is False)
        check(f"save refused on {plat}", cm.save_password("sid1", "pw") is False)
        check(f"load None on {plat}", cm.load_password("sid1") is None)
        check(f"delete True (nothing stored) on {plat}", cm.delete_password("sid1") is True)

    # ── 2. The Fail backend (keyring.backends.fail) is rejected on Linux ──
    fail_be = _make_fake("keyring.backends.fail", "FailKeyring")
    cm = _with_backend(fail_be, "Linux")
    check("fail backend REJECTED on Linux", cm.is_available is False)
    check("save refused (fail backend)", cm.save_password("sid2", "pw") is False)

    # ── 3. This machine's real backend: the round-trip (if accepted by the validation) ──
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
