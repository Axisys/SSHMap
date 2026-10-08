# -*- coding: utf-8 -*-
"""The read-only PREVIEW of ONE Files pane (`_SftpPane` wave 1).

`SftpPaneViewerMixin` owns the reader: the panel's share of the `QSplitter`, the read task and its
answer, the header (size, the truncation notice, the encoding, the heuristic language), the pane's
ONE `QSyntaxHighlighter` with its lazy window, the word-wrap mode and the ENCODING choice
(`ui_viewer_encoding`), and the panel's MOVE into the other pane (`present_viewer_in()` /
`restore_viewer()` — the mc/far preview of `SFTP_PANES.md` §3b). The reader's CEILING
(`ui_viewer_max_bytes`) is resolved ONCE by the pane and travels in the task, so the workers read no
config (`AGENTS.md` §4.8, §4.15).

Contract — `SFTP_PANES.md` §3b; mechanism — `DOCUMENTATION.md` §38, §64.
"""
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QPlainTextEdit, QTreeWidgetItem

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # v1.4.7 (ROADMAP task 4): detection + tokenizers + the ONE highlighter
    from . import syntax_highlight as syntax
except ImportError:
    import syntax_highlight as syntax

try:  # v1.3.1: the shipped read policy — the FLOOR of the reader's ceiling
    from .sftp_worker import MAX_READ_BYTES
except ImportError:
    from sftp_worker import MAX_READ_BYTES

try:  # v1.9.3: the DECLARED encoding list, its normaliser and the value of "the shipped rule"
    from .sftp_pane_helpers import (VIEWER_ENCODING_DEFAULT, VIEWER_ENCODINGS,
                                    normalize_viewer_encoding)
except ImportError:
    from sftp_pane_helpers import (VIEWER_ENCODING_DEFAULT, VIEWER_ENCODINGS,  # type: ignore
                                   normalize_viewer_encoding)

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

#: v1.7.5: the reader's CEILING as a SETTING — the reader truncates at the cap instead of refusing
#: the file, so `MAX_READ_BYTES` (the shipped read policy) is the DEFAULT and the FLOOR of this key
#: while the slider's top is a DECLARED 250 MiB. The pane resolves the cap ONCE and hands it to the
#: task (`_SftpTask.max_bytes`), so the worker never reads a config (AGENTS.md §4.8, §4.15).
VIEWER_MAX_BYTES_CONFIG = "ui_viewer_max_bytes"
VIEWER_MAX_BYTES_MIN = MAX_READ_BYTES            # 1 MiB — the shipped policy is the smallest cap
VIEWER_MAX_BYTES_MAX = 250 * 1024 * 1024         # the slider's hard top
VIEWER_MAX_BYTES_STEP = 1024 * 1024              # one step of the slider and of the value box
#: Above this the settings page WARNS: a `QPlainTextEdit` fed tens of megabytes is seconds of freeze.
VIEWER_MAX_BYTES_WARN = 3 * 1024 * 1024

#: The GUI cost of the ceiling, MEASURED (N57): the dominant term of one preview is
#: `QPlainTextEdit.setPlainText()` — the document build and layout — at ~159 ms per MiB, while the
#: decode (~0.17 ms/MiB) and the syntax verdict (~1.2 ms/MiB) are noise beside it. The freeze
#: cannot leave the GUI thread (a `QPlainTextEdit` document is built there), so the number is the
#: PRICE the setting carries, and the settings row prints it for the cap the user is choosing.
VIEWER_FREEZE_MS_PER_MB = 159.0


def viewer_freeze_seconds(cap) -> float:
    """PURE (N57): the seconds one preview of a `cap`-byte file costs on the GUI thread.

    A foreign value answers `0.0` — the caller is a label, never a gate. The slope is the declared
    `VIEWER_FREEZE_MS_PER_MB`, so the warning and the measurement cannot drift apart.
    """
    try:
        mib = max(0.0, float(cap) / (1024 * 1024))
    except (TypeError, ValueError):
        return 0.0
    return mib * VIEWER_FREEZE_MS_PER_MB / 1000.0


