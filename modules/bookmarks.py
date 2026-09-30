# -*- coding: utf-8 -*-
""""The bookmarks" — ONE application-level place for the links (AGENTS.md §4.23; DOCUMENTATION.md §57).

The quick launch of a card is PER SERVER, so a link that belongs to nobody's server (the team wiki, a
dashboard, a hypervisor console, the ticket queue) has no home in the application at all. This module is
that home: ONE user file, `~/.sshmap/bookmarks.json`, holding the very entry SHAPE the project already
declares for a quick launch entry — `{"type": "url", "name", "value"}` — so the sanitizer is the
EXISTING `models.server.sanitize_quick_launch()` and there is no second copy of it.

Pinned: the list is GLOBAL and it is ONE file (a per-server list would be a second truth, so the panel
names no server and the file lives OUTSIDE the project — `VERSION_FORMAT` does not move); a
`"type": "command"` entry is KEPT but NOT OFFERED (it needs a target host the global list cannot name,
but it is user data: loaded, written back untouched, never listed); the file is read `utf-8-sig` and written with an atomic MERGE-write whose foreign top-level keys survive; a broken file is SKIPPED with a log line, never a crash and never a silent overwrite; and the module is HEADLESS (pure Python, no Qt) — `ui/bookmark_panel.py` renders it and `dialogs/bookmark_edit_dialog.py` edits it through `get_bookmark_store()`. `ui.main_window` is never imported (the "module + callbacks" pattern)."""

import json
import os

try:  # the ONE entry sanitizer of the project — never a second copy of it
    from ..models.server import sanitize_quick_launch
except ImportError:  # flat layout: the project root is on sys.path
    from models.server import sanitize_quick_launch


#: The entry type the panel OFFERS. The file may carry others (a `command` entry is kept
#: and written back, never listed) — the sanitizer's shape is reused, the scope is narrower.
BOOKMARK_TYPE = "url"

#: The declared cap of the URL list. A write never lets the file grow past it and `add()`
#: refuses at the bound instead of silently dropping an entry (the `MAX_ENTRIES_PER_SERVER`
#: rule of `modules/command_history.py`, applied to a list a human edits by hand).
MAX_BOOKMARKS = 200

#: The document key holding the entry list. A bare JSON list is accepted on READ as well
#: (a hand-edited file), so a hand-edit is never a reason to lose the links.
DOC_KEY = "bookmarks"


def _log():
    """The app logger (lazy — the module is imported by the startup path)."""
    try:
        from modules.logger import get_logger as _gl
        return _gl("modules.bookmarks")
    except Exception:  # noqa: BLE001 — logging must never break a read
        return None


