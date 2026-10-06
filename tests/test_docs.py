# -*- coding: utf-8 -*-
"""The documentation-consistency guards (the changelog family, ROADMAP, the counters, INDEX freshness, the code-comment budget).

§1 the section ownership of the changelog family and `ROADMAP.md` (the migration pin of the
family's pairing rule included); §2 the counters the reference
docs quote are the code's counters (the i18n key pin, the action registry in every spelling and
its empty-default count); §3 `DOCUMENTATION.md` is self-consistent (every `§N` resolves, a dotted
`§N.M` names `AGENTS.md`, the contents list is complete, the gotcha numbering is shared with §7);
§4 `tests/INDEX.md` freshness, §5 the documentation rules over the two reference docs (and the
repository's own closed world: an ignored `*.md` is untracked), §6 the CODE
ratchet and §7 the byte budget of `AGENTS.md` (the harness TRUNCATES it) are the rest — a missing
documentation set is a SKIP, never a defect (they are gitignored, so a fresh clone stays runnable).
Run: python tests/test_docs.py   (from the project root) or python tests/run_all.py"""
import collections
import glob
import os
import re
import subprocess
import sys

from _common import bootstrap, check, finish, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS
import _comment_budget as CB  # the ONE owner of the history markers + the code-comment ratchet (§6)
import _docs_budget as DB     # the byte budget of AGENTS.md — the harness truncates it (§7)

ROOT, WORK = bootstrap()  # HOME isolation + offscreen + sys.path (BEFORE any app import)


def _read(path):
    """The text of one documentation file (the guards below read several of them)."""
    with open(path, encoding="utf-8") as f:
        return f.read()


REFERENCE_DOCS = ("DOCUMENTATION.md", "AGENTS.md")
_DOC = os.path.join(ROOT, "DOCUMENTATION.md")
_AGENTS = os.path.join(ROOT, "AGENTS.md")
_ROADMAP = os.path.join(ROOT, "ROADMAP.md")
_LIVE_CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
_HISTORY = sorted(glob.glob(os.path.join(ROOT, "CHANGELOG_HISTORY_*.md")))
# The DETAILS family (the released mechanism/decisions/measurements the reference docs no longer
# carry): `CHANGELOG_DETAILS.md` is the LIVE line and `CHANGELOG_DETAILS_V<digits>.md` a closed one,
# paired with `CHANGELOG_HISTORY_V<digits>.md` by the SAME rule — `<digits>` = the last version of the
# line, dots dropped. It is deliberately NOT part of REFERENCE_DOCS (§2/§5: it IS the release
# narrative, so the marker scan must never see it).
_DETAILS = sorted(glob.glob(os.path.join(ROOT, "CHANGELOG_DETAILS*.md")))
_LIVE_DETAILS = os.path.join(ROOT, "CHANGELOG_DETAILS.md")

# The rules block of each reference doc STATES the forbidden vocabulary and NAMES the files a doc may
# point at — it is a DEFINITION, not a claim, so the scans that would otherwise read it (the §5 history
# markers below and the §5 stub-pointer check) run over the document WITHOUT it. Its existence is
# asserted by §5, so the exclusion can never silently swallow a whole file.
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

_missing = [p for p in (_DOC, _AGENTS, _ROADMAP, _LIVE_CHANGELOG) if not os.path.exists(p)]
if not _HISTORY:
    _missing.append(os.path.join(ROOT, "CHANGELOG_HISTORY_*.md"))
if _DETAILS and not os.path.exists(_LIVE_DETAILS):
    # The gate is STAGED: the moment the family exists, the live file must exist too (the details of
    # the OPEN line are edited in place, exactly like `CHANGELOG.md`).
    _missing.append(_LIVE_DETAILS)
