# -*- coding: utf-8 -*-
"""Syntax highlighting of the read-only SFTP viewer (v1.4.7, ROADMAP v1.4.7).

The viewer of `modules/sftp_tab.py` made a file READABLE ("is this the config I
think it is?"); this module makes it SKIMMABLE. It is deliberately small and
deliberately dumb:

  * **no new dependency** — the whole feature is the standard library (`json`,
    `xml.etree.ElementTree`, `re`) plus `QSyntaxHighlighter` from PySide6;
  * **the honesty rule (a hint must not lie).** The EXTENSION is a hint, the
    CONTENT is the verdict: a `.json` is coloured as JSON only after
    `json.loads` accepted it and a `.xml` only after `ElementTree` did — content
    that does not parse degrades to the language-agnostic number-only mode
    instead of being coloured with a grammar that does not describe it. YAML has
    no standard-library parser (PyYAML is a dependency — not allowed), so YAML
    highlighting is a HEURISTIC and the viewer header says so
    (`sftp.viewer.syntax_heuristic`, the `encoding_note` pattern);
  * **colours only, never bold/italic** — the palette changes foreground colours
    alone, so highlighting can be applied LAZILY to the visible blocks (task 4 of
    the plan) without disturbing the document layout. This is a skimmer, not an
    IDE: no parsing library, no grammar files, no folding, no completion.

Layout of the module:

    SYNTAX_ROLES / role constants — the vocabulary (`number`, `string`, `key`,
        `keyword`, `comment`, `tag`, `attribute`, `punctuation`); the palette
        field of a role is `syntax_<role>` on `ui.theme.Theme`
        (`syntax_field()` / `theme.Theme.syntax_colors` — the topical test pins
        the two halves against each other);
    detect_syntax(path, text)   — the pure, Qt-free verdict;
    tokenize_line(...)          — the pure, Qt-free tokenizer (rules as DATA:
        `(start, length, role)` spans, no paint code);
    create_highlighter(document) — the ONE thin `QSyntaxHighlighter` subclass,
        built LAZILY (the import sits inside the factory), which is what keeps
        this module importable — and the tokenizers testable — without Qt (the
        `ui/theme.py` contract of the same project).

**The YAML limitation is documented, not hidden.** The line rules understand
comments, `key:`, list markers, quoted scalars, `|`/`>` block scalars (through
the block state), booleans/nulls and numbers. They do NOT parse anchors/aliases,
tags (`!!str`), multi-line flow collections (`[a,` / `b]` spread over lines) or
the full block-scalar indentation rules: a block scalar simply ends at the first
non-blank line that is not indented deeper than the line the `|` stood on.
"""

import json
import posixpath
import re
import xml.etree.ElementTree as ElementTree

# ── The role vocabulary ───────────────────────────────────────────────────────
# A role is the NAME of a colour, not a colour: `ui/theme.py` owns the values
# (`Theme.syntax_<role>`), which is what keeps every literal out of this module.

ROLE_NUMBER = "number"
ROLE_STRING = "string"
ROLE_KEY = "key"
ROLE_KEYWORD = "keyword"
ROLE_COMMENT = "comment"
ROLE_TAG = "tag"
ROLE_ATTRIBUTE = "attribute"
ROLE_PUNCTUATION = "punctuation"

SYNTAX_ROLES = (ROLE_NUMBER, ROLE_STRING, ROLE_KEY, ROLE_KEYWORD,
                ROLE_COMMENT, ROLE_TAG, ROLE_ATTRIBUTE, ROLE_PUNCTUATION)

# ── The language ids ──────────────────────────────────────────────────────────

LANG_JSON = "json"
LANG_XML = "xml"
LANG_YAML = "yaml"
LANG_NUMBERS = "numbers"        # the always-truthful fallback of plain text

LANGUAGES = (LANG_JSON, LANG_XML, LANG_YAML, LANG_NUMBERS)

