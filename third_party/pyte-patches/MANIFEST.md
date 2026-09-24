# MANIFEST — the managed pyte fork (sshmap v1.3rc1)

> The single source of truth of the fork: `third_party/pyte/` = pristine upstream pyte 0.8.2 +
> an explicit set of patches from this directory. In-place edits that get "forgotten what was changed" —
> are forbidden: the drift is measured (sha256 below) and checked by the test
> (`tests/test_pyte_fork.py`). Converted: v1.3rc1 (2026-09-10), per PYTE82_AUDIT.md
> ("Appendix: the "managed fork" variant" + the "Decision" section).

## Base

| Field | Value |
|---|---|
| Source | PyPI sdist pyte 0.8.2 — https://files.pythonhosted.org/packages/ab/ab/b599762933eba04de7dc5b31ae083112a6c9a9db15b01d3109ad797559d9/pyte-0.8.2.tar.gz |
| sha256 (archive) | `5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f` |
| Verified | 2026-09-10: downloaded, the hash cross-checked with pypi.org/pypi/pyte/0.8.2/json (the latest release on PyPI — 0.8.2), unpacked; `F:\PythonAI\pyte` (not a git repository) was NOT used as the base |
| License | GNU LGPL v3 — `third_party/pyte/LICENSE` and the copyright headers of the files MUST NOT be removed; the patches do not strip the license from the base. If the application is commercial — check the LGPL terms with a lawyer |

## Patches (applied IN ORDER, from sshmap/third_party/: `git apply pyte-patches/<file>`)

| # | File | Source | Policy |
|---|---|---|---|
| 0001 | 0001-private-sgr-ignore.patch | upstream PR #203 (issue #202, Vim 9+ `\x1b[?4m`), merged into master 2025-09-02; the hunks are byte-for-byte as in the PR | drop when it lands in an upstream release (0.8.3+) |
| 0002 | 0002-lnm-default.patch | sshmap, PYTE82_AUDIT.md batch A2 (v1.2.11): LNM=20 in `_DEFAULT_MODE` — a bare LF = CR+LF (xterm); one line | keep until upstream ships it; then drop |
| 0003 | 0003-alt-screen-47-1047-1048-1049.patch | the semantics of upstream PR #212, author **dwgx** (closed without merge 2026-08-14; issue #90); moved verbatim from the v1.2.12 subclass | permanent: PR #212 was never merged — an upstream patch will not absorb it |
| 0004 | 0004-private-csi-ignore.patch | sshmap (v1.5.7): the `CSI ? r` / `CSI ? n` crash found from a real session — `pyte/streams.py` passes `private=True` to the handler of every `?`-prefixed CSI, and the DECSTBM/DSR handlers do not accept it, so `feed()` raised `TypeError` and the canvas kept the old frame | keep until upstream makes the private dispatch tolerant (0.8.3+); then drop |

Rebasing onto a future upstream release: `git apply` (or `git am`) the four patches onto the new
base, drop the ones absorbed upstream, recompute the tables below. Verified 2026-09-10:
the patches apply to the pristine base with `git apply` without offsets; the result is byte-for-byte
identical to the post-patch table (the conversion script). 0004 was generated from the post-0003
tree and verified with `git apply -R --check` (the diff and the tree agree byte for byte).

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
| screens.py | fc36eac2b4e4560dbe14b1c2d8e30c0db1ce16d5d19d58980d09ec0a766324a2 |
| streams.py | a8c667e0f288b20064c3d8600aaf792f562cdfa84b4a39bc852ce05acc04c14d |

The files untouched by the patches have the same hash in both tables; the only
file changed by patches 0001–0004 is `screens.py`.

## Verified facts about the upstream internals (moved here from PYTE82_AUDIT.md §5/§7 and the terminal_screen.py docstring)

Knowledge about someone else's code lives here, not in our docstrings; the historical
"TERMINAL.md §…" references in comments were left untouched at conversion (provenance).

- SGR 33 → `fg='brown'`, SGR 93 → `'brightbrown'` — yellow is named brown (graphics.py FG_ANSI/BG_ANSI);
- 256-colors and truecolor are stored as hex strings WITHOUT '#' ('ff0000', '0a141e') — the isdigit() branch in resolve_color() never fires, a hex passthrough is needed;
- pyte's own typo in 0.8.2: `BG_AIXTERM[105] = 'bfightmagenta'` (SGR 4;105) — fixed in master ('brightmagenta'), not fixed in 0.8.2;
- private modes are stored in `screen.mode` with a <<5 shift (`set_mode(private=True)`: `mode << 5`) — DECCKM is 32, not 1; mouse tracking: 1000/1002/1003/1006 → 32000/32064/32128/32192 (DECSET 1006 ALONE does NOT enable tracking — it only changes the reporting encoding);
- 0.8.2 has NO alternate screen: modes 47/1047/1048/1049 were inert bits (patch 0003 adds the handlers; there are no constants in pyte.modes — the class attribute `Screen.ALTSCREEN_MODES` is declared);
- HistoryScreen auto-return to live: `before_event()` spins `next_page()` in a loop for every event except prev_page/next_page (measurement D1 v1.2.12: 68–73 ms/chunk with deep history → batching D2 in modules/terminal_screen.py, v1.2.14);
- `HistoryScreen.__getattribute__` wraps set_mode/reset_mode/index/reverse_index (all of them are in `Stream.events`) and calls `self.before_event(event)` by name → subclass overrides are picked up automatically; `before_event` is not in `_wrapped` (no recursion);
- `Char` has an `italics` field; a wide glyph = 2 cells, the second one — a stub with `data==""` (draw() uses wcwidth(3)); `display()` skips the stubs;
- the private-CSI dispatch (`pyte/streams.py`): `csi_dispatch[char](*params, private=True)` for EVERY
  `?`-prefixed CSI — the handlers that must act on the flag declare `**kwargs` (set_mode/reset_mode);
  the rest raise `TypeError` unless they do (patch 0004: `set_margins` and `report_device_status`);
- `Screen.reset()` restores `mode = _DEFAULT_MODE.copy()` (after patch 0002 — {DECAWM, DECTCEM, LNM}); `HistoryScreen.__init__` sets `self.history` first, then calls `super().__init__()` (which calls `self.reset()`) → the alt state is initialized in `Screen.__init__` BEFORE reset.
