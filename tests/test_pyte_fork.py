# -*- coding: utf-8 -*-
"""v1.3rc1 — Terminal: the managed pyte fork (vendored 0.8.2 + patch manifest).
v1.5.7.1 — the dependency audit's five patches (0005–0009) join the manifest and its smoke.

(ROADMAP v1.3rc1, the PYTE82_AUDIT.md "The application: the 'controlled fork' variant" +
the section "The decision"; v1.5.7.1 — its raise-review section.)

The test of the provenance of the fork in third_party/pyte/. Zero behavioral conversion —
the existing terminal tests (test_pyte_compat / test_alt_screen / …) are green
unchanged; this file adds the PROVENANCE CHECKS on top of them:

  * the sha256 of every file of third_party/pyte/ == the tables of MANIFEST.md (two tables:
    the pristine files == the upstream PyPI sdist 0.8.2; the post-patch — the expected hashes
    after the patches 0001–0010); the drift "and forgot what was changed" is caught here;
    the two patched files are screens.py (0001–0005, 0007–0009) and streams.py (0006, 0010);
  * the manifest of the patches: the files are in place, the names by the convention NNNN-slug.patch, the headers
    with the provenance (the upstream issue/PR, the audit report, the date) and the attribution (0003 — the
    author of PR #212, dwgx; the code of pyte is LGPL-3.0 — the attribution is mandatory); the patch files
    are UTF-8 (a cp1251-piped `git diff` produces mojibake in their non-ASCII comments);
  * the behavioral smoke of the fork itself (headless, without Qt): the private SGR does not crash;
    a private CSI with a NON-mode final byte (`\\x1b[?r` — XTRESTORE, sent by ncurses/mc on exit —
    and the private DSR) is ignored while the public DECSTBM keeps working (patch 0004) +
    the tail of the chunk is preserved (b'AB\\x1b[?4mCD\\r\\n' → "ABCD"); the LNM is the default
    (b'ab\\ncd' → ["ab", "cd"], after the explicit \\x1b[20l — the shift x=2); the alt-screen
    round-trip (\\x1b[?1049h…\\x1b[?1049l → the grid is equal to before the enter
    character by character, including the fg/bg); and one probe per defect of v1.5.7.1 (§3.5–§3.9):
    a grapheme cluster lands whole (the tail is not dropped), no final of the CSI table raises on a
    malformed sequence, an unknown erase mode is a no-op, DECOM without a region neither raises nor
    goes silent, a resize keeps the cursor — and the following text — inside the screen, and the G0/G1
    designation of the VT100 special graphics really reaches the grid (patch 0010).

Run: python tests/test_pyte_fork.py   (from the project root) or python tests/run_all.py
"""
import hashlib
import os
import re

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from third_party import pyte          # v1.3rc1: the fork itself — the provenance of this test
import modules.terminal_screen as TS  # the seam: the production code must use the same fork

TPYTE = os.path.join(ROOT, "third_party", "pyte")
PATCHDIR = os.path.join(ROOT, "third_party", "pyte-patches")
MANIFEST = os.path.join(PATCHDIR, "MANIFEST.md")

EXPECTED_PATCHES = (
    "0001-private-sgr-ignore.patch",
    "0002-lnm-default.patch",
    "0003-alt-screen-47-1047-1048-1049.patch",
    "0004-private-csi-ignore.patch",
    "0005-grapheme-clusters.patch",
    "0006-tolerant-csi-dispatch.patch",
    "0007-erase-unknown-mode-noop.patch",
    "0008-decom-guard.patch",
    "0009-resize-cursor-clamp.patch",
    "0010-honour-charset-designation.patch",
)
SDIST_SHA256 = "5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f"  # PyPI pyte-0.8.2.tar.gz


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_manifest_tables(text):
    """The two sha256 tables of MANIFEST.md → (pristine, post-patch): {name: hash}."""
    tables = []
    current = None
    for line in text.splitlines():
        if line.startswith("## sha256"):
            current = {}
            tables.append(current)
        elif current is not None and line.startswith("## "):
            current = None
        elif current is not None:
            m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([0-9a-f]{64})\s*\|$", line)
            if m:
                current[m.group(1)] = m.group(2)
    assert len(tables) == 2, "MANIFEST.md should contain exactly two sha256 tables"
    return tables[0], tables[1]


