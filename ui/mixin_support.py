"""Shared plumbing for the mixins of a FACADE (`MainWindow`, `_SftpPane`; AGENTS.md §4.1, §4.3).

The mixins do NOT import their facade module — that would be a cycle, since the facade imports THEM — so
access to the module's globals goes through `sys.modules` by the class's module name, which by call time is
fully loaded.

This is also the test seam for monkeypatching: the existing tests patch MODULE attributes
(`MW.SSHConnectDialog = Fake`, `MW._ext_term = Fake`, `MW.format_size = Fake`, …), and a method that moved
into a mixin must still see the replacement — otherwise the fakes would not take effect and an offscreen run
would hang on a real dialog.

It follows the "module + callbacks" pattern of `ui/sidebar.py` and `services/diagnostics.py`: the mixin holds only methods, all shared state lives on the facade instance through duck typing, and the ownership of that state is pinned by a comment in each mixin."""
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
