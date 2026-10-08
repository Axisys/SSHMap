"""The PURE helpers of the Files pane family (`_SftpPane` wave 2).

`format_size` / `format_mtime` / `decode_text` / `preview_block_reason` turn a size, a timestamp or
a byte buffer into the text a row or the reader shows — no widget, no provider, no network — and the
reader's encoding CHOICE (its declared list, its resolver and its writer) lives here beside the
decode it feeds (`ui_viewer_encoding`, the word-wrap rule of one global value).
`ask_conflict()` is the overwrite question of ONE item of a batch: the module's only Qt surface and
the ONE seam a caller substitutes (`modules.sftp_tab.QMessageBox`). Every name here is re-exported
by the pane family and by the shipped `modules.sftp_tab`, so a caller imports them from the facade.

Contract — `SFTP_PANES.md` §5-§6; mechanism — `DOCUMENTATION.md` §59, §64.
"""

import codecs
import sys
from datetime import datetime

from PySide6.QtWidgets import QCheckBox, QMessageBox

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # the extension classifier of the reader's own guess
    from .sftp_worker import READ_ERROR_BINARY, classify_extension
except ImportError:
    from sftp_worker import READ_ERROR_BINARY, classify_extension


def _facade_attr(name, default=None):
    """An attribute of the SHIPPED facade module at call time — the `modules.sftp_tab` seam.

    A module-level helper has no `self` for `host_attr()`, and the facade imports THIS module, so
    the module object is read from `sys.modules` (fully loaded by call time). `STAB.<name> = fake`
    therefore keeps working for the Qt classes the suite substitutes.
    """
    for mod_name in ("modules.sftp_tab", "sftp_tab"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            return getattr(mod, name, default)
    return default


def format_size(n) -> str:
    """Human-readable size: 0 → "0 B", 1536 → "1.5 KB" (no locales)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n < 0:
        return "?"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def format_mtime(ts) -> str:
    """Local mtime time "%Y-%m-%d %H:%M"; broken/zero → ""."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def decode_text(data: bytes, truncated: bool = False, encoding: str = "auto"):
    """v1.3.1 (ROADMAP task 3): bytes → (text, encoding really used).

    UTF-8 (BOM-aware — "utf-8-sig" strips an UTF-8 BOM) first; on a decode
    failure the Latin-1 fallback, which never fails and always yields a string
    (mojibake instead of an exception — the header carries the encoding note).

    v1.9.3: `encoding` is the reader's CHOICE — `"auto"` is the shipped rule above and a NAMED codec
    (one of `VIEWER_ENCODINGS`) is tried FIRST with that rule kept as the fallback, so a buffer the
    chosen encoding cannot read is still SHOWN. The second half of the pair is the codec that really
    read it, which is how the caller tells a choice that worked from one that fell back.

    `truncated` says the read STOPPED AT THE CEILING (N46): a byte-exact cut lands inside a
    multi-byte character roughly every second time on Cyrillic/CJK text, and the resulting
    `UnicodeDecodeError` describes the CAP, not the file — the incomplete tail is therefore held
    back (an incremental decoder with `final=False`, at most three bytes) and the text stays
    UTF-8. A COMPLETE buffer keeps the shipped rule BYTE FOR BYTE, so a real Latin-1 file whose
    last byte is a lead byte keeps its last character; a genuinely invalid byte still raises and
    still falls back.
    """
    data = bytes(data)
    chosen = normalize_viewer_encoding(encoding)
    if chosen != "auto":
        codec = "utf-8-sig" if chosen == "utf-8" else chosen
        try:
            decoder = codecs.getincrementaldecoder(codec)()
            return decoder.decode(data, final=not truncated), chosen
        except (UnicodeDecodeError, LookupError):
            pass   # the choice cannot read this buffer — the shipped rule below is the answer
    if truncated:
        try:
            decoder = codecs.getincrementaldecoder("utf-8-sig")()
            return decoder.decode(data, final=False), "utf-8"
        except (UnicodeDecodeError, LookupError):
            pass   # a real invalid byte — the fallback below is the shipped answer
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), "latin-1"


#: v1.9.3: the reader's ENCODING choice — ONE key of `~/.sshmap/config.json` (the `ui_viewer_wrap`
#: rule: one global value, an unknown or broken one falling back to `auto`) and the DECLARED list the
#: reader's submenu offers. A codec NAME is an identifier and is deliberately never translated; only
#: `auto` — the shipped utf-8 → latin-1 rule — carries a word of its own.
VIEWER_ENCODING_CONFIG = "ui_viewer_encoding"
VIEWER_ENCODING_DEFAULT = "auto"
VIEWER_ENCODINGS = ("auto", "utf-8", "cp1251", "cp1252", "cp866", "koi8-r", "latin-1", "gbk")

#: v1.7.3: the reader's WORD WRAP — the twin of the key above, and the reason both live here: the
#: reader's two global settings are resolved ONCE by a pane and travel into the read/show path.
VIEWER_WRAP_CONFIG = "ui_viewer_wrap"


def resolve_viewer_wrap(cfg: dict = None) -> bool:
    """The reader's word wrap as a PURE value (v1.7.3).

    Only a real JSON `true`/`false` counts; anything else — a string `"true"`, a number, a missing
    key, an unreadable config — answers the DEFAULT (`False`: the shipped no-wrap look).
    """
    if not isinstance(cfg, dict):
        try:
            from i18n import load_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the default
            return False
        try:
            cfg = load_config() or {}
        except Exception:  # noqa: BLE001 — a broken config store keeps the default
            cfg = {}
    value = cfg.get(VIEWER_WRAP_CONFIG) if isinstance(cfg, dict) else None
    return value if isinstance(value, bool) else False


