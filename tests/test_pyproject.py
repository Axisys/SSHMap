# -*- coding: utf-8 -*-
"""v0.9.9.6 — pyproject.toml: installable identity for 1.0 (ROADMAP).

The cross-check pyproject ↔ version.py ↔ requirements.txt WITHOUT an install:
  * pyproject.toml exists and parses (tomllib / tomli);
  * [project].name matches the APP_NAME from version.py (normalization: the lower
    case, the non-alphanumerics stripped — "SSH Map" → "sshmap");
  * [project].version == the APP_VERSION from version.py (the single source of truth — version.py);
  * [project].dependencies match requirements.txt (the same set of name+pin);
  * the entry point sshmap = main:main points to the existing top-level function
    main() in main.py (ast, without an import), and the module is in the build;
  * [build-system] is present (pipx / pip install .).

The suite is run through tests/run_all.py; the file is self-contained:
bootstrap() → the checks → finish().
"""
import ast
import os
import re

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()

PYPROJECT = os.path.join(ROOT, "pyproject.toml")
VERSION_PY = os.path.join(ROOT, "version.py")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")


def load_toml(path):
    """The TOML parsing: tomllib (Python 3.11+) or tomli (pip install tomli)."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError as e:
            raise SystemExit(
                "no TOML parser: need Python 3.11+ (tomllib) or pip install tomli"
            ) from e
    with open(path, "rb") as f:
        return tomllib.load(f)


def version_py_constants(path):
    """APP_NAME/APP_VERSION from version.py via ast — without import and side effects."""
    vals = {}
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("APP_NAME", "APP_VERSION"):
                    try:
                        vals[target.id] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        pass  # a non-literal — the check below will report the missing field
    return vals


def split_requirement(req):
    """'PySide6>=6.5' → ('pyside6', '>=6.5'); the name is normalized per PEP 503."""
    m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*?)\s*$", req)
    if not m:
        return None
    name = re.sub(r"[-_.]+", "-", m.group(1)).lower()
    return name, m.group(2)


def parse_requirements(path):
    """requirements.txt → {normalized_name: specifier}; comments/blank lines — skipped."""
    reqs = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = re.sub(r"\s+#.*$", "", raw).strip()  # a trailing comment
            if not line or line.startswith("#"):
                continue
            pair = split_requirement(line)
            if pair:
                reqs[pair[0]] = pair[1]
    return reqs


def norm_name(name):
    """The name normalization for the cross-check of [project].name against APP_NAME (the case/separators are not significant)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ── 1. pyproject.toml exists and parses ───────────────────────────────
exists = os.path.isfile(PYPROJECT)
check("pyproject.toml exists", exists, "the file is not found in the project root")
pp = None
if exists:
    try:
        pp = load_toml(PYPROJECT)
        check("pyproject.toml parses (TOML)", True)
    except Exception as e:
        check("pyproject.toml parses (TOML)", False, f"{type(e).__name__}: {e}")

project = (pp or {}).get("project", {})

# ── 2. the name and the version match version.py ────────────────────────────────
consts = version_py_constants(VERSION_PY) if os.path.isfile(VERSION_PY) else {}
app_name = consts.get("APP_NAME")
app_version = consts.get("APP_VERSION")
check("version.py: APP_NAME/APP_VERSION are readable (ast)", bool(app_name and app_version),
      f"APP_NAME={app_name!r}, APP_VERSION={app_version!r}")

if app_name is not None:
    py_name = project.get("name")
    check("[project].name matches version.py (APP_NAME)",
          py_name is not None and norm_name(py_name) == norm_name(app_name),
          f"pyproject={py_name!r} vs APP_NAME={app_name!r}")

if app_version is not None:
    py_version = project.get("version")
    check("[project].version matches version.py (APP_VERSION)",
          py_version == app_version,
          f"pyproject={py_version!r} vs APP_VERSION={app_version!r}")

# ── 3. the dependencies match requirements.txt ────────────────────────
reqs = parse_requirements(REQUIREMENTS) if os.path.isfile(REQUIREMENTS) else {}
check("requirements.txt: the dependencies are readable", len(reqs) > 0, "no valid lines")

py_deps = {}
for dep in project.get("dependencies") or []:
    pair = split_requirement(dep) if isinstance(dep, str) else None
    if pair:
        py_deps[pair[0]] = pair[1]
check("[project].dependencies match requirements.txt (the same set of name+pin)",
      py_deps == reqs,
      f"pyproject={py_deps} vs requirements={reqs}")

# ── 4. the entry point sshmap = main:main → the existing function ──────────────
scripts = project.get("scripts") or {}
ep = scripts.get("sshmap")
check("entry point sshmap = main:main", ep == "main:main", f"got {ep!r}")

if isinstance(ep, str) and ":" in ep:
    mod, attr = ep.split(":", 1)
    mod_path = os.path.join(ROOT, mod + ".py")
    found = False
    detail = f"{mod}.py is not found in the project root"
    if os.path.isfile(mod_path):
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=mod_path)
        for node in tree.body:  # top-level only — the entry point refers to module level
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == attr:
                found = True
                detail = ""
    check(f"the entry point points to the existing function {mod}:{attr} (ast, without an import)",
          found, detail)

    # The module must enter the build — otherwise it will not be in site-packages.
    st = (pp or {}).get("tool", {}).get("setuptools", {})
    if st:
        installed = set(st.get("py-modules") or []) | set(st.get("packages") or [])
        check(f"the module {mod!r} is in the build ([tool.setuptools])", mod in installed,
              f"in the build: {sorted(installed)}")

# ── 5. [build-system] — pipx / pip install . ──────────────────────────────
bs = (pp or {}).get("build-system", {})
check("[build-system] is present (requires + build-backend)",
      bool(bs.get("requires")) and bool(bs.get("build-backend")),
      f"got {bs!r}")

finish()
