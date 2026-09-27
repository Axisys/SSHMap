# SSHMap (Visual Node Map + SSH Terminal and SFTP manager)

Desktop application (Python + PySide6): an interactive map of your IT infrastructure with direct SSH connections to nodes.
*"Draw your infrastructure. Organize it. Connect to it."*

![The example map in SSH Map](docs/map-example.png)

*The example map (Help → Open the example map): five servers and six connections — one of every type — plus a group, a
note and tags, all on documentation addresses (`192.0.2.0/24`) with statuses marked as emulated. The picture is
generated from that example map only, by `python tests/_gen_docs_image.py`.*

---

## 1. Features

### Map & canvas
- Server cards with a status, six typed connections (`ssh`, `vpn`, `http`, `database`, `nfs`, `kubernetes`), free and pinned sticky notes, groups and a background image (drag and resize it) — on an infinite zoomable canvas (0.1–5.0).
- Draw a connection two ways: hold `Shift` and drag from one card to another, or pick **"Connect to…"** in a card's right-click menu (both open the same dialog with the source filled in). The dialog's From/To pickers can be typed into — type part of a name or of an address and pick the server from the list.
- A group can be folded into a grid of badges (undoable) and answers for its members: its frame carries the worst member status as a shape plus the counts (`Offline 2 · Warn 1`).
- Multi-selection (Ctrl+click, rubber band), group drag, "connect selected" / "delete selected"; **bulk edit** of the selected cards (tags, comment, quick launch in one undo step, each field "leave unchanged" by default); per-server quick launch (URL → browser, command → first line of the SSH session); tags with a sidebar filter — the primary tag colours the card's icon and is written on the card, so the environment is never a colour alone.
- A card density switch (Comfortable / Compact) in the settings hub: the compact card keeps the alias, the host and the status marks and drops the information block and the environment chip — for a map of hundreds of nodes.
- A group can be lined up in one gesture (a vertical line, a horizontal line, or rows of N cards) — the arrangement moves cards and is one undo step; the group frame itself is never resized.
- Several connections between the same two servers are drawn as parallel arcs (a second link bends aside instead of hiding under the first), and a drag of the background image comes back with Ctrl+Z.
- Minimap, legend and an **Export** menu that holds everything which leaves the application: "Copy Map as Image", PNG, JPEG, PDF, SVG and `.drawio` — print-friendly by default (a light page with high-contrast lines), with "use the current theme" as a one-click opt-out. "Save Documentation Image…" writes a fixed 1600×900 @2× poster of the map, and the two data reports (below) sit in the same menu.
- **Bookmarks**: one place for the links the team uses — a wiki, a dashboard, a hypervisor's console. The panel lists every entry as a name with its address under it, filters as you type, opens a link in your browser on a double click or Enter, and remembers its state between runs; "Edit bookmarks…" adds, edits in place, reorders and removes entries. The list lives in `~/.sshmap/bookmarks.json`, outside every project — a shared map never carries another machine's links.

### Statuses, facts & diagnostics
- `online` / `warn` / `offline` from parallel SSH probes (TCP + banner) off the GUI thread; a status carries its age and turns grey once it is stale — the status itself never changes, and "Check statuses now" runs a round on demand. The cadence has a third setting, **manual only** (`status_interval_sec = 0`, or the checkbox in the Status Checks tab): nothing is probed on its own — not at startup, not when a project is opened — while the on-demand round keeps working; the age of a status is then the only signal, and a status older than a day is marked stale.
- Collected hardware facts (OS / CPU / RAM / disk / IP) are dated too, and one click gathers them for a selection or the whole map through a bounded queue with progress and a summary that names the failures.
- The disk facts read **two** filesystems: the root, and the node's **data mount** (a per-card path, `/opt` by default) — so a server whose capacity lives on a separate volume reports that volume's free space and capacity on its card (`DISK /opt: 48 gb free of 59 gb`) instead of only the root's small number. A mount that is a **network share** is refused by name and never counted as local capacity, and the answer names the mount point the server really reported.
- "Why is it offline?" asks a red card a direct question: DNS resolve → TCP connect → SSH banner → ICMP ping, in order, naming the first failing step in its own words. It explains; it never rewrites the status.
- Trouble first: one click dims everything that is not warn, offline or stale, and a floating plaque names every active filter (search, tag, status, lens) with one × each.
- **The neighbours on the map:** mark a server as **unmanaged** and it keeps its place in the diagram without pretending. Such a card stores no credentials, no probe round ever touches it, no SSH verb reaches it, and its band carries a "no ssh" mark while its tooltip says "not monitored" — the honest answer for a box nobody here administers. You can still ping it one card at a time if you switch that on; the answer is a manual note, never a status.

