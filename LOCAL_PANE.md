# LOCAL_PANE.md — the LOCAL pane (the frozen contract of v1.7.4)

> **Status.** This document is the **frozen contract** of `v1.7.4` — the release that makes the
> DATA SOURCE of a Commander pane a CHOICE, so the OS disk of this machine can be read beside a
> server. It is pinned BEFORE the first rc, the `PLUGINS.md` / `SFTP_PANES.md` / `PYTE82_AUDIT.md`
> pattern: **the rc series implements this contract, it does not change it.** A behaviour that is
> not described here is not part of the local pane; a change to what IS described here is a
> decision that belongs to the maintainer and is written HERE first.
>
> **What each slot ships.** **`v1.7.4rc1`:** the provider seam of §1, the path dialect of §2, the
> LOCAL surface of §3 (listing, navigation, the address bar, the read-only preview) and the SOURCE
> SWITCH of §4 with its two refusals — **a local pane browsed beside a remote one, transferring
> nothing.** **`v1.7.4rc2` (SHIPPED):** the cross-pane dispatch of §5, the recursive local side of §6
> and the drag & drop of §7 — the four source pairs move bytes. **`v1.7.4` (SHIPPED):** the clause audit
> of this document (`tests/test_local_pane_contract.py`), the topical files of both slots and the line's
> documents. **`v1.7.5` (the slot still open):** the pane's SOURCE HEADER LINE of §3 — the wording that
> names what a pane reads — with the sortable listing and the preview ceiling of that release.
>
> **What does NOT move.** ONE transport, ONE `SftpWorker`, ONE queue, one authentication per
> session (`SFTP_PANES.md` §1/§2 restated, not bent): the remote half of a pane is the shipped
> worker and every remote call site is untouched. The LOCAL provider has NO credentials, NO network
> and NO project-file footprint — a path is never written into a project, and `VERSION_FORMAT`
> stays `0.9`.

---

## 1. The provider seam

**A pane's data source is its PROVIDER.** `_SftpPane.provider` resolves ONE object per pane, and
every call site inside the pane keeps its shipped shape — the provider answers the SAME method
names and the SAME signals as the shipped `SftpWorker`, so not one of them moves with the source:

| | The remote provider | The local provider |
|---|---|---|
| The object | the SHIPPED `SftpWorker` of the session (the container owns it, `SftpTab._worker`) | a NEW `modules/local_fs_worker.py` (`LocalFsWorker`), ONE per pane |
| The thread | one per session | one per LOCAL pane (its own `QThread` — a mapped share or a 50 000-entry folder must not freeze the GUI, `AGENTS.md` §4.8) |
| The `queue_*` family | `queue_list`, `queue_read`, `queue_mkdir`, `queue_rename`, `queue_delete`, `queue_normalize`, `queue_copy`, `queue_move`, `queue_upload`, `queue_download`, `cancel`, `shutdown` | the SAME names (§3 declares which of them rc1 really binds) |
| The signals | `list_ready`, `task_started`, `progress`, `task_done`, `task_error`, `task_cancelled`, `read_ready`, `normalize_ready` | the SAME names |
| The task ids | unique per worker; the pane answers only the ids IT queued | the same rule — the pane's own maps stay the answer |

- **`bind_worker(old, new)` keeps its name and its job** (the pane's bookkeeping belongs to ONE
  source): every task map of the pane is cleared, the old object is disconnected and the new one
  is connected through the SAME `WORKER_SIGNAL_NAMES` loop. It gains ONE keyword,
  `source="remote"`, because the "waiting" state is not the same sentence on both sides: a remote
  pane with no transport shows `sftp.waiting_connection`, while a LOCAL pane with no provider is a
  state that cannot happen (the provider is created with the pane) and is therefore reported as an
  empty listing.
- **The local provider is NOT the container's.** `SftpTab._worker` and `set_worker()` keep owning
  the SESSION's transport, and `SftpTab.relist_dir()` keeps its remote job; a LOCAL pane is never
  re-listed by a remote task, and its own answers are never routed through the container.
- **A local pane never borrows the session's channel and never reports through it**: its sentences
  ride the pane's own `message` signal, which the container forwards (`SFTP_PANES.md` §1,
  unchanged).
- **Nothing a remote task says is rendered by a local pane.** The pane's own maps are the filter
  (`SFTP_PANES.md` §3), and a local provider answers only its own task ids.

