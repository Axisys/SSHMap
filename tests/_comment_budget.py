# -*- coding: utf-8 -*-
"""The code-comment budget: the marker list and the ratchet pins behind `tests/test_docs.py` §6.

The rule: code text (comments and docstrings) obeys the same "THE DOCUMENTATION RULES" as the two
reference docs — a release narrative belongs to the changelog family, the mechanism to
`DOCUMENTATION.md`, a rule and a name to `AGENTS.md`. `HISTORY_MARKERS` is the ONE marker list:
`tests/test_docs.py` §5 scans the two documents with it, §6 scans the code.

§6 is a RATCHET, not a green field: the debt that shipped before the rule existed is PINNED and the
pins may only go DOWN. Clean a file, lower the pin; new narrative or a longer header fails the suite.
Measure, and print a paste-ready pin block:  python tests/_comment_budget.py
"""
import ast
import io
import os
import re
import tokenize

# ── The marker list (the changelog family's vocabulary) ───────────────────────────────────────
# The patterns are deliberately HIGH-PRECISION (a present-tense "no longer exists" or a dated PINNED
# decision is documentation, not history), and every one of them reads 0 in the two reference docs.
HISTORY_MARKERS = (
    ("'used to'", re.compile(r"\bused to\b", re.I)),
    ("a removal story", re.compile(r"\b(?:was|were|has been|have been)\s+removed\b", re.I)),
    ("the all-caps REMOVED status", re.compile(r"\bREMOVED\b")),
    ("a change attributed to a release",
     re.compile(r"\b(?:added|introduced|renamed|replaced|dropped|deleted|removed|fixed)\b"
                r"[^.]{0,40}\b(?:in|since)\s+v?\d+(?:\.\d+)+", re.I)),
 ("a -fix marker", re.compile(r"\bv?\d[\d.]*-fix\b")),
    ("'fixed in vX.Y'", re.compile(r"\bfixed in v\d", re.I)),
    ("a narrative 'in vX.Y <subject>'",
     re.compile(r"\bin v\d+(?:\.\d+)+\s+(?:we|the|a|this|it)\b", re.I)),
    ("a release verb",
     re.compile(r"\bv\d+(?:\.\d+)+\s+(?:renamed|rewrote|rewritten|reworked|replaced|dropped"
                r"|deleted|introduced|reintroduced)\b", re.I)),
    ("'this release/version adds|changed|fixes'",
     re.compile(r"\bthis (?:release|version|line)\s+"
                r"(?:adds|added|changes|changed|fixes|fixed|brings|brought|replaces|replaced)\b")),
)

# ── The targets (AGENTS.md §12 owns the rule; these are the numbers it states) ────────────────
HEADER_BUDGET_LINES = 12   # a module docstring: what it is, who owns it, a pointer to the mechanism
BLOCK_BUDGET_LINES = 5     # a comment block in the body: the invariant + the pointer, never a story

# ── The pins (the debt measured when the ratchet was introduced; LOWER them, never raise) ─────
NARRATIVE_PIN = 0          # HISTORY_MARKERS matches in the code text — the goal state, reached by §7 step 5
HEADER_LINES_PIN = 2439    # module docstring lines, all files — RAISED for v1.7.3 … v1.8, always with
                           # the reason in the changelog family: a NEW module or topical file needs a
                           # header (`local_fs_worker`, the 38 files of the 1.8rc1–rc6 waves and the 1.8
                           # FEATURE's five: the elevated provider, its pane mixin, its dialogue and
                           # the two topical gates).
MAX_HEADER_PIN = 12        # the longest module docstring — the budget itself
HEADER_FILES_PIN = 0       # module docstrings longer than HEADER_BUDGET_LINES — the goal state
BLOCK_LINES_PIN = 0        # lines inside comment blocks longer than BLOCK_BUDGET_LINES — the goal state
MAX_BLOCK_PIN = 5          # the longest contiguous comment block — the budget itself
BLOCK_FILES_PIN = 0        # comment blocks longer than BLOCK_BUDGET_LINES — the goal state

_SKIP_DIRS = {"third_party", ".git", "__pycache__", "test-results", "build", "dist"}