# ════════════════════════════════════════════════════════════
# 1. sha256 of the third_party/pyte/ tree == the MANIFEST.md table
# ════════════════════════════════════════════════════════════
print("== manifest: sha256 of third_party/pyte ==")

check("MANIFEST.md exists", os.path.isfile(MANIFEST), "third_party/pyte-patches/MANIFEST.md")
manifest_text = ""
if os.path.isfile(MANIFEST):
    with open(MANIFEST, encoding="utf-8") as f:
        manifest_text = f.read()

check("MANIFEST: the PyPI sdist sha256 is pinned (5af970e8…f083f)",
      SDIST_SHA256 in manifest_text)

pristine_tbl, postpatch_tbl = ({}, {})
if manifest_text:
    try:
        pristine_tbl, postpatch_tbl = parse_manifest_tables(manifest_text)
        check("MANIFEST: both sha256 tables parsed (11 files each)",
              len(pristine_tbl) == 11 and len(postpatch_tbl) == 11,
              f"pristine={len(pristine_tbl)}, post-patch={len(postpatch_tbl)}")
    except Exception as e:  # noqa: BLE001
        check("MANIFEST: both sha256 tables parsed (11 files each)", False, repr(e))

actual_files = sorted(
    n for n in os.listdir(TPYTE) if os.path.isfile(os.path.join(TPYTE, n)))
check("the third_party/pyte/ tree: the files == the set of the MANIFEST tables",
      actual_files == sorted(pristine_tbl) == sorted(postpatch_tbl),
      f"tree={actual_files}")

hash_ok = True
detail = ""
for name in actual_files:
    real = sha256_file(os.path.join(TPYTE, name))
    want = postpatch_tbl.get(name)
    if want is None or real != want:
        hash_ok = False
        detail = f"{name}: real={real[:12]}… want={str(want)[:12]}…"
        break
check("the sha256 of every third_party/pyte/ file == the post-patch table", hash_ok, detail)

# The unpatched files are identical in both tables; patches 0001–0010 touch TWO files:
# screens.py (0001–0005, 0007–0009) and streams.py (0006, 0010).
untouched = [n for n in actual_files if pristine_tbl.get(n) == postpatch_tbl.get(n)]
changed = [n for n in actual_files if pristine_tbl.get(n) != postpatch_tbl.get(n)]
check("the unpatched files: the same hash in both tables (9 of 11)",
      len(untouched) == 9 and len(changed) == 2, f"untouched={len(untouched)}, changed={changed}")
check("the patched files are screens.py and streams.py", changed == ["screens.py", "streams.py"],
      str(changed))

# The seam: the production code uses THE SAME fork (not the stock pyte from site-packages).
check("the seam: modules.terminal_screen imports third_party/pyte (the same module)",
      TS.pyte is pyte, f"TS.pyte={getattr(TS.pyte, '__file__', '?')}")


# ════════════════════════════════════════════════════════════
# 2. The patch manifest: the naming convention + headers with provenance/attribution
# ════════════════════════════════════════════════════════════
print("== patch manifest ==")

actual_patches = sorted(
    n for n in os.listdir(PATCHDIR) if n.endswith(".patch"))
check("patches 0001–0010 are in place, no extras", actual_patches == list(EXPECTED_PATCHES),
      str(actual_patches))
check("the names follow the NNNN-slug.patch convention",
      all(re.fullmatch(r"\d{4}-[a-z0-9][a-z0-9-]*\.patch", n) for n in actual_patches),
      str(actual_patches))

