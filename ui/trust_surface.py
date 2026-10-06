# -*- coding: utf-8 -*-
"""The interactive TRUST SURFACE — the answerer of `modules/interactive_ask.py` (AGENTS.md §4.4).

`install()` is called ONCE by the application entry point (`main.py`), because the questions arrive on a
connect thread while the windows belong to the GUI thread: `answer(request)` runs THERE and picks the
window by the request's KIND — a host key, a credential — publishing the answer back through the request.

Without `install()` there is no surface: `ask()` answers `None` at once and every caller resolves that
through its own DECLARED fallback (the shipped TOFU accept for a host key, an honest refusal for a
credential). The known-hosts manager is opened from the Profile menu.

Mechanism — `DOCUMENTATION.md` §16."""

try:
    from ..modules import interactive_ask as _ask
except ImportError:
    from modules import interactive_ask as _ask

try:
    from ..dialogs.host_key_dialog import HostKeyDialog, KnownHostsManagerDialog
    from ..dialogs.auth_prompt_dialog import AuthPromptDialog
except ImportError:
    from dialogs.host_key_dialog import HostKeyDialog, KnownHostsManagerDialog
    from dialogs.auth_prompt_dialog import AuthPromptDialog

from PySide6.QtWidgets import QApplication, QDialog


def _parent():
    """The window a prompt hangs on: the ACTIVE one, else the last visible top-level (never None)."""
    try:
        active = QApplication.activeWindow()
    except Exception:  # noqa: BLE001 — no GUI yet
        active = None
    if active is not None:
        return active
    try:
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible():
                return widget
    except Exception:  # noqa: BLE001
        pass
    return None


def _t(key, **kwargs):
    """A translated sentence — never raises without i18n (the key itself is the answer)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kwargs) if kwargs else _translate(key)
    except Exception:  # noqa: BLE001
        return key


def answer(request):
    """ONE question from a worker thread, answered by a window here. `None` — no answer was given."""
    kind = request.kind
    fields = request.fields
    if kind in (_ask.KIND_HOST_KEY, _ask.KIND_CHANGED_KEY):
        dialog = HostKeyDialog(
            _parent(), host=fields.get("host", ""), port=fields.get("port", 22),
            keytype=fields.get("keytype", ""), fingerprint=fields.get("fingerprint", ""),
            expected=fields.get("expected", ""))
        return dialog.exec() == QDialog.DialogCode.Accepted
    if kind == _ask.KIND_KEY_PASSPHRASE:
        dialog = AuthPromptDialog(
            _parent(), title=_t("auth.title_passphrase"), label=_t("auth.label_passphrase"),
            hint=_t("auth.hint_passphrase", path=fields.get("key_path", "")), secret=True)
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None
    if kind == _ask.KIND_SECOND_FACTOR:
        dialog = AuthPromptDialog(
            _parent(), title=_t("auth.title_second_factor"),
            label=fields.get("prompt") or _t("auth.label_second_factor"),
            hint=_t("auth.hint_second_factor", host=fields.get("host", ""),
                    user=fields.get("user", "")),
            secret=bool(fields.get("secret", True)))
        return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None
    return None


def install():
    """Install this module as THE answerer (the entry point calls it once). True — installed."""
    _ask.set_answerer(answer)
    return True


def uninstall():
    """Remove the surface — a closing application must not leave a live dialog behind."""
    _ask.set_answerer(None)


def open_known_hosts_manager(parent=None):
    """Show the known-hosts manager (the Profile menu's item). Returns the dialog it used."""
    dialog = KnownHostsManagerDialog(parent if parent is not None else _parent())
    dialog.exec()
    return dialog