def default_store_path() -> str:
    """`~/.sshmap/bookmarks.json` — next to `config.json` (the `commands.json` precedent)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "bookmarks.json")


def _atomic_write_json(path: str, doc) -> bool:
    """An atomic write of the WHOLE document (tmp + flush + fsync + os.replace).

    The `i18n.save_config` technique (which is what makes a half-written file impossible);
    False on OSError, and a failed write leaves no `*.tmp` behind (v1.6.1 rule)."""
    directory = os.path.dirname(path)
    tmp = path + ".tmp"
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # an atomic rename (one file system)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def filter_entries(entries, text: str) -> list:
    """The PURE filter of the panel: a case-insensitive substring of the NAME or the URL.

    An empty (or unusable) query answers every entry, so "no filter" and "a cleared field"
    are one state. The widget renders; this function decides — the
    `modules/activity_log.matches_level()` split.
    """
    items = list(entries or [])
    query = str(text or "").strip().casefold()
    if not query:
        return items
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").casefold()
        value = str(entry.get("value") or "").casefold()
        if query in name or query in value:
            out.append(entry)
    return out


def url_entries(entries) -> list:
    """Only the entries the panel may OFFER (`type == "url"`), in file order.

    The store's list is the file's; this is the panel's SCOPE — a `command` entry stays in
    the file and never reaches a surface that could not run it (it has no host to run on).
    """
    return [dict(e) for e in (entries or [])
            if isinstance(e, dict) and str(e.get("type") or "").strip().lower() == BOOKMARK_TYPE]


class BookmarkStore:
    """The bookmarks store (`~/.sshmap/bookmarks.json`) — pure Python, no Qt.

    The document is `{"bookmarks": [{type, name, value}, …]}`; a bare JSON list is accepted
    on read (a hand-edited file). Every write RE-READS the file first, so
    `load()`/`save()` never raise, a corrupt file is a log line plus an empty list, and the
    foreign top-level keys of the document survive (the merge-write rule).
    """

    def __init__(self, path: str = None):
        self.path = path or default_store_path()

    # ── reading ─────────────────────────────────────────────────────────────

    def _read_document(self):
        """The raw document (a dict) or None when the file is missing/unreadable.

        A bare list is wrapped into `{DOC_KEY: [...]}` so both shapes share ONE path. A
        broken file answers None and is NEVER rewritten by this read."""
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            lg = _log()
            if lg is not None:
                lg.warning(f"bookmarks: unreadable file {self.path} — skipped ({e})")
            return None
        if isinstance(data, list):
            return {DOC_KEY: data}
        if isinstance(data, dict):
            return data
        lg = _log()
        if lg is not None:
            lg.warning(f"bookmarks: unexpected document type in {self.path} — skipped")
        return None

    def load(self) -> list:
        """Every usable entry of the file (the panel filters the `url` ones itself).

        A missing file is an EMPTY list and is never created by a read; corrupt records are
        dropped one by one by the project's ONE sanitizer (`sanitize_quick_launch`), so a
        hand-edited junk entry costs itself and nothing else."""
        doc = self._read_document()
        if doc is None:
            return []
        raw = doc.get(DOC_KEY)
        return [dict(e) for e in sanitize_quick_launch(raw)]

    def load_urls(self) -> list:
        """The entries the panel OFFERS (`type == "url"`), in file order."""
        return url_entries(self.load())

    def is_full(self) -> bool:
        """Has the URL list reached the declared cap?"""
        return len(self.load_urls()) >= MAX_BOOKMARKS

    # ── writing ─────────────────────────────────────────────────────────────

    def save(self, entries) -> bool:
        """Write the WHOLE entry list, keeping the document's foreign top-level keys.

        A merge-write: the existing document is re-read and only `DOC_KEY` is replaced, so a
        key a plugin or a hand-edit put beside the list survives. The list is sanitized on
        the way out (the file never carries a record the reader would drop)."""
        clean = [dict(e) for e in sanitize_quick_launch(list(entries or []))]
        doc = self._read_document() or {}
        doc[DOC_KEY] = clean
        return _atomic_write_json(self.path, doc)

    def save_urls(self, url_entries_) -> bool:
        """Write the URL list the panel owns, leaving every FOREIGN entry where it is.

        The panel owns the `url` subset and nothing else: the file's other entries (a
        `command` a hand-edit or a plugin typed) keep their POSITION — the URL entries fill
        the URL slots in the given order and any extra ones are appended at the end. That is
        the rule behind "a `command` entry survives a save/load and is never listed"."""
        urls = [dict(e) for e in sanitize_quick_launch(list(url_entries_ or []))
                if str(e.get("type") or "").strip().lower() == BOOKMARK_TYPE]
        urls = urls[:MAX_BOOKMARKS]
        current = self.load()
        merged = []
        pending = list(urls)
        for entry in current:
            if str(entry.get("type") or "").strip().lower() == BOOKMARK_TYPE:
                if pending:
                    merged.append(pending.pop(0))
                continue
            merged.append(entry)
        merged.extend(pending)
        return self.save(merged)

    # ── the list operations of the editor ───────────────────────────────────

    def add(self, name: str, value: str) -> bool:
        """Append ONE URL entry. False when the list is full or the pair is unusable."""
        name = str(name or "").strip()
        value = str(value or "").strip()
        if not name or not value:
            return False
        urls = self.load_urls()
        if len(urls) >= MAX_BOOKMARKS:
            return False
        urls.append({"type": BOOKMARK_TYPE, "name": name, "value": value})
        return self.save_urls(urls)

    def update(self, index: int, name: str, value: str) -> bool:
        """Replace the URL entry at `index` in place (its position does not move)."""
        name = str(name or "").strip()
        value = str(value or "").strip()
        if not name or not value:
            return False
        urls = self.load_urls()
        if not (0 <= int(index) < len(urls)):
            return False
        urls[int(index)] = {"type": BOOKMARK_TYPE, "name": name, "value": value}
        return self.save_urls(urls)

    def remove(self, index: int) -> bool:
        """Drop the URL entry at `index` (the foreign entries are untouched)."""
        urls = self.load_urls()
        if not (0 <= int(index) < len(urls)):
            return False
        del urls[int(index)]
        return self.save_urls(urls)

    def move(self, index: int, delta: int) -> bool:
        """Move the URL entry at `index` by `delta` places — the list's own order.

        A move past either end is REFUSED instead of wrapping around: the order of the panel
        is the order of the file, and a wrap would make it unpredictable."""
        urls = self.load_urls()
        index = int(index)
        target = index + int(delta)
        if not (0 <= index < len(urls)) or not (0 <= target < len(urls)):
            return False
        urls[index], urls[target] = urls[target], urls[index]
        return self.save_urls(urls)


# ── the module-level singleton (the `command_library` / `activity_log` pattern) ─────

_store = None


def get_bookmark_store() -> BookmarkStore:
    """The ONE store of the process (a panel and a dialog share it).

    Headless by construction: an explicit `BookmarkStore(path=…)` is the test seam, and this
    singleton simply points at the default location for the application."""
    global _store
    if _store is None:
        _store = BookmarkStore()
    return _store
