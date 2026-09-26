# -*- coding: utf-8 -*-
"""The single source of truth for the application version (AUDIT v0.8.3, medium #1).

Previously the version was scattered across the main.py log, the i18n key title.main_window,
the version field in the project JSON (storage/project.py) and comments — which already
led to drift (the code said v0.8.1 while the release was v0.8.3).

Now all consumers import it from here:

    from version import APP_VERSION          # flat run (from the root)
    from ..version import APP_VERSION        # from a package

VERSION_FORMAT holds the version of the project JSON FORMAT (changes only on
an actual schema change; the format is not required to match the release).
"""

APP_VERSION = "1.5.7.1"      # application release (startup log, window title)
APP_NAME = "SSH Map"         # base name (window title)
VERSION_FORMAT = "0.9"       # project JSON format version (+ "background", storage/project.py)
