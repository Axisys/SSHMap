# -*- coding: utf-8 -*-
"""v1.4.7 — Syntax highlighting in the SFTP viewer (numbers, JSON/XML/YAML, ROADMAP v1.4.7).

The release theme: the read-only preview of the SFTP tab stops being monochrome. The
viewer and its "no preview" markers made the LISTING informative; what was missing was
the readability of the CONTENT — a 40 KB nginx config, a minified JSON or a k8s manifest
in a monochrome canvas is hard to skim. Nothing about the read path changes: the same
worker queue, the same 1 MB limit, the same encodings — the release only PAINTS what is
already in the widget, and it does so without a new dependency (the standard library for
the grammars, `QSyntaxHighlighter` for the paint).

Everything here is checked WITHOUT the network: the fake in-memory SFTP of
tests/_fakes.py feeds the real worker queue, exactly like test_sftp_viewer.py.

The sections:
  1. The palette — the `SYNTAX_*` block of `ui/theme.py`: the 8 roles of the tokenizer
     vocabulary, a PER-INSTANCE field pair (DARK/LIGHT each carry their own), valid
     hexes, pairwise distinct, never the "no preview" tone, live proxies; and the
     module contract of `modules/syntax_highlight.py` (importable WITHOUT PySide6 —
     the tokenizers must stay headless).
  2. Detection — `detect_syntax(path, text)`: the extension is a HINT, the content is
     the VERDICT. A `.json`/`.xml` that does not really parse degrades to "numbers";
     `.yaml`/`.yml` is accepted as a HEURISTIC; an unknown extension NEVER guesses from
     the content.
  3. The tokenizers — exact spans: JSON (escapes inside a string, keys vs values,
     numbers, keywords, punctuation), XML (tag/attribute/value/comment/CDATA/
     declaration + a multi-line comment and CDATA through the block state), YAML
     (comments, keys, list markers, quoted scalars, a `|`/`>` block scalar up to the
     end of the block, a `#` inside a quoted scalar is NOT a comment) and the shared
     numbers-only rule (no false positives: `abc123`, `1.2.3`, a date, a glued size).
  4. The budgets — the per-block TOKEN cap (a minified MB-scale single line must not
     freeze the GUI) and the measured opening budgets of a ~1 MB file.
  5. The tab — the detected language, the heuristic note in the header (YAML only), the
     colours really applied to the blocks, the reset between two files (no bleed).
  6. Laziness — only the blocks around the viewport carry formats; scrolling formats the
     next ones; the repeat pass is free.
  7. The theme switch — the applied formats follow the ACTIVE theme (they are values).
  8. i18n (613) + the release state.

Run:  python tests/test_sftp_syntax.py   (from the project root) or python tests/run_all.py
"""
import ast
import dataclasses
import json
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs,
                     placeholder_names, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
from ui import theme
from ui import theme_qss
from modules import syntax_highlight as SH
from modules.sftp_tab import SftpTab, format_size
from modules.sftp_worker import SftpWorker

# The fake in-memory FS + the fake SFTPClient (no network) — the shared stubs _fakes.py
from _fakes import FakeSftpFS, FakeSftpClient, EventLog, wire_worker


def tokens(language, line, state=0):
    """`tokenize_line` as readable tokens: ([(text, role), …], next_state)."""
    spans, next_state = SH.tokenize_line(language, line, state)
    return [(line[start:start + length], role) for start, length, role in spans], next_state


def block_formats(edit, number):
    """The formats really applied to ONE block: [(text, "#rrggbb"), …].

    Read from the block's QTextLayout — that is what the user sees, so a check here
    fails for the real defect and not for a bookkeeping one. `None` — the block does
    not exist / was never laid out.
    """
    block = edit.document().findBlockByNumber(number)
    if block is None or not block.isValid():
        return None
    layout = block.layout()
    if layout is None:
        return None
    text = block.text()
    return [(text[r.start:r.start + r.length], r.format.foreground().color().name())
            for r in layout.formats()]


def all_applied_colours(edit):
    """Every colour the highlighter really painted in the document."""
    colours = set()
    for number in range(edit.document().blockCount()):
        for _text, colour in block_formats(edit, number) or ():
            colours.add(colour)
    return colours


def item_by_name(tab, name):
    """The row of the SFTP listing by its visible name (None — not there yet)."""
    for i in range(tab.tree.topLevelItemCount()):
        item = tab.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


# ════════════════════════════════════════════════════════════
# 1. The palette (ui/theme.py) + the module contract
# ════════════════════════════════════════════════════════════
print("== 1. the SYNTAX_* palette of the theme + the module contract ==")

check("the theme carries exactly the 8 roles of the tokenizer vocabulary",
      tuple(theme.THEME.syntax_colors) == SH.SYNTAX_ROLES and len(SH.SYNTAX_ROLES) == 8,
      f"roles={SH.SYNTAX_ROLES}")
check("every role resolves to its own `syntax_<role>` field (one spelling, no second table)",
      all(SH.syntax_field(role) in {f.name for f in dataclasses.fields(theme.Theme)}
          for role in SH.SYNTAX_ROLES)
      and all(getattr(theme.DARK, SH.syntax_field(role)) == theme.DARK.syntax_colors[role]
              for role in SH.SYNTAX_ROLES),
      str(SH.syntax_field("number")))