class SftpPaneViewerMixin:
    """The read-only preview panel of ONE Files pane (mixed into `_SftpPane`)."""

    # v1.3.1: the preview panel — the tree's share of the splitter on the first open.
    VIEWER_TREE_SHARE = 0.45

    # v1.3.1: the width the share above is measured against while the splitter is not laid out yet
    # (a panel opened on a never-shown tab measured 0 — the share is computed for SOMETHING).
    VIEWER_MIN_TOTAL_PX = 640

    # v1.4.7: the blocks formatted AROUND the viewport on either side (the lazy
    # window of the highlighter — a small scroll costs nothing because the
    # neighbours are already done).
    VIEWER_LAZY_MARGIN = syntax.VIEWER_LAZY_MARGIN

    # v1.7.3: the multiplier of that margin while the reader WRAPS — one block is several visual
    # rows there, so the window has to reach further to cover the same distance on the screen.
    WRAP_MARGIN_FACTOR = 2

    # ── v1.7.5: the preview ceiling of THIS pane ─────────────────────────

    def viewer_cap(self) -> int:
        """The ceiling every read of this pane is TRUNCATED at (the resolved setting)."""
        return int(getattr(self, "_viewer_cap", 0) or VIEWER_MAX_BYTES_MIN)

    def set_viewer_max_bytes(self, value) -> int:
        """Apply a new ceiling to THIS pane and re-read the marks (v1.7.5).

        The per-session "no preview" FACTS are dropped: a size verdict is a fact of the CAP that
        produced it, so a read attempt that answered under the old ceiling says nothing about the
        new one. Every row of the listing is re-marked from the (now clean) state.
        """
        self._viewer_cap = host_attr(self, "clamp_viewer_max_bytes")(value)
        self._blocked.clear()
        self._mark_rows()
        return self._viewer_cap

    def _mark_rows(self):
        """Re-apply the preview marker of EVERY row of the listing on the screen. Never raises."""
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is not None:
                    self._apply_preview_marker(item, item.data(0, self.PATH_ROLE))
        except RuntimeError:
            pass  # Qt teardown — the tree is already gone

    def _known_size(self, path: str) -> int:
        """The size the CURRENT listing knows for `path` (0 — the path is not on the screen)."""
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is not None and item.data(0, self.PATH_ROLE) == path:
                    return int(item.data(0, self.SIZE_ROLE) or 0)
        except (RuntimeError, TypeError, ValueError):
            pass
        return 0

    # ── v1.3.1: the preview panel (ROADMAP task 1) ───────────────────────

    def _open_viewer(self, item: QTreeWidgetItem):
        """A double click on a file → read it through the worker queue and show it.

        The pane never touches the remote file itself: the read is a "read" task
        of the existing queue (32 KB chunks, the limit and the binary check are
        the worker's job), the answer arrives via read_ready. The panel opens
        only when the answer is there — a refusal (binary / too large) stays a
        message in the status bar (task_error → _on_task_error).

        v1.7rc3: in the TWO-PANE view the preview is shown WHERE THE OTHER PANE IS (the mc
        behaviour) and THIS pane keeps the keyboard and the cursor; the reading pane stays the
        owner of the task and of the message, so a refusal is reported exactly as before.

        v1.7.4rc1: the read goes to THIS pane's provider, so a LOCAL file previews through the
        SHIPPED read policy unchanged (LOCAL_PANE.md §3).
        """
        if self.provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        # v1.7rc3: the GATE is asked first — ONE preview exists at a time, and a file opened while
        # the OTHER pane shows a panel is refused with ONE sentence. A panel THIS pane owns is not
        # in the way: the new file is read into it (walking the listing with F3 is the whole point
        # of a commander, so a second open from the reading pane must never be refused as "busy").
        if not self._container.preview_allowed(self):
            return
        # Opening a file ALWAYS starts from a clean look: a preview already open in the two-pane
        # view (whichever pane lent or carries its panel) closes first, so a new preview can never
        # share a splitter with the old one, and a re-open of the SAME file re-reads it. The panel
        # is MOVED to the other pane only once the content is there (`_show_viewer()`): a read the
        # worker refuses must not leave the other pane dressed as a panel that shows nothing.
        self._container.close_preview()
        self._queue_viewer_read(path, item.data(0, self.SIZE_ROLE))

    def _queue_viewer_read(self, path: str, size=0) -> bool:
        """Ask this pane's provider for `path` at the pane's ceiling (the ONE preview read).

        v1.9.3: the ENCODING choice needs the same read a double click makes — the shown text was
        decoded with the previous codec, so a change re-reads the file instead of leaving a
        mis-decoded document on the screen — and ONE place asks `queue_read()`, so the ceiling
        travels with it exactly once (AGENTS.md §4.15).
        """
        provider = self.provider
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return False
        tid = provider.queue_read(path, int(size or 0), max_bytes=self.viewer_cap())
        if tid is None:
            return False   # the worker is finished — there is nobody to read
        self._read_tasks[tid] = path
        self._last_read = tid
        self.viewer_label.setText(_t("sftp.viewer.reading", name=self.paths.basename(path)))
        return True

    def _on_read_ready(self, task_id: int, remote_path: str, data: bytes):
        """The read answer (already on the GUI thread): render it in the panel.

        The pane is the ONE place that knows whether the read was CUT — it holds the cap it handed
        to the task and the size the listing reports — so the truncation fact is resolved HERE and
        travels into `decode_text()` (`N46`: a byte cut is not a different encoding).
        """
        path = self._read_tasks.pop(task_id, remote_path)
        if task_id != self._last_read:
            return  # an outdated answer (another file was opened since) — dropped
        self._last_read = None
        # v1.3.1.1: a successful read is a FACT too — drop a stale mark of this row
        # (defensive: the two heuristics agree today, and the state must not drift).
        if self._blocked.pop(path, None) is not None:
            self._mark_row(path)
        truncated = host_attr(self, "read_was_truncated")(
            len(data), self.viewer_cap(), self._known_size(path))
        text, encoding = host_attr(self, "decode_text")(bytes(data), truncated=truncated,
                                                        encoding=self.viewer_encoding_choice)
        self._show_viewer(path, len(data), text, encoding)

    def _show_viewer(self, path: str, size: int, text: str, encoding: str = "utf-8"):
        """Fill the panel with the file and show it (an unshown panel gets sizes).

        v1.4.7: the language is decided from the path AND the content
        (`syntax.detect_syntax` — the honesty rule: a `.json`/`.xml` hint is
        accepted only after a real parse) and the pane's ONE highlighter colours
        the blocks around the viewport. The header carries the heuristic note
        for the modes no parser verified (YAML), exactly like the encoding note.

        v1.7rc3: the panel may have been MOVED to the other pane before this call
        (`present_viewer_in()`), so the share is computed for the splitter that really carries it
        and the READING pane keeps the keyboard (its listing stays under the cursor while the
        preview appears beside it — the mc behaviour).

        v1.7.5: the header's SIZE becomes the truncation notice when the read stopped at the
        ceiling — the listing knows the real size, so the panel can say how much of how many it
        shows (`sftp.viewer.truncated`) instead of presenting a part as the whole.
        """
        # The parser has a declared budget (N57): over it the extension hint is accepted WITHOUT the
        # parse and the header owes the heuristic note — a 250 MiB `.json` is never `json.loads`-ed.
        verifiable = syntax.within_verify_budget(text)
        language = syntax.detect_syntax(path, text, verify=verifiable)
        format_bytes = host_attr(self, "format_size")
        size_text = format_bytes(size)
        total = self._known_size(path)
        if int(total or 0) > int(size or 0):
            size_text = _t("sftp.viewer.truncated", shown=format_bytes(size),
                           total=format_bytes(total))
        head = _t("sftp.viewer.header", path=path, size=size_text)
        chosen = self.viewer_encoding_choice
        if chosen != "auto" and encoding != chosen:
            # v1.9.3: the CHOICE could not read the file — the shipped rule did, and the header says
            # which is which instead of presenting a fallback as the requested decoding.
            head = f"{head} · {_t('sftp.viewer.encoding_failed', encoding=chosen, fallback=encoding)}"
        elif encoding != "utf-8":
            head = f"{head} · {_t('sftp.viewer.encoding_note', encoding=encoding)}"
        if syntax.is_heuristic(language) or not verifiable:
            head = f"{head} · {_t('sftp.viewer.syntax_heuristic', language=language)}"
        self.viewer_label.setText(head)
        self.viewer_label.setToolTip(path)
        self._viewer_encoding = encoding
        self._viewer_path = path
        self._viewer_language = language
        highlighter = self._ensure_highlighter()
        if highlighter is not None:
            highlighter.set_language(language)
            # BEFORE setPlainText: Qt reformats the WHOLE changed range, and with
            # an EMPTY window that pass applies no format at all — which is what
            # keeps the previous file from bleeding into this one.
            highlighter.reset_for_document()
        self._highlight_range = None
        self.viewer_text.setPlainText(text)   # the cursor lands at the start by itself
        self._viewer_open = True
        # The panel is where the FILE is: with two panes it takes the OTHER pane's slot (mc/far),
        # with one it stays inside this one (the shipped look). The move happens HERE — with the
        # content already in the widget — so a read the worker refused leaves every pane alone.
        self._container.present_viewer(self)
        self.viewer.show()
        self._layout_viewer_share()
        self._highlight_visible(force=True)

    # ── v1.7rc3: the preview moved to the other pane (the mc F3 of the two-pane view) ──

    def _viewer_splitter(self):
        """The splitter that really carries the viewer (its HOME pane's by default)."""
        parent = self.viewer.parent()
        return parent if parent is not None else self.splitter

    def _layout_viewer_share(self):
        """Give the panel its declared share of the splitter that REALLY carries it. Never raises.

        Qt gotcha #13: a splitter member's share is set via `setSizes()` only. The splitter can hold
        a THIRD member — a pane carrying a borrowed panel keeps its OWN one in the layout (hidden,
        so it lands nowhere) while the borrowed one takes the slot it left — which is why the share
        is computed over the members BY NAME: the listing takes `VIEWER_TREE_SHARE`, the viewer that
        is really on screen takes the rest and a panel that stepped aside answers 0. A share handed
        out by POSITION would give the column to the hidden member and leave the borrowed panel zero
        pixels wide: the borrowing pane changed its look and showed nothing at all.
        """
        splitter = self._viewer_splitter()
        try:
            count = splitter.count()
            index = splitter.indexOf(self.viewer)
        except RuntimeError:
            return   # Qt teardown — the splitter or the viewer is already gone
        if count <= 0 or index < 0:
            return
        total = max(splitter.width(), self.VIEWER_MIN_TOTAL_PX)
        left = int(total * self.VIEWER_TREE_SHARE)
        try:
            # v1.7: a pane CARRYING a borrowed panel is a PANEL — its own listing left the layout
            # (`present_viewer_in()` hides it), so the panel takes the WHOLE pane.
            listing = splitter.widget(0)
            if listing is not None and listing.isHidden():
                left = 0
        except RuntimeError:
            pass   # Qt teardown — the splitter is already gone
        sizes = [0] * count
        sizes[0] = left                                   # the listing is the first member
        sizes[index] = max(total - left, 0)               # the panel is the one that is showing
        splitter.setSizes(sizes)

    def viewer_host(self):
        """The pane whose splitter currently carries the viewer (None — no preview is open).

        ONE answer for the whole container: the pane that BORROWED the viewer registers itself in
        `_viewer_host`, so "close the preview and restore the listing" has a single subject and
        the pane that opened it never has to guess. The state is the DECLARED `_viewer_open` flag,
        never `QWidget.isVisible()` — a pane that is not on screen yet (a never-shown dock tab, the
        offscreen test platform) reports its widgets as invisible while its preview is really open.
        """
        if not getattr(self, "_viewer_open", False):
            return None
        if self._viewer_host is not None:
            return self._viewer_host
        return self._viewer_home or self

    def _restore_listing(self):
        """Put the tree and the pane's own rows back after a borrowed viewer leaves it.

        Called with `_viewer_host` ALREADY cleared (the owner has taken its panel home), so the
        only question is whether this pane was CARRYING it — a pane that never did must keep its
        own panel's look untouched. Never raises.
        """
        try:
            if not getattr(self, "_viewer_borrowed", False):
                return
            self._viewer_borrowed = False
            self.path_label.show()
            self.tree.show()                  # v1.7: the listing comes back with the rows
            self.splitter.setCollapsible(0, False)   # the tree is never draggable shut again
            self.set_pane_keys_enabled(True)
            self._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the rows exist

    def present_viewer_in(self, host, source=None) -> bool:
        """Move THIS pane's viewer into `host`'s splitter; True — it really moved.

        The two-pane view shows a preview WHERE THE OTHER PANE IS (mc and far do the same): the
        listing that opened it keeps the cursor and the keyboard, and the panel takes the other
        pane's place for as long as it is open. The viewer is ONE widget owned by the pane it was
        built in, so the move is a re-parent (`QSplitter.insertWidget()`) instead of a second
        `QPlainTextEdit` per pane — the highlighter, the content and the × belong to the same
        object, and closing the preview puts it back where it came from.

        **The host is a PANEL for as long as it carries the preview**: its address bar and its key
        row were already gone, and since v1.7 its LISTING leaves the layout too (`tree.hide()`), so
        the panel gets the whole pane instead of sharing it with a listing nobody is looking at.
        That is also why the pane's own pane-scoped keys are disarmed here: a key that acts on a
        listing off the screen would act on rows nobody can see.

        Refused (False) for the pane itself and for a foreign pane: the container asks
        `preview_allowed()` BEFORE the read (the ONE-preview rule) and `present_viewer()` decides
        whether the move is still wanted when the answer is there, this method only performs it.
        """
        if host is None or host is self or host is not self._container.other_pane(self):
            return False
        try:
            # The host's OWN panel steps aside — it stays in the splitter, hidden (a hidden member
            # takes no room) — and the borrowed one is inserted in the very slot it left, so the
            # panel is the pane's RIGHT column and not a third member squeezed to nothing.
            index = host.splitter.indexOf(host.viewer)
            if index < 0:
                index = host.splitter.count()
            else:
                host.viewer.hide()
            host.splitter.insertWidget(index, self.viewer)
        except RuntimeError:
            return False
        self._viewer_host = host
        self._viewer_from = source if source is not None else self
        # The host is a PREVIEW now: its address bar belongs to a listing nobody can see and the
        # key row of a pane that carries a panel is hidden (see `_sync_secondary_ui`). Since v1.7
        # its LISTING leaves the layout as well — the panel takes the WHOLE pane (the mc/far quick
        # view), and the tree's own keys (`Tab` into it, `F3`-`F8` on a row) are disarmed with it.
        host._viewer_borrowed = True
        try:
            host.path_label.hide()
            host.tree.hide()
            host.splitter.setCollapsible(0, True)   # a HIDDEN listing may really collapse to 0
            host.set_pane_keys_enabled(False)
            host._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the rows exist
        return True

    def restore_viewer(self) -> bool:
        """Move the viewer back to its HOME pane; True — it really moved. Never raises.

        The home splitter shows the panel again (hidden) and the borrowing pane gets its listing
        rows back; a pane that is being TORN DOWN never takes the viewer with it (the container
        calls this before it destroys the pane).
        """
        host = self._viewer_host
        if host is None:
            return False
        self._viewer_host = None
        self._viewer_from = None
        try:
            self.viewer.hide()
        except RuntimeError:
            pass  # Qt teardown — the panel is already gone
        home = self._viewer_home
        if home is not None and home is not host:
            try:
                home.splitter.addWidget(self.viewer)
            except RuntimeError:
                pass  # Qt teardown — the home pane is already gone
        try:
            # `_restore_listing()` clears the borrowing flag itself and puts the host's own rows
            # (its address bar, its buttons or its hints) back.
            host._restore_listing()
        except (RuntimeError, AttributeError):
            pass
        try:
            if home is not None:
                home._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # the home pane is gone / has no rows yet
        return True

    # ── v1.4.7 (ROADMAP task 3/4): the lazy syntax highlighting ─────────────

    def _ensure_highlighter(self):
        """The pane's ONE highlighter (built on the first preview, reused after).

        A viewer must keep working when the highlighter cannot be built (an
        exotic Qt build): the preview then stays monochrome, which is exactly
        the v1.3.1 behaviour.
        """
        if self._highlighter is None:
            try:
                self._highlighter = syntax.create_highlighter(
                    self.viewer_text.document())
            except Exception:   # noqa: BLE001 — highlighting is never critical
                self._highlighter = None
        return self._highlighter

    # ── v1.7.3 (task 4): the reader's word wrap ─────────────────────────────

    def _build_viewer_menu(self):
        """The reader's menu: Qt's OWN standard one PLUS the TWO app rows (wrap, encoding).

        `createStandardContextMenu()` carries Copy / Select All translated by Qt itself (no i18n
        key of ours), so the app rows are APPENDED after a separator — the same seam shape as
        `_build_context_menu()`: the tests trigger the QAction directly and never run `exec()`.
        v1.9.3: the encoding row is a SUBMENU of the declared codecs (a codec name is an
        identifier, so only `auto` carries a translated word) whose checkmark mirrors the ONE
        global value the container owns.
        """
        menu = self.viewer_text.createStandardContextMenu()
        menu.addSeparator()
        act = QAction(_t("sftp.viewer.word_wrap"), menu)
        act.setCheckable(True)
        act.setChecked(bool(self._viewer_wrap))
        act.toggled.connect(self._on_wrap_toggled)
        menu.addAction(act)
        self._wrap_action = act
        submenu = menu.addMenu(_t("sftp.viewer.encoding"))
        self._encoding_menu = submenu
        self._encoding_actions = {}
        for codec in VIEWER_ENCODINGS:
            item = QAction(_t("sftp.viewer.encoding_auto") if codec == VIEWER_ENCODING_DEFAULT
                           else codec, submenu)
            item.setCheckable(True)
            item.setChecked(codec == self._viewer_encoding_choice)
            item.triggered.connect(lambda _checked=False, code=codec:
                                   self._on_encoding_chosen(code))
            submenu.addAction(item)
            self._encoding_actions[codec] = item
        return menu

    def _on_encoding_chosen(self, codec):
        """An encoding row was chosen: the CONTAINER owns the ONE global setting (v1.9.3)."""
        apply_all = getattr(self._container, "apply_viewer_encoding", None)
        if callable(apply_all):
            try:
                apply_all(codec)
                return
            except RuntimeError:
                return   # Qt teardown — nothing left to re-read
        self.set_viewer_encoding(codec)

    def set_viewer_encoding(self, codec, persist: bool = True, reread: bool = True) -> str:
        """Set the reader's encoding CHOICE for THIS pane (the container walks the rest).

        The text on the screen was decoded with the PREVIOUS choice, so a real change re-reads the
        file the preview holds instead of leaving a mis-decoded document there; a panel with nothing
        open simply carries the new default into its next read. The value is normalised against the
        DECLARED list, so a hand-edited config cannot reach the decoder with an unknown codec.
        Never raises.
        """
        resolved = normalize_viewer_encoding(codec)
        changed = resolved != self._viewer_encoding_choice
        self._viewer_encoding_choice = resolved
        for name, act in (getattr(self, "_encoding_actions", None) or {}).items():
            try:
                act.setChecked(name == resolved)
            except RuntimeError:
                pass   # Qt teardown — the menu is already gone
        if persist:
            host_attr(self, "save_viewer_encoding")(resolved)
        if changed and reread and self._viewer_open and self._viewer_path:
            self._queue_viewer_read(self._viewer_path, self._known_size(self._viewer_path))
        return resolved

    @property
    def viewer_encoding_choice(self) -> str:
        """The encoding this reader ASKS for (`auto` — the shipped utf-8 → latin-1 rule)."""
        return str(getattr(self, "_viewer_encoding_choice", "") or VIEWER_ENCODING_DEFAULT)

    def _on_viewer_menu(self, pos):
        """Show the reader's menu at the click (the event is the only caller of the seam)."""
        try:
            menu = self._build_viewer_menu()
            menu.exec(self.viewer_text.viewport().mapToGlobal(pos))
            menu.deleteLater()
        except RuntimeError:
            return   # Qt teardown — the panel is already gone

    def _on_wrap_toggled(self, on: bool):
        """The row was toggled: the CONTAINER owns the ONE global setting (v1.7.3)."""
        apply_all = getattr(self._container, "apply_viewer_wrap", None)
        if callable(apply_all):
            try:
                apply_all(bool(on))
                return
            except RuntimeError:
                return   # Qt teardown — nothing left to re-text
        self.set_viewer_wrap(on)

    def _apply_viewer_wrap(self):
        """Write the mode into the widget and re-run the lazy pass (the wrap changes the window).

        Never raises: a viewer without the enum (an exotic Qt build) keeps the shipped no-wrap look.
        """
        mode = (QPlainTextEdit.LineWrapMode.WidgetWidth if self._viewer_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap)
        try:
            self.viewer_text.setLineWrapMode(mode)
        except (RuntimeError, AttributeError):
            return
        self._highlight_range = None
        self._highlight_visible(force=True)

    def set_viewer_wrap(self, on, persist: bool = True) -> bool:
        """Set the reader's word wrap for THIS pane (the container walks the rest)."""
        self._viewer_wrap = bool(on)
        self._apply_viewer_wrap()
        act = getattr(self, "_wrap_action", None)
        if act is not None:
            try:
                act.setChecked(self._viewer_wrap)
            except RuntimeError:
                pass   # Qt teardown — the menu is already gone
        if persist:
            return host_attr(self, "save_viewer_wrap")(self._viewer_wrap)
        return True

    @property
    def viewer_wrap(self) -> bool:
        """Is the reader wrapping long lines (the topical seam)?"""
        return bool(self._viewer_wrap)

    def _lazy_margin(self) -> int:
        """The blocks the lazy window keeps around the viewport.

        Under wrapping ONE block covers SEVERAL visual rows, so the block margin is widened: the
        same visual distance stays formatted around the viewport (the measured seam of the mode).
        """
        if self._viewer_wrap:
            return self.VIEWER_LAZY_MARGIN * self.WRAP_MARGIN_FACTOR
        return self.VIEWER_LAZY_MARGIN

    def _viewer_block_range(self):
        """The block numbers on the screen → `(first, last)`, or None.

        Measured from the LAYOUT (`blockBoundingGeometry` + `contentOffset`), so
        it answers correctly for a hidden panel too (it degrades to block 0).
        """
        edit = self.viewer_text
        try:
            block = edit.firstVisibleBlock()
            if not block.isValid():
                return None
            height = edit.viewport().height()
            offset = edit.contentOffset()
            first = last = block.blockNumber()
            while block.isValid():
                if edit.blockBoundingGeometry(block).translated(offset).top() > height:
                    break
                last = block.blockNumber()
                block = block.next()
            return first, last
        except RuntimeError:
            return None   # the C++ object was already destroyed (a close race)

    def _highlight_visible(self, force: bool = False) -> int:
        """Format the blocks around the viewport (v1.4.7 task 4 — the lazy half).

        A 1 MB file is ~20 000 blocks and `setPlainText()` marks every one of
        them dirty, so the EXPENSIVE half (turning spans into text formats) is
        applied only to the visible window ± `VIEWER_LAZY_MARGIN`; the block
        STATE is still computed for every line, because the state of a line
        depends on the line before it. A repeated call whose window is already
        done costs one comparison.

        Returns the number of blocks really rehighlighted.
        """
        highlighter = self._highlighter
        if highlighter is None:
            return 0
        window = self._viewer_block_range()
        if window is None:
            return 0
        margin = self._lazy_margin()
        first = max(0, window[0] - margin)
        last = window[1] + margin
        if not force and (first, last) == self._highlight_range:
            return 0
        self._highlight_range = (first, last)
        highlighter.set_window(first, last)
        return highlighter.highlight_window(force=force)

    def _on_viewer_update_request(self, _rect, dy):
        """`QPlainTextEdit.updateRequest`: a scroll (`dy != 0`) or a resize.

        A hidden panel is skipped: the content of a closed viewer is gone, and
        `clear()` fires the signal while it empties the document — formatting a
        block nobody can see would only leave a mark behind.
        """
        if self.viewer.isHidden():
            return
        self._highlight_visible()

    @property
    def viewer_highlighter(self):
        """The pane's highlighter (None until the first preview — the test seam)."""
        return self._highlighter

    @property
    def viewer_language(self) -> str:
        """The language the shown content was detected as (v1.4.7)."""
        return self._viewer_language

    @property
    def viewer_encoding(self) -> str:
        """The encoding of the shown content ("utf-8" | "latin-1")."""
        return self._viewer_encoding

    def close_viewer(self):
        """v1.3.1: hide the panel and drop its content.

        Idempotent and never raises: it is called by the header's ×, by the
        container's `set_worker(None)` (the worker died) and by the single page
        teardown (page.shutdown()) — the preview closes together with the session.

        v1.7rc3: a BORROWED panel goes back to the pane it belongs to first (the other pane gets
        its listing and its address bar back), so closing the preview always restores the two-pane
        look the user had before it.
        """
        self._read_tasks.clear()
        self._last_read = None
        # v1.4.7: the panel is empty → the formatting pass has nothing to cover.
        self._highlight_range = None
        self._viewer_open = False
        self._viewer_path = ""   # v1.9.3: no file on the screen → the choice re-reads nothing
        if self._highlighter is not None:
            self._highlighter.reset_for_document()
        self.restore_viewer()
        try:
            self.viewer.hide()
            self.viewer_text.clear()
            self.viewer_label.clear()
            self.viewer_label.setToolTip("")
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race) — nothing to hide
        # v1.7rc3: this pane may have been the CARRYING one while the panel belonged to its
        # sibling — its own path row and key hints come back with the panel's closing.
        if getattr(self, "_viewer_borrowed", False):
            self._viewer_borrowed = False
            self._viewer_host = None
            try:
                self.path_label.show()
            except RuntimeError:
                pass
            self._sync_secondary_ui()
