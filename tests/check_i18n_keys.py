"""The i18n completeness check: the discovered languages vs en + the keys used in the code.

Three parts (all must be clean for exit code 0):

  1. PARITY (v1.3.3): auto-discovery of EVERY i18n/*.json (the file name is the
     language code — no hardcoded list) + the parity policy: a built-in language
     must cover 100% of en's keys — STRICT parity (no missing, no extra) — and the
     count of the translation keys must match the pin EXPECTED_I18N_KEYS
     (tests/_common.py; the same discovery/parity helpers the topical tests use).
     The meta keys are NOT translations: "name" (the language name in its own
     language) is skipped here, and "partial": true (v1.3.3.1) marks a DELIBERATELY
     incomplete file — its missing keys and its count become a WARNING, not a defect
     (an extra key stays a defect: a key en does not have is a typo/dead weight).
     Every file is read as "utf-8-sig", so a Notepad "UTF-8 with BOM" file loads.

  2. FORMAT (v1.3.3.1, ROADMAP task 4): two defect types the key parity cannot see —
     the SET of `{placeholder}` names and the COUNT of `\\n` line breaks of every
     translation against en. A dropped `{alias}` renders a literal brace in the UI;
     a lost line break silently reshapes a dialog. Helpers — tests/_common.py
     (`placeholder_names` / `newline_count` / `i18n_format_problems`).

  3. USED KEYS (as before): every t('key') in the code must exist in en — and, by
     parity, in every other language.

Run:  python tests/check_i18n_keys.py   (exit code 0 = all the keys are in place)
Catches the class of the bugs of the former AUDIT.md #9 ("the raw keys in the UI"; the decoding of the items — in CHANGELOG.md).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # the harness: the pin + the parity policy (one source of truth)
from _common import (EXPECTED_I18N_KEYS, I18N_REFERENCE, i18n_format_problems,  # noqa: E402
                     i18n_parity_problems, i18n_parity_warnings, is_partial_lang,
                     load_i18n_langs, translation_keys)

ROOT = os.path.dirname(HERE)  # the project root (the parent of tests/)

# t('key') / .t("key") — \b matches before 't' in both forms; plus __t('key')
# and _t('key') (v0.9.8: the safe i18n hook of graphics/* and ui/map_search_bar.py —
# without it the keys of these modules were invisible to the check).
_PATTERNS = [
    re.compile(r"""\bt\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
    re.compile(r"""(?<![\w])__t\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
    re.compile(r"""(?<![\w])_t\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]"""),
]


def collect_used_keys(root):
    """{key: {file, …}} — every i18n key the code asks for (the test meta-scripts are skipped)."""
    used = {}
    for dirpath, _, files in os.walk(root):
        if "__pycache__" in dirpath or "_tmp_testdata" in dirpath:
            continue
        if os.path.relpath(dirpath, root) == "tests":
            continue  # the test meta-scripts are not UI code
        for f in files:
            if not f.endswith(".py") or f.startswith("_"):
                continue  # skip helper scripts like _smoke_test.py
            p = os.path.join(dirpath, f)
            src = open(p, encoding="utf-8").read()
            rel = os.path.relpath(p, root).replace("\\", "/")
            for pat in _PATTERNS:
                for m in pat.finditer(src):
                    used.setdefault(m.group(1), set()).add(rel)
    return used


def main(root=None):
    """Run both parts; return the exit code (0 = all the keys are in place)."""
    # v0.9.4-fix: UTF-8 stdout on cp1251 consoles
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = os.path.abspath(root or ROOT)
    codes = None  # discovery is inside load_i18n_langs (v1.3.3)
    try:
        langs = load_i18n_langs(root)
    except (OSError, ValueError) as e:
        print(f"the i18n files cannot be read under {root}: {e!r}")
        return 1

    print(f"== parity of the discovered languages ({len(langs)}): {', '.join(sorted(langs))} ==")
    problems = i18n_parity_problems(langs)
    warnings = i18n_parity_warnings(langs)
    keyed = {c: translation_keys(d) for c, d in langs.items()}
    for code in sorted(keyed):
        marks = [p for p in problems if p.startswith(f"{code}:")]
        counts = f"{len(keyed[code])} keys"
        if code == I18N_REFERENCE:
            counts += " (the reference)"
        elif is_partial_lang(langs[code]):
            counts += " (partial)"
        print(f"    {code}: {counts}" + ("" if not marks else "  <-- " + "; ".join(marks)))
    if not problems:
        print(f"    OK — every language covers 100% of {I18N_REFERENCE} "
              f"({EXPECTED_I18N_KEYS} translation keys; the meta keys \"name\"/\"partial\" are not counted)")
    for w in warnings:
        print(f"    WARNING {w}")

    # ── 2. v1.3.3.1: the placeholders and the line breaks vs en ──
    print(f"\n== placeholders + line breaks of the discovered languages vs {I18N_REFERENCE} ==")
    format_problems = i18n_format_problems(langs)
    for code in sorted(keyed):
        got = format_problems.get(code, [])
        if code == I18N_REFERENCE:
            print(f"    {code}: the reference")
            continue
        if is_partial_lang(langs[code]):
            print(f"    {code}: skipped (partial)")
            continue
        print(f"    {code}: {len(got)} problem(s)")
        for p in got:
            print("        ", p)
    format_total = sum(len(v) for v in format_problems.values())

    # ── 3. The keys used in the code must exist in every discovered language ──
    used = collect_used_keys(root)
    missing_total = 0
    print(f"\n== used keys vs the language files: {len(used)} unique keys in the code ==")
    for code in sorted(keyed):
        missing = sorted(k for k in used if k not in keyed[code])
        print(f"    {code}: {len(missing)} missing")
        for k in missing:
            print("        ", k, "->", sorted(used[k]))
        missing_total += len(missing)

    problems_total = len(problems) + missing_total + format_total
    print(f"\ntotal defects: {problems_total} (parity: {len(problems)}, "
          f"format: {format_total}, used keys: {missing_total})")
    if warnings:
        print(f"warnings (partial languages, not defects): {len(warnings)}")
    return 1 if problems_total else 0


if __name__ == "__main__":
    sys.exit(main())