# A mode that is NOT verified by a parser — the viewer header has to say so.
HEURISTIC_LANGUAGES = (LANG_YAML,)

# ── The extension hints (a hint — the content decides, see detect_syntax) ─────

JSON_EXTENSIONS = (".json",)
XML_EXTENSIONS = (".xml", ".xsd", ".xsl", ".xslt", ".svg", ".plist", ".rss",
                  ".atom", ".csproj", ".pom", ".ui", ".qrc", ".kml", ".gpx",
                  ".drawio")
YAML_EXTENSIONS = (".yaml", ".yml")

# ── The block states (QTextBlock state ints; 0 must stay "normal") ────────────

STATE_NORMAL = 0
STATE_XML_COMMENT = 1           # inside `<!-- … -->`
STATE_XML_CDATA = 2             # inside `<![CDATA[ … ]]>`
STATE_YAML_BLOCK_BASE = 100     # + the indent of the `|`/`>` line

# ── Budgets ───────────────────────────────────────────────────────────────────
# A minified 1 MB JSON document is ONE block: laziness by blocks cannot help
# there, so a single block stops producing tokens after this many. The rest of
# the block stays plain — an honest "too dense to colour", never a frozen GUI.

MAX_TOKENS_PER_BLOCK = 2000


def syntax_field(role: str) -> str:
    """The `ui.theme.Theme` field that carries the colour of `role` (v1.4.7)."""
    return "syntax_" + role


# ══════════════════════════════════════════════════════════════════════════════
# Detection — a pure function (no Qt, no state, never raises)
# ══════════════════════════════════════════════════════════════════════════════

def detect_syntax(path, text) -> str:
    """`"json" | "xml" | "yaml" | "numbers"` for a viewer payload (v1.4.7).

    The rule of the release, in order:

      1. the EXTENSION of `path` is the only hint taken. No extension / an
         unknown one (``README``, ``hosts``, ``data.weird``) → `"numbers"` —
         a guess from the content of an unknown file would be exactly the lie
         the honesty rule forbids;
      2. a `.json` / `.xml` hint must survive VERIFICATION (`json.loads` /
         `ElementTree.fromstring` over a ≤ 1 MB string — milliseconds). A file
         that does not parse is NOT coloured with that grammar: it degrades to
         `"numbers"`;
      3. a `.yaml` / `.yml` hint is accepted as-is — the standard library has no
         YAML parser, so the mode is a heuristic and the caller says so
         (`HEURISTIC_LANGUAGES`).

    Pure: no Qt, no I/O, no global state; a broken `path`/`text` answers
    `"numbers"` rather than raising.
    """
    extension = _extension(path)
    if extension in JSON_EXTENSIONS and _parses_json(text):
        return LANG_JSON
    if extension in XML_EXTENSIONS and _parses_xml(text):
        return LANG_XML
    if extension in YAML_EXTENSIONS:
        return LANG_YAML
    return LANG_NUMBERS


def is_heuristic(language) -> bool:
    """Is this mode unverified (the viewer header must name it as a heuristic)?"""
    return language in HEURISTIC_LANGUAGES


def _extension(path) -> str:
    """The lowercased extension of a REMOTE path ("", when there is none)."""
    if not isinstance(path, str):
        return ""
    name = posixpath.basename(path.strip())
    return posixpath.splitext(name)[1].lower()


def _parses_json(text) -> bool:
    """Does `text` really parse as JSON (the verdict of a `.json` hint)?"""
    if not isinstance(text, str):
        return False
    try:
        json.loads(text)
    except (ValueError, TypeError, RecursionError):
        return False
    return True


