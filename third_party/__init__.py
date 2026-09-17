# -*- coding: utf-8 -*-
"""third_party — vendored dependencies (v1.3rc1).

So far only one: the managed pyte 0.8.2 fork in third_party/pyte/
(pristine PyPI sdist with provenance, sha256 pinned) + an explicit set of
patches in third_party/pyte-patches/. The single source of truth of the fork is
third_party/pyte-patches/MANIFEST.md (the base, the patch list, the sha256 tables,
the "drop when upstream merges it" policy, facts about the upstream internals).

Import seam (the only place in our code that knows about the fork):

    from third_party import pyte        # modules/terminal_screen.py

Reverting to stock pyte = one line back (import pyte) — see MANIFEST.md.
"""
