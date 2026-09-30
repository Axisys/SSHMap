# -*- coding: utf-8 -*-
"""The refactor diff: prove that a comment/docstring cleanup did NOT touch the code.

    python tests/_refactor_diff.py --tree F:\\PythonAI\\backup\\sshmap   # a snapshot taken before
    python tests/_refactor_diff.py --git                              # the committed state

For every `.py` file present in BOTH trees the AST is compared with the docstrings STRIPPED — a code-level
equality that ignores comments, docstrings and formatting — and a second comparison masks the string
literals too, which separates "a test label changed" from "the structure changed". Every non-`.py` file is
compared byte for byte. Exit 0 ⇔ no file changed its STRUCTURE and nothing was deleted.

Not a test: the `_` prefix keeps it out of `run_all.py` (a snapshot tree is not part of the repository).
"""
import ast
import hashlib
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", ".git", "_tmp_testdata", "test-results", ".pytest_cache"}


def walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            path = os.path.join(base, name)
            yield os.path.relpath(path, root).replace("\\", "/"), path


def parse(source):
    try:
        return ast.parse(source.decode("utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def strip_docs(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


def mask_literals(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            node.value = "<str>"
    return tree


def literals(tree):
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def code_keys(source):
    """(code with docstrings stripped, the same with literals masked) or None when it does not parse."""
    tree = parse(source)
    if tree is None:
        return None
    return (ast.dump(strip_docs(parse(source))), ast.dump(mask_literals(strip_docs(tree))))


def snapshot_via_git(rel):
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True)
    return out.stdout if out.returncode == 0 else None


def main():
    argv = sys.argv[1:]
    quiet = "--quiet" in argv
    # `--git` sees the TRACKED files only: the gitignored documents (AGENTS.md, DOCUMENTATION.md, the
    # changelogs) then show up as "only in the work tree" — that is the mode's honest limit.
    use_git = "--git" in argv or "--tree" not in argv
    tree = None
    if "--tree" in argv:
        tree = argv[argv.index("--tree") + 1]
    if tree and not os.path.isdir(tree):
        sys.exit(f"no such snapshot tree: {tree}")

    current = dict(walk(ROOT))
    if tree:
        snap = dict(walk(tree))
        read_snap = lambda rel: open(snap[rel], "rb").read() if rel in snap else None  # noqa: E731
        names = set(current) | set(snap)
    else:
        names = set(current)
        read_snap = snapshot_via_git

    identical = literal_only = structural = binary_same = binary_diff = 0
    literal_files, structural_files, extra, missing, docs = [], [], [], [], []

    for rel in sorted(names):
        cur = current.get(rel)
        old = read_snap(rel)
        if cur is None:                      # the work tree lost a file the snapshot had
            missing.append(rel)
            continue
        if old is None:                      # a file the work tree added
            extra.append(rel)
            continue
        new = open(cur, "rb").read()
        if not rel.endswith(".py"):
            if hashlib.md5(new).hexdigest() == hashlib.md5(old).hexdigest():
                binary_same += 1
            else:
                binary_diff += 1
                docs.append(rel)
            continue
        keys_new, keys_old = code_keys(new), code_keys(old)
        if keys_new is None or keys_old is None:
            structural_files.append(rel)
            structural += 1
            continue
        if keys_new[0] == keys_old[0]:
            identical += 1
            continue
        if keys_new[1] == keys_old[1]:
            literal_only += 1
            literal_files.append(rel)
            continue
        structural += 1
        structural_files.append(rel)

    print(f"snapshot: {'git HEAD' if use_git else tree}")
    print(f"  .py code IDENTICAL      : {identical}")
    print(f"  .py only a LITERAL moved: {literal_only}")
    print(f"  .py STRUCTURE changed   : {structural}")
    print(f"  other files: same {binary_same}, changed {binary_diff}")
    print(f"  only in the snapshot    : {len(missing)}")
    print(f"  only in the work tree   : {len(extra)}")
    for label, rows in (("STRUCTURE", structural_files), ("only in snapshot", missing),
                        ("only in the work tree", extra), ("other file changed", docs)):
        if rows and not quiet:
            print(f"  {label}:")
            for r in rows[:40]:
                print(f"     {r}")
    if literal_files and not quiet:
        print("  a literal changed (a test label / a caption):")
        for rel in literal_files[:20]:
            old = read_snap(rel)
            cur_tree, old_tree = parse(open(os.path.join(ROOT, rel), "rb").read()), parse(old or b"")
            if cur_tree is None or old_tree is None:
                continue
            cur_lits = literals(strip_docs(cur_tree))
            old_lits = literals(strip_docs(old_tree))
            shown = 0
            for a, b in zip(old_lits, cur_lits):
                if a != b and shown < 3:
                    print(f"     {rel}")
                    print(f"        - {a[:90]}")
                    print(f"        + {b[:90]}")
                    shown += 1
    sys.exit(1 if (structural or missing) else 0)


if __name__ == "__main__":
    main()
