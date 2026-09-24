# -*- coding: utf-8 -*-
"""The documentation-consistency guards (the changelog family, ROADMAP, the quoted counters, INDEX freshness).

`DOCUMENTATION.md`, `AGENTS.md`, `CHANGELOG*.md` and `ROADMAP.md` are gitignored (".gitignore:
Overly detailed documentation; all the essentials are in README.md") and are NOT tracked by git —
no review and no checkout reads them, which is exactly why the suite guards them. Every rule
below is a PROPERTY over the whole document, never a pin of a literal sentence: the check that
read `CHANGELOG.md` by name and grepped for "## v1.4.1 " broke the moment v1.5rc1 closed the
1.4 line — a property survives that, a content pin does not.

This file owns the checks about the DOCUMENTS themselves. The numbers `README.md` / `ROADMAP.md`
quote (the test-file counter, the parity chain) stay where they were — `tests/test_i18n_live.py`
§6 — and no topical test reads a doc any more (the docs are local-only, so a fresh clone must
still be able to run the suite).

  §1 the section ownership: the shipped release has a section in the `CHANGELOG*.md` family, no
     release section is duplicated inside one file or across two, every history file follows the
     naming convention, and `ROADMAP.md` plans no ALREADY RELEASED version — the "a released
     section is removed from the plan" rule, generalised beyond the one version it started with;
  §2 the counters the reference docs quote are the code's counters: the i18n key pin and the
     action registry (its size in EVERY spelling — bold or not, "actions" or "entries" — and its
     EMPTY-default count);
  §3 `DOCUMENTATION.md` is self-consistent: every `§N` reference resolves to a heading, a DOTTED
     `§N.M` reference names `AGENTS.md` (that numbering is not this file's), the contents list names
     every section, and every gotcha citation stays inside the numbered list whose numbering
     `AGENTS.md` §7 shares (a "#13" must not mean two different items);
  §4 `tests/INDEX.md` is fresh (the generator `_gen_index.py` is the single source of truth);
  §5 the documentation rules `AGENTS.md` states are ENFORCED: the changelog never leaks into the two
     reference docs (no release narrative), a chapter number never collides with a numbered section,
     no block is copied between the files, and every cross-file `§`-reference resolves in the file
     that it names.

A missing documentation set is a SKIP, not a defect (they are gitignored): the guards are for
the maintainer's working copy, and a fresh clone stays runnable.

Run: python tests/test_docs.py   (from the project root) or python tests/run_all.py
"""
import collections
import glob
import os
import re
import sys

from _common import bootstrap, check, finish, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS

ROOT, WORK = bootstrap()  # HOME isolation + offscreen + sys.path (BEFORE any app import)

REFERENCE_DOCS = ("DOCUMENTATION.md", "AGENTS.md")
_DOC = os.path.join(ROOT, "DOCUMENTATION.md")
_AGENTS = os.path.join(ROOT, "AGENTS.md")
_ROADMAP = os.path.join(ROOT, "ROADMAP.md")
_LIVE_CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
_HISTORY = sorted(glob.glob(os.path.join(ROOT, "CHANGELOG_HISTORY_*.md")))

_missing = [p for p in (_DOC, _AGENTS, _ROADMAP, _LIVE_CHANGELOG) if not os.path.exists(p)]
if not _HISTORY:
    _missing.append(os.path.join(ROOT, "CHANGELOG_HISTORY_*.md"))
if _missing:
    print("  SKIP  the local documentation set is not present: "
          + ", ".join(os.path.basename(p) for p in _missing))
    print("        (DOCUMENTATION.md / AGENTS.md / CHANGELOG*.md / ROADMAP.md are gitignored "
          "local files — a fresh clone has none of them)")
    finish()          # 0 checks, 0 failures: a SKIP is not a defect
    sys.exit(0)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _flat(path):
    """The text with the line breaks folded (the docs wrap at ~100 columns, so a phrase-level
    regex must see the paragraphs, not the wrapping — "24 with an\\nEMPTY default")."""
    return re.sub(r"\s+", " ", _read(path))


_ARROW_BEFORE = re.compile(r"(?:→|->)\s*$")