def _parses_xml(text) -> bool:
    """Does `text` really parse as XML (the verdict of a `.xml` hint)?"""
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped.startswith("<"):
        return False
    try:
        ElementTree.fromstring(stripped)
    except (ElementTree.ParseError, ValueError, TypeError, RecursionError):
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# The tokenizers — pure functions: (line, state) → (spans, state)
# ══════════════════════════════════════════════════════════════════════════════
#
# A span is `(start, length, role)`; the spans of a line are sorted by `start`
# and never overlap. Nothing here knows about Qt, a font or a colour — the
# highlighter at the bottom of the file only turns a role into a QTextCharFormat.

# A NUMBER is a standalone token: not glued to a letter, a dot or a hyphen. That
# single rule is what keeps the mode truthful on the four cases the plan names —
# `abc123` (an identifier), `1.2.3` (a version), `2026-09-28` (a date) and
# `10GB` (a size with a glued unit) stay plain, while `42`, `-5`, `3.14` and
# `1.5e-3` are numbers. A thousands separator (`1,000`) is NOT understood: a
# comma is a delimiter here, because `1, 2, 3` must keep its digits coloured.
_NUMBER_RE = re.compile(
    r"(?<![\w.\-])([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w.\-])")

# A JSON string with escapes; an unterminated one runs to the end of the block.
_JSON_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_JSON_PUNCTUATION = "{}[],:"
_JSON_KEYWORDS = ("true", "false", "null")

_XML_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.:\-]*")
_XML_CDATA_OPEN = "<![CDATA["

# A quoted scalar, single or double, with backslash escapes inside `"`.
_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"' + r"|'[^']*'")

_YAML_KEYWORDS = frozenset({"true", "false", "null", "yes", "no", "on", "off",
                            "True", "False", "Null", "Yes", "No", "On", "Off",
                            "NULL", "~"})
_YAML_WORD_RE = re.compile(r"[^\s\[\]{},]+")
# A KEY is shorter than a word: it may not contain the `:` that ends it (a VALUE
# may, and does — `url: http://host` must stay one word of the value region).
_YAML_KEY_RE = re.compile(r"[^\s\[\]{},:]+")


def tokenize_line(language, line, state=STATE_NORMAL,
                  max_tokens=MAX_TOKENS_PER_BLOCK):
    """Tokenize ONE line (a QTextBlock) of `language` → `(spans, next_state)`.

    `state` is the block state of the PREVIOUS line (`STATE_NORMAL` for the
    first) and the returned one must be handed to the next call — that is how
    XML comments/CDATA and YAML block scalars survive a line break.

    `max_tokens` is the per-block budget: the scan stops once it is reached, so
    the caller gets the first `max_tokens` spans and no freeze (see
    `MAX_TOKENS_PER_BLOCK`). An unknown language tokenizes as `"numbers"`.
    """
    if not isinstance(line, str):
        return [], STATE_NORMAL
    limit = max(1, int(max_tokens))
    if language == LANG_JSON:
        return _tokenize_json(line, limit), STATE_NORMAL
    if language == LANG_XML:
        return _tokenize_xml(line, state, limit)
    if language == LANG_YAML:
        return _tokenize_yaml(line, state, limit)
    return _tokenize_numbers(line, limit), STATE_NORMAL


def number_spans(line, max_tokens=MAX_TOKENS_PER_BLOCK):
    """The number spans of a plain line (the shared `"numbers"` fallback)."""
    return _tokenize_numbers(line, max(1, int(max_tokens)))


def _tokenize_numbers(line, max_tokens):
    spans = []
    for match in _NUMBER_RE.finditer(line):
        if len(spans) >= max_tokens:
            break
        spans.append((match.start(1), match.end(1) - match.start(1), ROLE_NUMBER))
    return spans


# ── JSON ──────────────────────────────────────────────────────────────────────