check("the palette is PER-INSTANCE: DARK and LIGHT each carry a complete entry",
      all(getattr(theme.LIGHT, SH.syntax_field(role))
          and getattr(theme.DARK, SH.syntax_field(role)) for role in SH.SYNTAX_ROLES))
check("every tone of both instances is a valid #rrggbb colour",
      all(theme.is_valid_hex(value)
          for value in list(theme.DARK.syntax_colors.values())
          + list(theme.LIGHT.syntax_colors.values())))
check("the 8 tones of a theme are pairwise DISTINCT (a role must be tellable apart)",
      len(set(theme.DARK.syntax_colors.values())) == 8
      and len(set(theme.LIGHT.syntax_colors.values())) == 8,
      f"dark={len(set(theme.DARK.syntax_colors.values()))} "
      f"light={len(set(theme.LIGHT.syntax_colors.values()))}")
check("no syntax tone is the 'no preview' tone (the marker of a refused row)",
      all(value != instance.sftp_preview_blocked
          for instance in (theme.DARK, theme.LIGHT)
          for value in instance.syntax_colors.values()),
      f"blocked={theme.DARK.sftp_preview_blocked}")
check("the two modes really differ (a light viewer needs its own tones)",
      theme.DARK.syntax_colors != theme.LIGHT.syntax_colors
      and theme.DARK.syntax_number != theme.LIGHT.syntax_number)
check("the palette follows the ACTIVE theme (a live proxy, never an import-time capture)",
      theme.SYNTAX_NUMBER == theme.DARK.syntax_number
      and theme.SYNTAX_COLORS == theme.DARK.syntax_colors)
check("the field names are the historical spelling of the role names",
      theme.SYNTAX_PUNCTUATION == theme.DARK.syntax_punctuation
      and theme.SYNTAX_KEYWORD == theme.DARK.syntax_keyword)


def _non_syntax_values(instance):
    """Every colour the instance already ships OUTSIDE the syntax block (the fields)."""
    names = {SH.syntax_field(role) for role in SH.SYNTAX_ROLES}
    return {getattr(instance, f.name) for f in dataclasses.fields(theme.Theme)
            if f.name not in names and isinstance(getattr(instance, f.name), str)}


check("every syntax tone is a value its instance ALREADY ships — the 'Do not touch' rule "
      "for DARK (a NEW field resolving to an existing value) and a re-tuned role set for LIGHT",
      set(theme.DARK.syntax_colors.values()) <= _non_syntax_values(theme.DARK)
      and set(theme.LIGHT.syntax_colors.values()) <= _non_syntax_values(theme.LIGHT),
      f"dark={sorted(set(theme.DARK.syntax_colors.values()) - _non_syntax_values(theme.DARK))} "
      f"light={sorted(set(theme.LIGHT.syntax_colors.values()) - _non_syntax_values(theme.LIGHT))}")

# The module contract: `modules/syntax_highlight.py` must stay importable (and its
# tokenizers runnable) WITHOUT PySide6 — the `ui/theme.py` rule of the same project,
# verified the same way (the AST of the MODULE level, not of a function body).
_src = open(os.path.join(ROOT, "modules", "syntax_highlight.py"), encoding="utf-8").read()
_tree = ast.parse(_src)
_top_modules = set()
for _node in _tree.body:
    if isinstance(_node, ast.Import):
        _top_modules.update(alias.name.split(".")[0] for alias in _node.names)
    elif isinstance(_node, ast.ImportFrom) and _node.module:
        _top_modules.add(_node.module.split(".")[0])
check("§1 syntax_highlight.py imports only the STANDARD LIBRARY at module level",
      _top_modules <= {"json", "posixpath", "re", "xml"}, str(sorted(_top_modules)))
check("§1 ...and the only PySide6 import is INSIDE the highlighter factory (lazy, Qt-free core)",
      "from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat" in _src
      and not any(line.startswith("from PySide6") for line in _src.splitlines()))
check("§1 importing the module does NOT build the Qt class (the factory is on demand)",
      SH._HIGHLIGHTER_CLASS is None)


# ════════════════════════════════════════════════════════════
# 2. Detection — the extension hint, the content verdict
# ════════════════════════════════════════════════════════════
print("== 2. detect_syntax: the hint and the verdict ==")

check("a .json that really parses → json",
      SH.detect_syntax("/etc/app.json", '{"a": 1, "b": [true, null]}') == SH.LANG_JSON)
check("a .json that does NOT parse → numbers (the honesty rule — no false grammar)",
      SH.detect_syntax("/etc/app.json", '{"a": ') == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/app.json", "not json at all") == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/app.json", "") == SH.LANG_NUMBERS)
check("a .xml that really parses → xml",
      SH.detect_syntax("/etc/svc.xml", "<a><b/></a>") == SH.LANG_XML)
check("a .xml that does NOT parse → numbers",
      SH.detect_syntax("/etc/svc.xml", "<a><b>") == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/svc.xml", "<?xml version='1.0'?><a>") == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/svc.xml", "plain text") == SH.LANG_NUMBERS)
