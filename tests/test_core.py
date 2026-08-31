"""Ядро сьюта (бывш. smoke_test.py §1–5): compile, i18n, models, ANSI, profiles/keyring.

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
Проверяет ключевые пункты AUDIT.md: компиляцию всех модулей, i18n-паритет en/ru/zh
+ fallback на английский, models.server (from_dict robustness / to_dict без пароля),
ANSI-очистку терминала, профили без паролей в JSON + семантику keyring update(None).

Запуск: python tests/test_core.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, snapshot_i18n_config, restore_i18n_config

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения


# ── 1. Compile all modules ───────────────────────────────
print("== compile ==")
import py_compile
bad = []
for dirpath, _, files in os.walk(ROOT):
    if "__pycache__" in dirpath:
        continue
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(dirpath, f)
            try:
                py_compile.compile(p, doraise=True)
            except Exception as e:
                bad.append((p, str(e)))
check("all .py compile", not bad, str(bad))

# ── 2. i18n: key parity + en fallback ────────────────────
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
check("key sets identical across en/ru/zh",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"]),
      str(set(langs["en"]).symmetric_difference(set(langs["ru"])))[:200])

from i18n import t, set_language
# Тест переключает языки и пишет в ~/.sshmap/config.json — сохраняем/возвращаем конфиг пользователя
_cfg_snap = snapshot_i18n_config()
check("t() imported from i18n module", t.__module__ == "i18n")  # sanity import
set_language("zh")
v = t("status.project_saved")
check("zh translation loaded (not raw key)", v != "status.project_saved" and v in langs["zh"].values())
# en fallback: all keys exist in zh, so simulate a missing one via monkeypatch
import i18n as I
saved = dict(I._translations)
I._translations.pop("menu.file", None)
check("t() falls back to en.json when current lang lacks key", t("menu.file") == "File")
I._translations.update(saved)
set_language("ru")

# ── 3. models/server: from_dict robustness, to_dict strips password ──
print("== models.server ==")
from models.server import ServerData, server_data_from_dict, server_data_to_dict
d = server_data_from_dict({"id": "abc12345", "alias": "x", "host": "h", "user": "u",
                          "extra_junk_key": 42, "ssh_port": "2222"})
check("from_dict ignores extra keys", d.host == "h" and not hasattr(d, "extra_junk_key"))
check("from_dict coerces ssh_port str->int", d.ssh_port == 2222)
d2 = server_data_from_dict({"alias": "no-id", "host": "h"})
check("from_dict generates id when missing", len(d2.id) == 8)
s = ServerData(id="i1", alias="a", host="h", user="u", password="SECRET", key_path=r"C:\k.pem")
js = server_data_to_dict(s)
check("to_dict excludes password", "password" not in js)
check("to_dict keeps key_path", js.get("key_path") == r"C:\k.pem")

# ── 4. ANSI regex ────────────────────────────────────────
print("== ansi ==")
from modules.ssh_terminal import ANSI_ESCAPE_RE
samples = {
    "\x1b[31mRED\x1b[0m": "RED",
    "\x1b[2Jclear": "clear",
    "\x1b[Hhome": "home",
    "\x1b[?25lhidden\x1b[?25hshown": "hiddenshown",
    "\x1b]0;vim\x07prompt": "prompt",      # OSC (title) + BEL terminator
    "\x1b]8;;http://x\x1b\\link text plain": "link text plain",  # OSC 8: удаляется до ST, видимый текст остаётся
}
for src, want in samples.items():
    got = ANSI_ESCAPE_RE.sub("", src)
    check(f"ansi {src!r} -> {got!r}", got == want, f"want {want!r}")

# ── 5. profiles: no password in JSON; update(None) keeps password ──
print("== profiles ==")
import models.profile as P
prof_path = os.path.join(WORK, "sshmap_profiles.json")
P._profiles_path = lambda: prof_path  # тест не трогает реальный файл пользователя

from services.credential_manager import get_credential_manager
cm = get_credential_manager()
print(f"  (keyring available on this host: {cm.is_available})")

p = P.add_profile(name="TestProf", user="tester", password="SuperSecret123")
with open(prof_path, encoding="utf-8") as f:
    raw_text = f.read()
check("profiles JSON has no plaintext password", "SuperSecret123" not in raw_text)
data = json.loads(raw_text)
test_entry = [e for e in data if e["id"] == p.id]
check("profile entry only id/name/user keys (no password key)",
      test_entry and set(test_entry[0].keys()) <= {"id", "name", "user"}, str(test_entry))

# update with empty -> None semantics: model level, password=None must NOT delete keyring entry
if cm.is_available:
    before = P.get_profile_password(p.id)
    up = P.update_profile(p.id, name="TestProf2", user="tester2", password=None)
    after = P.get_profile_password(p.id)
    check("update_profile(password=None) keeps keyring password", before == "SuperSecret123" and after == before, f"{before!r} -> {after!r}")
else:
    up = P.update_profile(p.id, name="TestProf2", user="tester2", password=None)
    check("update_profile(password=None) no exception (no keyring)", up is not None)

# cleanup test profile (файл в WORK удалится вместе с рабочей папкой)
P.delete_profile(p.id)

restore_i18n_config(_cfg_snap)
finish()
