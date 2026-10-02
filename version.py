# -*- coding: utf-8 -*-
"""The single source of truth for the application version and the project JSON format.

Every consumer reads the version from here — `APP_NAME` (the base name of the window title), `APP_VERSION`
(the application release, used by the startup log and the title) and `VERSION_FORMAT` (the version of the
project JSON FORMAT, which changes only on a real schema change and is NOT required to match the release).
A scattered version drifts, which is exactly why this module exists: a release number has ONE home.

Import it flat when running from the root:
    from version import APP_VERSION
or relatively when the application is used as a package:
    from ..version import APP_VERSION"""

APP_VERSION = "1.7.4rc1"      # application release (startup log, window title)
APP_NAME = "SSH Map"         # base name (window title)
VERSION_FORMAT = "0.9"       # project JSON format version (+ "background", storage/project.py)
