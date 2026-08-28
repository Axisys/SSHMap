"""Проверка полноты i18n: каждый t('key') из кода должен существовать в en/ru/zh.

Запуск:  python tests/check_i18n_keys.py   (exit code 0 = все ключи на месте)
Ловит класс багов AUDIT.md #9 («в UI показываются сырые ключи»).
"""
import json, os, re, sys

# v0.9.4-fix: UTF-8 stdout на cp1251-консолях
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень проекта (родитель tests/)
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = set(json.load(f).keys())

# t('key') / .t("key") — \b matches before 't' in both forms; plus __t('key')
# и _t('key') (v0.9.8: безопасный i18n-хук graphics/* и ui/map_search_bar.py —
# без него ключи этих модулей были невидимы проверке).
pats = [
    re.compile(r"""\bt\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
    re.compile(r"""(?<![\w])__t\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
    re.compile(r"""(?<![\w])_t\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
]

used = {}
for dirpath, _, files in os.walk(ROOT):
    if "__pycache__" in dirpath or "_tmp_testdata" in dirpath:
        continue
    if os.path.relpath(dirpath, ROOT) == "tests":
        continue  # мета-скрипты тестов не являются UI-кодом
    for f in files:
        if not f.endswith(".py") or f.startswith("_"):
            continue  # skip helper scripts like _smoke_test.py
        p = os.path.join(dirpath, f)
        src = open(p, encoding="utf-8").read()
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        for pat in pats:
            for m in pat.finditer(src):
                used.setdefault(m.group(1), set()).add(rel)

missing_total = 0
for code in ("en", "ru", "zh"):
    missing = sorted(k for k in used if k not in langs[code])
    print(f"== {code}: {len(missing)} missing of {len(used)} used keys ==")
    for k in missing:
        print("   ", k, "->", sorted(used[k]))
    missing_total += len(missing)

print(f"\nunique keys used in code: {len(used)}; total missing across langs: {missing_total}")
sys.exit(1 if missing_total else 0)