def _tokenize_json(line, max_tokens):
    """A small left-to-right scanner: strings (with escapes), numbers, keywords,
    punctuation. A string followed by `:` is a KEY, everything else a STRING."""
    spans = []
    i, n = 0, len(line)
    while i < n and len(spans) < max_tokens:
        ch = line[i]
        if ch == '"':
            match = _JSON_STRING_RE.match(line, i)
            if match is None:               # an unterminated string: to the end
                spans.append((i, n - i, ROLE_STRING))
                break
            end = match.end()
            j = end
            while j < n and line[j] in " \t":
                j += 1
            role = ROLE_KEY if j < n and line[j] == ":" else ROLE_STRING
            spans.append((i, end - i, role))
            i = end
            continue
        if ch in _JSON_PUNCTUATION:
            spans.append((i, 1, ROLE_PUNCTUATION))
            i += 1
            continue
        match = _JSON_NUMBER_RE.match(line, i)
        if match is not None:
            spans.append((i, match.end() - i, ROLE_NUMBER))
            i = match.end()
            continue
        keyword = _keyword_at(line, i, _JSON_KEYWORDS)
        if keyword is not None:
            spans.append((i, len(keyword), ROLE_KEYWORD))
            i += len(keyword)
            continue
        i += 1
    return spans


def _keyword_at(line, index, keywords):
    """The keyword starting exactly at `index` whose end is a token boundary."""
    for keyword in keywords:
        if line.startswith(keyword, index):
            after = index + len(keyword)
            if after >= len(line) or not (line[after].isalnum() or line[after] == "_"):
                return keyword
    return None


# ── XML ───────────────────────────────────────────────────────────────────────

def _tokenize_xml(line, state, max_tokens):
    """Tags, attribute names and values, comments, CDATA and declarations.

    The two multi-line constructs are carried by the block state: a comment left
    open at the end of a line (`STATE_XML_COMMENT`) and a CDATA section
    (`STATE_XML_CDATA`) colour every following line until their terminator.
    """
    spans = []
    n = len(line)
    i = 0

    if state == STATE_XML_COMMENT:
        end = line.find("-->")
        if end < 0:
            if n:
                spans.append((0, n, ROLE_COMMENT))
            return spans, STATE_XML_COMMENT
        spans.append((0, end + 3, ROLE_COMMENT))
        i = end + 3
    elif state == STATE_XML_CDATA:
        end = line.find("]]>")
        if end < 0:
            if n:
                spans.append((0, n, ROLE_STRING))
            return spans, STATE_XML_CDATA
        spans.append((0, end + 3, ROLE_STRING))
        i = end + 3

    while i < n and len(spans) < max_tokens:
        lt = line.find("<", i)
        if lt < 0:
            break
        if line.startswith("<!--", lt):
            end = line.find("-->", lt + 4)
            if end < 0:
                spans.append((lt, n - lt, ROLE_COMMENT))
                return spans, STATE_XML_COMMENT
            spans.append((lt, end + 3 - lt, ROLE_COMMENT))
            i = end + 3
            continue
        if line.startswith(_XML_CDATA_OPEN, lt):
            end = line.find("]]>", lt + len(_XML_CDATA_OPEN))
            if end < 0:
                spans.append((lt, n - lt, ROLE_STRING))
                return spans, STATE_XML_CDATA
            spans.append((lt, end + 3 - lt, ROLE_STRING))
            i = end + 3
            continue
        if line.startswith("<!", lt):          # <!DOCTYPE …>
            end = line.find(">", lt)
            if end < 0:
                spans.append((lt, 1, ROLE_PUNCTUATION))
                spans.append((lt + 1, n - lt - 1, ROLE_TAG))
                return spans, STATE_NORMAL
            spans.append((lt, 1, ROLE_PUNCTUATION))
            spans.append((lt + 1, end - lt - 1, ROLE_TAG))
            spans.append((end, 1, ROLE_PUNCTUATION))
            i = end + 1
            continue
        i = _tokenize_xml_element(line, lt, spans, max_tokens)
    return spans, STATE_NORMAL


