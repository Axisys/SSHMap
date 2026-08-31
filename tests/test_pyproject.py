# -*- coding: utf-8 -*-
"""v0.9.9.6 — pyproject.toml: installable-идентичность для 1.0 (ROADMAP).

Сверка pyproject ↔ version.py ↔ requirements.txt БЕЗ установки:
  * pyproject.toml существует и парсится (tomllib / tomli);
  * [project].name совпадает с APP_NAME из version.py (нормализация: нижний
    регистр, без не-алphanumeric — "SSH Map" → "sshmap");
  * [project].version == APP_VERSION из version.py (единая точка истины — version.py);
  * [project].dependencies соответствуют requirements.txt (тот же набор имя+пин);
  * entry point sshmap = main:main указывает на существующую top-level функцию
    main() в main.py (ast, без импорта), а модуль входит в сборку;
  * [build-system] присутствует (pipx / pip install .).

Сьют запускается через tests/run_all.py; файл самодостаточен:
bootstrap() → проверки → finish().
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
    """Парсинг TOML: tomllib (Python 3.11+) или tomli (pip install tomli)."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError as e:
            raise SystemExit(
                "нет TOML-парсера: нужен Python 3.11+ (tomllib) или pip install tomli"
            ) from e
    with open(path, "rb") as f:
        return tomllib.load(f)


def version_py_constants(path):
    """APP_NAME/APP_VERSION из version.py через ast — без импорта и side effects."""
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
                        pass  # не-литерал — проверка ниже отчётит про отсутствующее поле
    return vals


def split_requirement(req):
    """'PySide6>=6.5' → ('pyside6', '>=6.5'); имя нормализуется по PEP 503."""
    m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*?)\s*$", req)
    if not m:
        return None
    name = re.sub(r"[-_.]+", "-", m.group(1)).lower()
    return name, m.group(2)


def parse_requirements(path):
    """requirements.txt → {нормализованное_имя: спецификатор}; комментарии/пустые — мимо."""
    reqs = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = re.sub(r"\s+#.*$", "", raw).strip()  # trailing-комментарий
            if not line or line.startswith("#"):
                continue
            pair = split_requirement(line)
            if pair:
                reqs[pair[0]] = pair[1]
    return reqs


def norm_name(name):
    """Нормализация имени для сверки [project].name с APP_NAME (регистр/разделители не значимы)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ── 1. pyproject.toml существует и парсится ───────────────────────────────
exists = os.path.isfile(PYPROJECT)
check("pyproject.toml существует", exists, "файл не найден в корне проекта")
pp = None
if exists:
    try:
        pp = load_toml(PYPROJECT)
        check("pyproject.toml парсится (TOML)", True)
    except Exception as e:
        check("pyproject.toml парсится (TOML)", False, f"{type(e).__name__}: {e}")

project = (pp or {}).get("project", {})

# ── 2. имя и версия совпадают с version.py ────────────────────────────────
consts = version_py_constants(VERSION_PY) if os.path.isfile(VERSION_PY) else {}
app_name = consts.get("APP_NAME")
app_version = consts.get("APP_VERSION")
check("version.py: APP_NAME/APP_VERSION читаются (ast)", bool(app_name and app_version),
      f"APP_NAME={app_name!r}, APP_VERSION={app_version!r}")

if app_name is not None:
    py_name = project.get("name")
    check("[project].name совпадает с version.py (APP_NAME)",
          py_name is not None and norm_name(py_name) == norm_name(app_name),
          f"pyproject={py_name!r} vs APP_NAME={app_name!r}")

if app_version is not None:
    py_version = project.get("version")
    check("[project].version совпадает с version.py (APP_VERSION)",
          py_version == app_version,
          f"pyproject={py_version!r} vs APP_VERSION={app_version!r}")

# ── 3. dependencies соответствуют requirements.txt ────────────────────────
reqs = parse_requirements(REQUIREMENTS) if os.path.isfile(REQUIREMENTS) else {}
check("requirements.txt: зависимости читаются", len(reqs) > 0, "нет валидных строк")

py_deps = {}
for dep in project.get("dependencies") or []:
    pair = split_requirement(dep) if isinstance(dep, str) else None
    if pair:
        py_deps[pair[0]] = pair[1]
check("[project].dependencies соответствуют requirements.txt (тот же набор имя+пин)",
      py_deps == reqs,
      f"pyproject={py_deps} vs requirements={reqs}")

# ── 4. entry point sshmap = main:main → существующая функция ──────────────
scripts = project.get("scripts") or {}
ep = scripts.get("sshmap")
check("entry point sshmap = main:main", ep == "main:main", f"получено {ep!r}")

if isinstance(ep, str) and ":" in ep:
    mod, attr = ep.split(":", 1)
    mod_path = os.path.join(ROOT, mod + ".py")
    found = False
    detail = f"{mod}.py не найден в корне проекта"
    if os.path.isfile(mod_path):
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=mod_path)
        for node in tree.body:  # только top-level — entry point ссылается на модульный уровень
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == attr:
                found = True
                detail = ""
    check(f"entry point указывает на существующую функцию {mod}:{attr} (ast, без импорта)",
          found, detail)

    # Модуль обязан входить в сборку — иначе его не будет в site-packages.
    st = (pp or {}).get("tool", {}).get("setuptools", {})
    if st:
        installed = set(st.get("py-modules") or []) | set(st.get("packages") or [])
        check(f"модуль {mod!r} входит в сборку ([tool.setuptools])", mod in installed,
              f"в сборке: {sorted(installed)}")

# ── 5. [build-system] — pipx / pip install . ──────────────────────────────
bs = (pp or {}).get("build-system", {})
check("[build-system] присутствует (requires + build-backend)",
      bool(bs.get("requires")) and bool(bs.get("build-backend")),
      f"получено {bs!r}")

finish()
