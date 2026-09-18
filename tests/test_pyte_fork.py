# -*- coding: utf-8 -*-
"""v1.3rc1 — Terminal: the managed pyte fork (vendored 0.8.2 + patch manifest).

(ROADMAP v1.3rc1, the PYTE82_AUDIT.md "The application: the 'controlled fork' variant" +
the section "The decision".)

The test of the provenance of the fork in third_party/pyte/. Zero behavioral conversion —
the existing terminal tests (test_pyte_compat / test_alt_screen / …) are green
unchanged; this file adds the PROVENANCE CHECKS on top of them:

  * the sha256 of every file of third_party/pyte/ == the tables of MANIFEST.md (two tables:
    the pristine files == the upstream PyPI sdist 0.8.2; the post-patch — the expected hashes
    after the patches 0001–0003); the drift "and forgot what was changed" is caught here;
  * the manifest of the patches: the files are in place, the names by the convention NNNN-slug.patch, the headers
    with the provenance (the upstream issue/PR, the date) and the attribution (0003 — the author of PR #212,
    dwgx; the code of pyte is LGPL-3.0 — the attribution is mandatory);
  * the behavioral smoke of the fork itself (headless, without Qt): the private SGR does not crash +
    the tail of the chunk is preserved (b'AB\x1b[?4mCD\r\n' → "ABCD"); the LNM is the default
    (b'ab\ncd' → ["ab", "cd"], after the explicit \x1b[20l — the shift x=2); the alt-screen
    round-trip (\x1b[?1049h…\x1b[?1049l → the grid is equal to before the enter
    character by character, including the fg/bg).

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

# The unpatched files are identical in both tables; the only patched one — screens.py.
untouched = [n for n in actual_files if pristine_tbl.get(n) == postpatch_tbl.get(n)]
changed = [n for n in actual_files if pristine_tbl.get(n) != postpatch_tbl.get(n)]
check("the unpatched files: the same hash in both tables (10 of 11)",
      len(untouched) == 10 and len(changed) == 1, f"untouched={len(untouched)}, changed={changed}")
check("the only patched file is screens.py", changed == ["screens.py"], str(changed))

# The seam: the production code uses THE SAME fork (not the stock pyte from site-packages).
check("the seam: modules.terminal_screen imports third_party/pyte (the same module)",
      TS.pyte is pyte, f"TS.pyte={getattr(TS.pyte, '__file__', '?')}")


# ════════════════════════════════════════════════════════════
# 2. The patch manifest: the naming convention + headers with provenance/attribution
# ════════════════════════════════════════════════════════════
print("== patch manifest ==")

actual_patches = sorted(
    n for n in os.listdir(PATCHDIR) if n.endswith(".patch"))
check("patches 0001–0003 are in place, no extras", actual_patches == list(EXPECTED_PATCHES),
      str(actual_patches))
check("the names follow the NNNN-slug.patch convention",
      all(re.fullmatch(r"\d{4}-[a-z0-9][a-z0-9-]*\.patch", n) for n in actual_patches),
      str(actual_patches))

HEADER_FIELDS = ("Subject:", "Provenance:", "Base:", "Policy:", "Applied:")
for name, must_contain in (
    (EXPECTED_PATCHES[0], ("PR #203",)),
    (EXPECTED_PATCHES[1], ("LNM",)),
    (EXPECTED_PATCHES[2], ("PR #212", "dwgx")),   # the attribution to the PR author — mandatory (LGPL)
):
    path = os.path.join(PATCHDIR, name)
    if not os.path.isfile(path):
        check(f"{name}: the header with the provenance and the diff body", False, "the file is not found")
        continue
    with open(path, encoding="utf-8") as f:
        text = f.read()
    head_ok = all(field in text for field in HEADER_FIELDS)
    attr_ok = all(tok in text for tok in must_contain)
    diff_ok = "diff --git a/pyte/screens.py b/pyte/screens.py" in text
    check(f"{name}: the header (Subject/Provenance/Base/Policy/Applied) + the provenance "
          f"({', '.join(must_contain)}) + unified diff", head_ok and attr_ok and diff_ok,
          f"head={head_ok}, provenance={attr_ok}, diff={diff_ok}")


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


# ════════════════════════════════════════════════════════════
# 4. Release state + i18n parity (no new keys — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