if _missing:
    print("  SKIP  the local documentation set is not present: "
          + ", ".join(os.path.basename(p) for p in _missing))
    print("        (DOCUMENTATION.md / AGENTS.md / CHANGELOG*.md / ROADMAP.md are gitignored "
          "local files — a fresh clone has none of them)")
    CB.report(check)  # §6 guards the CODE, not a document: it runs on this path too
    finish()          # 0 checks, 0 failures: a SKIP is not a defect
    sys.exit(0)


def _flat(path):
    """The text with the line breaks folded (the docs wrap at ~100 columns, so a phrase-level
    regex must see the paragraphs, not the wrapping — "24 with an\\nEMPTY default")."""
    return re.sub(r"\s+", " ", _read(path))


def _section_versions(path):
    """The release versions the file declares as `## vX.Y… — <title>` headings."""
    return _RELEASE_HEADING.findall(_read(path))


def _line_digits(name):
    """The `<digits>` of a `CHANGELOG_<KIND>_V<digits>.md` name (the last version, dots dropped)."""
    m = re.fullmatch(r"CHANGELOG_(?:HISTORY|DETAILS)_V(\d+)\.md", os.path.basename(name))
    return m.group(1) if m else None


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

# The DETAILS family is scanned with the SAME release-heading regex, and the rule is the one that
# matters at a rollover: a version that has a `## vX.Y` section in the details may be in EXACTLY ONE
# details file. A closed line's details left inside the live file (or copied into the closed one
# without being deleted from the live one) is the same mistake §1 catches in the changelog family.
_family_details = {os.path.basename(p): _section_versions(p) for p in _DETAILS}
_by_version_details = collections.defaultdict(set)
for _file, _versions in _family_details.items():
    for _v in _versions:
        _by_version_details[_v.lower()].add(_file)

check(f"§1 the changelog family carries the shipped release (v{EXPECTED_APP_VERSION})",
      f"v{EXPECTED_APP_VERSION}".lower() in _by_version,
      f"{len(_family)} file(s), {len(_by_version)} release section(s)")
check("§1 no release section is duplicated inside one file",
      all(len(v) == len(set(v)) for v in list(_family.values()) + list(_family_details.values())),
      [n for n, v in {**_family, **_family_details}.items() if len(v) != len(set(v))])
check("§1 no release section is duplicated across two files (the close-a-line mistake)",
      all(len(files) == 1 for files in _by_version.values()),
      {v: sorted(f) for v, f in _by_version.items() if len(f) > 1})
check("§1 every history file is named for a closed line (CHANGELOG_HISTORY_V<digits>.md)",
      all(re.fullmatch(r"CHANGELOG_HISTORY_V\d+\.md", os.path.basename(p)) for p in _HISTORY),
      [os.path.basename(p) for p in _HISTORY])
check("§1 every details file is named for a line (CHANGELOG_DETAILS.md or "
      "CHANGELOG_DETAILS_V<digits>.md)",
      all(os.path.basename(p) == "CHANGELOG_DETAILS.md" or _line_digits(p) is not None
          for p in _DETAILS),
      [os.path.basename(p) for p in _DETAILS])
# The PAIRING rule runs the direction that can be wrong: every CLOSED details file must have the history
# file of the SAME line beside it (a details file named `_V1711` with no `CHANGELOG_HISTORY_V1711.md` is
# a typo or a half-finished rollover). The other direction is a MIGRATION, not a rule: the reference
# docs are being compressed line by line, so a line may still have its history without its details yet —
# what the rollover has to move in ONE step is checked by the naming rule above and by AGENTS.md §9.
_broken_pairs = sorted({_line_digits(p) for p in _DETAILS if _line_digits(p)} -
                       {_line_digits(p) for p in _HISTORY if _line_digits(p)})
check("§1 every CLOSED details file has the history file of its line beside it",
      not _broken_pairs,
      f"details without their history: {_broken_pairs}")
_still_to_move = sorted({_line_digits(p) for p in _HISTORY if _line_digits(p)} -
                        {_line_digits(p) for p in _DETAILS if _line_digits(p)})
