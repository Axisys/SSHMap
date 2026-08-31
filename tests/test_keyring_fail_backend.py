# -*- coding: utf-8 -*-
"""Регрессия v0.9.4b: keyring fail-бэкенд + замечания ревью.

Запуск: python tests/test_keyring_fail_backend.py или python tests/run_all.py
Проверяет поведение CredentialManager на fail-бэкенде (keyring 25.x бросает
NoKeyringError из set/get на машинах без хранилища) и атомарную запись профилей.
"""
import json
import os
import sys
import tempfile

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

import keyring


class _FailBackend(keyring.backend.KeyringBackend):
    """Имитация keyring fail-бэкенда (как chainer None в keyring 25.x):
    любой set/get/delete бросает NoKeyringError."""

    name = "fail"

    def set_password(self, service, username, password):
        import keyring.errors
        raise keyring.errors.NoKeyringError("no backend")

    def get_password(self, service, username):
        import keyring.errors
        raise keyring.errors.NoKeyringError("no backend")

    def delete_password(self, service, username):
        import keyring.errors
        raise keyring.errors.NoKeyringError("no backend")


def main():
    print("== v0.9.4b: keyring fail-backend + review fixes ==")

    # ── #1 CredentialManager на fail-бэкенде: без исключений, False/None ──
    import keyring
    from services.credential_manager import CredentialManager

    cm = CredentialManager()
    orig = keyring.get_keyring()
    keyring.set_keyring(_FailBackend())
    try:
        # Форсируем переинициализацию под fail-бэкенд
        cm._try_init()
        check("save returns False on fail backend",
              cm.save_password("deadbeef", "pw") is False)
        check("load returns None on fail backend",
              cm.load_password("deadbeef") is None)
        check("delete returns True on fail backend (nothing to delete — by design)",
              cm.delete_password("deadbeef") is True)
        # Главное: никакое исключение не вырвалось наружу (тест дошёл сюда)
        check("no exception escaped to caller", True)
    finally:
        keyring.set_keyring(orig)
        cm._try_init()

    # ── #2 save_profiles: атомарная запись, .tmp не остаётся ──
    import models.profile as prof_mod
    tmpdir = tempfile.mkdtemp()
    profiles_path = os.path.join(tmpdir, "sshmap_profiles.json")
    orig_path_fn = prof_mod._profiles_path
    prof_mod._profiles_path = lambda: profiles_path
    try:
        p = prof_mod.Profile(id="p1", name="web", user="ubuntu")
        prof_mod.save_profiles([p])
        with open(profiles_path, encoding="utf-8") as fh:
            data = json.load(fh)
        check("profiles written and readable", len(data) == 1 and data[0]["name"] == "web")
        check("password not in file", "password" not in data[0])
        check("no leftover .tmp", not os.path.exists(profiles_path + ".tmp"))
    finally:
        prof_mod._profiles_path = orig_path_fn

    # ── #3 MapScene.notes(): публичный итератор заметок ──
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        from graphics.map_scene import MapScene
        scene = MapScene()
        check("notes() public iterator exists", scene.notes() == [])
    except Exception as e:
        check(f"notes() iterator ({e})", False)

    # ── #4 Модель ServerData: tags аннотация и дефолт ──
    from models.server import ServerData
    check("tags default [] via __post_init__", ServerData(id="x", alias="a", host="h", user="u").tags == [])

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