def _tokenize_xml_element(line, lt, spans, max_tokens):
    """One `<…>` / `</…>` / `<?…?>` construct starting at `lt`; returns the position
    after it (or `lt + 1` when this is not a tag at all)."""
    n = len(line)
    pos = lt + 1
    declaration = False
    if pos < n and line[pos] == "?":
        spans.append((lt, 2, ROLE_PUNCTUATION))
        pos += 1
        declaration = True
    elif pos < n and line[pos] == "/":
        spans.append((lt, 2, ROLE_PUNCTUATION))
        pos += 1
    else:
        spans.append((lt, 1, ROLE_PUNCTUATION))

    name = _XML_NAME_RE.match(line, pos)
    if name is None:
        return lt + 1                      # a bare "<" in text — not a tag
    spans.append((pos, name.end() - pos, ROLE_TAG))
    pos = name.end()

    while pos < n and len(spans) < max_tokens:
        while pos < n and line[pos] in " \t\r\n":
            pos += 1
        if pos >= n:
            break
        if declaration and line.startswith("?>", pos):
            spans.append((pos, 2, ROLE_PUNCTUATION))
            return pos + 2
        if line.startswith("/>", pos):
            spans.append((pos, 2, ROLE_PUNCTUATION))
            return pos + 2
        if line[pos] == ">":
            spans.append((pos, 1, ROLE_PUNCTUATION))
            return pos + 1
        attribute = _XML_NAME_RE.match(line, pos)
        if attribute is None:
            pos += 1
            continue
        spans.append((pos, attribute.end() - pos, ROLE_ATTRIBUTE))
        pos = attribute.end()
        while pos < n and line[pos] in " \t":
            pos += 1
        if pos < n and line[pos] == "=":
            spans.append((pos, 1, ROLE_PUNCTUATION))
            pos += 1
            while pos < n and line[pos] in " \t":
                pos += 1
            if pos < n and line[pos] in "\"'":
                quote = line[pos]
                end = line.find(quote, pos + 1)
                end = n if end < 0 else end + 1
                spans.append((pos, end - pos, ROLE_STRING))
                pos = end
    return max(pos, lt + 1)


# ── YAML (a heuristic — see the module docstring) ─────────────────────────────

def _tokenize_yaml(line, state, max_tokens):
    spans = []
    n = len(line)

    if state >= STATE_YAML_BLOCK_BASE:
        base = state - STATE_YAML_BLOCK_BASE
        if not line.strip():
            return spans, state               # a blank line stays in the block
        indent = len(line) - len(line.lstrip(" \t"))
        if indent > base:
            spans.append((indent, n - indent, ROLE_STRING))
            return spans, state
        state = STATE_NORMAL                  # the block ended on this line

    comment_at = _yaml_comment_start(line)
    content_end = n if comment_at is None else comment_at
    if comment_at is not None:
        spans.append((comment_at, n - comment_at, ROLE_COMMENT))

    i = 0
    while i < content_end and line[i] in " \t":
        i += 1
    indent = i

    if i == 0 and line[:3] in ("---", "...") \
            and (content_end <= 3 or line[3] in " \t"):
        spans.append((0, 3, ROLE_PUNCTUATION))
        i = 3
        while i < content_end and line[i] in " \t":
            i += 1
    if i < content_end and line[i] == "-" \
            and (i + 1 >= content_end or line[i + 1] in " \t"):
        spans.append((i, 1, ROLE_PUNCTUATION))
        i += 1
        while i < content_end and line[i] in " \t":
            i += 1

    key_end = _yaml_key_end(line, i, content_end)
    if key_end is not None:
        spans.append((i, key_end - i, ROLE_KEY))
        spans.append((key_end, 1, ROLE_PUNCTUATION))
        i = key_end + 1

    next_state = state
    j = i
    while j < content_end and len(spans) < max_tokens:
        ch = line[j]
        if ch in " \t":
            j += 1
            continue
        if ch in "\"'":
            match = _QUOTED_RE.match(line, j)
            end = match.end() if match is not None else content_end
            spans.append((j, end - j, ROLE_STRING))
            j = end
            continue
        if ch in "|>":
            end = j + 1
            while end < content_end and line[end] in "+-0123456789":
                end += 1
            spans.append((j, end - j, ROLE_PUNCTUATION))
            next_state = STATE_YAML_BLOCK_BASE + indent
            j = end
            continue
        if ch in "[{":
            spans.append((j, 1, ROLE_PUNCTUATION))
            j += 1
            continue
        if ch in "]},":
            spans.append((j, 1, ROLE_PUNCTUATION))
            j += 1
            continue
        match = _NUMBER_RE.match(line, j)
        if match is not None:
            spans.append((j, match.end() - j, ROLE_NUMBER))
            j = match.end()
            continue
        word = _YAML_WORD_RE.match(line, j)
        if word is not None:
            if word.group(0) in _YAML_KEYWORDS:
                spans.append((j, len(word.group(0)), ROLE_KEYWORD))
            j = word.end()
            continue
        j += 1
    spans.sort(key=lambda span: span[0])   # the language layer appends the comment first
    return spans, next_state