def default_root():
    """The repository root (this file lives in `<root>/tests/`)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iter_sources(root):
    """Every Python source of the project (the vendored fork and the tooling artifacts excluded)."""
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in sorted(files):
            if name.endswith(".py"):
                out.append(os.path.join(base, name))
    return sorted(out)


def _parse(source):
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def module_header_span(source):
    """(first_line, last_line) of the module docstring, 1-based; None when there is none."""
    tree = _parse(source)
    if tree is None or not tree.body:
        return None
    first = tree.body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return None
    return first.value.lineno, first.value.end_lineno or first.value.lineno


def comment_blocks(source):
    """Every contiguous run of comment-ONLY lines as (first_line, last_line) — the block prose."""
    lines = source.splitlines()
    numbered = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and lines[tok.start[0] - 1][:tok.start[1]].strip() == "":
                numbered.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    blocks, run = [], []
    for i in range(1, len(lines) + 1):
        if i in numbered:
            run.append(i)
        else:
            if run:
                blocks.append((run[0], run[-1]))
            run = []
    if run:
        blocks.append((run[0], run[-1]))
    return blocks


def comment_text(source):
    """All comment and docstring text of one file, whitespace-folded (the marker scan's input)."""
    parts = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                parts.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    tree = _parse(source)
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                parts.append(ast.get_docstring(node, clean=False) or "")
    return re.sub(r"\s+", " ", " ".join(parts))


def measure(root, markers=HISTORY_MARKERS):
    """The code-comment footprint of the tree: the totals, the offenders and the worst cases."""
    out = {"files": 0, "narrative": 0, "header_lines": 0, "max_header": 0, "header_files": 0,
           "block_lines": 0, "max_block": 0, "block_files": 0,
           "header_offenders": [], "block_offenders": [], "narrative_offenders": []}
    for path in iter_sources(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        out["files"] += 1

        text = comment_text(source)
        hits = sum(len(pat.findall(text)) for _, pat in markers)
        if hits:
            out["narrative"] += hits
            out["narrative_offenders"].append((hits, rel))

        span = module_header_span(source)
        if span:
            n = span[1] - span[0] + 1
            out["header_lines"] += n
            out["max_header"] = max(out["max_header"], n)
            if n > HEADER_BUDGET_LINES:
                out["header_files"] += 1
                out["header_offenders"].append((n, rel))

        for start, end in comment_blocks(source):
            n = end - start + 1
            if n > BLOCK_BUDGET_LINES:
                out["block_files"] += 1
                out["block_lines"] += n
                out["block_offenders"].append((n, f"{rel}:{start}-{end}"))
            out["max_block"] = max(out["max_block"], n)

    out["narrative_offenders"].sort(reverse=True)
    out["header_offenders"].sort(reverse=True)
    out["block_offenders"].sort(reverse=True)
    return out


def _top(rows, limit=3, suffix=""):
    return ", ".join(f"{name}{suffix} ({n})" for n, name in rows[:limit]) or "none"


def report(check, root=None, prefix="§6"):
    """The §6 ratchet: every measured figure against its pin. Returns the measurement."""
    m = measure(root or default_root())
    check(f"{prefix} the scan really read the sources (a guard over nothing is useless)",
          m["files"] > 100, f"files={m['files']}")
    check(f"{prefix} the code carries no more release narrative than the pin ({NARRATIVE_PIN})",
          m["narrative"] <= NARRATIVE_PIN,
          f"measured={m['narrative']} — worst: {_top(m['narrative_offenders'])}; "
          f"move the story to the changelog and lower NARRATIVE_PIN")
    check(f"{prefix} the module headers total no more than the pin ({HEADER_LINES_PIN} lines)",
          m["header_lines"] <= HEADER_LINES_PIN,
          f"measured={m['header_lines']} — longest: {_top(m['header_offenders'], suffix=' lines')}; "
          f"cut as you clean and lower HEADER_LINES_PIN")
    check(f"{prefix} no module header exceeds the pinned worst ({MAX_HEADER_PIN} lines)",
          m["max_header"] <= MAX_HEADER_PIN,
          f"measured={m['max_header']} — {_top(m['header_offenders'], 1, ' lines')}")
    check(f"{prefix} the over-budget module headers do not grow ({HEADER_FILES_PIN}, budget "
          f"{HEADER_BUDGET_LINES} lines)",
          m["header_files"] <= HEADER_FILES_PIN,
          f"measured={m['header_files']} — worst: {_top(m['header_offenders'], suffix=' lines')}; "
          f"lower HEADER_FILES_PIN when a header drops to the budget")
    check(f"{prefix} the comment blocks total no more than the pin ({BLOCK_LINES_PIN} lines)",
          m["block_lines"] <= BLOCK_LINES_PIN,
          f"measured={m['block_lines']} — longest: {_top(m['block_offenders'], suffix=' lines')}; "
          f"lower BLOCK_LINES_PIN")
    check(f"{prefix} no comment block exceeds the pinned worst ({MAX_BLOCK_PIN} lines)",
          m["max_block"] <= MAX_BLOCK_PIN,
          f"measured={m['max_block']} — {_top(m['block_offenders'], 1, ' lines')}")
    check(f"{prefix} the over-budget comment blocks do not grow ({BLOCK_FILES_PIN}, budget "
          f"{BLOCK_BUDGET_LINES} lines)",
          m["block_files"] <= BLOCK_FILES_PIN,
          f"measured={m['block_files']} — longest: {_top(m['block_offenders'], suffix=' lines')}; "
          f"lower BLOCK_FILES_PIN when a block drops to the budget")
    return m


def pin_block(m):
    """The paste-ready constants of a measurement (the maintainer lowers them by hand)."""
    return "\n".join((
        f"NARRATIVE_PIN = {m['narrative']}",
        f"HEADER_LINES_PIN = {m['header_lines']}",
        f"MAX_HEADER_PIN = {m['max_header']}",
        f"HEADER_FILES_PIN = {m['header_files']}",
        f"BLOCK_LINES_PIN = {m['block_lines']}",
        f"MAX_BLOCK_PIN = {m['max_block']}",
        f"BLOCK_FILES_PIN = {m['block_files']}",
    ))


def _main():
    m = measure(default_root())
    print(f"files read                : {m['files']}")
    print(f"narrative marker matches  : {m['narrative']}")
    print(f"module docstring lines    : {m['header_lines']}  (longest {m['max_header']})")
    print(f"headers over {HEADER_BUDGET_LINES:2} lines      : {m['header_files']}")
    print(f"comment-block lines       : {m['block_lines']}  (longest {m['max_block']})")
    print(f"blocks over {BLOCK_BUDGET_LINES} lines       : {m['block_files']}")
    print("\n--- the worst module headers ---")
    for n, rel in m["header_offenders"][:15]:
        print(f"{n:5}  {rel}")
    print("\n--- the worst comment blocks ---")
    for n, rel in m["block_offenders"][:15]:
        print(f"{n:5}  {rel}")
    print("\n--- the narrative, by file ---")
    for n, rel in m["narrative_offenders"][:15]:
        print(f"{n:5}  {rel}")
    print("\n--- the pin block ---")
    print(pin_block(m))


if __name__ == "__main__":
    _main()
