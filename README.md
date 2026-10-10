# SSHMap (Visual Node Map + SSH Terminal and SFTP manager)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

![The example map in SSH Map](docs/map-example.png)

*Help → Open the example map: six cards (one of them unmanaged) and six connections - one of every type - a group, a note and tags, all on documentation addresses (`192.0.2.0/24`) with statuses emulated. The picture is generated from that file by `python tests/_gen_docs_image.py`.*

---

## 1. Features

### Map & canvas
- Server cards with status marks, six typed connections (`ssh`, `vpn`, `http`, `database`, `nfs`, `kubernetes`), sticky notes, groups and a background image (drag it, resize it) on an infinite zoomable canvas (0.1–5.0).
- Draw a connection by `Shift`+drag between two cards or the card's "Connect to…" dialog - both open the same dialog with the source filled in; the From/To pickers narrow as you type a name or an address.
- A group folds into a grid of badges (undoable) and its frame carries the worst member status as a shape plus the counts (`Offline 2 · Warn 1`). "Arrange group" lines the members up (vertical line, horizontal line, rows of N) in one undo step without resizing the frame - a card pushed outside leaves the group, and Ctrl+Z brings the whole arrangement back. **"Arrange Map…"** on the empty map does the same for the whole top level: each group moves as one unit with its members, the free cards fill in around them, one undo step.
- Multi-selection (Ctrl+click, rubber band), group drag, connect/delete selected and **bulk edit** of tags, comment and quick launch in one undo step. Per-server quick launch opens a URL in the browser or sends a command as the first line of an SSH session. Tags filter the sidebar; the primary tag colours the icon and is written on the card - the environment is never a colour alone.
- **See what depends on a card**: `Ctrl`+click highlights it together with every node whose connections lead to it (the transitive answer to *"what breaks if I stop this one?"*) and recedes the rest, with the count in the status bar. `Ctrl`+click again, plain-click another card or `Esc` clears - a view change, nothing moves, nothing lands in the undo stack.
- A density switch (Comfortable / Compact) keeps hundreds of nodes readable (the compact card keeps alias, host and status marks and drops the information block); several connections between the same pair draw as parallel arcs.
- Minimap, legend and an **Export** menu holding everything that leaves the application: "Copy Map as Image", PNG, JPEG, PDF, SVG and `.drawio` - print-friendly by default (a light page, high-contrast lines), "use the current theme" is a one-click opt-out. "Save Documentation Image…" writes a fixed 1600×900 @2× poster; the two data reports below sit in the same menu.
- **Bookmarks**: the links the team uses - a wiki, a dashboard, a hypervisor's console - in one panel: filter as you type, open on double click or Enter, edit in place, reorder, remove. Stored in `~/.sshmap/bookmarks.json`, outside every project - a shared map never carries another machine's links.

### Statuses, facts & diagnostics
- `online` / `warn` / `offline` from parallel SSH probes (TCP + banner) off the GUI thread; a status carries its age and turns grey once stale. "Check statuses now" runs a round on demand, and the cadence has a third setting - **manual only** (`status_interval_sec = 0` or the Status Checks tab): nothing is probed at startup and the age is the only signal.
- Hardware facts (OS / CPU / RAM / disk / IP) carry an age too; one click gathers them for a selection or the whole map through a bounded queue with progress, and the summary names the failures.
- The disk facts read **two** filesystems - the root and the card's **data mount** (a per-card path, `/opt` by default) - and the **inode** table of that volume: from 90 % used on, the card's line says so (`DISK /opt: 48 gb free of 59 gb - inodes 100% used`), the percentage waits in the tooltip - a volume can be 40 % free by space and full by inodes.
- The Add/Edit dialog can pin a card to a **physical disk** (`lsblk -d` of the last collection; the choice is a NAME) and the card's `DISK` line answers with that device's capacity (`DISK: SDB 100 gb`); the full device list rides the tooltip, and a device gone from the listing is reported in the status bar with no capacity shown at all.
- "Why is it offline?" diagnoses a red card directly: DNS resolve → TCP connect → SSH banner → ICMP ping, naming the first failing step. It explains; it never rewrites the status.
- Trouble first: one click dims everything that is not warn, offline or stale, and a floating plaque names every active filter (search, tag, status, lens) with one × each.
- **The neighbours on the map:** mark a server **unmanaged** and it keeps its place without pretending - no credentials stored, no probe round touches it, no SSH verb reaches it; its band carries a "no ssh" mark and its tooltip says "not monitored". A per-card ping exists behind an opt-in switch and is a manual note, never a status.

