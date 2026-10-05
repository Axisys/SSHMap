# -*- coding: utf-8 -*-
"""The ELEVATED source of ONE Files pane — a server read as ANOTHER user (`sudo`).

`SftpPaneElevatedMixin` owns the pane's half of `ELEVATED_PANE.md`: the state (`_elevated_provider`,
`_elevated_client`, `_elevation_user`, `_elevation_pending`, `_handshake`), the door the source
control calls (`begin_elevation()` / `leave_elevation()`), the two slots of the handshake, the ONE
refusal every write door asks and the teardown. The pane keeps `source = SOURCE_REMOTE` (the
dialect, the dispatch and the drag payload do not move) and only its PROVIDER changes — the shipped
`modules/sftp_worker` over the client the handshake opened. A facade global is resolved through
`host_attr()` and never imported: this module must not import `modules/sftp_tab` (a cycle)."""

from PySide6.QtCore import QCoreApplication, QEvent

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

try:  # the handshake, the command table and the machine codes of the elevation
    from . import sftp_elevated as elevation
except ImportError:
    import sftp_elevated as elevation

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key


class SftpPaneElevatedMixin:
    """The elevated source of one pane: the switch, the handshake and the ONE refusal."""

    # ── The state of this pane (the container reads it, nothing else writes it) ──

    @property
    def elevated(self) -> bool:
        """Does this pane read the server through the elevated client right now?"""
        return getattr(self, "_elevated_provider", None) is not None

    def elevated_user(self) -> str:
        """The user the elevation was asked for ("" — this pane reads as the session's account)."""
        return str(getattr(self, "_elevation_user", "") or "")

    def elevated_label(self) -> str:
        """The user the pane's header line names (an empty target IS `root`)."""
        return self.elevated_user() or "root"

    def _switch_state(self) -> str:
        """The token the pane's SOURCE CONTROL shows (`ELEVATED_PANE.md` §4)."""
        if self.elevated or bool(getattr(self, "_elevation_pending", False)):
            return host_attr(self, "SOURCE_ELEVATED", "elevated")
        return str(getattr(self, "_source", "")) or host_attr(self, "SOURCE_REMOTE", "remote")

    # ── The door the source control calls ────────────────────────────────

    def begin_elevation(self, notify: bool = True) -> bool:
        """Ask for the target user and start the handshake; False — nothing was elevated.

        Three structural answers come BEFORE a channel is opened: the container must offer the
        elevation at all (`SftpTab.can_elevate()`, the sibling of `can_use_local()`), the session
        must have a live transport to ride, and the typed user must pass the PURE allowlist. A
        cancelled dialogue changes nothing. True means the handshake is RUNNING — the pane is
        elevated when its `ready` arrives, not before.
        """
        if self.elevated or bool(getattr(self, "_elevation_pending", False)):
            return True
        can = getattr(self._container, "can_elevate", None)
        if callable(can) and not bool(can(self)):
            if notify:
                self.message.emit(_t("sftp.elevated.unavailable"))
            self._sync_source_availability()
            return False
        transport = self._elevation_transport()
        if transport is None:
            if notify:
                self.message.emit(_t("sftp.elevated.no_transport"))
            self._sync_source_availability()
            return False
        answer = host_attr(self, "ask_elevation")(self, self.elevated_user())
        if answer is None:   # a cancel is NO answer — ("", "") means `root` without a password
            self._sync_source_availability()
            return False
        user, password = answer
        if elevation.user_problem(user):
            if notify:
                self.message.emit(_t("sftp.elevated.bad_user", user=str(user or "")))
            self._sync_source_availability()
            return False
        self._elevation_user = str(user or "")
        self._elevation_pending = True
        self.message.emit(_t("sftp.elevated.working", user=self.elevated_label()))
        handshake = host_attr(self, "ElevatedHandshake")(transport, self._elevation_user,
                                                         password, self)
        self._handshake = handshake
        handshake.ready.connect(self._on_elevation_ready)
        handshake.failed.connect(self._on_elevation_failed)
        handshake.start()
        self._sync_source_availability()
        return True

    def leave_elevation(self, target: str, notify: bool = True) -> bool:
        """Drop the elevation and continue with the ordinary source switch (`ELEVATED_PANE.md` §4)."""
        self._release_elevated()
        if str(target or "") == host_attr(self, "SOURCE_LOCAL", "local"):
            return bool(self.set_source(host_attr(self, "SOURCE_LOCAL", "local"), notify=notify))
        self._sync_source_availability()
        return True

    def _elevation_transport(self):
        """The SESSION's live transport (`None` — there is nothing to open a channel on)."""
        getter = getattr(self._container, "transport", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except (AttributeError, RuntimeError):
            return None

    # ── The handshake's two answers ──────────────────────────────────────

    def _on_elevation_ready(self, client, directory: str):
        """The client is up: bind the SHIPPED engine over it and open the server's own directory.

        An answer nobody waits for any more (the ask was dropped by a source switch, a release or a
        lost transport while the emission was in flight) elevates NOTHING: the client it carries is
        closed here, because the handshake has already let go of it.
        """
        if not bool(getattr(self, "_elevation_pending", False)):
            self._close_unclaimed_client(client)
            return
        self._elevation_pending = False
        self._drop_handshake()
        provider = host_attr(self, "SftpWorker")(client)
        self._elevated_provider = provider
        self._elevated_client = client
        self._current_dir = str(directory or "") or self.paths.root()
        self._restored = True   # the per-server memory belongs to the LOGIN user's look
        provider.start()
        self.bind_worker(self._bound_provider, provider)
        self._sync_source_availability()
        self._sync_header()

    def _on_elevation_failed(self, code: str, detail: str):
        """A declared refusal: ONE sentence from the code table, and the pane stays as it was."""
        if not bool(getattr(self, "_elevation_pending", False)):
            return   # the ask was dropped before its answer landed — there is nothing to report
        self._elevation_pending = False
        self._drop_handshake()
        sentence = self.elevation_sentence(code, detail)
        if sentence:
            self.message.emit(sentence)
        self._sync_source_availability()
        self._sync_header()

    @staticmethod
    def _close_unclaimed_client(client):
        """Close a client of an answer the pane no longer claims. Never raises."""
        try:
            client.close()
        except Exception:  # noqa: BLE001 — a channel that is already gone is closed enough
            pass

    @staticmethod
    def elevation_sentence(code: str, detail: str = "") -> str:
        """A machine code (and the server's own detail) → its translated sentence. PURE-ish."""
        key = elevation.ELEVATED_ERROR_KEYS.get(str(code or ""))
        if not key:
            return ""
        if str(code) == elevation.ELEVATED_NO_TRANSPORT:
            return _t(key)
        return _t(key, error=str(detail or ""))

    def transport_lost(self):
        """The session's transport is gone: the elevation loses its channel and is dropped."""
        if not (self.elevated or bool(getattr(self, "_elevation_pending", False))):
            return
        label = self.elevated_label()
        self._release_elevated()
        self.message.emit(_t("sftp.elevated.lost", user=label))

    # ── The ONE refusal of every write door (`ELEVATED_PANE.md` §5) ───────

    def _refuse_elevated_write(self) -> bool:
        """True — this pane reads as another user and the write door answers ONE sentence."""
        if not self.elevated:
            return False
        self.message.emit(_t("sftp.elevated.read_only"))
        return True

    def _elevated_batch_refused(self, target_pane) -> bool:
        """True — the copy/move batch has an elevated pane as its SOURCE or its DESTINATION."""
        try:
            other = bool(getattr(target_pane, "elevated", False))
        except RuntimeError:
            other = False   # Qt teardown — a dead pane is not an elevated one
        if not (self.elevated or other):
            return False
        self.message.emit(_t("sftp.elevated.read_only"))
        return True

    def _elevated_drop_refused(self, payload) -> bool:
        """True — the DRAGGING pane of a pane payload is elevated (the payload names that pane)."""
        pane_id = (payload or {}).get("pane") if isinstance(payload, dict) else None
        if pane_id is None:
            return False
        panes = getattr(self._container, "panes", None)
        if not isinstance(panes, list):
            return False
        for pane in panes:
            try:
                if id(pane) == pane_id and pane.elevated:
                    self.message.emit(_t("sftp.elevated.read_only"))
                    return True
            except (RuntimeError, AttributeError):
                continue   # Qt teardown / a foreign pane object — not this drop's business
        return False

    # ── The teardown ─────────────────────────────────────────────────────

    def shutdown_elevated(self):
        """Stop the pane's elevated provider and close its client. Idempotent, never raises."""
        self._release_elevated()

    def _release_elevated(self):
        """Drop the handshake, the worker and the state; the session's transport comes back."""
        self._elevation_pending = False
        self._drop_handshake()
        provider = getattr(self, "_elevated_provider", None)
        client = getattr(self, "_elevated_client", None)
        self._elevated_provider = None
        self._elevated_client = None
        if provider is not None:
            try:
                provider.shutdown(wait_ms=elevation.ELEVATED_SHUTDOWN_WAIT_MS)
                if provider.isRunning():
                    host_attr(self, "register_orphan_sftp_worker")(provider)
            except Exception:  # noqa: BLE001 — teardown robustness
                pass
        if client is not None:
            try:
                client.close()   # closing the client closes the channel it was built on
            except Exception:  # noqa: BLE001 — a dead channel is closed enough
                pass
        if provider is None and client is None:
            return
        try:
            self.bind_worker(None, self.worker)
        except (RuntimeError, AttributeError):
            pass   # Qt teardown — there is no listing left to re-bind

    def _drop_handshake(self):
        """Forget and stop the handshake of this pane (if any). Never raises."""
        handshake, self._handshake = getattr(self, "_handshake", None), None
        if handshake is None:
            return
        # A QUEUED answer of the handshake just left is delivered even after the disconnect (Qt does
        # not cancel a posted call), and a late `ready` would re-bind an elevated provider on a pane
        # that has already left the elevation. The pane's pending calls go with the handshake.
        try:
            QCoreApplication.removePostedEvents(self, QEvent.Type.MetaCall)
        except (RuntimeError, TypeError):
            pass  # no event loop yet (a bare construction) — nothing is queued anyway
        for signal, slot in ((handshake.ready, self._on_elevation_ready),
                             (handshake.failed, self._on_elevation_failed)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass   # the slot was never connected / the object is already gone
        try:
            handshake.close()
            handshake.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        try:
            handshake.deleteLater()
        except RuntimeError:
            pass   # the C++ object is already gone
