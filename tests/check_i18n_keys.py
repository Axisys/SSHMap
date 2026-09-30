"""The i18n completeness check: the discovered languages vs en plus the keys used in the code (§17).

  1. PARITY — every `i18n/*.json` is discovered (the file name is the code) and a built-in language must
     cover 100% of en STRICTLY, with the count equal to the pin `EXPECTED_I18N_KEYS` (`tests/_common.py`).
     Meta keys are not translations: "name" is skipped and `"partial": true` turns the missing keys and
     the count into a WARNING (an EXTRA key stays a defect); every file is read "utf-8-sig".
  2. FORMAT — the SET of `{placeholder}` names and the COUNT of `\n` breaks of every translation
     against en; 3. USED KEYS — every `t('key')` in the code exists in en (and by parity in all).
  4. FALLBACK LITERALS — `fallback_literal_problems(source, en)`: the else-branch of every declared
     availability ternary and every `*_FALLBACKS` table vs `en.json`; 5. REFUSAL BODIES —
     `refusal_body_problems(source, function)` over `REFUSAL_SITES`: a DECLARED refusal's dialog body
     must be a `t('key')` call, never a literal (a key that already exists is invisible to §3/§4)."""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # the harness: the pin + the parity policy (one source of truth)
from _common import (EXPECTED_I18N_KEYS, I18N_META_KEYS, I18N_REFERENCE,  # noqa: E402
                     i18n_format_problems, i18n_parity_problems, i18n_parity_warnings,
                     is_partial_lang, load_i18n_langs, translation_keys)

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
    for p, rel in _source_files(root):
        src = open(p, encoding="utf-8").read()
        for pat in _PATTERNS:
            for m in pat.finditer(src):
                used.setdefault(m.group(1), set()).add(rel)
    return used


def _source_files(root):
    """[(absolute path, relative posix path)] — the APPLICATION source (never tests/, third_party/)."""
    for dirpath, _, files in os.walk(root):
        if "__pycache__" in dirpath or "_tmp_testdata" in dirpath:
            continue
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir.split("/")[0] in ("tests", "third_party", ".git"):
            continue
        for f in sorted(files):
            if not f.endswith(".py") or f.startswith("_"):
                continue  # skip helper scripts like _smoke_test.py
            p = os.path.join(dirpath, f)
            yield p, os.path.relpath(p, root).replace("\\", "/")


# ── 4. v1.6.1 (ROADMAP task 2): the no-i18n fallback literals vs en ───────────

# The DECLARED availability flag (§4.5). Only a ternary whose TEST mentions this
# name is a fallback candidate — a value-carrying ternary never is.
I18N_FLAG_NAME = "_i18n_available"
# Every spelling of the translator the code uses: t(), _t() and __t() (the safe
# i18n hook of graphics/*) and _tr() (the QuickLaunchDialog helper).
TRANSLATOR_NAMES = ("t", "_t", "__t", "_tr")


def _test_uses_flag(test) -> bool:
    """Whether the ternary's condition mentions the DECLARED availability flag."""
    for node in ast.walk(test):
        if isinstance(node, ast.Attribute) and node.attr == I18N_FLAG_NAME:
            return True
        if isinstance(node, ast.Name) and node.id == I18N_FLAG_NAME:
            return True
    return False