### Terminal & SFTP
- Built-in SSH terminal on a vendored pyte fork: scrollback, full keyboard, mouse selection, alternate screen (vim/htop/less restore the previous screen), wheel passthrough to TUIs, a find bar, clear scrollback / reset screen / save transcript, and correct multi-code-point glyphs (emoji sequences and combining marks render as one cell, wide where the emoji is wide). Every glyph is drawn at its own grid cell, so a frame stays aligned whatever monospace font you pick.
- The terminal speaks the mouse protocol a full-screen program asks for: a click, a drag and a release are reported to it (not swallowed by the local selection), `Shift` keeps the selection and the scrollback for you, and a program that left the mouse mode behind after a crash is bypassed the same way — hold `Shift` to scroll.
- The cursor is a thin blinking bar (the Windows Terminal look) out of the box, and its shape is yours to pick — Bar, Block or Underline — in the Terminal tab of the settings.
- A program that draws its frames with the VT100 special graphics (an `mc` panel, a `dialog` box) gets the frames, not the letters, and a session whose server went away says so instead of freezing on a blinking cursor.
- Sessions as tabs in separate windows or in a detachable "Terminals" dock on the map, a split pane with a second shell of the same node, multi-input broadcast with per-session exclusions, and a command library of macros.
- SFTP over the same live transport (no second authentication): a directory tree with a typed address bar (`~`, a relative path and a symlink are resolved by the server, and the field completes the names as you type), upload/download including drag & drop, a file manager (new folder / rename / delete, an overwrite prompt, atomic transfers, rate and ETA) and a read-only text preview (≤ 1 MB) with syntax highlighting and "no preview" row markers.
- The Files tab can follow the shell: switch it on with "Follow the shell's directory" and the listing moves every time a `cd` in the terminal does (the hook the tab installs is appended to your `PROMPT_COMMAND` and never replaces it; off by default).
- The Files tab has a two-pane **Files Commander**: the button in the corner of the session tab bar (next to "Split Terminal") shows two directory panes side by side in one tab, each with its own address bar, listing and preview. The pane you last clicked is the *active* one — it is outlined, the keys belong to it, and `Tab` (or `Shift`+`Tab`) moves the keyboard to the other pane. The left pane keeps the usual `Up` / `Refresh` / `Upload` / `Download` / `Cancel` buttons; the right one shows the key hints instead. `F3` views the row under the cursor, `F5` **copies** and `F6` **moves** the selected rows into the other pane's directory, `F7` makes a folder, `F8` deletes it; `Enter` opens the row under the cursor, `Insert` (or the space bar) **marks** it and moves down so several files can be picked without the mouse, `Backspace` goes one level up and `←` on a folder jumps to its parent row. **A preview opens in the other pane** — the file appears where the second pane is, while the pane you are browsing keeps its cursor and its keys — and **`Esc` closes it** (from either pane, and from inside the panel itself). Only one preview is open at a time — a file opened while the *other* pane is previewing is refused with a message, and `Esc` is the way through — while the pane that opened the preview keeps walking its listing: `↓` then `F3`/`Enter` shows the next file in the same place, exactly like a classic commander. **The pane that shows the file stops being a listing while it does**: its own directory listing and its keys step aside, so the file gets that whole half of the tab (the `far` quick view — `Tab` does nothing while the panel is up). A file the reader cannot show (a binary, or one over the limit) leaves both panes exactly as they were and says why. With one pane the preview stays inside that pane. With one pane `F6` renames in place, and all of these keys work only inside the Files tab, so an `F3`–`F8` typed into a shell still reaches the shell. Copying or moving a folder carries the whole tree with it, and every single file lands atomically: a cancelled or failed transfer leaves the destination exactly as it was, and a tree that stopped halfway says which file it stopped on instead of pretending it finished. If a name already exists in the target directory the overwrite question is asked **once** for the whole batch ("Apply to all" covers the rest), a skipped file is counted, and one closing line reports how many were copied, skipped and failed. The two panes are one connection: the mode remembers itself between runs, and the "follow the shell's directory" switch is off and greyed while it is on (one shell directory cannot answer for two panes).
- A **History** tab per session: the commands of that server, kept between sessions. Import a history file from disk or the server's `~/.bash_history` over the session's SFTP channel, filter and sort the rows by their data (command, last use, repeat count), copy one, send one back to the terminal, delete a single row, merge the duplicates and clear the list. A command that looks like it carries a secret (a password or a token in the line) is kept AND marked with a padlock in the list, so nothing you really sent disappears silently.
- The wheel zooms the font: `Ctrl`+wheel steps the terminal's point size by one and remembers it; it is the same setting the Terminal tab shows, so a restart keeps the size you picked.
- A session that produced output while you were looking at another one marks its tab with a dot (and says so in the tab's tooltip); switching to that tab clears it.
- The scrollback behaves like a real terminal's when you want it to: with `terminal_scroll` set to `"pin"` in `~/.sshmap/config.json` (the default, `"live"`, is the behaviour above) new output no longer pulls you back to the bottom while you are reading history — typing or pasting returns you to the live line.
- External system terminal as an alternative to the built-in one.

### The list becomes a report
- Collapsing the map turns the sidebar into a 13-column table: alias, host (IP), SSH port, user, status, the age of the status, OS, CPU, RAM, disk, the age of the facts, comment and tags.
- Sort by any column — the key follows the data, not the text (`512 MB` before `8 GB`, `10.9.0.1` before `10.10.0.1`, an empty cell last).
- Take it with you: "Copy List as TSV" and "Export List…" (CSV or TSV, UTF-8 with a BOM) in the **Export** menu write exactly the columns and rows you see, in the order you sorted them.
- "Export Connections…" writes the other half of the map — one row per link with both endpoints, the declared type, the direction and the bidirectional flag, in the same CSV/TSV form.
- "Export Problems…" writes the servers that need a look — the same set the "problems only" dim highlights (warn, offline or a stale measurement), with the status, the reason and the age of the check, in the same CSV/TSV form. A map with nothing to report says so instead of writing an empty file.

### Look, motion & keyboard
- Dark, light and Auto (system) themes, an accent colour picked as a hue, and a "Reduce motion" switch; the light palette is measured against the surface each tone is drawn on and gated by contrast tests.
- Meaning never lives in a colour alone: each connection type has its own line style, each status its own shape (dot / ring / triangle), and the legend samples both.
- Motion that can be interrupted: camera flights, a scale-in on add, hover focus on a connection — the wheel or a drag always wins.
- Command palette on Ctrl+K, a searchable settings hub (8 tabs), and every one of the 60 global actions assignable in the Hotkeys tab; `?` or F1 opens the shortcut list. The map also works from the keyboard alone (Tab/arrows/Enter).

### Projects & data
- One JSON project file (`.json` / `.sshmap`), a recent-files list, a project dropped onto the window, autosave with a ring of backups, and rollback — an unreadable file offers its newest autosave or backup instead of a dead end.
- A first screen with three doors: add your first server, **open an existing map**, or open the example map.
- Bulk import from a text file (one host per line, DNS resolved off the GUI thread) and from `~/.ssh/config` (with an `Include` recursion and a checkbox picker); a whole import is one undo.
- SSH profiles with passwords in the OS keyring — never in a project file.

### Languages & plugins
- English (default), Russian, Chinese and German, plus any other language as one JSON file in `~/.sshmap/languages/`; a file there shadows the built-in one of the same code, and the Language tab imports and exports files without touching the installed package.
- Plugins from an installed entry point (`sshmap.plugins/v1`) or from one file in `~/.sshmap/plugins/`: a plugin can run a command on selected servers, contribute a status to a card, and add palette commands and node-menu rows. UI hooks are timed and background hooks run on managed threads, so a broken plugin is reported instead of freezing the window.

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
- `password` is never serialized; it lives only in the OS keyring (the loader normalizes old records but never keeps a password in the file).
- Connection types: `ssh|vpn|http|database|nfs|kubernetes`; an unknown or missing type loads as `ssh` (files from 0.6+ are readable).
- `bidirectional` is optional on a connection record: written only when true, absent means a one-way arrow. A bidirectional arrow draws heads at both ends of the curve.
- Group membership is not stored; it is computed from geometry. Each card joins exactly the topmost group whose rect contains its center, and a folded group keeps only its `collapsed` and `expanded_width/height` fields.
- `tags` is an array of strings; a missing or non-array value in an old file becomes an empty list, and a broken `quick_launch` record is dropped.
- `info_collected_at` is when the collected facts were measured, as epoch seconds. It is written only when a server has one; a missing, null, non-numeric or negative value means "not dated" and the card stays unmarked. The key holds an age, never a status.
- `server_id` on a note is optional: absent means a free note, and a broken reference leaves the note free at its saved position. An attached note keeps its saved position, so a note moved by hand does not jump.
- `background` stores a path to the image, not the file itself; a missing file is logged and ignored. Background geometry is not part of undo.

---

## 4. Security & Limitations

Passwords: keyring only (servers by id, profiles as `"profile:{id}"`). Only an allowlisted system backend is accepted —
Windows Credential Manager (requires `pywin32`, optional in `requirements.txt`), secret-service or netrc on Linux,
keychain on macOS; plaintext fallbacks are rejected. Without a secure backend the app still works, but passwords do not
survive a restart. The external terminal is an OS `ssh` process: the password is entered there, never passed in argv.

**Limitations:**
- TOFU on first connect: a host key that is not in `~/.sshmap/known_hosts` is accepted automatically (the fingerprint is logged). Protection kicks in when an already-recorded key changes, so verify the first-connect fingerprint of a critical host over a trusted channel.
- Undo/redo covers the map (nodes, connections, notes, groups, imports, the bulk edit of a selection, the background image and a group arrangement) but not node statuses.
- The background image is stored by path: move the file together with the project.
- Several connections between the same two servers are drawn as parallel arcs; a group arrangement moves the cards and never resizes the group frame, so a member pushed outside the frame leaves the group (one Ctrl+Z brings the whole arrangement back).
- Plugins run inside the application's process: a plugin with a broken C extension can take it down — install plugins you trust.
- A host key change and an unreadable project are reported, never repaired silently; recovery means an autosave or backup slot.
- The command history is a plain-text file per server under `~/.sshmap/history/`. Its entries are the commands the application sent or the ones you imported, so they can contain secrets (a token or a password passed as an argument); the file is never written into a project, never exported and never logged. Passwords typed into a shell are not recorded — only what the app itself sends is. A sent command that matches one of the declared secret shapes is marked in the list (the padlock and its tooltip) and is still kept: the mark is a warning, not a redaction, so the file itself stays plain text.
- The bookmarks list is the same kind of local file — plain JSON in `~/.sshmap/bookmarks.json`, never written into a project and never exported. A link may carry a token in its query string, so treat the file the way you treat the command history: it holds what you put there, and opening an entry hands the address to your browser.
- **Manual only means no automatic traffic at all** (`status_interval_sec = 0` in `~/.sshmap/config.json`, or the checkbox in the Status Checks tab): no round starts at launch or when a project is opened, so nothing is checked unless you ask. The age of a status is then the only signal — a green card is not refreshed behind your back, and a status older than a day is marked stale. "Check statuses now" and the card's own menu keep probing.
- The data mount of a card is a path YOU give (`/opt` by default) and the card reports the mount point the server's `df` really answered for it — which is `/` when that path has no filesystem of its own, so a data directory on the root is shown as the root, not as a mount of its own. A mount on a network filesystem (`nfs`, `cifs`, `smb`, `sshfs`) is deliberately **not** reported as capacity: a share is somebody else's disk, and the refusal is a line in the status bar and the activity history rather than a number. `disk`, the column of the list view, stays the ROOT's capacity.
- `terminal_scroll` (a `~/.sshmap/config.json` key, no settings row) defaults to `"live"`: new output pulls the view back to the bottom. Set it to `"pin"` if you would rather keep reading history while a build talks — then typing or pasting returns you to the live line.
- A full-screen program that dies without turning its mouse reporting off leaves that mode on in the session: the wheel keeps reporting to a program that is no longer there until you hold `Shift` (which always scrolls the scrollback) or reopen the session.
- "Follow the shell's directory" writes one line into the shell of that session at connect (appended to `PROMPT_COMMAND`, with a `zsh` variant). It is off by default; a shell that never answers simply does not follow, and the tab keeps working. In the two-pane Files Commander the switch is off and greyed: one shell directory cannot say which of the two panes should move.
- The Files Commander downloads, uploads, renames, copies, moves and deletes; it never edits a remote file. The preview of a file is read-only and has no "save" — a remote config is edited on the server, in an editor you trust, not through this window.
- The two panes of the Files Commander share the ONE SFTP channel of their session (one authentication, one queue): a long transfer in one pane is queued behind, not parallel with, the operations of the other, and "Cancel" stops that shared queue.
- Copying or moving a folder walks it in one operation, so very large trees are bounded on purpose (5000 entries / 32 levels deep in one go, then it says so instead of half-copying): split a huge folder into parts. A symbolic link is not followed as a link — the SFTP protocol cannot read a link target, so a link to a file is copied as that file's content and a link to a folder is refused by the server.
- A move between two directories is one atomic rename, which the server can only do inside one filesystem. Across two filesystems (a data disk, a network mount) the server refuses it and the app says so instead of guessing: copy the item, then delete the original. Moving a folder into a folder that already has that name merges them file by file, and the source folder is removed only once it is empty.
- An **unmanaged** card is never monitored and is never contacted: it holds no credentials (the keyring is never written for it, and a password that reaches the model by any other route is not stored either), the status round skips it together with the demo's emulated nodes, and every verb that needs a login — connect, the external terminal, the built-in terminal and its SFTP tab, gather information, "Check statuses now", "Why is it offline?" and a quick-launch *command* — is disabled with the reason in its tooltip. Copying its IP or hostname, revealing, duplicating, grouping, tagging, notes, the search and every export keep working, and a quick-launch **URL** still opens (the browser needs no shell on that host). The one network call such a card can make is the per-card ICMP check, OFF by default; its answer is a note marked as a manual result and never becomes a status. Older builds read the card as a fully managed one.

---

## 5. Development

Everything is plain Python — no build step, no generated sources.

```bash
python main.py                         # run the GUI
python tests/run_all.py                # the whole suite (exit 0 ⇔ all green)
python tests/run_all.py --fast         # daily profile: skips files tagged slow/network
python tests/run_all.py --tag network  # real-network sections run only on this explicit opt-in
python tests/run_all.py --failed-only  # re-run only the files that failed last time
python tests/run_all.py --junit        # JUnit XML report → test-results/junit.xml
python tests/test_tags.py              # a single file, from the project root
python tests/check_i18n_keys.py        # translation parity and the keys used in code
```

Tests are plain scripts without pytest: one topical `test_*.py` file per area, each in an isolated process (sandbox
HOME, offscreen Qt, UTF-8 stdout), plus one parallel runner. `run_all.py` picks the worker count from the CPU count
(capped at 16) and starts the longest files first. The suite map and the harness conventions are in `tests/INDEX.md`.

Contributing rules:
- All code text is English: comments, docstrings, UI strings and test labels. Russian, Chinese and German live only in `i18n/ru.json`, `i18n/zh.json` and `i18n/de.json`.
- A new UI string is a new key in **all** language files at once; each built-in language must cover 100% of `en` in keys, `{placeholder}` names and line breaks. A deliberately incomplete translation may declare `"partial": true`, which downgrades its missing keys to warnings. `check_i18n_keys.py` is the gate.
- A comment explains what the code does today — never when it changed or what it replaced.
- The pyte fork is vendored on purpose: change it only by adding a patch under `third_party/pyte-patches/` and updating that folder's `MANIFEST.md` (provenance, checksums, policy) — never by editing the sources in `third_party/pyte/`.

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
| `version.py` | `APP_VERSION` and `VERSION_FORMAT` — the single source of truth |
| `models/` | `ServerData` (a password is never serialized), SSH profiles |
| `graphics/` | The scene and its items: cards, typed arrows, notes, groups, background, the minimap |
| `modules/` | Terminals, SFTP, the pyte fork seam, plugins, the command library and the command history, undo commands, logging |
| `storage/` | Project save/load, the example map, autosave with backups, the `.drawio` writer |
| `services/` | Credentials, probes, reachability diagnostics, info batches, importers |
| `dialogs/` | Add/edit dialogs, connect, profiles, backups, imports, export options |
| `ui/` | Main window and mixins, sidebar, theme, palette, panels, settings, hotkeys, icons |
| `i18n/` | `en` (reference), `ru`, `zh`, `de` — one JSON file per language |
| `tests/` | 116 test files, the parallel runner and the harness — map in `tests/INDEX.md` |
| `examples/plugins/` | Two working example plugins, not installed and never auto-discovered |
| `third_party/pyte/`, `third_party/pyte-patches/` | The managed pyte 0.8.2 fork: sdist plus explicit patches, provenance in the patches' `MANIFEST.md` |
| `docs/` | The map image above, rendered from the example map |
| `PLUGINS.md` | The plugin contract (API v1): manifest, hooks, context, isolation |
| `pyproject.toml`, `requirements.txt` | Installable identity (`sshmap` command) and the dependencies |
| `LICENSE` | MIT |