def _stale_figures(text, figure_re, live):
    """The figures that are neither the LIVE value nor the successor of an "N → M" chain.

    A reference doc may quote the PAST — but only as a chain ("44 → 45 actions"), never as a bare
    claim about the present: the v1.4.7 text still read "44 actions since v1.4.1 …" while the
    registry held 46, and that is exactly the drift this pair of checks exists to catch."""
    stale = []
    for m in figure_re.finditer(text):
        value = int(m.group(1))
        if value == live or _ARROW_BEFORE.search(text[:m.start(1)]):
            continue
        stale.append(value)
    return sorted(set(stale))


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the section ownership (the changelog family vs the plan) ==")
# ════════════════════════════════════════════════════════════════════════════

# A RELEASE section is "## vX.Y[.Z[.W]][rcN] — <title>" (or "... (date)"). The audit snapshots
# of the old lines look like "## v0.8.3 audit (…)" and are deliberately NOT release sections.
_RELEASE_HEADING = re.compile(r"^## (v[0-9][0-9A-Za-z.]*)\s*(?:—|\()", re.M)

_family = {os.path.basename(p): _RELEASE_HEADING.findall(_read(p))
           for p in [_LIVE_CHANGELOG] + _HISTORY}
_by_version = collections.defaultdict(set)          # version → the files carrying a section
for _file, _versions in _family.items():
    for _v in _versions:
        _by_version[_v.lower()].add(_file)

check(f"§1 the changelog family carries the shipped release (v{EXPECTED_APP_VERSION})",
      f"v{EXPECTED_APP_VERSION}".lower() in _by_version,
      f"{len(_family)} file(s), {len(_by_version)} release section(s)")
check("§1 no release section is duplicated inside one file",
      all(len(v) == len(set(v)) for v in _family.values()),
      [n for n, v in _family.items() if len(v) != len(set(v))])
check("§1 no release section is duplicated across two files (the close-a-line mistake)",
      all(len(files) == 1 for files in _by_version.values()),
      {v: sorted(f) for v, f in _by_version.items() if len(f) > 1})
check("§1 every history file is named for a closed line (CHANGELOG_HISTORY_V<digits>.md)",
      all(re.fullmatch(r"CHANGELOG_HISTORY_V\d+\.md", os.path.basename(p)) for p in _HISTORY),
      [os.path.basename(p) for p in _HISTORY])

_planned = _RELEASE_HEADING.findall(_read(_ROADMAP))
_released_in_plan = [v for v in _planned if v.lower() in _by_version]
check("§1 ROADMAP.md plans only unreleased versions (a shipped section leaves the plan)",
      not _released_in_plan,
      f"planned={_planned} released-in-plan={_released_in_plan}")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the counters quoted by the docs are the code's counters ==")
# ════════════════════════════════════════════════════════════════════════════

# The i18n pin is strict: the reference docs may quote the SHIPPED key count and nothing else
# (the "545 / 566 / 603 / 611" drift came from exactly this — a figure frozen at release time).
# The per-release chains of ROADMAP.md / README.md stay in tests/test_i18n_live.py §6.
_PIN_FIGURE = re.compile(r"\b(\d{3,4})\s+keys\b")
for _name in REFERENCE_DOCS:
    _figures = sorted({int(m.group(1)) for m in _PIN_FIGURE.finditer(_flat(os.path.join(ROOT, _name)))})
    check(f"§2 {_name}: the quoted i18n key count is the shipped pin ({EXPECTED_I18N_KEYS})",
          _figures == [EXPECTED_I18N_KEYS], f"quoted={_figures}")

import ui.hotkey_registry as HR  # noqa: E402 — the declarative list, no window needed

_N_ACTIONS = len(HR.HOTKEY_ACTIONS)
_N_EMPTY = len(HR.empty_default_action_ids())
# The markdown-tolerant pattern: "**51** actions" is the SAME claim as "51 actions" — the v1.5.5
# review found figures wrapped in bold that the bare pattern could not see at all, so a guard over
# this counter has to see every spelling of it.
_ACTION_FIGURE = re.compile(r"\b(\d+)\*{0,2}\s+\*{0,2}actions\b")
# "the registry stays 46" / "stays at **49 entries**" — the same counter in OTHER words, which is
# how a stale registry size ("the action registry stays 46" in the v1.4.6 section, against a live 56)
# survived the suite for a whole line.
_REGISTRY_FIGURE = re.compile(r"registry\s+(?:holds|stays|is)\s+(?:at\s+)?\*{0,2}(\d+)\*{0,2}"
                              r"(?:\s+(?:actions|entries))?")