def _call_key(node):
    """The string key of a `t('key')`-shaped call, or None (a dynamic key is no candidate)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in TRANSLATOR_NAMES or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def fallback_literal_problems(source, en, path=""):
    """The no-i18n fallback literals of ONE source text that disagree with `en` (pure).

    Two shapes are compared, both keyed on the DECLARED flag or on a declared TABLE:
      * `t("key") if <flag> else "<literal>"` — the else-branch must equal `en["key"]`;
      * a `*_FALLBACKS` dict TABLE (the `ui/sidebar.py` `_AGE_FALLBACKS` pattern) —
        every string value must equal the `en` value of its key.

    Returns a sorted list of human-readable problems (empty = clean). `path` only
    labels them; the function itself is pure, so a synthetic source can be handed
    to it directly (the topical test does exactly that).
    """
    problems = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:  # a syntactically broken source is not this check's business
        return [f"{path}: cannot parse ({e})"]

    def compare(key, literal, lineno):
        if key in en and literal != en[key]:
            problems.append(f"{path}:{lineno} {key}: {literal!r} != {en[key]!r}")

    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and _test_uses_flag(node.test):
            literal = node.orelse
            key = _call_key(node.body)
            if key is not None and isinstance(literal, ast.Constant) \
                    and isinstance(literal.value, str):
                compare(key, literal.value, node.lineno)
        elif isinstance(node, ast.Assign):
            for key, literal, lineno in _fallback_table_entries(node):
                compare(key, literal, lineno)
    return sorted(set(problems))


def _fallback_table_entries(node):
    """The `(key, literal, lineno)` triples of a `*_FALLBACKS` dict TABLE (else none).

    The NAME is the declaration: only a table whose name ends in `_FALLBACKS` is
    read, so a dict keyed by i18n keys for another purpose (the toolbar's own
    `_VIEW_TOOLBAR_ACTIONS`, an action id → attribute name map) is never a candidate.
    """
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return ()
    if not node.targets[0].id.endswith("_FALLBACKS") or not isinstance(node.value, ast.Dict):
        return ()
    entries = []
    for k, v in zip(node.value.keys, node.value.values):
        if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                and isinstance(v, ast.Constant) and isinstance(v.value, str):
            entries.append((k.value, v.value, v.lineno))
    return tuple(entries)


def collect_fallback_problems(root, en):
    """`fallback_literal_problems` over the whole application source."""
    problems = []
    for p, rel in _source_files(root):
        try:
            src = open(p, encoding="utf-8").read()
        except OSError as e:
            problems.append(f"{rel}: cannot read ({e})")
            continue
        problems.extend(fallback_literal_problems(src, en, rel))
    return sorted(set(problems))


# ── 5. v1.7.1.3: the dialog BODY of a declared refusal is a KEY, not a literal ──

#: The DECLARED refusal sites — `(relative path, function name)`. The NAME is the declaration,
#: exactly like `*_FALLBACKS`: a site is listed here once, and its body is then audited.
REFUSAL_SITES = (("ui/main_window.py", "_open_log_file"),)

#: The dialog entry points whose TEXT argument is the body (`QMessageBox.<kind>(parent, title, body)`).
MESSAGEBOX_KINDS = ("warning", "information", "critical", "question")


def refusal_body_problems(source, func_name, path=""):
    """The dialog bodies of ONE function that are NOT a `t('key')` call (pure).

    A translated TITLE beside an English body speaks two languages at once, and `en.json`
    usually already carries the sentence (the key is simply unused) — which is exactly why
    §3 cannot see it (it only wants keys that EXIST) and §4 cannot either (a ternary or a
    table is another shape). `path` only labels the problems.
    """
    problems = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:  # a syntactically broken source is not this check's business
        return [f"{path}: cannot parse ({e})"]
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    if func is None:
        return [f"{path}: no {func_name}() — the declared refusal site is gone"]
    found = False
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or getattr(node.func, "attr", None) not in MESSAGEBOX_KINDS:
            continue
        if len(node.args) < 3:      # a two-argument dialog carries no body of its own
            continue
        found = True
        if _call_key(node.args[2]) is None:
            problems.append(f"{path}:{node.lineno} {func_name}(): the dialog BODY is not a "
                            f"translated key")
    if not found:
        problems.append(f"{path}: {func_name}() has no dialog any more")
    return sorted(set(problems))


def collect_refusal_problems(root, sites=REFUSAL_SITES):
    """`refusal_body_problems` over the DECLARED refusal sites of the project.

    A site whose FILE is absent is skipped: a minimal or synthetic root (the fake projects of
    the topical test) carries no application source at all, exactly like its used-keys part.
    """
    problems = []
    for rel, func_name in sites:
        path = os.path.join(root, *rel.split("/"))
        if not os.path.exists(path):
            continue
        try:
            src = open(path, encoding="utf-8").read()
        except OSError as e:
            problems.append(f"{rel}: cannot read ({e})")
            continue
        problems.extend(refusal_body_problems(src, func_name, rel))
    return sorted(set(problems))


def main(root=None):
    """Run both parts; return the exit code (0 = all the keys are in place)."""
    # UTF-8 stdout on cp1251 consoles
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
    # ── 4. v1.6.1 (ROADMAP task 2): the no-i18n fallback literals vs en ──
    en = {k: v for k, v in (langs.get(I18N_REFERENCE) or {}).items()
          if k not in I18N_META_KEYS and isinstance(v, str)}
    fallback_problems = collect_fallback_problems(root, en)
    print("\n== the no-i18n fallback literals vs "
          f"{I18N_REFERENCE}: {len(fallback_problems)} problem(s) ==")
    for p in fallback_problems:
        print("    ", p)
    problems_total += len(fallback_problems)

    # ── 5. v1.7.1.3: the dialog bodies of the declared refusals ──
    refusal_problems = collect_refusal_problems(root)
    print("\n== the dialog bodies of the declared refusals: "
          f"{len(refusal_problems)} problem(s) ==")
    for p in refusal_problems:
        print("    ", p)
    problems_total += len(refusal_problems)

    print(f"\ntotal defects: {problems_total} (parity: {len(problems)}, "
          f"format: {format_total}, used keys: {missing_total}, "
          f"fallback literals: {len(fallback_problems)}, "
          f"refusal bodies: {len(refusal_problems)})")
    if warnings:
        print(f"warnings (partial languages, not defects): {len(warnings)}")
    return 1 if problems_total else 0


if __name__ == "__main__":
    sys.exit(main())
