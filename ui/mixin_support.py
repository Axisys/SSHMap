"""Shared plumbing for the MainWindow mixins (v1.1.4 — the split of ui/main_window.py).

The mixins do NOT import ui.main_window (cycle: main_window imports them
itself), so access to the facade module's globals goes through sys.modules
by the class's module name — by call time the facade is fully loaded.

This is also the test seam for monkeypatching: existing tests patch MODULE
attributes (``MW.SSHConnectDialog = Fake``, ``MW._ext_term = Fake``, etc.),
and methods moved into mixins must see the replacement — otherwise the
mocks/fakes would not take effect and the offscreen run would hang on a
real dialog.

"Module + callbacks" pattern (precedents: v0.9.9.4 sidebar, v0.9.9.3
diagnostics): the mixin holds only methods; all shared state lives on the
MainWindow instance (duck-typing), ownership pinned by a comment in each
mixin.
"""
import sys


def host_attr(self, name, default=None):
    """Read an attribute of the MainWindow module (ui.main_window) at call time.

    ``type(self).__module__`` is either "ui.main_window" (package import)
    or "main_window" (flat run); sys.modules finds both variants.
    Returns ``default`` if the module/attribute is unavailable.
    """
    mod = sys.modules.get(type(self).__module__)
    if mod is None:
        return default
    return getattr(mod, name, default)