HEADER_FIELDS = ("Subject:", "Provenance:", "Base:", "Policy:", "Applied:")
# (patch, the file its diff must touch, the provenance tokens the header must carry).
# 0003's author attribution is mandatory (LGPL); 0005–0009 name the audit report they come from,
# so a future rebase can find the upstream discussion again.
PATCH_PROVENANCE = (
    (EXPECTED_PATCHES[0], "pyte/screens.py", ("PR #203",)),
    (EXPECTED_PATCHES[1], "pyte/screens.py", ("LNM",)),
    (EXPECTED_PATCHES[2], "pyte/screens.py", ("PR #212", "dwgx")),   # the attribution — mandatory (LGPL)
    (EXPECTED_PATCHES[3], "pyte/screens.py", ("CSI ? r", "XTRESTORE")),
    (EXPECTED_PATCHES[4], "pyte/screens.py", ("0.8.3.dev", "grapheme")),
    (EXPECTED_PATCHES[5], "pyte/streams.py", ("BUG-A", "surplus")),
    (EXPECTED_PATCHES[6], "pyte/screens.py", ("BUG-C",)),
    (EXPECTED_PATCHES[7], "pyte/screens.py", ("BUG-D",)),
    (EXPECTED_PATCHES[8], "pyte/screens.py", ("BUG-E",)),
    (EXPECTED_PATCHES[9], "pyte/streams.py", ("use_utf8", "ACS")),
)
check("every patch is covered by the provenance table (a new patch cannot skip it)",
      [n for n, _, _ in PATCH_PROVENANCE] == list(EXPECTED_PATCHES),
      str([n for n, _, _ in PATCH_PROVENANCE]))
for name, target, must_contain in PATCH_PROVENANCE:
    path = os.path.join(PATCHDIR, name)
    if not os.path.isfile(path):
        check(f"{name}: the header with the provenance and the diff body", False, "the file is not found")
        continue
    with open(path, encoding="utf-8") as f:
        text = f.read()
    head_ok = all(field in text for field in HEADER_FIELDS)
    attr_ok = all(tok in text for tok in must_contain)
    diff_ok = f"diff --git a/{target} b/{target}" in text
    check(f"{name}: the header (Subject/Provenance/Base/Policy/Applied) + the provenance "
          f"({', '.join(must_contain)}) + unified diff of {target}", head_ok and attr_ok and diff_ok,
          f"head={head_ok}, provenance={attr_ok}, diff={diff_ok}")

# A patch header that carries a mojibake em dash is what a cp1251-piped `git diff` produces — the
# patches are UTF-8, and so is every reader of them.
_patch_encoding_ok = True
for _name in EXPECTED_PATCHES:
    with open(os.path.join(PATCHDIR, _name), encoding="utf-8") as _f:
        _text = _f.read()
    if "\ufffd" in _text or "\u0402" in _text or "\u0403" in _text:
        _patch_encoding_ok = False
        break
check("every patch file is valid UTF-8 (no cp1251 mojibake in the non-ASCII comments)",
      _patch_encoding_ok, _name)


# ════════════════════════════════════════════════════════════
# 3. A behavioural smoke of the fork (headless, no Qt)
# ════════════════════════════════════════════════════════════
print("== fork behavioral smoke ==")


def lines(scr):
    """screen.display → the lines without the trailing spaces."""
    return [line.rstrip() for line in scr.display]


# 3.1 Private SGR (patch 0001): no crash + the chunk tail is preserved.
sgr = pyte.HistoryScreen(40, 5)
exc = ""
try:
    pyte.ByteStream(sgr).feed(b"AB\x1b[?4mCD\r\n")   # Vim 9+ (upstream issue #202)
except Exception as e:  # noqa: BLE001
    exc = repr(e)
check("private SGR: b'AB\\x1b[?4mCD\\r\\n' — no exceptions", exc == "", exc)
check("private SGR: the chunk tail is preserved → the line \"ABCD\"", lines(sgr)[0] == "ABCD",
      repr(lines(sgr)[0]))

# 3.2 LNM default (patch 0002): a bare LF = CR+LF; an explicit \\x1b[2l — an offset.
lnm = pyte.HistoryScreen(40, 5)
pyte.ByteStream(lnm).feed(b"ab\ncd")
check("LNM default: b'ab\\ncd' → [\"ab\", \"cd\"]", lines(lnm)[:2] == ["ab", "cd"],
      repr(lines(lnm)[:2]))
# An explicit LNM disable by the remote program — RM 20 (\\x1b[20l): the \\x1b[2l from the plan
# ROADMAP — a known typo (that is IRM, mode 2) — pinned in test_pyte_compat.py.
lnm_off = pyte.HistoryScreen(40, 5)
pyte.ByteStream(lnm_off).feed(b"\x1b[20lab\ncd")
check("LNM: after \\x1b[20l a bare LF without CR — \"cd\" at offset x=2",
      lines(lnm_off)[:2] == ["ab", "  cd"], repr(lines(lnm_off)[:2]))