_EMPTY_FIGURE = re.compile(r"\b(\d+)\s+(?:of the \d+(?:\s+actions)?\s+ship this way"
                           r"|of them empty|with an EMPTY default|empty defaults)")
for _name in REFERENCE_DOCS:
    _text = _flat(os.path.join(ROOT, _name))
    _actions = sorted({int(m.group(1)) for m in _ACTION_FIGURE.finditer(_text)})
    _empty = sorted({int(m.group(1)) for m in _EMPTY_FIGURE.finditer(_text)})
    check(f"§2 {_name} states the live action count ({_N_ACTIONS})",
          _N_ACTIONS in _actions, f"quoted={_actions}")
    check(f"§2 {_name} states the live empty-default count ({_N_EMPTY})",
          _N_EMPTY in _empty, f"quoted={_empty}")
    # A reference doc may quote the PAST, but only as a chain successor ("44 → 45 actions") or as
    # the live figure itself: the "44 actions since v1.4.1" that shipped in v1.4.7 is a stale claim
    # about the present, and it is what this pair of checks exists to catch.
    _stale_actions = _stale_figures(_text, _ACTION_FIGURE, _N_ACTIONS)
    _stale_empty = _stale_figures(_text, _EMPTY_FIGURE, _N_EMPTY)
    _stale_registry = _stale_figures(_text, _REGISTRY_FIGURE, _N_ACTIONS)
    check(f"§2 {_name}: every action figure is the live one or a chain successor",
          not _stale_actions, f"stale={_stale_actions}")
    check(f"§2 {_name}: every empty-default figure is the live one or a chain successor",
          not _stale_empty, f"stale={_stale_empty}")
    check(f"§2 {_name}: every registry-size figure is the live one or a chain successor",
          not _stale_registry, f"stale={_stale_registry}")


# ════════════════════════════════════════════════════════════════════════════
print("== §3 DOCUMENTATION.md is self-consistent ==")
# ════════════════════════════════════════════════════════════════════════════

_doc = _read(_DOC)
_headings = {m for m in re.findall(r"^#### ([0-9]{1,2}[a-z]?)\.", _doc, re.M)}
# "§5b of tests/test_terminal_output.py" points INSIDE a test file, not into this document
# (the topical-test convention: §Na lettered sections of a test are not document sections).
_TEST_SECTIONS = {"1b", "1c", "2b", "5b"}
_refs = {m for m in re.findall(r"§\s?([0-9]{1,2}[a-z]?)", _doc)}
check("§3 every §-reference resolves to a heading of this document",
      not (_refs - _headings - _TEST_SECTIONS),
      sorted(_refs - _headings - _TEST_SECTIONS))

# The DOTTED form is AGENTS.md's ("§4.6"): this document numbers its sections 1..48 and has no §4.x,
# so an unlabelled "§4.6" here resolves to §4 and quietly points the reader at the wrong section (the
# v1.5.5 review found six of them — the theme, i18n, secrets and the hotkey registry all live in
# OTHER sections of this file). Two dotted forms are legitimate: this file's OWN sub-sections, which
# it declares in bold ("**§45.2 The two thin taps**"), and a reference that NAMES AGENTS.md.
_DOTTED_REF = re.compile(r"§\s?(\d{1,2}\.[0-9]+)")
_SELF_SUBSECTIONS = set(re.findall(r"\*\*§(\d{1,2}\.\d+)\b", _doc))
_unlabelled_refs = sorted({m.group(0) for m in _DOTTED_REF.finditer(_doc)
                           if m.group(1) not in _SELF_SUBSECTIONS
                           and "AGENTS" not in _doc[max(0, m.start() - 40):m.start() + 40]})