### Terminal & SFTP
- Built-in terminal on the vendored pyte fork: scrollback, full keyboard, mouse selection, alternate screen (vim/htop/less restore the previous screen), wheel passthrough to TUIs, a find bar, clear / reset / save transcript. Every glyph is drawn at its own grid cell - emoji sequences and combining marks count as one cell - so frames stay aligned with whatever monospace font you pick.
- A full-screen program that asks for the mouse protocol gets it (clicks, drags and releases reported instead of swallowed); `Shift` keeps the selection and scrollback yours and is your exit if a crashed program left mouse mode on. VT100 line graphics render as frames (`mc`, `dialog`), and a session whose server went away says so instead of freezing.
- The cursor is a thin blinking bar out of the box; Bar, Block or Underline in the Terminal tab. The font zooms with `Ctrl`+wheel and remembers its size across restarts.
- **A link a program prints is clickable**: a URL wrapped in an `OSC 8` sequence is underlined while the pointer is over it and opens in your browser - a plain click while the program is not using the mouse, `Ctrl`+click while it is (`Shift` stays the selection override). Only `http` and `https` open.
- **A session whose connection dropped comes back**: right-click its tab (or the window's background) → *Reconnect* - the screen you were reading stays, with one marker line between the two lives, and a fresh channel opens with the saved credential; a session with no stored password, no credential of its own and no key file is refused with one sentence, and the row is greyed out while the session is alive. The first command the session was opened with is sent again (a `tmux` session attaches by itself); *Attach tmux session…* sends `tmux attach` for a name you type, and a later Reconnect attaches again.
- Sessions as tabs in separate windows, in a detachable "Terminals" dock on the map, or in ONE shared window (Settings → Terminal → *Single window*). `Merge Windows` collects the other windows' sessions into one - sessions move as they are, so scrollback, command history and running transfers survive. A tab that produced output while you were elsewhere gets a dot.
- `Split Terminal` gives a second shell of the same node below the tabs (window and dock alike). The split belongs to the session on screen and MOVES to another session after asking about the one it leaves; the button's tooltip names its session. A tab's tooltip carries the title the remote program sets (`OSC 0`/`OSC 2`). Multi-input broadcasts to several sessions with per-session exclusions; a command library holds macros.
- **A production tag can guard the dangerous gestures**: name the tags that mean "careful" (`guard_tags` in `~/.sshmap/config.json`; empty by default) and the application asks once before a multi-input broadcast or a multi-line paste that reaches such a session - the question names the sessions it protects, a single-line paste and every unguarded session are untouched, and `guard_verbs` narrows the guard to one of the two gestures.
- **A destructive command asks before it reaches the fleet**: `rm -rf`, `reboot`, `mkfs`, `dd` onto a device, a fatal `kill` and the like are recognised in the FINAL command line and confirmed once per run - with the count of the servers it would reach - when you run a command from *Plugins*, when a plugin calls its own command service, and when the multi-input broadcast submits a line (`Enter`). A refusal sends nothing and is reported as a result; `guard_commands: false` in `~/.sshmap/config.json` turns the question off. It is a confirmation and never a lock.
- **A command you proved on a server becomes a macro in one gesture**: right-click a row of a session's `History` tab → *Send to Commands…* opens the usual form filled in; a row that looks like a secret is refused instead of stored. Every library change keeps the previous version in a ring of ten (*Restore from a backup…* brings any back), and *Import…* / *Export…* carry the whole library to another machine as JSON.
- SFTP over the same live transport - no second authentication: a directory tree with a typed address bar (`~` and relative paths resolved by the server, names completed as you type), upload/download including drag & drop, a file manager (new folder / rename / delete, an overwrite prompt, atomic transfers, rate and ETA) and a read-only preview (1 MB by default, sized in Settings → Files) with syntax highlighting.
- **Files Commander**: the corner button of the session tab bar opens two directory panes side by side in one tab, each with its own address bar, listing and preview. The pane you last clicked is active (`Tab` / `Shift+Tab` moves between them). `F3` views a row, `F5` copies, `F6` moves into the other pane's directory, `F7` makes a folder, `F8` deletes, `Enter` opens, `Insert` or space marks a row and steps down, `Backspace` goes up a level. The preview opens **in the other pane** (in place when there is one pane), one at a time, `Esc` closes it - and all of these keys stay inside the Files tab: an `F3`–`F8` typed into a shell still reaches the shell.
- **Follow the shell's directory** - off by default: a hook appended to your `PROMPT_COMMAND` moves the listing on every `cd`. In two-pane mode it is greyed out - one shell cannot answer for two panes.
- **Send to ▸ another session**: the context menu of a file row sends it to any open session with its Files listing ready - the dialog names both sides and asks about an existing file. Same server and same login - the file is copied on the server itself; a different server or login - it is relayed through this computer, one file at a time, up to 100 MB, atomic, and a cancelled transfer leaves nothing behind.
- The two panes remember each server's directory (a folder that no longer exists falls back with one status line). A row dragged between panes is copied, or moved with `Shift`; a drop from another session's pane is refused and points at *Send to*.
- Sort any listing by a column (`Name` / `Size` / `Modified`, click again to reverse) - folders stay grouped above the files and `..` stays on top, in both panes and on both sides.
- **The size a preview reads is yours**: Settings → Files sets the ceiling (1 MB default, up to 250 MB, a warning above 3 MB). A bigger file opens instead of being refused - the header says *the first 1.0 MB of 4.0 GB*.
- The preview wraps long lines on request (right-click → **Word wrap**).
- **The reader's encoding is yours too**: the same menu offers eight of them - automatic (UTF-8, then Latin-1), UTF-8, CP1251, CP1252, CP866, KOI8-R, Latin-1 and GBK. The header names the encoding that really read the file, a choice the file cannot be read with says so instead of pretending, and an open preview re-reads the file the moment you switch. Like word wrap it is one setting for every reader.
- **The local pane**: the Files Commander's second pane can read the filesystem of this computer - `Server | Local` in its address row - with the same listing, address bar (`~`, relative paths, a UNC share), preview, file operations and drag & drop. `F5` copies across both ways - one file or a whole folder as a tree, byte for byte and atomically, with the same overwrite question and closing report; `F6` moves inside one side and `F5` never removes an original. A row dragged out of a local pane carries a real OS path (Explorer or an editor accepts it), files dropped from Explorer copy in or upload, and deleting a local entry is permanent - the confirmation says so.
- **An elevated pane**: `Elevated` in the second pane reads the server as ANOTHER user through `sudo` - the `/etc`, `/var/log` or a colleague's home your shell can touch but the session's account cannot. It lists, opens and downloads; it never writes (upload, new folder, rename, delete and any copy or move with that pane at either end answer one sentence). The sudo password is asked once per elevation, goes to sudo alone on its own channel, is never stored, and the elevation ends with the pane.
- **Files display mode** (Settings → Terminal): *Files tab* (the default) keeps the tree in the session's `Files` tab; *Panel beside the shell* lays it out as a right-hand column instead - `[commands | terminal | files]` at once (standalone windows only). The tab hides while the panel is on; the panel folds to a 24 px strip, is mutually exclusive with the Commander, and a single window can switch on the spot from its context menu without changing the setting.
- A **History** tab per server, kept between sessions: import from disk or the server's `~/.bash_history` over SFTP, filter and sort by command, last use or repeat count; copy a row, send it back to the terminal, delete one, merge duplicates, clear the list. A command that looks like a secret is kept **and** marked with a padlock - the mark is a warning, not redaction.
- Set `terminal_scroll` to `"pin"` in `~/.sshmap/config.json` to keep reading history while a build talks (typing returns you to the live line; the default `"live"` pulls the view back). An external system terminal (`ssh`) works as an alternative to the built-in one.

### The list becomes a report
- Collapsing the map turns the sidebar into a 13-column table: alias, host (IP), SSH port, user, status and its age, OS, CPU, RAM, disk and the facts' age, comment, tags.
- Sort by any column - the key follows the data, not the text (`512 MB` before `8 GB`, `10.9.0.1` before `10.10.0.1`, an empty cell last).
- **Export** writes what you see: "Copy List as TSV" and "Export List…" (CSV or TSV, UTF-8 with a BOM) in the order you sorted; "Export Connections…" one row per link with both endpoints, type, direction and the bidirectional flag; "Export Problems…" the warn / offline / stale set with status, reason and check age. A map with nothing to report says so instead of writing an empty file.

### Look, motion & keyboard
- Dark, light and Auto (system) themes, an accent colour picked as a hue, a "Reduce motion" switch; the light palette is measured against each surface and gated by contrast tests. Meaning never lives in a colour alone: every connection type has its own line style, every status its own shape (dot / ring / triangle), and the legend samples both.
- Motion can be interrupted - camera flights, a scale-in on add, hover focus on a connection; the wheel or a drag always wins.
- Command palette on Ctrl+K, a searchable settings hub (8 tabs), all 62 global actions assignable in the Hotkeys tab; `?` or F1 opens the shortcut list. The map works from the keyboard alone (Tab / arrows / Enter).

### Projects & data
- One JSON project file (`.json` / `.sshmap`); a recent-files list, a project dropped onto the window, autosave with a ring of backups - an unreadable file offers its newest autosave or backup instead of dead ends.
- The first screen has three doors: add your first server, **open an existing map**, or open the example map.
- Bulk import from a text file (one host per line) and from `~/.ssh/config` (`Include` recursion, checkbox picker); DNS resolves off the GUI thread; a whole import is one undo step.
- SSH profiles with passwords in the OS keyring - never in a project file.

### Languages & plugins
- English (default), Russian, Chinese and German - plus any language as one JSON file dropped into `~/.sshmap/languages/`; a file there shadows the built-in of the same code, and the Language tab imports and exports without touching the installed package.
- Plugins from an entry point (`sshmap.plugins/v1`) or one file in `~/.sshmap/plugins/`: run a command on selected servers, contribute a status to a card, add palette commands and node-menu rows. A broken plugin is reported instead of freezing the window. Eight working examples ship in `examples/plugins/` - one lesson each, including a monitor that never touches SSH - with the table and the walkthrough in `examples/README.md`.
- The Plugins window (the Plugins menu, or the rightmost switch of the toolbar beside the panel toggles) puts the plugins with their switch on the left, the servers to run on in the middle and what each run reported on the right - with a text export of the visible lines. The history lives until the application exits.
- **A command of your own, without a plugin**: *Plugins → Run a command on servers…* sends one shell command to the servers checked in the Plugins window (or the whole project when none is checked), names how many it reaches, and shows every server's exit code and output in that same window.

---

## 2. Install & Run

```bash
pip install -r requirements.txt   # PySide6, paramiko, keyring, wcwidth (pyte is vendored in third_party/pyte)
python main.py                    # run the GUI
pipx install .                    # or pip install . → the `sshmap` command
```

Requirements: Python 3.10+, Windows / Linux / macOS. Settings live in `~/.sshmap/config.json`, plugins in
`~/.sshmap/plugins/`, languages in `~/.sshmap/languages/`, logs in `~/.sshmap/logs/sshmap.log`.

---

## 3. Project Format (JSON files, `.json` / `.sshmap`)

```json
{
  "version": "0.9",
  "servers":  [{"id": "710602ee", "alias": "...", "host": "...", "user": "...",
                "x": 0.0, "y": 0.0, "cpu": "", "ram": "", "disk": "", "ip": "",
                "comment": "", "ssh_port": 22, "key_path": "",
                "os_name": "", "cpu_model": "", "tags": ["prod", "dev"],
                "info_collected_at": 1750000000.0,
                "quick_launch": [{"type": "url", "name": "Webmin", "value": "http://host:10000/"},
                                 {"type": "command", "name": "K9S", "value": "k9s"}]}],
  "connections": [{"source_id": "...", "target_id": "...", "label": "", "type": "ssh", "bidirectional": true}],
  "notes":  [{"id": "...", "text": "", "x": 0.0, "y": 0.0, "width": 240.0, "height": 160.0, "server_id": "..."}],
  "groups": [{"id": "...", "name": "", "x": 0.0, "y": 0.0, "width": 480.0, "height": 320.0}],
  "background": {"path": "/path/to/background.png", "x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0},
  "zoom": 1.0, "center_x": 0.0, "center_y": 0.0
}
```

Format invariants:
- `password` is never serialized - it lives only in the OS keyring; the loader normalizes old records but never keeps a password in the file.
- Connection types: `ssh|vpn|http|database|nfs|kubernetes`; an unknown or missing type loads as `ssh` (files from 0.6+ are readable). `bidirectional` is written only when true - absent means one-way, and a bidirectional arrow draws heads at both ends.
- Group membership is not stored: each card joins exactly the topmost group whose rect contains its center; a folded group keeps only its `collapsed` and `expanded_width/height` fields.
- `tags` is an array of strings (a broken value becomes empty); a broken `quick_launch` record is dropped.
- `info_collected_at` dates the collected facts as epoch seconds - an age, never a status; missing or invalid means "not dated".
- A note's `server_id` is optional: absent means a free note, a broken reference leaves the note free, and an attached note keeps its saved position so one moved by hand does not jump.
- `background` stores a path to the image, not the file - move it together with the project; a missing file is logged and ignored, and background geometry is not part of undo.

---

## 4. Security & Limitations

Passwords: keyring only (servers by id, profiles as `"profile:{id}"`). Only an allowlisted system backend is accepted -
Windows Credential Manager (`pywin32`, optional in `requirements.txt`), secret-service or netrc on Linux, keychain on
macOS; plaintext fallbacks are rejected. Without a secure backend the app works, but passwords do not survive a restart.
The external terminal is an OS `ssh` process: the password is entered there, never passed in argv.

**Limitations:**
- A host key is never trusted in silence: a missing key opens a window with its algorithm and SHA256 fingerprint to accept explicitly (verify a critical host's fingerprint over a trusted channel), and a CHANGED key shows both fingerprints and offers replacement - also the recovery path after a server is rebuilt. Profile → Known hosts lists, deletes or replaces recorded fingerprints; the file is written atomically and re-read before every addition, and when it cannot be read the session runs **unpinned** and says so.
- A second factor and a private-key passphrase are answered in a window of this application (only when the file really needs one); closing it cancels the connection with a sentence, and neither the code nor the passphrase is stored anywhere.
- A stored password belongs to the endpoint it was saved for (`user@host:port`): change a card's host, user or port and the connect dialog asks again instead of offering it to the new address. A profile password is deliberately not bound this way.
- `~` and relative paths work wherever a local path is typed or stored; an absolute path is used exactly as written.
- The external terminal accepts a host, a user or a jump host only as a plain name (`letters, digits, . - _ : [ ]`) - anything a shell could read as its own syntax is refused; a key path is never restricted.
- Quick-launch links, bookmarks and the terminal's links open `http`/`https` only. The OS opener accepts any registered protocol handler and, on Windows, `webbrowser.open()` *is* `os.startfile()`, so a value from a foreign project could otherwise run a local file or a URI handler - the entry is kept, only the open is refused.
- The production-tag guard is a CONFIRMATION and not a lock - off until you name a tag in `config.json`, asked once per gesture, and it refuses the gesture when no dialog can be shown rather than passing it. The command guard is the same kind of question: on by default, asked once per run or per submitted line, and it recognises the destructive SHAPES a typo takes (`echo cmVib290 | base64 -d | sh` walks past it, and a line edited with history recall or a cursor move is not judged at all).
- A download whose server-side name is invalid on this system (a path separator, a reserved device name such as `NUL`, a trailing dot or space) is refused with a sentence; on Linux the same names are legal and accepted.
- Undo/redo covers the map (nodes, connections, notes, groups, imports, bulk edits, background image, group arrangements) but not node statuses.
- An unreadable project is reported, never repaired silently; recovery means an autosave or backup slot.
- Plugins run inside the application's process: a plugin with a broken C extension can take it down - install plugins you trust.
- The command history is a plain-text file per server under `~/.sshmap/history/` and can carry secrets (a token or password passed as an argument). Passwords typed into a shell are not recorded; a secret-shaped command is marked with a padlock but still kept. The file never enters a project, an export or the log.
- The bookmarks list is plain JSON in `~/.sshmap/bookmarks.json`, outside every project and never exported - a link may carry a token in its query string, so treat it like the history.
- An **unmanaged** card is never monitored or contacted: connect, both terminals, SFTP, gather information, "Check statuses now", "Why is it offline?" and a quick-launch *command* are disabled with the reason in their tooltip; copying, revealing, duplicating, grouping, tagging, notes, search, every export and a quick-launch **URL** keep working.
- The data mount of a card is a path YOU give (`/opt` by default) and reports whatever filesystem `df` really answers for it - `/` when the path has none of its own. A network mount (`nfs`, `cifs`, `smb`, `sshfs`) is never reported as capacity - a share is somebody else's disk - and the disk YOU name for a card wins over the root's figure; both are stored as plain sizes, so the list's `disk` column keeps sorting numerically.
- The Files Commander's two panes share ONE SFTP channel of their session: a long transfer queues behind, not parallel with, the other pane's work, and Cancel stops that shared queue. Every file lands atomically (a cancelled or failed transfer leaves the destination as it was), the overwrite question is asked once for a whole batch ("Apply to all") and one closing line reports copied, skipped and failed. It never edits a remote file and every preview is read-only.
- Copying or moving a folder walks it in one operation bounded at 5000 entries / 32 levels deep per go, then names the file it stopped on instead of half-copying. A symlink is not followed: a link to a file lands as its content, a link to a folder is refused by the server.
- An **elevated** pane is READ-ONLY with another user's rights: `sudo -n -l` decides what the host allows before a channel is opened, the password is typed per elevation and reaches sudo's own STDIN on a separate channel - never a command line, a log or a file - and the elevation is dropped with the pane. It is not a config key and never enters a project.
- The local pane works on THIS computer's disk with your own rights: it copies, moves, renames and deletes real files, and a delete is permanent (no recycle bin). A folder crosses between the sides as a whole tree under the same bounds as a server-side copy, a folder SYMLINK is never followed, and `F5` never removes an original - only `F6` inside one side moves.
- A move is one atomic rename inside one filesystem; across two filesystems (a data disk, a network mount) the server refuses it and says so - copy the item, then delete the original. Moving into an existing same-name folder merges them file by file; the source leaves only once empty.
- **A file sent between two sessions of DIFFERENT servers is relayed through this computer**, so a copy lands in the OS temporary folder for the duration of the transfer (the tightest permissions the platform offers), deleted when the send succeeds, fails or is cancelled, with crashed-run leftovers swept at the next start - nothing of it is logged or kept. Between two sessions of the SAME server the file never leaves the server, and a file over 100 MB is refused before anything is transferred.

---

## 5. Development

Everything is plain Python - no build step, no generated sources.

```bash
python main.py                         # run the GUI
python tests/run_all.py                # the whole suite (exit 0 ⇔ all green)
python tests/run_all.py --fast         # daily profile: skips files tagged slow/network
python tests/run_all.py --tag network  # real-network sections run only on this explicit opt-in
python tests/run_all.py --failed-only  # re-run only the files that failed last time
python tests/test_tags.py              # a single file, from the project root
python tests/check_i18n_keys.py        # translation parity and the keys used in code
```

Tests are plain scripts without pytest: one topical `test_*.py` file per area, each in an isolated process (sandbox HOME,
offscreen Qt), plus a parallel runner that picks the worker count from the CPU count (capped at 16) and starts the
longest files first. The suite map and harness conventions are in `tests/INDEX.md`.

Contributing rules:
- All code text is English: comments, docstrings, UI strings and test labels. Russian, Chinese and German live only in `i18n/ru.json`, `i18n/zh.json` and `i18n/de.json`.
- A new UI string is a new key in **all** language files at once; each built-in language must cover 100% of `en` (keys, `{placeholder}` names, line breaks), and a deliberately incomplete translation may declare `"partial": true`. `check_i18n_keys.py` is the gate. A comment explains what the code does today - never when it changed or what it replaced.
- The pyte fork is vendored on purpose: change it only by adding a patch under `third_party/pyte-patches/` and updating that folder's `MANIFEST.md` (provenance, checksums, policy) - never by editing the sources in `third_party/pyte/`.

PySide6 / Qt 6 gotchas worth knowing before writing UI code:

| Issue | Solution |
|---|---|
| Mouse input in QGraphicsView tests | Only `PySide6.QtTest.QTest.mousePress/Move/Release/DClick` works; hand-crafted QMouseEvents are ignored by the core |
| Monkey-patching C++ slots with return values (`itemChange`, `eventFilter`) | FORBIDDEN: infinite recursion or Access Violation 0xC0000005. Only subclass overrides |
| `QPropertyAnimation(target=QGraphicsItem)` | Does not work ("non-existing property opacity") → use QVariantAnimation |
| `QGraphicsItemGroup.boundingRect()` | Not recomputed from children (zero rect) → explicit override |
| `itemChange(ItemPositionChange)` | Called BEFORE the position is applied → pass target rects explicitly |
| QGraphicsProxyWidget "eats" the mouse | Dragging a widget item is handled manually; the view temporarily switches `dragMode` to NoDrag |
| strokeToFill / strokedPath QPainterPath | Not bound in PySide6 → hit zones via a custom `contains()` with curve sampling |
| `QWidget` focusIn/focusOut signals | Do not exist in Qt6 → eventFilter |
| Death of the Python QAction wrapper with an attached QMenu | PySide6 6.11 destroys the C++ QMenu along with it; keep such QActions permanently and avoid `action.menu()` where a direct path exists |
| `QPdfWriter` coordinates | Paints in device pixels at `resolution()` (1200 dpi by default) while the page layout is in points → set the resolution and draw into `device.width()/height()`; a custom page size is transposed for Landscape (pass the portrait form) |

---

## 6. Repository Layout

| Path | What is in it |
|---|---|
| `main.py` | Entry point: logging → QApplication → MainWindow → plugin discovery → status checks |
| `version.py` | `APP_VERSION` and `VERSION_FORMAT` - the single source of truth |
| `models/` | `ServerData` (a password is never serialized), SSH profiles |
| `graphics/` | The scene and its items: cards, typed arrows, notes, groups, background, the minimap |
| `modules/` | Terminals, SFTP, the pyte fork seam, plugins, the command library and history, undo commands, logging |
| `storage/` | Project save/load, the example map, autosave with backups, the `.drawio` writer |
| `services/` | Credentials, probes, reachability diagnostics, info batches, importers |
| `dialogs/` | Add/edit dialogs, connect, profiles, backups, imports, export options |
| `ui/` | Main window and mixins, sidebar, theme, palette, panels, settings, hotkeys, icons |
| `i18n/` | `en` (reference), `ru`, `zh`, `de` - one JSON file per language |
| `tests/` | 141 test files, the parallel runner and the harness - map in `tests/INDEX.md` |
| `examples/plugins/` | Eight working example plugins, one lesson each, not installed and never auto-discovered (table: `examples/README.md`) |
| `third_party/pyte/`, `third_party/pyte-patches/` | The managed pyte 0.8.2 fork: sdist plus explicit patches, provenance in the patches' `MANIFEST.md` |
| `docs/` | The map image above, rendered from the example map |
| `PLUGINS.md` | The plugin contract (API v1): manifest, hooks, context, isolation |
| `pyproject.toml`, `requirements.txt` | Installable identity (`sshmap` command) and the dependencies |
| `LICENSE` | MIT |