# 3.3 Alt-screen round-trip (patch 0003, the PR #212/dwgx semantics): character by character.
SHELL = (b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ls\r\n"
         b"\x1b[0;34mdocs\x1b[0m  \x1b[93mnotes.txt\x1b[0m  \x1b[38;5;196mall.xml\x1b[0m\r\n")
alt = pyte.HistoryScreen(80, 24)
stream = pyte.ByteStream(alt)
stream.feed(SHELL)
grid0 = [[alt.buffer[y][x] for x in range(80)] for y in range(24)]
cur0 = (alt.cursor.x, alt.cursor.y)
check("alt: the fork's constant Screen.ALTSCREEN_MODES = (47, 1047, 1048, 1049)",
      pyte.HistoryScreen.ALTSCREEN_MODES == (47, 1047, 1048, 1049),
      str(pyte.HistoryScreen.ALTSCREEN_MODES))
stream.feed(b"\x1b[?1049h\x1b[2J\x1b[H" + b"TUI frame (alt screen)\r\n")
check("alt: \\x1b[?1049h → in_alt True, the grid = the TUI",
      alt.in_alt is True and "TUI frame" in "\n".join(alt.display),
      repr("\n".join(alt.display)[:60]))
stream.feed(b"\x1b[?1049l")
grid1 = [[alt.buffer[y][x] for x in range(80)] for y in range(24)]
check("alt: \\x1b[?1049l → the grid equals G0 character by character (including fg/bg)", grid1 == grid0)
check("alt: the cursor is restored (1049 = 1047+1048)",
      (alt.cursor.x, alt.cursor.y) == cur0, str((alt.cursor.x, alt.cursor.y)))

# 3.4 A PRIVATE CSI whose final byte is NOT a mode (patch 0004). `pyte/streams.py` dispatches
#     every `?`-prefixed CSI as `handler(*params, private=True)`; `CSI ? r` (XTRESTORE — what an
#     ncurses program such as mc sends on exit) lands on the DECSTBM handler and `CSI ? 6 n` on the
#     DSR one. Both raised TypeError out of feed() before the patch, which aborted the whole chunk
#     and left the canvas on the previous frame.
for _seq, _what in ((b"\x1b[?r", "XTRESTORE (mc on exit)"),
                    (b"\x1b[?1r", "XTRESTORE with a parameter"),
                    (b"\x1b[?6n", "the private DSR")):
    _scr = pyte.HistoryScreen(20, 5)
    try:
        pyte.ByteStream(_scr).feed(_seq)
        _exc = ""
    except Exception as _e:  # noqa: BLE001
        _exc = repr(_e)
    check(f"private CSI: {_seq!r} ({_what}) — no exception out of feed()", _exc == "", _exc)
_marg = pyte.HistoryScreen(20, 5)
_marg_stream = pyte.ByteStream(_marg)
_marg_stream.feed(b"\x1b[?r")
check("private CSI: `CSI ? r` is NOT a DECSTBM (the margins stay unset)",
      _marg.margins is None, str(_marg.margins))
_marg_stream.feed(b"\x1b[1;5r")
check("the PUBLIC `CSI 1;5r` still sets the scrolling region (vim/less splits)",
      _marg.margins is not None
      and (_marg.margins.top, _marg.margins.bottom) == (0, 4), str(_marg.margins))

# 3.5 Grapheme clusters (patch 0005). An emoji sequence used to TRUNCATE the chunk in silence:
#     draw() `break`s out of the whole data string on a zero-width code point that is not a
#     combining mark (ZWJ U+200D, VS16 U+FE0F), so everything after it in the same feed() was
#     dropped with no exception and no log line (AUDIT_PENDING.md N26). The fork's cluster rule
#     also attaches the marks whose canonical combining class is 0 (Thai, Devanagari, the keycap's
#     U+20E3) — upstream leaves those as zero-width clusters and still loses the tail on them.
for _text, _what in (("A\u2764\ufe0fB", "a heart + VS16"),
                     ("A\U0001f469\u200d\U0001f469B", "a ZWJ sequence"),
                     ("A1\ufe0f\u20e3B", "a keycap (its U+20E3 is Me — the M-extend rule)"),
                     ("a\u0e01\u0e31b", "a Thai vowel sign (Mn, class 0)"),
                     ("x\u0915\u093ey", "a Devanagari matra (Mc, class 0)")):
    _emoji = pyte.HistoryScreen(20, 3)
    pyte.ByteStream(_emoji).feed(_text.encode("utf-8"))
    check(f"grapheme: {_what} lands whole (the tail is no longer dropped)",
          lines(_emoji)[0] == _text, repr(lines(_emoji)[0]))