check("§3 a dotted §-reference in DOCUMENTATION.md names its file (the numbering is AGENTS.md's)",
      not _unlabelled_refs, _unlabelled_refs)

check("§3 the contents block is really there (a guard over nothing is useless)",
      "<summary><b>Contents" in _doc and "</details>" in _doc)
_toc = _doc[_doc.find("<summary><b>Contents"):_doc.find("</details>")]
check("§3 the contents list names every section (a new section joins the TOC)",
      all(re.search(rf"(?<![0-9]){re.escape(n)}(?![0-9])", _toc) for n in _headings),
      [n for n in sorted(_headings) if not re.search(rf"(?<![0-9]){re.escape(n)}(?![0-9])", _toc)])

# The gotcha list: DOCUMENTATION.md carries the numbered list, AGENTS.md §7 the table with the
# SAME numbering — every "#N" in the prose must mean the same item in both files.
_GOTCHA_HEAD = "### PySide6/Qt 6.11 gotchas"
_items = [int(n) for n in re.findall(r"^(\d+)\. ", _doc[_doc.find(_GOTCHA_HEAD):], re.M)]
_rows = [int(n) for n in re.findall(r"^\| (\d+) \|", _read(_AGENTS), re.M)]
check("§3 the gotcha list is numbered 1..N without gaps",
      _items == list(range(1, len(_items) + 1)), f"items={len(_items)}")
check("§3 the gotcha numbering is the SAME in DOCUMENTATION.md and AGENTS.md §7",
      _items == _rows, f"documentation={len(_items)} agents={len(_rows)}")
_cited = sorted({int(n) for n in re.findall(r"(?:gotcha[s]?|item[s]?|pitfall[s]?)\s*#?\s*(\d+)", _doc)})
check("§3 every gotcha citation points inside that list",
      all(1 <= c <= len(_items) for c in _cited), f"cited={_cited} items={len(_items)}")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 tests/INDEX.md is fresh ==")
# ════════════════════════════════════════════════════════════════════════════

sys.path.insert(0, os.path.join(ROOT, "tests"))   # _gen_index imports run_all from its own folder
import _gen_index as GI  # noqa: E402
from run_all import collect_files  # noqa: E402

_names = [n for n in collect_files() if n.startswith("test_")]
_block, _problems = GI.build_block(_names)
check("§4 every test file carries a module docstring (the INDEX table needs it)",
      not _problems, _problems[:3])
check("§4 tests/INDEX.md is fresh (update: python tests/_gen_index.py)",
      GI.extract_block(_read(GI.INDEX_PATH)) == _block,
      f"the «Suite files» block differs ({len(_names)} files)")


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the documentation rules are enforced ==")
# ════════════════════════════════════════════════════════════════════════════

# §5 guards the rules AGENTS.md states in "THE DOCUMENTATION RULES": the changelog family never leaks
# into the two reference docs, a chapter number never collides with a numbered section, no block is
# copied between the files and a cross-file §-reference resolves where it points. The rules block
# ITSELF is EXCLUDED from the marker scan (it names the forbidden words on purpose) — and its
# existence is asserted, so the exclusion can never silently swallow the whole file.

_RULES_BLOCK = {
    "AGENTS.md": ("> **THE DOCUMENTATION RULES", "\n---\n"),
    "DOCUMENTATION.md": ("> **THE RULES OF THIS FILE**", "\n\n"),
}


def _without_rules(name, text):
    """The document without its rules block (None when the block is gone)."""
    start, end = _RULES_BLOCK[name]
    i = text.find(start)
    j = text.find(end, i) if i >= 0 else -1
    return None if i < 0 or j < 0 else text[:i] + text[j:]


_rules_free = {n: _without_rules(n, _read(os.path.join(ROOT, n))) for n in REFERENCE_DOCS}
check("§5 both reference docs still carry their rules block (the scans below exclude it)",
      all(_rules_free.values()), [n for n in REFERENCE_DOCS if not _rules_free[n]])
_rules_free = {n: (_rules_free[n] if _rules_free[n] is not None else _read(os.path.join(ROOT, n)))
               for n in REFERENCE_DOCS}