def _yaml_comment_start(line):
    """The index of the `#` that opens a comment, or None.

    Two rules, both of them the reason this function exists: a `#` INSIDE a
    quoted scalar is not a comment (`key: "a # b"`), and a `#` glued to a word
    is part of that word (`a#b` is a plain scalar).
    """
    quote = ""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return i
        i += 1
    return None


def _yaml_key_end(line, start, content_end):
    """The index of the `:` of a `key:` at `start`, or None (not a key).

    A key is a quoted scalar or a run without spaces/flow characters, followed
    immediately by `:`; `- name` (a list of scalars) therefore has no key.
    """
    if start >= content_end:
        return None
    quoted = _QUOTED_RE.match(line, start)
    if quoted is not None:
        end = quoted.end()
    else:
        word = _YAML_KEY_RE.match(line, start)
        if word is None:
            return None
        end = word.end()
    if end < content_end and line[end] == ":":
        return end
    return None


# ══════════════════════════════════════════════════════════════════════════════
# The highlighter — ONE QSyntaxHighlighter subclass, built lazily
# ══════════════════════════════════════════════════════════════════════════════
#
# Why a factory instead of a module-level class: this module must stay
# importable — and the tokenizers above runnable — without PySide6 (the
# `ui/theme.py` contract; `tests/test_sftp_syntax.py` pins it with the AST).
# Why the visible-window machinery: a 1 MB file is ~20 000 blocks and
# `setPlainText()` marks every one of them dirty, so the FORMATTING (the
# expensive half) is applied only around the viewport, while the cheap block
# STATE is still computed for every line (the next line's state depends on it).

_HIGHLIGHTER_CLASS = None

# The blocks formatted around the viewport on either side: a small scroll costs
# nothing because the neighbours are already done.
VIEWER_LAZY_MARGIN = 20