if _still_to_move:
    print(f"  note  lines whose details are still to be created: {_still_to_move} "
          f"(the migration of the reference docs is staged)")

# The MISSING direction of the pairing rule (AUDIT R8): the check above catches a details file whose
# history is absent, while a line that arrives WITHOUT its details passed in silence — which is
# exactly the half of the rollover nobody looks at for a year. The lines the details family never
# reached are a PINNED debt: the set is the measured one and it may only SHRINK, so a new line
# (whose digits are not in it) MUST bring its pair, and a migrated line must lower the pin.
_DETAILS_MIGRATION_LINES = {"0997", "114", "1214", "1338", "147"}
check("§1 the lines whose details are still to be created are the PINNED migration set (R8)",
      _still_to_move == sorted(_DETAILS_MIGRATION_LINES),
      f"unpaired={_still_to_move} pinned={sorted(_DETAILS_MIGRATION_LINES)} — a NEW line must bring "
      f"CHANGELOG_DETAILS_V<digits>.md in the same rollover; a migrated line must LOWER the pin")
check("§1 every pinned migration line really has its history file (the pin names no phantom)",
      all(os.path.exists(os.path.join(ROOT, f"CHANGELOG_HISTORY_V{d}.md"))
          for d in _DETAILS_MIGRATION_LINES),
      [d for d in sorted(_DETAILS_MIGRATION_LINES)
       if not os.path.exists(os.path.join(ROOT, f"CHANGELOG_HISTORY_V{d}.md"))])
check("§1 a release section of the DETAILS family is not duplicated across two files "
      "(the details of a closed line leave the live file)",
      all(len(files) == 1 for files in _by_version_details.values()),
      {v: sorted(f) for v, f in _by_version_details.items() if len(f) > 1})

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

# The same rule for the two figures a document writes as a LITERAL (`EXPECTED_I18N_KEYS = 870`,
# `APP_VERSION = "1.7.1.1"`): the regex above cannot see them, and a stale literal is exactly how the
# shipped pin survived a whole line beside a wrong number.
_PIN_LITERAL = re.compile(r"EXPECTED_I18N_KEYS\s*=\s*(\d+)")
_VERSION_LITERAL = re.compile(r'APP_VERSION\s*=\s*"([0-9][0-9A-Za-z.]*)"')
for _name in REFERENCE_DOCS:
    _doc_text = _read(os.path.join(ROOT, _name))
    _pins = sorted({int(m.group(1)) for m in _PIN_LITERAL.finditer(_doc_text)})
    _vers = sorted({m.group(1) for m in _VERSION_LITERAL.finditer(_doc_text)})
    check(f"§2 {_name}: a literal `EXPECTED_I18N_KEYS = N` is the shipped pin ({EXPECTED_I18N_KEYS})",
          all(v == EXPECTED_I18N_KEYS for v in _pins), f"quoted={_pins}")
    check(f"§2 {_name}: a literal `APP_VERSION = \"X\"` is the shipped version "
          f"({EXPECTED_APP_VERSION})", all(v == EXPECTED_APP_VERSION for v in _vers), f"quoted={_vers}")

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