## 2. The path dialect

POSIX and the OS disk do not speak the same dialect, and the pane used to speak the first one
everywhere. **ONE small PURE object per pane resolves it** (`PathDialect`, two instances:
`POSIX_PATHS` and `LOCAL_PATHS`), and the pane calls it instead of `posixpath` in every place that
joins, splits, names or roots a path:

| Member | POSIX (the remote pane) | Local (the OS disk) |
|---|---|---|
| `dirname(path)` | `posixpath.dirname` | `os.path.dirname` |
| `join(base, name)` | `posixpath.join` | `os.path.join` |
| `basename(path)` | `posixpath.basename` | `os.path.basename` |
| `root` | `/` | the ROOT of the platform: a drive (`C:\`), a UNC share root |
| `is_root(path)` | `path == "/"` | the path whose `dirname` is itself (a drive root, a UNC share root) — never a bare drive name and never `~` |
| `is_absolute(path)` | starts with `/` | `os.path.isabs(path)`, with `~` counted as absolute (it resolves to a home) |
| `same(a, b)` | byte equality | `os.path.normcase` equality (the OS disk is case-insensitive) |
| `display(path)` | the path itself | the path itself (a local path is shown the way the OS spells it) |

- **The dialect is a property of the PANE** (`_SftpPane.paths`), resolved from its source, and the
  pane's root test goes through it: this is the one place where a stale `/` would turn "go up" into
  a wrong listing.
- **A typed local path is resolved by the LOCAL side**, exactly as a typed remote path is resolved
  by the server: the address bar hands the text to the provider's `queue_normalize()`, so `~`, a
  relative path and a case-differing path are the OS's business and never a guess of the pane.
- **The separator is the dialect's**: a completion row of the local pane continues into a
  directory through the dialect, so `C:\Users\` beats `C:/Users` on Windows.
- **The dialect is PURE** (no Qt, no IO, no i18n) and has its own test over BOTH dialects.

## 3. The local surface — what rc1 ships

`modules/local_fs_worker.py` holds ONE `QThread` with a FIFO queue, the shape of the shipped
`SftpWorker` (`run()` takes one task at a time, a failure never kills the queue, `shutdown()`
cancels and waits, the thread NAMES itself and is registered as an orphan if it outlives its wait —
`AGENTS.md` §4.8):

| Method | Task kind | Answers | rc1 |
|---|---|---|---|
| `queue_list(directory)` | `list` | `list_ready(task_id, directory, entries)` — `[{name, is_dir, size, mtime}]`, directories first then case-insensitive by name | **SHIPPED** |
| `queue_normalize(path, base_dir)` | `normalize` | `normalize_ready(task_id, requested, resolved)` — `~` expanded, relative resolved against `base_dir`, the result `os.path.normpath`-ed | **SHIPPED** |
| `queue_read(path, total_size)` | `read` | `read_ready(task_id, path, bytes)` | **SHIPPED** — the SHIPPED read policy, unchanged: `classify_extension()` refuses a known-binary name, the NULL byte of the first chunk refuses the rest, `MAX_READ_BYTES` is the hard limit (from the listing and again on every chunk), 32 KB chunks with `progress` between them |
| `queue_mkdir(dir, name)` | `mkdir` | `task_done(task_id, detail=new path)` | **SHIPPED** |
| `queue_rename(path, new_name)` | `rename` | `task_done` | **SHIPPED** — in place: the name changes, the directory does not |
| `queue_delete(path, is_dir)` | `delete` | `task_done` | **SHIPPED** — the permanent delete of §4's warning |
| `cancel()` / `shutdown(wait_ms)` | — | `task_cancelled` for what was queued | **SHIPPED** |
| `queue_upload` / `queue_download` / `queue_copy` / `queue_move` | the four transfer doors — one copy engine, `shutil.copy2` through a `.part` + `os.replace`, a move in one volume and copy+delete across volumes | **SHIPPED in rc2** (§5/§6) |

- **The row shape does not move**: the entry dicts are exactly the remote ones
  (`PATH_ROLE` / `ISDIR_ROLE` / `SIZE_ROLE` / `MTIME_ROLE`), so the tree, the "no preview" markers,
  the viewer, the completer, the walk of `SFTP_PANES.md` §3a and the batch of §3 work untouched.
  The FULL path of a row is built by the pane through its dialect (`join(current_dir, name)`).
- **Hidden and system entries are SHOWN** (the classic commander does), with the shipped row
  markers. **A directory symlink is REFUSED** with one sentence when it is entered — following it
  silently can walk out of the folder the user pointed at; a FILE symlink is listed and read as the
  file's content (the OS resolves it).
- **A pane NAMES ITS SOURCE in a header line** (`_SftpPane.header_label`, the pane's FIRST row, above the
  address row): a pane that reads the OS disk shows `sftp.local.this_computer`, a pane that reads a
  server shows the session's ALIAS (the label `set_session_info()` was given; `user@host` is the fallback
  when the session was never identified). It is a VIEW of the source: re-texted by `retranslate()`,
  re-styled by `refresh_theme()` through `status.sftp_row`, ONE line of height, and it takes neither the
  keyboard walk of §4 nor the drop coordinates (a drop is resolved in the tree's viewport). The ADDRESS
  BAR keeps the shipped wording — `sftp.waiting_connection` before a transport, the directory after one —
  so "This computer" belongs to the header and never to the path. The BUTTONS keep their own labels
  (Up / Refresh / Upload / Download / Cancel); the Upload/Download pair of a LOCAL pane is LIVE and runs
  the local engine of §5 through the pane's own provider.
- **Every refusal is ONE translated sentence, never a traceback and never an empty pane**: the
  provider reports a MACHINE code in `task_error` (`sftp_worker.task_payload()`'s shape, so the
  activity log has no JSON either), and the pane owns the sentence:

| Code | When | The sentence |
|---|---|---|
| `permission` | `PermissionError` (a system folder, a protected file) | `sftp.local.permission` |
| `locked` | `OSError` of a file another process holds (`winerror` 32/33) | `sftp.local.locked` |
| `too_long` | the path exceeds the platform limit (Windows `MAX_PATH` without the `\\?\` form, `winerror` 206) | `sftp.local.too_long` |
| `missing` | `FileNotFoundError` (a directory that was deleted under the listing) | `sftp.local.missing` |
| `symlink_dir` | a directory symlink is entered | `sftp.local.symlink_dir` |
| `not_dir` / `is_dir` | the path is not a directory / an operation needs the other kind | `sftp.local.not_dir` / `sftp.local.is_dir` |
| `exists` | `mkdir` / `rename` onto an existing name | `sftp.local.exists` |
| `unreadable` | any other `OSError` — the OS's own text rides in the payload as the detail | `sftp.local.unreadable` |

## 4. The SOURCE SWITCH and its two refusals

- **The switch is an action of the SECOND pane's address row** ("Server | Local", ONE checkable
  pair driving ONE state), NOT a container control and NOT a config key: the local pane is a
  gesture of the moment, and a new session opens with TWO REMOTE PANES. A per-session memory is a
  candidate for a later version and deliberately not part of this one.
- **The FIRST pane is always remote** (it is the session's own tree, and the cwd follow, the
  "Send to…" provider and the Files panel all address it), so the switch is **DISABLED while the
  container holds ONE pane** — the Commander is what makes "the other side" a concept.
- **The two refusals are structural, not cosmetic**: the switch is UNAVAILABLE in the
  `terminal_mode = "tabs"` dock and in the v1.7.1 Files PANEL, because both are single-pane views
  of the SESSION's remote tree — and a refusal that is asked for says so in ONE sentence
  (`sftp.local.unavailable`), never a silent no-op.
- **The cwd follow stays the remote pane's alone.** It is already switched OFF by the two-pane
  mode by construction (`SFTP_PANES.md` §6); a local pane must not invent a second follower, and
  an OSC 7 report never moves a local listing.
- **A local pane keeps its own directory** across a switch to remote and back (the object, its
  listing and its provider survive), and turning the Commander OFF destroys the second pane through
  the SHIPPED `_destroy_pane()` path — which now also shuts the local provider down.
- **The permanent-delete warning is the local pane's.** A local `F8` deletes for good: there is no
  recycle bin, because `send2trash` would be a new dependency for a convenience. The confirmation
  therefore SAYS so in words (`sftp.local.delete_confirm`), and a visible refusal beats a silent
  recoverability the user assumes.

## 5. The cross-pane dispatch (rc2)

`_remote_batch()` becomes the DISPATCH over the PAIR of providers, and the SHIPPED batch machinery
(ONE conflict question with "apply to all", the shipped counters, ONE closing report) survives for
all four cases:

| Source → destination | What runs |
|---|---|
| remote → remote | the SHIPPED `queue_copy` / `queue_move` (untouched, `SFTP_PANES.md` §3) |
| **local → remote** | the SHIPPED `queue_upload` of the SESSION's worker |
| **remote → local** | the SHIPPED `queue_download` — into the destination pane's directory, atomically (`<name>.part` + `os.replace`) |
| **local → local** | the LOCAL engine of `modules/local_fs_worker.py`: a copy is `shutil.copy2` through a `.part` + `os.replace`, a move is `shutil.move` inside one volume and copy+delete across volumes |

- **The batch bookkeeping is per SOURCE**: a task id belongs to the provider that queued it, so the
  pane keeps its `_op_tasks` / `_op_batches` maps keyed by task id AND resolves the provider that
  answered. A remote answer never re-lists a local pane and the other way round.
- **ONE closing report for all four cases** — a commander reads the same on either side.

## 6. The recursive local side (rc2)

`queue_upload()` is FILE-only today, while the remote `F5` carries a directory as a whole tree — a
local pane that refused a folder would look broken beside its own sibling. The local walk uses the
SHIPPED bounds and rules (`SFTP_PANES.md` §2a): `MAX_TREE_ENTRIES` / `MAX_TREE_DEPTH`, every file
atomic, an interrupted tree REPORTED through `task_payload(PARTIAL_CODE, …)`, a copy additive, a
move's emptied directories removed last (deepest first), a directory symlink never followed.

## 7. Drag & drop (rc2)

- **A local row dragged OUT hands a real OS path**: `text/uri-list` (the Explorer contract) beside
  `text/plain` (the shipped consumers).
- **A drop of Explorer files on the LOCAL pane is a LOCAL copy**, not the shipped upload; a drop on
  the REMOTE pane stays the shipped upload.
- **The payload that travels BETWEEN panes keeps the pane identity** (`{session, pane, path}`, the
  private mime type of v1.7.3) with the SOURCE dialect declared in it, so a drop is resolved by the
  WIDGET UNDER THE CURSOR — the v1.7.1 panel and a borrowed preview both RE-PARENT a pane's widget.

## 8. The refactor boundary (rc1's regression)

- The remote pane's behaviour does NOT move: `tests/test_sftp_tab.py`, `_viewer`, `_ops`, `_dnd`,
  `_syntax`, `_commander*` and `test_files_surface.py` stay green for a tab whose panes are both
  remote.
- **ONE clause of the CLOSED contract changes and is recorded as a decision**: `SFTP_PANES.md` §1
  said "a pane never stores a worker" — a LOCAL pane does, because its provider is not the
  container's. The shipped audit keeps its sentence for the REMOTE pane and the local exception is
  asserted beside it.
- ONE deliberate addition to the closed line's audit: the pane's own `release()` shuts the local
  provider down (the orphan registry of `AGENTS.md` §4.8 holds it if the wait is exhausted).

## 9. Acceptance per slot

- **rc1** — `modules/local_fs_worker.py`, the dialect of §2, the provider seam of §1, the surface
  of §3 and the switch of §4; the topical file `tests/test_local_pane.py`; the i18n pin follows (the
  source switch, the local dialect sentences, the permanent-delete warning); `python tests/run_all.py`
  → exit 0 and `python tests/test_docs.py` green; no new dependency, no new colour field,
  `Theme.DARK` untouched, `VERSION_FORMAT` stays `0.9`.
- **rc2 (SHIPPED)** — the dispatch of §5, the recursion of §6 and the drag & drop of §7 with the topical
  rows for both (`tests/test_local_pane.py`, 107 checks).
- **`v1.7.4`** — the clause-by-clause audit of THIS document against the shipped code (one section
  per clause group), the line's documents (`CHANGELOG.md`, `DOCUMENTATION.md`, `AGENTS.md`
  §4.3/§4.24, `README.md` §1 and its Security & limitations sentence) and `ROADMAP.md` losing the
  version. A gap that needs a decision goes back to the maintainer instead of being patched into the
  release.