def save_viewer_wrap(on) -> bool:
    """Write the ONE word-wrap key (merge-write; False — the config could not be written)."""
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a build without i18n cannot remember it
        return False
    try:
        return bool(save_config({VIEWER_WRAP_CONFIG: bool(on)}))
    except Exception:  # noqa: BLE001 — a write failure must not break the reader
        return False


def normalize_viewer_encoding(value) -> str:
    """PURE: one value into the DECLARED list — `auto` (the shipped rule) for anything else."""
    code = str(value if value is not None else "").strip().lower()
    return code if code in VIEWER_ENCODINGS else VIEWER_ENCODING_DEFAULT


def resolve_viewer_encoding(cfg: dict = None) -> str:
    """The reader's encoding choice as a PURE value (v1.9.3): the config's codec, else `auto`.

    A missing key, a foreign type or an unreadable config answers the DEFAULT — the shipped
    utf-8 → latin-1 rule is what a user who never touched the setting has.
    """
    if not isinstance(cfg, dict):
        try:
            from i18n import load_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the default
            return VIEWER_ENCODING_DEFAULT
        try:
            cfg = load_config() or {}
        except Exception:  # noqa: BLE001 — a broken config store keeps the default
            cfg = {}
    value = cfg.get(VIEWER_ENCODING_CONFIG) if isinstance(cfg, dict) else None
    return normalize_viewer_encoding(value)


def save_viewer_encoding(value) -> bool:
    """Write the ONE encoding key, NORMALISED (merge-write; False — the config could not be written)."""
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a build without i18n cannot remember it
        return False
    try:
        return bool(save_config({VIEWER_ENCODING_CONFIG: normalize_viewer_encoding(value)}))
    except Exception:  # noqa: BLE001 — a write failure must not break the reader
        return False


def preview_block_reason(path: str, size=0, facts=None) -> str:
    """v1.3.1.1: will the viewer refuse this file? "" (no) | "binary" | "too_large".

    The order of the answers is the point of this function — from the certain to
    the guessed:

      1. `facts` — the results of REAL read attempts of this session (path →
         reason): the worker is the only one who sees the content, so its verdict
         wins. A `.txt` with a null byte looks like text by name and is refused by
         the worker — the row is marked only after the attempt, and from then on
         the mark is the truth;
      2. the extension (a GUESS — the null-byte screen can still refuse the file,
         and a file with an unknown/absent extension usually reads fine).

    **`size` is accepted for the callers' shape and is deliberately NOT a reason**
    (v1.7.5): the read is TRUNCATED at the configured ceiling, never refused, so a
    file over the cap opens with its first `cap` bytes and the panel says how much
    of how many it shows (`sftp.viewer.truncated`). A `too_large` FACT of a real
    read attempt still marks the row; the size alone does not.
    """
    if facts:
        known = facts.get(path)
        if known:
            return known
    if classify_extension(path) == "binary":
        return READ_ERROR_BINARY
    return ""


def ask_conflict(parent, name: str, target: str, remaining: int = 0, facts: str = ""):
    """v1.3.3.2 (ROADMAP task 2): the overwrite question for ONE item of a batch.

    Returns `(action, apply_all)`, where action is one of

      * `"overwrite"` — replace the existing destination;
      * `"skip"` — leave the destination alone and go on with the batch;
      * `"rename"` — ask for another name (the caller prompts, then uploads /
        downloads under it) — `apply_all` is never set for it: a batch rename needs
        a name per file;
      * a cancelled dialog (Esc / the window's X) is reported as `"skip"`.

    `remaining` is the number of conflicts still to come in this batch — "Apply to
    all" is offered only when there is anything left to apply it to.

    `facts` is the ONE optional line the cross-session send adds (v1.7.3): both sides'
    size and date, rendered as the message box's informative text when it is non-empty.

    The QMessageBox is taken as a MODULE ATTRIBUTE at call time
    (`STAB.QMessageBox = <fake>` is the test seam — the command-library pattern);
    the pane's `_ask_conflict()` is the caller, so a test can also replace the whole
    decision.
    """
    box_cls = _facade_attr("QMessageBox", QMessageBox)   # a module attribute — the monkeypatch seam
    box = box_cls(parent)
    box.setWindowTitle(_t("sftp.conflict.title"))
    try:
        box.setIcon(box_cls.Icon.Question)
    except Exception:   # noqa: BLE001 — an exotic Qt build without the enum
        pass
    box.setText(_t("sftp.conflict.message", name=name, target=target))
    if facts:
        try:
            box.setInformativeText(str(facts))
        except Exception:   # noqa: BLE001 — a build without the setter keeps the question
            pass
    btn_over = box.addButton(_t("sftp.conflict.overwrite"),
                             box_cls.ButtonRole.AcceptRole)
    box.addButton(_t("sftp.conflict.skip"),
                  box_cls.ButtonRole.RejectRole)
    btn_rename = box.addButton(_t("sftp.conflict.rename"),
                               box_cls.ButtonRole.ActionRole)
    check = QCheckBox(_t("sftp.conflict.apply_all"))
    check.setEnabled(int(remaining or 0) > 0)
    box.setCheckBox(check)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_over:
        action = "overwrite"
    elif clicked is btn_rename:
        action = "rename"
    else:
        action = "skip"        # Skip, or a cancelled dialog (clickedButton() is None)
    apply_all = bool(check.isChecked()) and action in ("overwrite", "skip")
    return action, apply_all
