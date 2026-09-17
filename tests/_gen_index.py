# -*- coding: utf-8 -*-
"""The autogeneration of the "Files of the suite" table in tests/INDEX.md from the docstrings and the tags.

The source of the truth = the test files themselves: the first line of the module docstring (the essence)
and the `# tags:` line (parsed by the same functions of run_all.py as the runner — without
the import of the files, ast.parse). The block between the AUTOGEN markers is fully recreated;
the rest of the content of INDEX.md — manual. The set of files is taken from
run_all.collect_files() (only test_*.py: check_i18n_keys.py is described in the section
"Helper files"), hence the table always matches what the runner
starts.

Run from the project root:
    python tests/_gen_index.py          # update INDEX.md
    python tests/_gen_index.py --check  # without a write: exit 1 if the block is stale (CI)

The convention (INDEX.md, item 9): after adding/renaming a test file or
changing its docstring/tags run this script. Not part of the suite — run_all.py
skips the files with the _ prefix.
"""
import ast
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # the reliability of running not from the project root
from run_all import TESTS, collect_files, read_tags  # noqa: E402

INDEX_PATH = os.path.join(HERE, "INDEX.md")
BEGIN = "<!-- AUTOGEN:BEGIN test-files -->"
END = "<!-- AUTOGEN:END test-files -->"


def docstring_first_line(name):
    """The first non-empty line of the module docstring (ast.parse — without the import of the file).

    Return: None — the file does not parse (SyntaxError), "" — the docstring is absent,
    otherwise the string of the essence.
    """
    path = os.path.join(TESTS, name)
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    try:
        doc = ast.get_docstring(ast.parse(src), clean=True) or ""
    except SyntaxError:
        return None
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return ""


def build_block(names):
    """The generated block (with the markers). Return: (block, problems)."""
    lines = [BEGIN, ""]
    lines.append("| file | tags | what it checks (first line of the docstring) |")
    lines.append("|---|---|---|")
    problems = []
    for name in names:
        first = docstring_first_line(name)
        if first is None:
            desc = "⚠ the file does not parse (SyntaxError)"
            problems.append(f"{name}: SyntaxError — the docstring cannot be extracted")
        elif not first:
            desc = "⚠ no module docstring"
            problems.append(f"{name}: no module docstring")
        else:
            desc = first.replace("|", "\\|")
        tags = read_tags(name)
        tag_s = ", ".join(sorted(tags)) if tags else "—"
        lines.append(f"| `{name}` | {tag_s} | {desc} |")
    lines += ["", END]
    return "\n".join(lines), problems


def extract_block(text):
    """The current block between the markers in INDEX.md or None, if the markers are absent."""
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j <= i:
        return None
    return text[i:j + len(END)]


def main(argv):
    check_only = "--check" in argv
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"unknown arguments: {unknown} (only --check is supported)")
        return 2

    names = [n for n in collect_files() if n.startswith("test_")]
    block, problems = build_block(names)

    with open(INDEX_PATH, encoding="utf-8") as f:
        text = f.read()
    current = extract_block(text)
    if current is None:
        print(f"error: the markers {BEGIN} … {END} are not found in INDEX.md")
        return 1

    for p in problems:
        print("warning: " + p)

    if check_only:
        if current != block:
            diff = list(difflib.unified_diff(
                current.splitlines(), block.splitlines(),
                "INDEX.md (the current block)", "generated", lineterm=""))
            print(f"INDEX.md is STALE — the «Suite files» block does not match "
                  f"({len(diff)} diff lines):")
            for line in diff[:40]:
                print("  " + line)
            if len(diff) > 40:
                print(f"  … {len(diff) - 40} more lines")
            print("update: python tests/_gen_index.py")
            return 1
        print(f"INDEX.md is up to date ({len(names)} files)")
        return 0

    i = text.find(BEGIN)
    j = text.find(END) + len(END)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(text[:i] + block + text[j:])
    print(f"INDEX.md updated: {len(names)} files in the «Suite files» table")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