_comb = pyte.HistoryScreen(20, 3)
pyte.ByteStream(_comb).feed("A\u0301B".encode("utf-8"))
check("grapheme: a combining mark still merges into the previous cell (NFC) → \"\u00c1B\"",
      lines(_comb)[0] == "\u00c1B", repr(lines(_comb)[0]))
_zwj = pyte.HistoryScreen(20, 3)
pyte.ByteStream(_zwj).feed("a\U0001f469\u200d\U0001f469".encode("utf-8"))
check("grapheme: a ZWJ cluster is ONE wide cell + the data=='' stub (the grid and the canvas agree)",
      _zwj.buffer[0][1].data == "\U0001f469\u200d\U0001f469" and _zwj.buffer[0][2].data == "",
      repr([_zwj.buffer[0][x].data for x in range(4)]))

# 3.6 A malformed CSI is ignored (patch 0006). The parser forwards every collected parameter to
#     the mapped handler, so a surplus parameter or a private marker on a command with no private
#     form raised TypeError out of feed() (AUDIT_PENDING.md N27 — 19 finals per shape).
_finals = sorted(pyte.Stream(pyte.Screen(10, 5)).csi)
_crashes = []
for _final in _finals:
    for _seq in (f"\x1b[?0{_final}", f"\x1b[1;2{_final}"):
        try:
            pyte.Stream(pyte.Screen(10, 5)).feed(_seq)
        except Exception as _e:  # noqa: BLE001
            _crashes.append((_seq, repr(_e)))
check(f"malformed CSI: NO final of the CSI table ({len(_finals)}) raises for either shape",
      not _crashes, str(_crashes[:2]))
_tail = pyte.Screen(10, 5)
pyte.Stream(_tail).feed("\x1b[1;2AA")
check("malformed CSI: the tail of the chunk survives → \"A\"", _tail.display[0].rstrip() == "A",
      repr(_tail.display[0]))

# 3.7 An erase mode the handler does not know is a no-op (patch 0007) — ESC[3K / ESC[4J raised
#     UnboundLocalError out of feed() (AUDIT_PENDING.md N28).
for _seq, _keep in ((b"\x1b[3K", "abc"), (b"\x1b[4J", "abc")):
    _el = pyte.HistoryScreen(10, 3)
    try:
        pyte.ByteStream(_el).feed(b"abc" + _seq)
        _exc = ""
    except Exception as _e:  # noqa: BLE001
        _exc = repr(_e)
    check(f"erase: {_seq!r} is a no-op, not an exception", _exc == "" and lines(_el)[0] == _keep,
          f"{_exc!r} line={lines(_el)[0]!r}")
_el_public = pyte.HistoryScreen(10, 3)
pyte.ByteStream(_el_public).feed(b"abc\x1b[2K")
check("erase: the PUBLIC `ESC[2K` still erases the line", lines(_el_public)[0] == "",
      repr(lines(_el_public)[0]))
_ed_public = pyte.HistoryScreen(10, 3)
pyte.ByteStream(_ed_public).feed(b"abc\x1b[2J")
check("erase: the PUBLIC `ESC[2J` still clears the display", lines(_ed_public)[0] == "",
      repr(lines(_ed_public)[0]))

# 3.8 DECOM without a scrolling region cannot raise (patch 0008): VPA and the DSR report added
#     `self.margins.top` behind a bare `assert` (AUDIT_PENDING.md N29).
for _seq, _what in ((b"\x1b[?6h\x1b[5d", "VPA"), (b"\x1b[?6h\x1b[6n", "DSR")):
    _decom = pyte.HistoryScreen(10, 5)
    try:
        pyte.ByteStream(_decom).feed(_seq)
        _exc = ""
    except Exception as _e:  # noqa: BLE001
        _exc = repr(_e)
    check(f"DECOM, no region: {_what} — no exception out of feed()", _exc == "", _exc)