check("a .yaml / .yml is accepted as-is — the documented HEURISTIC (no stdlib parser)",
      SH.detect_syntax("/etc/k8s.yaml", "a: 1") == SH.LANG_YAML
      and SH.detect_syntax("/etc/k8s.yml", "---\nnot: [valid") == SH.LANG_YAML
      and SH.HEURISTIC_LANGUAGES == (SH.LANG_YAML,) and SH.is_heuristic(SH.LANG_YAML))
check("the verified modes are NOT heuristics (the colours speak for themselves)",
      not SH.is_heuristic(SH.LANG_JSON) and not SH.is_heuristic(SH.LANG_XML)
      and not SH.is_heuristic(SH.LANG_NUMBERS))
check("an unknown / absent extension NEVER guesses from the content → numbers",
      SH.detect_syntax("/etc/README", '{"a": 1}') == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/hosts", "<a/>") == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/data.weird", "a: 1") == SH.LANG_NUMBERS
      and SH.detect_syntax("", '{"a": 1}') == SH.LANG_NUMBERS)
check("the extension is matched case-insensitively and on the LAST dot",
      SH.detect_syntax("/etc/A.JSON", "{}") == SH.LANG_JSON
      and SH.detect_syntax("C:/tmp/B.Xml", "<a/>") == SH.LANG_XML
      and SH.detect_syntax("/etc/archive.tar.gz", "x") == SH.LANG_NUMBERS)