# The TEST-FILE counter in every spelling these docs use. `tests/test_i18n_live.py` §6 owns the PUBLIC
# form ("123 test files" in the README, via the shared `TEST_FILE_COUNTER_RE`); the reference docs write
# it as "123 `test_*.py`", where the backtick before the word made that regex blind — and a quoted 118 /
# 120 / 121 survived a whole line beside a live 123. Hence ONE tolerant pattern here, markdown included.
_TESTFILE_FIGURE = re.compile(r"\b(\d+)\s+(?:topical\s+)?\**`?\**test[ _-]?(?:files?|\*\.py)`?\**")
_N_TEST_FILES = len(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
for _name in REFERENCE_DOCS + ("ROADMAP.md",):
    _tests_text = _flat(os.path.join(ROOT, _name))
    _quoted_tests = sorted({int(m.group(1)) for m in _TESTFILE_FIGURE.finditer(_tests_text)})
    _stale_tests = _stale_figures(_tests_text, _TESTFILE_FIGURE, _N_TEST_FILES)
    check(f"§2 {_name}: every test-file figure is the live one ({_N_TEST_FILES}) or a chain successor",
          not _stale_tests, f"quoted={_quoted_tests} stale={_stale_tests}")

# The SIZE figures of the PLAN (AUDIT N62): `ROADMAP.md` sizes its waves with quoted measurements and
# nothing read them back (the file the `1.8` line is about was quoted at 3 454 lines while it held 5 284).
# Rule 7 applied to a FILE size: every `**N lines / K KB**`, `**N / K KB**` and `(N lines)` of the plan is
# read against the file it NAMES — the nearest backticked `.py` path before it. A CLASS figure
# (`MainWindow` at 169 methods, `_SftpPane` alone) is deliberately NOT read: it has no resolvable owner.
_SIZE_FIGURE = re.compile(r"\*\*(\d[\d\u2009\u00a0 ]*)\s*(?:lines\s*)?/\s*([\d.]+)\s*KB\*\*")
_SIZE_PAREN = re.compile(r"\((\d[\d\u2009\u00a0 ]*)\s+lines\)")
_SIZE_TOTAL = re.compile(r"\*\*(\d[\d\u2009\u00a0 ]*)\*\*\s+lines of\s+Python")
_PATH_BEFORE = re.compile(r"`([A-Za-z_][\w./-]*\.py)`")


def _size_int(text):
    """The digits of a figure written with thin or normal spaces as thousands separators ("5 462")."""
    return int(re.sub(r"\D", "", text))


def _measured_size(rel):
    """(lines, KB) of a repository-relative `.py` file — None when this tree does not hold it."""
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return len(text.splitlines()), round(os.path.getsize(path) / 1024, 1)


_roadmap_text = _read(_ROADMAP)
_size_problems = []
_size_read = 0
for _m in _SIZE_FIGURE.finditer(_roadmap_text):
    _paths = _PATH_BEFORE.findall(_roadmap_text[:_m.start()])
    _real = _measured_size(_paths[-1]) if _paths else None
    if _real is None:
        continue  # a figure about a file this tree does not hold (a planned module)
    _size_read += 1
    _quoted = (_size_int(_m.group(1)), float(_m.group(2)))
    if _quoted != _real:
        _size_problems.append(f"`{_paths[-1]}`: plan {_quoted[0]} lines / {_quoted[1]} KB, "
                              f"measured {_real[0]} / {_real[1]}")
for _m in _SIZE_PAREN.finditer(_roadmap_text):
    _paths = _PATH_BEFORE.findall(_roadmap_text[:_m.start()])
    _real = _measured_size(_paths[-1]) if _paths else None
    if _real is None:
        continue
    _size_read += 1
    if _size_int(_m.group(1)) != _real[0]:
        _size_problems.append(f"`{_paths[-1]}`: plan {_size_int(_m.group(1))} lines, measured {_real[0]}")
check("§2 ROADMAP.md sizes its files with REAL figures (a guard over nothing is useless)",
      # A plan with NO version section left (every planned version shipped) has no size to quote; the
      # moment a `## vN` section exists it must size its files, so the reader cannot go blind unseen.
      _size_read >= 5 or (_size_read == 0 and not re.search(r"^## v\d", _roadmap_text, re.M)),
      f"figures read={_size_read}")
check("§2 every file size quoted by the plan is the measurement today (AUDIT N62)",
      not _size_problems, _size_problems)
_size_total = 0
for _base, _dirs, _files in os.walk(ROOT):
    _dirs[:] = [d for d in _dirs if d not in {"__pycache__", ".git", "tests", "third_party",
                                             "_tmp_testdata", "test-results", "docs", "examples"}]
    for _fname in _files:
        if _fname.endswith(".py"):
            with open(os.path.join(_base, _fname), encoding="utf-8", errors="replace") as _fh:
                _size_total += len(_fh.read().splitlines())
_quoted_total = [_size_int(m.group(1)) for m in _SIZE_TOTAL.finditer(_roadmap_text)]
check(f"§2 the plan's application total is the measurement ({_size_total} lines of *.py outside "
      f"tests/ and third_party/)", _quoted_total == [_size_total], f"quoted={_quoted_total}")


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

check("§5 both reference docs still carry their rules block (the scans below exclude it)",
      all(_rules_free.values()), [n for n in REFERENCE_DOCS if not _rules_free[n]])
_rules_free = {n: (_rules_free[n] if _rules_free[n] is not None else _read(os.path.join(ROOT, n)))
               for n in REFERENCE_DOCS}

# The release narrative the changelog family owns. The LIST lives in `tests/_comment_budget.py` —
# ONE owner, because §6 below scans the CODE with exactly the same markers ("what a document may not
# say, a comment may not say either"), and a marker added in two places would drift.
_HISTORY_MARKERS = CB.HISTORY_MARKERS
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
    _order = [int(n) for n in re.findall(r"^## ([0-9]{1,2})\.", _text, re.M)]
    if _name == DB.DOC:
        # The chapter ORDER is the PRIORITY: the harness reads the file until its byte budget runs out,
        # so the operational contract is written first and the reference chapters last. The order is
        # DECLARED in one place (`tests/_docs_budget.py`) and audited here — a botched move fails.
        check(f"§5 {_name}: the chapter numbers are UNIQUE and in the DECLARED reading order",
              len(_order) == len(set(_order)) and _order == list(DB.CHAPTER_ORDER),
              f"{_order} != {list(DB.CHAPTER_ORDER)}")
    else:
        check(f"§5 {_name}: the chapter numbers are UNIQUE",
              len(_order) == len(set(_order)), f"{_order}")
    _sub = re.findall(r"^### (4\.[0-9]+) ", _text, re.M)
    check(f"§5 {_name}: every §4.x heading appears exactly once",
          len(_sub) == len(set(_sub)), f"{sorted({n for n in _sub if _sub.count(n) > 1})}")
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


# ── The DETAILS family and the STUB contract ─────────────────────────────────────────────────
# A section whose body moved away keeps a pointer to the file that now owns the detail, and that
# pointer is audited here: the reference docs are the ENTRY POINT of the family, so a pointer at a file
# that does not exist is a dead end. `CHANGELOG_DETAILS*.md` may be a GLOB (the map of §2 uses one for
# the whole family); the scan skips the rules block, which DEFINES the names rather than pointing.
_DETAILS_REF = re.compile(r"CHANGELOG_DETAILS(?:_V\d+|\*)?\.md")


def _details_pointers(name):
    """Every `CHANGELOG_DETAILS*.md` pointer of a reference doc, its rules block aside."""
    scanned = _without_rules(name, _read(os.path.join(ROOT, name)))
    if scanned is None:
        scanned = _read(os.path.join(ROOT, name))
    return [m.group(0) for m in _DETAILS_REF.finditer(scanned)]


# The scan runs over the docs WITHOUT their rules block: the block that STATES the family (and names
# its live file as the thing an author writes) is a DEFINITION, not a pointer — the same exclusion §5
# itself makes for the marker scan. A GLOB pointer is checked against the family that really exists.
for _name in REFERENCE_DOCS:
    _broken = sorted({p for p in _details_pointers(_name)
                      if not (glob.glob(os.path.join(ROOT, p)) if "*" in p
                              else os.path.exists(os.path.join(ROOT, p)))})
    check(f"§5 {_name}: every CHANGELOG_DETAILS file it points a reader at EXISTS (a stub names its "
          f"details)", not _broken or not _DETAILS, _broken)
check("§5 the live details file is named by a reference doc "
      "(otherwise the family has no entry point for an agent)",
      not os.path.exists(_LIVE_DETAILS)
      or os.path.basename(_LIVE_DETAILS) in [p for _n in REFERENCE_DOCS
                                             for p in _details_pointers(_n)],
      f"{os.path.basename(_LIVE_DETAILS)} exists but no reference doc names it")

# The same "one fact, one home" rule as above, applied to the family that has just been created
# outside the pair: a paragraph that was MOVED into the details and left behind in the reference doc
# is the drift the move exists to remove. `CHANGELOG_HISTORY_V*.md` predates the rule and is not
# scanned (its overlap with the old docs is pinned by the changelog family's own history).
_details_paras = collections.Counter(k for _p in _DETAILS for k, _ in _paragraphs(_read(_p)))
_shared_details = {_n: [k for k in _details_paras if k in dict(_paras[_n])]
                   for _n in REFERENCE_DOCS}
check("§5 no block is copied between the details family and the reference docs "
      "(a moved paragraph is DELETED from its old home)",
      not any(_shared_details.values()),
      {_n: v[:1] for _n, v in _shared_details.items() if v})


# ── the repository's own closed world (AUDIT N60) ────────────────────────────
# `.gitignore` is the project's ANSWER to §13's question "is this internal document public?" — it
# names every internal `*.md`. A file that is ignored AND tracked makes that answer WRONG for every
# other name in the list, so the two states must agree: a `*.md` the ignore list names is untracked.
# Git is asked ONCE and its absence (or a tree that is not a repository) is a clean skip.
_GITIGNORE = os.path.join(ROOT, ".gitignore")
_GITIGNORED_MD = re.compile(r"^\s*([A-Za-z0-9_.*/-]+\.md)\s*$", re.M)


def _git(args):
    """(exit code, stdout) of one git call; (None, "") when git is missing or unusable."""
    try:
        done = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    if done.returncode != 0:
        return None, done.stdout or ""
    return done.returncode, done.stdout or ""


if os.path.exists(_GITIGNORE):
    _ignored_md = sorted(set(_GITIGNORED_MD.findall(_read(_GITIGNORE))))
    _code, _tracked_out = _git(["ls-files"])
    if _code is None:
        print("  note  git is unavailable (or this tree is not a repository) — "
              "the tracked/ignored cross-check is skipped")
    else:
        _tracked = {line.strip().replace("\\", "/") for line in _tracked_out.splitlines()
                    if line.strip()}
        _published = sorted(name for name in _ignored_md if name in _tracked)
        check("§5 every *.md named by .gitignore is UNTRACKED (an internal document stays internal)",
              not _published,
              f"ignored yet TRACKED (untrack with: git rm --cached <path>): {_published}")
        check("§5 the closed world really has names to check (a guard over nothing is useless)",
              len(_ignored_md) >= 5, f"patterns={_ignored_md}")


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the code-comment budget (a ratchet — the pins live in _comment_budget.py) ==")
# ════════════════════════════════════════════════════════════════════════════

# §6 applies the §5 rule to the text INSIDE the code: a release narrative belongs to the changelog
# family, the mechanism to DOCUMENTATION.md, a rule and a name to AGENTS.md (§12 states the budget).
# The debt that shipped before the rule existed is PINNED in `tests/_comment_budget.py` and the pins
# may only go DOWN — cleaning a file is the only way to move them. Measure: `python tests/_comment_budget.py`.
CB.report(check)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the byte budget of AGENTS.md (a ratchet — the pins live in _docs_budget.py) ==")
# ════════════════════════════════════════════════════════════════════════════

# A consistent file may still be USELESS: the harness reads an instruction file under a byte budget
# and truncates what does not fit, so the positions are pinned and they only go DOWN.
DB.report(check)

finish()