_answers = []
_dsr = pyte.HistoryScreen(10, 5)
_dsr.write_process_input = _answers.append
pyte.ByteStream(_dsr).feed(b"\x1b[?6h\x1b[1;1H\x1b[6n")
check("DECOM, no region: the DSR really ANSWERS (a program waits for the reply)",
      _answers == ["\x1b[1;1R"], repr(_answers))
_vpa_reg = pyte.HistoryScreen(10, 5)
pyte.ByteStream(_vpa_reg).feed(b"\x1b[2;4r\x1b[?6h\x1b[2d")
check("DECOM WITH a region: the VPA arithmetic is unchanged (line 2 of the region → y=2)",
      _vpa_reg.cursor.y == 2, str(_vpa_reg.cursor.y))

# 3.9 A resize clamps the cursor into the new geometry (patch 0009): the clamp used to run against
#     the OLD bounds (or not at all), so the next draw() wrote an off-screen cell that display()
#     never showed — silent data loss (AUDIT_PENDING.md N30).
_rows = pyte.HistoryScreen(20, 10)
pyte.ByteStream(_rows).feed(b"".join(b"line %d\r\n" % n for n in range(8)))
_rows.resize(lines=3, columns=20)
check("resize: the cursor is inside the shrunk screen", _rows.cursor.y < 3, str(_rows.cursor.y))
pyte.ByteStream(_rows).feed(b"VISIBLE")
check("resize: the first text after a row shrink is VISIBLE",
      "VISIBLE" in "\n".join(_rows.display), repr(_rows.display[:3]))
_cols = pyte.HistoryScreen(20, 3)
pyte.ByteStream(_cols).feed(b"x" * 15)
_cols.resize(lines=3, columns=4)
check("resize: the cursor x is inside the shrunk width", _cols.cursor.x < 4, str(_cols.cursor.x))
pyte.ByteStream(_cols).feed(b"Z")
check("resize: the text after a width shrink is VISIBLE",
      "Z" in "\n".join(_cols.display), repr(_cols.display[:1]))

# 3.10 The G0/G1 designation is honoured in UTF-8 mode (patch 0010). A program that draws its frame
#      with the VT100 special graphics designates the map and then sends the ASCII LETTERS of the
#      frame — the terminal must translate them (xterm paints `q` as a horizontal line). Before the
#      patch the `if self.use_utf8: continue` guard skipped the designation, so every ACS frame
#      arrived as its letters (the colleagues' `mc` report; AUDIT_PENDING.md N34).
_acs = pyte.HistoryScreen(20, 3)
_acs_stream = pyte.ByteStream(_acs)
_acs_stream.feed(b"\x1b(0q")
check("charset: `ESC ( 0` + `q` → the box drawing `\u2500` (the VT100 special graphics)",
      lines(_acs)[0] == "\u2500", repr(lines(_acs)[0]))
check("charset: the CELL holds the box character, not the designated letter",
      _acs.buffer[0][0].data == "\u2500", repr(_acs.buffer[0][0].data))
_acs_stream.feed(b"\x1b(Bq")
check("charset: `ESC ( B` puts the identity map back → a literal `q`",
      lines(_acs)[0] == "\u2500q", repr(lines(_acs)[0]))
_acs_g1 = pyte.HistoryScreen(20, 3)
_g1_stream = pyte.ByteStream(_acs_g1)
_g1_stream.feed(b"\x1b)0\x0eq")            # designate G1 + SO
check("charset: G1 (`ESC ) 0` + SO — honoured by the patch too) draws the same box character",
      lines(_acs_g1)[0] == "\u2500", repr(lines(_acs_g1)[0]))
_g1_stream.feed(b"\x0fq")                  # SI — back to G0 (the identity map)
check("charset: SI selects G0 again → a literal `q`", lines(_acs_g1)[0] == "\u2500q",
      repr(lines(_acs_g1)[0]))
_acs_frame = pyte.HistoryScreen(10, 3)
pyte.ByteStream(_acs_frame).feed(b"\x1b(0lqqqk\x1b(B\r\nx   x")
check("charset: a whole ACS frame arrives as box drawing (the mc panel separator)",
      lines(_acs_frame)[:2] == ["\u250c\u2500\u2500\u2500\u2510", "x   x"],
      repr(lines(_acs_frame)[:2]))


# ════════════════════════════════════════════════════════════
# 4. Release state + i18n parity (no new keys — the pin does not move)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