check("a broken path / a broken text never raises (the viewer must not care)",
      SH.detect_syntax(None, None) == SH.LANG_NUMBERS
      and SH.detect_syntax(42, "{}") == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/a.json", None) == SH.LANG_NUMBERS)
check("the four language ids are exactly the documented set",
      SH.LANGUAGES == ("json", "xml", "yaml", "numbers"))


# ════════════════════════════════════════════════════════════
# 3. The tokenizers — exact spans
# ════════════════════════════════════════════════════════════
print("== 3. the tokenizers: exact spans ==")

DARK = theme.DARK

# ── JSON ──
_json_line = r'  "name": "a\"b", "n": 12, "ok": true }'
_json_tokens, _json_state = tokens(SH.LANG_JSON, _json_line)
check("json: a key is told from a value, and an ESCAPED quote does not end the string",
      _json_tokens == [('"name"', SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                       (r'"a\"b"', SH.ROLE_STRING), (",", SH.ROLE_PUNCTUATION),
                       ('"n"', SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                       ("12", SH.ROLE_NUMBER), (",", SH.ROLE_PUNCTUATION),
                       ('"ok"', SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                       ("true", SH.ROLE_KEYWORD), ("}", SH.ROLE_PUNCTUATION)],
      str(_json_tokens))
check("json: the block state is never carried over (a document ends on its line)",
      _json_state == SH.STATE_NORMAL)
_nested, _ = tokens(SH.LANG_JSON, '{"a": [1, 2.5, -3e4], "b": null}')
check("json: numbers (int/float/exponent/sign), keywords and punctuation",
      _nested == [("{", SH.ROLE_PUNCTUATION), ('"a"', SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                  ("[", SH.ROLE_PUNCTUATION), ("1", SH.ROLE_NUMBER), (",", SH.ROLE_PUNCTUATION),
                  ("2.5", SH.ROLE_NUMBER), (",", SH.ROLE_PUNCTUATION),
                  ("-3e4", SH.ROLE_NUMBER), ("]", SH.ROLE_PUNCTUATION),
                  (",", SH.ROLE_PUNCTUATION), ('"b"', SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                  ("null", SH.ROLE_KEYWORD), ("}", SH.ROLE_PUNCTUATION)],
      str(_nested))
_unterminated, _ = tokens(SH.LANG_JSON, '{"a": "never closed')
check("json: an unterminated string runs to the end of the line (and stops there)",
      _unterminated == [("{", SH.ROLE_PUNCTUATION), ('"a"', SH.ROLE_KEY),
                        (":", SH.ROLE_PUNCTUATION), ('"never closed', SH.ROLE_STRING)],
      str(_unterminated))
check("json: a word that merely STARTS with a keyword is not coloured as one",
      tokens(SH.LANG_JSON, "trueish nulled")[0] == [], str(tokens(SH.LANG_JSON, "trueish nulled")[0]))

# ── XML ──
_xml_tag, _ = tokens(SH.LANG_XML, '<a href="x" data-y="1">text</a>')
check("xml: tag, attribute names, attribute values, punctuation (the text stays plain)",
      _xml_tag == [("<", SH.ROLE_PUNCTUATION), ("a", SH.ROLE_TAG),
                   ("href", SH.ROLE_ATTRIBUTE), ("=", SH.ROLE_PUNCTUATION),
                   ('"x"', SH.ROLE_STRING), ("data-y", SH.ROLE_ATTRIBUTE),
                   ("=", SH.ROLE_PUNCTUATION), ('"1"', SH.ROLE_STRING),
                   (">", SH.ROLE_PUNCTUATION), ("</", SH.ROLE_PUNCTUATION),
                   ("a", SH.ROLE_TAG), (">", SH.ROLE_PUNCTUATION)],
      str(_xml_tag))
_xml_decl, _ = tokens(SH.LANG_XML, '<?xml version="1.0" encoding="UTF-8"?>')
check("xml: a DECLARATION is a tag with attributes of its own",
      _xml_decl == [("<?", SH.ROLE_PUNCTUATION), ("xml", SH.ROLE_TAG),
                    ("version", SH.ROLE_ATTRIBUTE), ("=", SH.ROLE_PUNCTUATION),
                    ('"1.0"', SH.ROLE_STRING), ("encoding", SH.ROLE_ATTRIBUTE),
                    ("=", SH.ROLE_PUNCTUATION), ('"UTF-8"', SH.ROLE_STRING),
                    ("?>", SH.ROLE_PUNCTUATION)],
      str(_xml_decl))
check("xml: a self-closing tag and a DOCTYPE are both understood",
      tokens(SH.LANG_XML, "<br/>")[0] == [("<", SH.ROLE_PUNCTUATION), ("br", SH.ROLE_TAG),
                                          ("/>", SH.ROLE_PUNCTUATION)]
      and tokens(SH.LANG_XML, "<!DOCTYPE html>")[0]
      == [("<", SH.ROLE_PUNCTUATION), ("!DOCTYPE html", SH.ROLE_TAG),
          (">", SH.ROLE_PUNCTUATION)])
_comment_open, _comment_state = tokens(SH.LANG_XML, "<!-- a comment")
check("xml: a one-line comment is a comment",
      tokens(SH.LANG_XML, "<a/><!-- why -->")[0][3] == ("<!-- why -->", SH.ROLE_COMMENT))
check("xml: an OPEN comment leaves the block state open",
      _comment_open == [("<!-- a comment", SH.ROLE_COMMENT)]
      and _comment_state == SH.STATE_XML_COMMENT, f"state={_comment_state}")
_comment_mid, _comment_mid_state = tokens(SH.LANG_XML, "still a comment", _comment_state)
check("xml: the next line CONTINUES the comment through `previousBlockState()`",
      _comment_mid == [("still a comment", SH.ROLE_COMMENT)]
      and _comment_mid_state == SH.STATE_XML_COMMENT)
_comment_end, _comment_end_state = tokens(SH.LANG_XML, "ends --> <b/>", _comment_mid_state)
check("xml: the comment closes on the terminator and the rest of the line is code again",
      _comment_end == [("ends -->", SH.ROLE_COMMENT), ("<", SH.ROLE_PUNCTUATION),
                       ("b", SH.ROLE_TAG), ("/>", SH.ROLE_PUNCTUATION)]
      and _comment_end_state == SH.STATE_NORMAL, str(_comment_end))
_cdata_open, _cdata_state = tokens(SH.LANG_XML, "<![CDATA[ raw ")
check("xml: CDATA colours its payload and keeps the state open",
      _cdata_open == [("<![CDATA[ raw ", SH.ROLE_STRING)]
      and _cdata_state == SH.STATE_XML_CDATA)
_cdata_end, _cdata_end_state = tokens(SH.LANG_XML, "raw ]]> tail", _cdata_state)
check("xml: the CDATA section closes on `]]>`",
      _cdata_end == [("raw ]]>", SH.ROLE_STRING)] and _cdata_end_state == SH.STATE_NORMAL)

# ── YAML (the honest heuristic) ──
check("yaml: a whole-line comment",
      tokens(SH.LANG_YAML, "# a comment")[0] == [("# a comment", SH.ROLE_COMMENT)])
check("yaml: a key + a trailing comment (the comment reaches the end of the line)",
      tokens(SH.LANG_YAML, "key: value  # trailing")[0]
      == [("key", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
          ("# trailing", SH.ROLE_COMMENT)])
check("yaml: a `#` inside a QUOTED scalar is NOT a comment (both quote styles)",
      tokens(SH.LANG_YAML, 'key: "a # b"')[0]
      == [("key", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION), ('"a # b"', SH.ROLE_STRING)]
      and tokens(SH.LANG_YAML, "key: 'x # y'")[0]
      == [("key", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION), ("'x # y'", SH.ROLE_STRING)],
      str(tokens(SH.LANG_YAML, 'key: "a # b"')[0]))
check("yaml: a glued `#` is part of the word, not a comment",
      tokens(SH.LANG_YAML, "url: http://host/#frag")[0]
      == [("url", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION)])
check("yaml: a LIST MARKER is punctuation, and a key may follow it",
      tokens(SH.LANG_YAML, "- item")[0] == [("-", SH.ROLE_PUNCTUATION)]
      and tokens(SH.LANG_YAML, "  - b: 2")[0]
      == [("-", SH.ROLE_PUNCTUATION), ("b", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
          ("2", SH.ROLE_NUMBER)],
      str(tokens(SH.LANG_YAML, "  - b: 2")[0]))
check("yaml: document markers and flow collections",
      tokens(SH.LANG_YAML, "---")[0] == [("---", SH.ROLE_PUNCTUATION)]
      and tokens(SH.LANG_YAML, "a: [1, 2]")[0]
      == [("a", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION), ("[", SH.ROLE_PUNCTUATION),
          ("1", SH.ROLE_NUMBER), (",", SH.ROLE_PUNCTUATION), ("2", SH.ROLE_NUMBER),
          ("]", SH.ROLE_PUNCTUATION)])
check("yaml: bool / null keywords and numbers are values, not keys",
      tokens(SH.LANG_YAML, "flag: true")[0]
      == [("flag", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION), ("true", SH.ROLE_KEYWORD)]
      and tokens(SH.LANG_YAML, "n: 1.5")[0]
      == [("n", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION), ("1.5", SH.ROLE_NUMBER)])
_block_open, _block_state = tokens(SH.LANG_YAML, "name: |")
check("yaml: `|` opens a block scalar and records the line's indentation in the state",
      _block_open == [("name", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                      ("|", SH.ROLE_PUNCTUATION)]
      and _block_state == SH.STATE_YAML_BLOCK_BASE, f"state={_block_state}")
_block_body, _ = tokens(SH.LANG_YAML, "  block line one", _block_state)
check("yaml: the block body is a string (the indent is kept out of the span)",
      _block_body == [("block line one", SH.ROLE_STRING)], str(_block_body))
check("yaml: a BLANK line stays inside the block",
      tokens(SH.LANG_YAML, "", _block_state) == ([], _block_state))
_block_after, _block_after_state = tokens(SH.LANG_YAML, "next: 1", _block_state)
check("yaml: the block ENDS at the first line that is not indented deeper",
      _block_after == [("next", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                       ("1", SH.ROLE_NUMBER)]
      and _block_after_state == SH.STATE_NORMAL, str(_block_after))
_folded, _folded_state = tokens(SH.LANG_YAML, "b: >-")
check("yaml: the folded indicator `>-` opens a block as well",
      _folded == [("b", SH.ROLE_KEY), (":", SH.ROLE_PUNCTUATION),
                  (">-", SH.ROLE_PUNCTUATION)]
      and _folded_state == SH.STATE_YAML_BLOCK_BASE)

# ── the shared numbers-only rule ──
_numbers, _ = tokens(SH.LANG_NUMBERS, "abc123 and 1.2.3 and 2026-09-28 and 10GB and 42")
check("numbers: an identifier, a VERSION, a DATE and a glued SIZE are not numbers",
      _numbers == [("42", SH.ROLE_NUMBER)], str(_numbers))
check("numbers: plain numbers are coloured, signs and exponents included",
      tokens(SH.LANG_NUMBERS, "value = -5, 3.14e-2, 1e6")[0]
      == [("-5", SH.ROLE_NUMBER), ("3.14e-2", SH.ROLE_NUMBER), ("1e6", SH.ROLE_NUMBER)],
      str(tokens(SH.LANG_NUMBERS, "value = -5, 3.14e-2, 1e6")[0]))
check("numbers: a comma stays a delimiter (a flow list keeps its digits coloured)",
      tokens(SH.LANG_NUMBERS, "1, 2, 3")[0]
      == [("1", SH.ROLE_NUMBER), ("2", SH.ROLE_NUMBER), ("3", SH.ROLE_NUMBER)])
check("numbers: the rule is shared — YAML and the fallback agree on the same line",
      SH.number_spans("x = 42") == SH.tokenize_line(SH.LANG_NUMBERS, "x = 42")[0]
      and tokens(SH.LANG_YAML, "k: 42")[0][-1] == ("42", SH.ROLE_NUMBER))

# The general invariants of every tokenizer: sorted, non-overlapping, in bounds.
_probe_lines = [
    (SH.LANG_JSON, '{"a": [1, {"b": "x"}], "c": null}'),
    (SH.LANG_XML, '<?xml version="1.0"?><a b="c"><!-- x --><![CDATA[y]]></a>'),
    (SH.LANG_YAML, "a: [1, 'x # y'] # c"),
    (SH.LANG_NUMBERS, "1 2.5 -3e4 abc123"),
]
_invariant_defects = []
for _language, _line in _probe_lines:
    _spans, _ = SH.tokenize_line(_language, _line)
    _cursor = 0
    for _start, _length, _role in _spans:
        if _start < _cursor or _length <= 0 or _start + _length > len(_line) \
                or _role not in SH.SYNTAX_ROLES:
            _invariant_defects.append((_language, _line, _start, _length, _role))
        _cursor = _start + _length
check("every tokenizer answers sorted, non-overlapping, in-bounds spans with known roles",
      not _invariant_defects, str(_invariant_defects))
check("an unknown language / a broken line degrades to numbers / nothing — never raises",
      SH.tokenize_line("klingon", "42") == ([ (0, 2, SH.ROLE_NUMBER) ], SH.STATE_NORMAL)
      and SH.tokenize_line(SH.LANG_JSON, None) == ([], SH.STATE_NORMAL)
      and SH.tokenize_line(SH.LANG_JSON, "") == ([], SH.STATE_NORMAL))


# ════════════════════════════════════════════════════════════
# 4. The budgets — the per-block cap and the measured opening
# ════════════════════════════════════════════════════════════
print("== 4. the budgets ==")

_minified = "{" + ",".join('"key%06d": %d' % (i, i) for i in range(120000)) + "}"
check("the minified probe really is a MB-scale SINGLE line",
      len(_minified) > 1_000_000 and "\n" not in _minified, f"len={len(_minified)}")
_t0 = time.perf_counter()
_capped_spans, _ = SH.tokenize_line(SH.LANG_JSON, _minified)
_capped_ms = (time.perf_counter() - _t0) * 1000.0
check(f"a minified MB-scale single line trips the TOKEN cap ({SH.MAX_TOKENS_PER_BLOCK} spans)",
      len(_capped_spans) == SH.MAX_TOKENS_PER_BLOCK, f"spans={len(_capped_spans)}")
check(f"...and the scan of that line stays far below a freeze budget "
      f"(measured {_capped_ms:.1f} ms < 250 ms)",
      _capped_ms < 250.0, f"{_capped_ms:.1f} ms")
check("the cap is honoured by the other tokenizers too",
      len(SH.tokenize_line(SH.LANG_NUMBERS, "1 " * 5000)[0]) == SH.MAX_TOKENS_PER_BLOCK)


# ════════════════════════════════════════════════════════════
# 5. The tab — the language, the header note, the colours, the reset
# ════════════════════════════════════════════════════════════
print("== 5. the tab: the language, the note, the applied colours ==")

JSON_OK = b'{\n  "a": 1,\n  "b": [true, null]\n}\n'
JSON_BROKEN = b'{"a": \n'
XML_OK = b'<a href="x">y</a>\n'
YAML_OK = b"a: 1\nb: |\n  text\n"
PLAIN = b"alpha 42 beta 123\n"

_fs = FakeSftpFS()
_fs.add_dir("/home")
_fs.add_file("/home/app.json", JSON_OK)
_fs.add_file("/home/broken.json", JSON_BROKEN)
_fs.add_file("/home/svc.xml", XML_OK)
_fs.add_file("/home/notes.yaml", YAML_OK)
_fs.add_file("/home/plain.txt", PLAIN)
_client = FakeSftpClient(_fs)
_worker = SftpWorker(_client)
_log = EventLog()
wire_worker(_worker, _log)
_worker.start()

tab = SftpTab()
tab.resize(700, 500)
tab.show()
_msgs = []
tab.message.connect(_msgs.append)
tab.set_worker(_worker)
wait_until(lambda: item_by_name(tab, "home") is not None, timeout_ms=5000)
tab._navigate("/home")
wait_until(lambda: item_by_name(tab, "app.json") is not None, timeout_ms=5000)

check("the tab has no highlighter until the first preview (nothing is built for a listing)",
      tab.viewer_highlighter is None and tab.viewer_language == SH.LANG_NUMBERS)


def open_file(name, prefix):
    """Double-click a row of the listing and wait for the panel (the real click path)."""
    item = item_by_name(tab, name)
    if item is None:
        return False
    tab._on_item_double_clicked(item, 0)
    wait_until(lambda: not tab.viewer.isHidden()
               and tab.viewer_text.toPlainText().startswith(prefix), timeout_ms=5000)
    app.processEvents()
    return not tab.viewer.isHidden()


def header_for(path, data):
    """The exact header line a file with no note must carry."""
    return i18n.t("sftp.viewer.header", path=path, size=format_size(len(data)))


open_file("app.json", "{")
check("a verified .json opens as json", tab.viewer_language == SH.LANG_JSON)
check("a verified file leaves the header untouched (no note — the colours speak)",
      tab.viewer_label.text() == header_for("/home/app.json", JSON_OK),
      f"got={tab.viewer_label.text()!r}")
check("ONE highlighter per tab — the second preview reuses the same object",
      tab.viewer_highlighter is not None)
_highlighter = tab.viewer_highlighter
check("the highlighter is a real QSyntaxHighlighter over the viewer's document",
      _highlighter.document() is tab.viewer_text.document())
check("the JSON block carries the theme's colours (a key, a number, a keyword)",
      (('"a"', DARK.syntax_key) in (block_formats(tab.viewer_text, 1) or []))
      and (("1", DARK.syntax_number) in (block_formats(tab.viewer_text, 1) or []))
      and (("true", DARK.syntax_keyword) in (block_formats(tab.viewer_text, 2) or [])),
      f"b1={(block_formats(tab.viewer_text, 1))} b2={block_formats(tab.viewer_text, 2)}")
check("the applied colours are exactly the palette values (no literal leaked in)",
      all_applied_colours(tab.viewer_text) <= set(DARK.syntax_colors.values()),
      str(all_applied_colours(tab.viewer_text)))

open_file("svc.xml", "<")
check("a .xml that parses opens as xml", tab.viewer_language == SH.LANG_XML)
check("the XML tag / attribute / value colours are applied",
      (("a", DARK.syntax_tag) in (block_formats(tab.viewer_text, 0) or []))
      and (("href", DARK.syntax_attribute) in (block_formats(tab.viewer_text, 0) or []))
      and (('"x"', DARK.syntax_string) in (block_formats(tab.viewer_text, 0) or [])),
      str(block_formats(tab.viewer_text, 0)))
check("the header of a verified XML carries no note either",
      tab.viewer_label.text() == header_for("/home/svc.xml", XML_OK),
      f"got={tab.viewer_label.text()!r}")

open_file("broken.json", "{")
check("a .json that does NOT parse opens as NUMBERS (the honesty rule, live)",
      tab.viewer_language == SH.LANG_NUMBERS)
check("...and it carries no heuristic note (numbers are not a guess — they are the truth)",
      i18n.t("sftp.viewer.syntax_heuristic", language="numbers") not in tab.viewer_label.text(),
      f"got={tab.viewer_label.text()!r}")

open_file("notes.yaml", "a:")
check("a .yaml opens as the HEURISTIC mode", tab.viewer_language == SH.LANG_YAML)
check("...and the header SAYS so (sftp.viewer.syntax_heuristic, the encoding-note pattern)",
      tab.viewer_label.text() == header_for("/home/notes.yaml", YAML_OK)
      + " · " + i18n.t("sftp.viewer.syntax_heuristic", language="yaml"),
      f"got={tab.viewer_label.text()!r}")
check("the YAML key / block-scalar colours are applied",
      (("a", DARK.syntax_key) in (block_formats(tab.viewer_text, 0) or []))
      and (("text", DARK.syntax_string) in (block_formats(tab.viewer_text, 2) or [])),
      f"b0={block_formats(tab.viewer_text, 0)} b2={block_formats(tab.viewer_text, 2)}")

open_file("plain.txt", "alpha")
check("a .txt opens as numbers — the language-agnostic mode",
      tab.viewer_language == SH.LANG_NUMBERS)
check("...and only the numbers are coloured (no grammar is invented for plain text)",
      all_applied_colours(tab.viewer_text) == {DARK.syntax_number},
      str(all_applied_colours(tab.viewer_text)))
check("NO BLEED: the previous file's language is not carried over (the reset works)",
      ("alpha", DARK.syntax_key) not in (block_formats(tab.viewer_text, 0) or [])
      and ("alpha 42 beta 123", DARK.syntax_string)
      not in (block_formats(tab.viewer_text, 0) or []))
check("the highlighter object is still the tab's ONE (a reset, not a rebuild)",
      tab.viewer_highlighter is _highlighter)

open_file("app.json", "{")
check("coming back to a JSON file restores the JSON colours (the reset is symmetric)",
      (('"a"', DARK.syntax_key) in (block_formats(tab.viewer_text, 1) or [])),
      str(block_formats(tab.viewer_text, 1)))
check("a successful preview never emitted a message", not _msgs, f"msgs={_msgs}")


# ════════════════════════════════════════════════════════════
# 6. Laziness — only the window carries formats
# ════════════════════════════════════════════════════════════
print("== 6. laziness: the window, the scroll, the free repeat ==")

_long = "\n".join("line %d = %d" % (i, i) for i in range(2000))
t0 = time.perf_counter()
tab._show_viewer("/var/log/long.log", len(_long), _long)
_open_ms = (time.perf_counter() - t0) * 1000.0
app.processEvents()

_document = tab.viewer_text.document()
_total_blocks = _document.blockCount()
_first_window = tab.viewer_highlighter.formatted_blocks()
check("the long file really has many blocks", _total_blocks == 2000, str(_total_blocks))
check("only the blocks AROUND the viewport are formatted (the lazy half of the plan)",
      0 < len(_first_window) < _total_blocks // 10,
      f"formatted={len(_first_window)} of {_total_blocks}")
check("a formatted block really carries a format (the mark is not a lie)",
      bool(block_formats(tab.viewer_text, min(_first_window))))
check("a block far outside the window carries NOTHING",
      not block_formats(tab.viewer_text, _total_blocks - 1),
      str(block_formats(tab.viewer_text, _total_blocks - 1)))
check("the lazy window is the visible range widened by VIEWER_LAZY_MARGIN",
      tab._highlight_range == (0, _total_blocks - 1) or
      tab._highlight_range[1] - tab._highlight_range[0] < _total_blocks)
check("a REPEAT pass formats nothing (a scroll that does not move is free)",
      tab._highlight_visible() == 0)

_scrollbar = tab.viewer_text.verticalScrollBar()
check("the long file is really scrollable (the probe needs a scrollbar)",
      _scrollbar.maximum() > 0, str(_scrollbar.maximum()))
_scrollbar.setValue(_scrollbar.maximum())
app.processEvents()
_after_scroll = tab.viewer_highlighter.formatted_blocks()
check("scrolling formats the blocks that became visible",
      len(_after_scroll) > len(_first_window)
      and max(_after_scroll) > max(_first_window),
      f"before={len(_first_window)} after={len(_after_scroll)}")
check("...and it keeps what was already done (the window is extended, never rebuilt)",
      _first_window <= _after_scroll)
check("...while the untouched middle stays unformatted (that is the whole point)",
      len(_after_scroll) < _total_blocks // 5,
      f"formatted={len(_after_scroll)} of {_total_blocks}")
check("the last block of the document is now the formatted one",
      max(_after_scroll) == _total_blocks - 1, str(max(_after_scroll)))

# ── the measured opening budgets (the numbers of the release go to CHANGELOG.md) ──
_big_source = [{"id": i, "name": "server-%04d" % i, "enabled": i % 3 == 0,
                "weight": i * 0.5} for i in range(9000)]
_big_text = json.dumps(_big_source, indent=2)
check("the MB-scale payload is a real ~1 MB document (the budget must mean something)",
      len(_big_text) > 800_000, f"len={len(_big_text)}")

_t0 = time.perf_counter()
check("the detection of the 1 MB document is a millisecond-scale call (a parse, not a scan)",
      SH.detect_syntax("/etc/big.json", _big_text) == SH.LANG_JSON)
_detect_ms = (time.perf_counter() - _t0) * 1000.0

_t0 = time.perf_counter()
tab._show_viewer("/etc/big.json", len(_big_text), _big_text)
_big_ms = (time.perf_counter() - _t0) * 1000.0
app.processEvents()
_big_formatted = tab.viewer_highlighter.formatted_blocks()
check(f"a ~1 MB file opens within the measured budget (measured {_big_ms:.0f} ms < 3000 ms)",
      _big_ms < 3000.0, f"{_big_ms:.0f} ms")
check(f"...and it does NOT format the whole document (formatted {len(_big_formatted)} of "
      f"{tab.viewer_text.document().blockCount()})",
      len(_big_formatted) < tab.viewer_text.document().blockCount() // 10)
check(f"the detection of that document stays in the millisecond range "
      f"(measured {_detect_ms:.1f} ms < 250 ms)",
      _detect_ms < 250.0, f"{_detect_ms:.1f} ms")
print(f"   [budget] 1 MB JSON: detect {_detect_ms:.1f} ms, first show {_big_ms:.0f} ms, "
      f"{len(_big_formatted)} blocks formatted of {tab.viewer_text.document().blockCount()}")

tab.close_viewer()
check("close_viewer() drops the content, the window and the format marks",
      tab.viewer.isHidden() and tab.viewer_text.toPlainText() == ""
      and tab._highlight_range is None
      and not tab.viewer_highlighter.formatted_blocks())


# ════════════════════════════════════════════════════════════
# 7. The theme switch — the applied formats are VALUES
# ════════════════════════════════════════════════════════════
print("== 7. the theme switch repaints the applied formats ==")

_light = theme.theme_for_mode("light")
_final_theme = theme_qss.apply_theme(_light, app=app, refresh_windows=False)
app.processEvents()
tab._show_viewer("/home/app.json", 30, '{\n  "a": 1\n}\n')
app.processEvents()
check("a preview opened under LIGHT carries the LIGHT syntax tones",
      (('"a"', theme.LIGHT.syntax_key) in (block_formats(tab.viewer_text, 1) or []))
      and (("1", theme.LIGHT.syntax_number) in (block_formats(tab.viewer_text, 1) or [])),
      str(block_formats(tab.viewer_text, 1)))

theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)
tab.refresh_theme()
app.processEvents()
check("refresh_theme() repaints the OPEN preview in the new tones (they are values, §4.6)",
      (('"a"', DARK.syntax_key) in (block_formats(tab.viewer_text, 1) or [])),
      str(block_formats(tab.viewer_text, 1)))
check("...and no colour of the old theme is left anywhere in the document",
      theme.LIGHT.syntax_key not in all_applied_colours(tab.viewer_text),
      str(all_applied_colours(tab.viewer_text)))
tab.close_viewer()
tab.refresh_theme()
check("refresh_theme() on a closed viewer is a safe no-op",
      tab.viewer.isHidden() and tab._highlight_range is None)


# ════════════════════════════════════════════════════════════
# 8. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 8. i18n: the new key + the release state ==")

SYNTAX_KEYS = ["sftp.viewer.syntax_heuristic"]
check("exactly ONE i18n key is added by the release", len(SYNTAX_KEYS) == 1)

_langs = load_i18n_langs(ROOT)
for _code in sorted(_langs):
    _values = {k: _langs[_code].get(k, "") for k in SYNTAX_KEYS}
    check(f"{_code}: sftp.viewer.syntax_heuristic is translated (not empty, not the raw key)",
          all(str(v).strip() and str(v) != k for k, v in _values.items()), str(_values))
    check(f"{_code}: the line carries the {{language}} placeholder and nothing else",
          all(placeholder_names(v) == {"language"} for v in _values.values()),
          str({k: sorted(placeholder_names(v)) for k, v in _values.items()}))

i18n.set_language("en")   # the default for cleanliness
check("the rendered note names the heuristic mode (the plan's own wording)",
      i18n.t("sftp.viewer.syntax_heuristic", language="yaml")
      == "highlighting: yaml (heuristic)",
      i18n.t("sftp.viewer.syntax_heuristic", language="yaml"))

check_i18n_parity(_langs)
check_release_state(ROOT)

_worker.shutdown(wait_ms=2000)
tab.close()

finish()