# The release narrative the changelog family owns: the patterns are deliberately HIGH-PRECISION (a
# present-tense "no longer exists" or a dated PINNED decision is documentation, not history), and
# every one of them reads 0 in the current docs.
_HISTORY_MARKERS = (
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
for _name in REFERENCE_DOCS:
    _flat_text = re.sub(r"\s+", " ", _rules_free[_name])
    _hits = []
    for _label, _pat in _HISTORY_MARKERS:
        _m = _pat.search(_flat_text)
        if _m:
            _hits.append(f"{_label}: …{_flat_text[max(0, _m.start() - 40):_m.end() + 40]}…")
    check(f"§5 {_name} carries no release narrative (that is the changelog family's)",
          not _hits, _hits[:2])

# The numbering: a "## N." chapter must NEVER share a number with a "#### N." section — that is the
# collision that made a bare "§5" mean both "Project format" and "5. ConnectionArrow".
for _name in REFERENCE_DOCS:
    _text = _rules_free[_name]
    _chapters = set(re.findall(r"^## ([0-9]{1,2})\.", _text, re.M))
    _sections = set(re.findall(r"^#### ([0-9]{1,2})[a-z]?\.", _text, re.M))
    check(f"§5 {_name}: no chapter number collides with a numbered section",
          not (_chapters & _sections),
          f"chapters={sorted(_chapters)} sections={sorted(_sections)}" if _chapters & _sections else "")
check("§5 DOCUMENTATION.md cites its chapters by NAME (they are unnumbered there)",
      not re.findall(r"^## [0-9]{1,2}\.", _doc, re.M),
      re.findall(r"^## [0-9]{1,2}\.", _doc, re.M))

# A cross-file reference must resolve in the file it NAMES (§3 above only checks the in-file ones).
_agt_text = _rules_free["AGENTS.md"]
_doc_refs = set()
for _line in _agt_text.splitlines():
    if "DOCUMENTATION.md" in _line:
        _doc_refs |= set(re.findall(r"§\s?([0-9]{1,2}[a-z]?)", _line))
_doc_sections = set(re.findall(r"^#{2,4} ([0-9]{1,2}[a-z]?)\.", _doc, re.M))
check("§5 every §-reference AGENTS.md makes into DOCUMENTATION.md resolves there",
      not (_doc_refs - _doc_sections), sorted(_doc_refs - _doc_sections))
_agt_refs = set()
for _line in _doc.splitlines():
    if "AGENTS" in _line:
        _agt_refs |= set(re.findall(r"§\s?([0-9]{1,2}\.[0-9]+)", _line))
_agt_sections = set(re.findall(r"^### (4\.[0-9]+)", _agt_text, re.M))
check("§5 every §-reference DOCUMENTATION.md makes into AGENTS.md resolves there",
      not (_agt_refs - _agt_sections), sorted(_agt_refs - _agt_sections))

# No block is copied between the two files (or repeated inside one) — a fact that moves must be
# DELETED from its old home, and a copied block is the shape the drift takes.
_DUP_MIN_LINES, _DUP_MIN_CHARS = 4, 200


def _paragraphs(text):
    out = []
    for _para in re.split(r"\n\s*\n", text):
        _lines = [l.strip() for l in _para.splitlines() if l.strip()]
        if len(_lines) < _DUP_MIN_LINES or len(" ".join(_lines)) < _DUP_MIN_CHARS:
            continue
        out.append((re.sub(r"\s+", " ", " ".join(_lines)).strip(), _lines[0][:60]))
    return out


_paras = {n: _paragraphs(_rules_free[n]) for n in REFERENCE_DOCS}
_shared = collections.Counter(k for k, _ in _paras["AGENTS.md"]) & \
          collections.Counter(k for k, _ in _paras["DOCUMENTATION.md"])
check("§5 no block is copied between AGENTS.md and DOCUMENTATION.md",
      not _shared, [k[:70] for k in list(_shared)[:2]])
for _name in REFERENCE_DOCS:
    _counted = collections.Counter(k for k, _ in _paras[_name])
    _dup = [k for k, n in _counted.items() if n > 1]
    check(f"§5 {_name} has no block duplicated inside itself", not _dup,
          [k[:70] for k in _dup[:2]])

finish()
