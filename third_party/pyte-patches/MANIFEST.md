# MANIFEST — the managed pyte fork (pyte 0.8.2 + patches 0001–0012, sshmap v1.9)

> The single source of truth of the fork: `third_party/pyte/` = pristine upstream pyte 0.8.2 +
> an explicit set of patches from this directory. In-place edits that get "forgotten what was changed" —
> are forbidden: the drift is measured (sha256 below) and checked by the test
> (`tests/test_pyte_fork.py`). Converted: v1.3rc1 (2026-09-10), per PYTE82_AUDIT.md
> ("Appendix: the "managed fork" variant" + the "Decision" section). The patch set grew in v1.5.7
> (0004), v1.5.7.1 (0005–0009 — the dependency audit of the raise-review section of
> PYTE82_AUDIT.md), v1.6.2 (0010 — the G0/G1 charset designation the VT100 special graphics needs)
> and v1.9 (0011 — OSC 8 hyperlinks, the terminal-link feature; 0012 — the erased background, the
> audit's cosmetic (b)).

## Base

| Field | Value |
|---|---|
| Source | PyPI sdist pyte 0.8.2 — https://files.pythonhosted.org/packages/ab/ab/b599762933eba04de7dc5b31ae083112a6c9a9db15b01d3109ad797559d9/pyte-0.8.2.tar.gz |
| sha256 (archive) | `5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f` |
| Verified | 2026-09-10: downloaded, the hash cross-checked with pypi.org/pypi/pyte/0.8.2/json (the latest release on PyPI — 0.8.2), unpacked; `F:\PythonAI\pyte` (not a git repository) was NOT used as the base. Re-verified 2026-09-26: the ten unpatched files of the vendored tree hash exactly to the "pristine base" table below, and `screens.py` after LF normalization |
| License | GNU LGPL v3 — `third_party/pyte/LICENSE` and the copyright headers of the files MUST NOT be removed; the patches do not strip the license from the base. If the application is commercial — check the LGPL terms with a lawyer |

## Patches (applied IN ORDER, from sshmap/third_party/: `git apply pyte-patches/<file>`)

| # | File | Source | Policy |
|---|---|---|---|
| 0001 | 0001-private-sgr-ignore.patch | upstream PR #203 (issue #202, Vim 9+ `\x1b[?4m`), merged into master 2025-09-02; the hunks are byte-for-byte as in the PR | drop when it lands in an upstream release (0.8.3+) |
| 0002 | 0002-lnm-default.patch | sshmap, PYTE82_AUDIT.md batch A2 (v1.2.11): LNM=20 in `_DEFAULT_MODE` — a bare LF = CR+LF (xterm); one line | keep until upstream ships it; then drop |
| 0003 | 0003-alt-screen-47-1047-1048-1049.patch | the semantics of upstream PR #212, author **dwgx** (closed without merge 2026-08-14; issue #90); moved verbatim from the v1.2.12 subclass | permanent: PR #212 was never merged — an upstream patch will not absorb it |
| 0004 | 0004-private-csi-ignore.patch | sshmap (v1.5.7): the `CSI ? r` / `CSI ? n` crash found from a real session — `pyte/streams.py` passes `private=True` to the handler of every `?`-prefixed CSI, and the DECSTBM/DSR handlers do not accept it, so `feed()` raised `TypeError` and the canvas kept the old frame | keep until upstream makes the private dispatch tolerant (0.8.3+); then drop |
| 0005 | 0005-grapheme-clusters.patch | upstream pyte master (0.8.3.dev), "Fixed rendering of multi code-point emoji sequences": `grapheme_clusters()` + a cached `wcswidth` in `draw()`/`display()` (`wcswidth` is NOT a per-character sum — it knows the emoji ZWJ sequences). TWO additions of our own, NOT upstream: (a) the cluster rule's extend test is the whole M category set (Mn/Mc/Me), because a mark whose canonical combining class is 0 — a Thai vowel sign, a Devanagari matra, a keycap's `U+20E3` — must attach to its base (upstream leaves it a zero-width cluster and drops the chunk tail on it); (b) the 0.8.2 NFC merge of a combining mark is preserved (upstream stores the decomposed form) | drop when the base is raised to a release carrying the emoji fix; (a), (b) and the zero-width skip have no upstream counterpart — keep them, or file them upstream |
| 0006 | 0006-tolerant-csi-dispatch.patch | the pyte-audit defect report BUG-A/BUG-B (github.com/org-ai-assisted/pyte-audit; the AI-assisted fork carries the report and NOT the fix, master neither): a surplus CSI parameter or a private marker on a command with no private form raised `TypeError` out of `feed()` — 19 finals of the fork's own CSI table per shape | keep until upstream makes the dispatch tolerant of both shapes |
| 0007 | 0007-erase-unknown-mode-noop.patch | the pyte-audit report BUG-C — the FIX is the AI-assisted fork's own (`pyte-audit-fixes.txt` declares `C`); `ESC[3K` / `ESC[4J` raised `UnboundLocalError` out of `feed()` | keep until upstream merges the report's fix |
| 0008 | 0008-decom-guard.patch | the pyte-audit report BUG-D (reported, fixed in neither tree): VPA and the DSR report added `self.margins.top` behind a bare `assert`, so `ESC[?6h ESC[5d` / `ESC[?6h ESC[6n` raised `AssertionError` out of `feed()` when DECOM was set with no scrolling region — the guard mirrors `cursor_position()` | keep until upstream merges the report's fix |
| 0009 | 0009-resize-cursor-clamp.patch | the pyte-audit report BUG-E (reported and fixed nowhere): `resize()` left the cursor outside the new geometry, so the next `draw()` wrote an off-screen cell that `display()` never shows. Deviation from the report's diff: the clamps run AFTER `set_margins()`, so they bound to the full new screen | keep until upstream merges the report's fix |
| 0010 | 0010-honour-charset-designation.patch | sshmap (v1.6.2; the colleagues' `mc` report): the G0/G1 designation of `ESC ( x` / `ESC ) x` was skipped in UTF-8 mode (`if self.use_utf8: continue` — twice in `pyte/streams.py`), so the VT100 special graphics, which is how an ACS frame is drawn, arrived as its literal letters (`ESC ( 0` + `q` stayed `q` in the grid). The tables (`pyte/charsets.py`: `MAPS["0"] = VT100_MAP`) and the translation in `Screen.draw()` were already there — only the designation never arrived | keep until upstream makes the designation independent of `use_utf8` (the same "input is Unicode-only" assumption stands in 0.8.3.dev) |
| 0011 | 0011-osc8-hyperlinks.patch | sshmap (v1.9, ROADMAP task 1): `OSC 8` hyperlinks. Upstream dispatches OSC `0`/`1`/`2` only and DROPS the rest, so a link a program sends was consumed and lost. `Char` gains the LAST field `hyperlink: str = ""`, `Screen.set_hyperlink()` parses `params;URI` (the `id=` params half is accepted and ignored) and re-applies the link on BOTH attribute-reset paths of `select_graphic_rendition` (SGR 0 is orthogonal to a link, as in xterm), and the OSC branch of `pyte/streams.py` dispatches `code == "8"`. The link travels WITH the cell through `draw()`, the erase paths and the scroll, because it lives in the attributes rather than in a map beside the grid | keep until upstream implements OSC 8 (`0.8.3.dev` has no hyperlink support at all — its OSC branch is behaviourally unchanged); the field is additive, so a rebase can keep the canvas side and drop the patch |
| 0012 | 0012-erase-background.patch | sshmap (v1.9, ROADMAP task 2) — item (b) of the dependency audit's three pyte cosmetics (PYTE82_AUDIT.md, the raise-review of 2026-09-26): `erase_in_display` ended its loop with `for x in line:` over a SPARSE `StaticDefaultDict`, whose iteration yields the KEYS, so only the cells that already had an entry were written — measured, `ESC[44m ESC[2J` on a blank 30-cell row painted 0 of 30 cells (against 6 of 30 for `ESC[K`) and 11 of 30 on a written one. The fix writes the WHOLE width through ONE private helper (`Screen._erase_attrs()` — the current attributes, the character blanked and the OSC 8 link dropped), used by `erase_characters` / `erase_in_line` / `erase_in_display`; measured cost of a full-screen clear: 0.016 → 0.229 ms at 200×50, 0.010 → 0.061 ms at 80×24 | keep — 0.8.3.dev carries the same sparse loop, so there is no release to wait for; the audit's item (c) (`CSI 3 J` clearing the visible screen, an underline carrying into the erased cells) is deliberately NOT part of this patch |

**Applying the patches on Windows — the EOL trap (measured 2026-09-26).** `git apply` honours
`core.autocrlf`: with the Git-for-Windows default (`true`, set in the SYSTEM gitconfig) it rewrites the
patched files to CRLF, the tree stops being LF, and every hash below stops matching (measured:
`screens.py` came out `96c1a763f6d9fedc6ac14e94ae586ca63d8bee64e70a8fe40e15bd1aaeccb818` instead of
`fc36eac2…`). The repository carries a `.gitattributes` that marks `third_party/pyte/**` and
`third_party/pyte-patches/**` as `-text`, so git never converts those bytes on a checkout either
(without it, a FRESH CLONE on Windows materializes CRLF and `tests/test_pyte_fork.py` goes red while the
repository itself is correct). Apply with `git -c core.autocrlf=false apply pyte-patches/<file>` — the
flag is belt-and-braces next to the attribute; the vendored tree and the pristine sdist are LF.

**The SECOND trap: where `git apply` resolves the patch paths (measured 2026-10-03, git 2.38.1.windows.1
in THIS repository).** Inside a work tree, `git apply <patch>` resolves the paths of the patch against the
WORK-TREE ROOT, not against the current directory: run from `sshmap/` the recipe above finds
`third_party/pyte/streams.py`, while the `cd third_party` form of the same command finds nothing, reports
NOTHING, exits 0 and prints `Skipped patch 'pyte/streams.py'.` — the same line an already-applied patch
prints, so the silence looks like success and the tree stays unpatched. The form that really applies a
patch here (verified: 0010 applied to the pristine base reproduced the vendored file byte-for-byte,
sha256 `e63eab3f25f5cc45bb4532c571435fa9f2a97866e0c9b802c2ac7a40959a73fc`) is run from the REPOSITORY ROOT:

    git -c core.autocrlf=false apply --directory=third_party pyte-patches/<file>

A patch that changed nothing is therefore always checked with
`git status --porcelain third_party/pyte` (a patch that was skipped leaves the tree clean).

Rebasing onto a future upstream release: `git apply` (or `git am`) the twelve patches onto the new
base, drop the ones absorbed upstream, recompute the tables below. Verified 2026-09-26: the nine
patches apply IN ORDER to the pristine base with `git -c core.autocrlf=false apply` without offsets,
and the result is byte-for-byte the post-patch table (0010 verified the same way 2026-10-03, on the
base of the nine; 0011 and 0012 verified the same way 2026-10-07, on the base of the ten — each
applied to a copy of that base reproduced the post-patch table byte-for-byte).

## sha256 — pristine base (upstream pyte 0.8.2, before the patches)

| File (relative to third_party/pyte/) | sha256 |
|---|---|
| LICENSE | da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768 |
| __init__.py | 5279e4cfba52135248b5ce33c7a915100046c6a679f4aff3d6f873643fb1eb44 |
| __main__.py | ea4420eac86603698753acf94105d8ac787cbb1f7e60262a1814e1fc89a1f0e7 |
| charsets.py | 9b9da43e3b5e8b7bfe4a1917e864063f6f54119f97bc9a9694e065ac7cdfc98b |
| control.py | dc799b2f4311d1d6457b9651be5471abcd081cebcc2db225e2a730fb7d54d2a2 |
| escape.py | 6a150147f0120ca5cb993b9b43e191c1cfadf27a093a6e9a53439cdf1babcb48 |
| graphics.py | 6a38c4f4cdcbc8178097ec90ce1d7bce6b3b356d9f2e27d4b7e2d26d35fa898a |
| modes.py | ffc0ad1a8264ac7e500349d5f3a8084cc634b72cc782b8664d0841d5d24e2650 |
| py.typed | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| screens.py | 43bcd10d5555f6a8e53a1f9c0e557a47ec801b3914533d5b51af5828a5242ecb |
| streams.py | a8c667e0f288b20064c3d8600aaf792f562cdfa84b4a39bc852ce05acc04c14d |

## sha256 — post-patch (the current state of third_party/pyte/)

| File (relative to third_party/pyte/) | sha256 |
|---|---|
| LICENSE | da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768 |
| __init__.py | 5279e4cfba52135248b5ce33c7a915100046c6a679f4aff3d6f873643fb1eb44 |
| __main__.py | ea4420eac86603698753acf94105d8ac787cbb1f7e60262a1814e1fc89a1f0e7 |
| charsets.py | 9b9da43e3b5e8b7bfe4a1917e864063f6f54119f97bc9a9694e065ac7cdfc98b |
| control.py | dc799b2f4311d1d6457b9651be5471abcd081cebcc2db225e2a730fb7d54d2a2 |
| escape.py | 6a150147f0120ca5cb993b9b43e191c1cfadf27a093a6e9a53439cdf1babcb48 |
| graphics.py | 6a38c4f4cdcbc8178097ec90ce1d7bce6b3b356d9f2e27d4b7e2d26d35fa898a |
| modes.py | ffc0ad1a8264ac7e500349d5f3a8084cc634b72cc782b8664d0841d5d24e2650 |
| py.typed | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| screens.py | 1344f495bf61fd36b728181eb4a56de186084a2575958c311c2000e2d0302faf |
| streams.py | 6b9d10873ce9688911edac88311636bbd6ab25382328985a43b43ccdde724881 |

The files untouched by the patches have the same hash in both tables; the files changed by
patches 0001–0012 are `screens.py` (0001–0005, 0007–0009, 0011, 0012) and `streams.py` (0006, 0010, 0011).

## Verified facts about the upstream internals (moved here from PYTE82_AUDIT.md §5/§7 and the terminal_screen.py docstring)

Knowledge about someone else's code lives here, not in our docstrings; the historical
"TERMINAL.md §…" references in comments were left untouched at conversion (provenance).

- SGR 33 → `fg='brown'`, SGR 93 → `'brightbrown'` — yellow is named brown (graphics.py FG_ANSI/BG_ANSI);
- 256-colors and truecolor are stored as hex strings WITHOUT '#' ('ff0000', '0a141e') — the isdigit() branch in resolve_color() never fires, a hex passthrough is needed;
- pyte's own typo in 0.8.2: `BG_AIXTERM[105] = 'bfightmagenta'` (SGR 4;105) — fixed in master ('brightmagenta'), not fixed in 0.8.2;
- the charset machinery: `Screen` keeps `g0_charset` / `g1_charset` / `charset` (0 = G0, 1 = G1) and `draw()` applies the SELECTED map with `data.translate(...)`; `define_charset()` accepts only the codes of `cs.MAPS` (`"B0UK"` — so `ESC ( 0` is the VT100 special graphics, `ESC ( B` is the identity `LAT1_MAP`) and `Stream._parser_fsm()` skipped the whole designation AND the SI/SO shift in UTF-8 mode before patch 0010. The designation is per `Screen` and is NOT part of `save_cursor`/`restore_cursor` or of the alternate-screen give-back (xterm resets it there; pyte never did — a divergence patch 0010 declares and keeps);
- the OSC branch of `Stream._parser_fsm()` reads ONE character as the code, then everything up to
  `ST`/`BEL` as the payload, drops the payload's FIRST character (the `;` after the code) and dispatches
  `0`/`1` → `set_icon_name` and `2` → `set_title` — and **nothing else**: `OSC 8`, `OSC 4`, `OSC 52`
  and the palette codes are consumed and dropped in silence (patch 0011 adds `8`; a handler therefore
  receives `params;URI`, and an EMPTY params half makes the whole tail the URI, which is the OSC 8
  reading);
- a buffer LINE is a `StaticDefaultDict` of `Char`, so iterating it yields the KEYS (`x` indices), never
  the cells — the same trap `TerminalScreen._row_text()` documents, and the defect patch 0012 fixes; a
  cell that was never written reads as `default_char` and is NOT stored, which is why an erase has to
  spell out `range(self.columns)` instead of walking the line;
- private modes are stored in `screen.mode` with a <<5 shift (`set_mode(private=True)`: `mode << 5`) — DECCKM is 32, not 1; mouse tracking: 1000/1002/1003/1006 → 32000/32064/32128/32192 (DECSET 1006 ALONE does NOT enable tracking — it only changes the reporting encoding);
- 0.8.2 has NO alternate screen: modes 47/1047/1048/1049 were inert bits (patch 0003 adds the handlers; there are no constants in pyte.modes — the class attribute `Screen.ALTSCREEN_MODES` is declared);
- HistoryScreen auto-return to live: `before_event()` spins `next_page()` in a loop for every event except prev_page/next_page (measurement D1 v1.2.12: 68–73 ms/chunk with deep history → batching D2 in modules/terminal_screen.py, v1.2.14);
- `HistoryScreen.__getattribute__` wraps set_mode/reset_mode/index/reverse_index (all of them are in `Stream.events`) and calls `self.before_event(event)` by name → subclass overrides are picked up automatically; `before_event` is not in `_wrapped` (no recursion);
- `Char` has an `italics` field and, after patch 0011, a LAST `hyperlink: str = ""` field (the OSC 8
  link of the cell, `""` for none; a wide glyph = 2 cells, the second one — a stub with `data==""`
  — carries the same link and `display()` skips it);
- after patch 0005 (upstream's own emoji change) `Char.data` may hold MORE than one code point — a **grapheme cluster** — so `len(data) == 1` is no longer an invariant: the width of a cell is `wcswidth(data)`, and the canvas reads the SAME table (`modules/terminal_widget.char_width()`), which is what keeps the runs and the grid in step;
- the private-CSI dispatch (`pyte/streams.py`): `csi_dispatch[char](*params, private=True)` for EVERY
  `?`-prefixed CSI — the handlers that must act on the flag declare `**kwargs` (set_mode/reset_mode);
  the rest raise `TypeError` unless they do (patch 0004: `set_margins` and `report_device_status`;
  patch 0006: the class as a whole);
- `Screen.reset()` restores `mode = _DEFAULT_MODE.copy()` (after patch 0002 — {DECAWM, DECTCEM, LNM}); `HistoryScreen.__init__` sets `self.history` first, then calls `super().__init__()` (which calls `self.reset()`) → the alt state is initialized in `Screen.__init__` BEFORE reset;
- **upstream master `0.8.3.dev` (verified 2026-09-26)** differs from 0.8.2 in exactly four files: `__init__.py` (+4/−4 — `__version__` + typing), `graphics.py` (+2/−2 — the `BG_AIXTERM[105]` typo and one f-string), `screens.py` (+77/−46 — the emoji cluster fix + typing), `streams.py` (+19/−18 — typing ONLY, the parser is behaviourally unchanged). It has **no alternate screen** and does **not** fix the malformed-CSI, the unknown erase mode, DECOM-without-margins or the resize cursor (all four measured live there) — which is why the policies of 0003 and 0006–0009 do not say "drop when 0.8.3 ships".

## The audit trail

`PYTE82_AUDIT.md` (internal, gitignored) holds the decision log of the fork and its raise-review of
2026-09-26 — the four trees compared (ours, `0.8.3.dev`, the AI-assisted fork, the Lillecarl
rewrite), the measured upstream delta, and the probe evidence behind patches 0005–0009.