def _highlighter_class():
    """The ONE `QSyntaxHighlighter` subclass (lazy PySide6 import — v1.4.7)."""
    global _HIGHLIGHTER_CLASS
    if _HIGHLIGHTER_CLASS is not None:
        return _HIGHLIGHTER_CLASS

    from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

    try:      # the theme module, the same two import shapes as every consumer
        from ..ui import theme as theme_module
    except ImportError:
        from ui import theme as theme_module

    class SyntaxHighlighter(QSyntaxHighlighter):
        """The viewer's highlighter: rules as DATA, colours from the LIVE theme.

        `highlightBlock()` is the only place that knows Qt; every decision comes
        from `tokenize_line()`. Formats are CACHED per active `Theme` INSTANCE
        (a switch replaces the instance, so the cache invalidates itself — the
        §4.6 rule "a value captured at construction time is a BUG"), and only
        the blocks inside the visible window are really formatted.
        """

        def __init__(self, document, language=LANG_NUMBERS,
                     max_tokens=MAX_TOKENS_PER_BLOCK):
            super().__init__(document)
            self._language = language if language in LANGUAGES else LANG_NUMBERS
            self._max_tokens = max_tokens
            self._formats = {}
            self._formats_theme = None
            self._formatted = set()      # the block numbers already formatted
            self._window = (-1, -1)

        # ── the language ────────────────────────────────────────────────

        @property
        def language(self) -> str:
            return self._language

        def set_language(self, language) -> str:
            """The language of the NEXT file (an unknown id → `"numbers"`)."""
            self._language = language if language in LANGUAGES else LANG_NUMBERS
            return self._language

        # ── the lazy window ─────────────────────────────────────────────

        def set_window(self, first: int, last: int) -> None:
            """The block numbers to format ([first, last], inclusive)."""
            self._window = (int(first), int(last))

        def window(self):
            return self._window

        def formatted_blocks(self) -> set:
            """The block numbers that really carry formats (the laziness probe)."""
            return set(self._formatted)

        def reset_for_document(self) -> None:
            """A NEW document content: forget the window and every format mark.

            Must be called BEFORE `QPlainTextEdit.setPlainText()`: with an empty
            window Qt's own full-document reformat applies no format at all, so
            the previous file can never bleed into the next one.
            """
            self._formatted.clear()
            self._window = (-1, -1)

        def highlight_window(self, force: bool = False) -> int:
            """Format the blocks of the window that are not formatted yet.

            Returns the number of blocks really rehighlighted (0 — nothing to
            do, which is what makes a repeated scroll free).
            """
            first, last = self._window
            if first < 0:
                return 0
            document = self.document()
            if document is None:
                return 0
            done = 0
            block = document.findBlockByNumber(first)
            while block.isValid() and block.blockNumber() <= last:
                number = block.blockNumber()
                if force or number not in self._formatted:
                    self.rehighlightBlock(block)
                    done += 1
                block = block.next()
            return done

        def refresh_theme(self) -> int:
            """A theme switch: drop the cached formats and repaint the window.

            The blocks OUTSIDE the window keep their stale tones until they
            scroll in — so the format marks are dropped as well and the window
            is reformatted at once (a switch is a rare, user-driven event).
            """
            self._formats = {}
            self._formats_theme = None
            self._formatted.clear()
            return self.highlight_window()

        # ── the Qt hook ─────────────────────────────────────────────────

        def highlightBlock(self, text):  # noqa: N802 — the Qt name
            block = self.currentBlock()
            state = self.previousBlockState()
            if state is None or state < 0:
                state = STATE_NORMAL
            spans, next_state = tokenize_line(self._language, text, state,
                                              self._max_tokens)
            self.setCurrentBlockState(next_state)
            number = block.blockNumber()
            first, last = self._window
            if not (first <= number <= last):
                return
            formats = self._format_map()
            for start, length, role in spans:
                fmt = formats.get(role)
                if fmt is not None:
                    self.setFormat(start, length, fmt)
            self._formatted.add(number)

        # ── the formats ─────────────────────────────────────────────────

        def _format_map(self):
            """One `QTextCharFormat` per role, rebuilt when the theme changed."""
            active = theme_module.THEME
            if self._formats_theme is active and self._formats:
                return self._formats
            colours = active.syntax_colors
            formats = {}
            for role in SYNTAX_ROLES:
                value = colours.get(role)
                if not value:
                    continue
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(value))   # colour ONLY — never a weight
                formats[role] = fmt
            self._formats = formats
            self._formats_theme = active
            return self._formats

    _HIGHLIGHTER_CLASS = SyntaxHighlighter
    return _HIGHLIGHTER_CLASS


def create_highlighter(document, language=LANG_NUMBERS,
                       max_tokens=MAX_TOKENS_PER_BLOCK):
    """Attach ONE highlighter to `document` (the viewer's only Qt entry point)."""
    return _highlighter_class()(document, language, max_tokens)
