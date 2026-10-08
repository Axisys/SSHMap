# -*- coding: utf-8 -*-
"""The byte budget of `AGENTS.md`: the harness reads the file WHOLE, and these are the pins.

The fact this module exists for: an instruction file is loaded into the agent's context under a byte
budget, and what does not fit is TRUNCATED silently — a file over it reaches an agent as ~65 KB, so
`§8 Testing conventions`, `§9 Release conventions` and `§12 Agent checklist` (the
sections an agent has to WORK by) are not read at all. A document the reader never receives is not a
document, so the size of this one file is a CORRECTNESS property, not a style preference.

`TARGET_BYTES` is the budget the harness applies: every pinned section must START before it, because
the rules, the testing conventions, the release conventions and the checklist have to be READ. The
positions are a RATCHET — a pin only goes DOWN.
"""
import os

# ── The budget (the byte budget the harness applies to an instruction file) ───────────────────
TARGET_BYTES = 65536

# How far a pin may sit BELOW the measured position before it is STALE: a compression that leaves
# the ratchet where it was hides the next regression, so the block this module prints is applied after
# every shrink. A pin ABOVE the measured position is always an error (the pin check below).
PIN_SLACK_BYTES = 2048

# The chapter order of AGENTS.md IS its priority: the harness reads the file until the byte budget runs
# out, so the operational contract (the checklist, the testing and release conventions, the README rules)
# is written ABOVE the per-subsystem contract and the reference chapters. `tests/test_docs.py` audits
# this order; §-NUMBERS stay stable identifiers, so re-ordering is not renaming.
CHAPTER_ORDER = (12, 8, 3, 10, 9, 13, 7, 4, 1, 2, 5, 6, 11)

# (name, the marker the section starts at, the pin) — the pins are byte offsets into AGENTS.md and
# they only ever DECREASE. The name is what the check reports; the marker is a literal of the file.
SECTION_PINS = (
    ("AGENTS.md: THE DOCUMENTATION RULES", "> **THE DOCUMENTATION RULES", 2392),
    ("AGENTS.md §8 Testing conventions", "## 8. Testing conventions", 12159),
    ("AGENTS.md §9 Release conventions", "## 9. Release conventions", 16468),
    ("AGENTS.md §12 Agent checklist", "## 12. Agent checklist", 7818),
)

DOC = "AGENTS.md"


def default_root():
    """The repository root (this file lives in `<root>/tests/`)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def offsets(text, pins=SECTION_PINS):
    """{name: (byte offset, found)} for every pinned section of one document."""
    out = {}
    for name, marker, _pin in pins:
        i = text.find(marker)
        out[name] = (-1, False) if i < 0 else (len(text[:i].encode("utf-8")), True)
    return out


def measure(root=None):
    """The byte footprint of AGENTS.md: its size, its pins and the ones already inside the budget."""
    path = os.path.join(root or default_root(), DOC)
    text = read_text(path)
    found = offsets(text)
    rows = []
    for name, _marker, pin in SECTION_PINS:
        at, ok = found[name]
        rows.append({"name": name, "pin": pin, "at": at, "found": ok,
                     "inside_target": ok and at < TARGET_BYTES})
    return {"path": path, "bytes": len(text.encode("utf-8")), "lines": text.count("\n") + 1,
            "target": TARGET_BYTES, "rows": rows,
            "missing": [r["name"] for r in rows if not r["found"]],
            "over_pin": [r for r in rows if not r["found"] or r["at"] > r["pin"]],
            "outside_target": [r["name"] for r in rows if not r["inside_target"]]}


def report(check, root=None, prefix="§7"):
    """The §7 ratchet: the file size and every pinned section position against its pin."""
    m = measure(root)
    check(f"{prefix} the scan really read {DOC} (a guard over nothing is useless)",
          m["bytes"] > 1000 and not m["missing"],
          f"bytes={m['bytes']} lines={m['lines']} missing markers={m['missing']}")
    for row in m["rows"]:
        where = "missing" if not row["found"] else f"byte {row['at']}"
        check(f"{prefix} {row['name']} starts no later than the pin ({row['pin']})",
              row["found"] and row["at"] <= row["pin"],
              f"{where} — a section pushed further down needs the text above it COMPRESSED, "
              f"never the pin raised")
    check(f"{prefix} every pinned section is inside the harness budget ({TARGET_BYTES} bytes) — "
          f"the goal state, reached by the compression waves",
          not m["outside_target"],
          f"outside={m['outside_target']} (file is {m['bytes']} bytes; compress the sections ABOVE "
          f"a section to pull it in — TARGET_BYTES is not negotiable, the harness truncates)")
    _slack = [(r["name"], r["pin"] - r["at"]) for r in m["rows"]
              if r["found"] and r["pin"] - r["at"] > PIN_SLACK_BYTES]
    check(f"{prefix} the ratchet is not stale (every pin is within {PIN_SLACK_BYTES} bytes of the "
          f"measured position — re-base it: python tests/_docs_budget.py)",
          not _slack, _slack)
    return m


def pin_block(m):
    """The paste-ready constants of a measurement (the maintainer lowers them by hand)."""
    return "\n".join(f"    ({r['name']!r}, {r['at']})," for r in m["rows"] if r["found"])


def _main():
    m = measure()
    print(f"{DOC}: {m['bytes']} bytes, {m['lines']} lines, target {m['target']} bytes")
    print(f"{'section':44} {'at':>8} {'pin':>8} {'target':>8}  margin")
    for row in m["rows"]:
        state = "?" if not row["found"] else ("OK" if row["inside_target"] else "OUTSIDE")
        print(f"{row['name']:44} {row['at']:>8} {row['pin']:>8} {m['target']:>8}  {state}")
    over = [r["name"] for r in m["over_pin"]]
    print(f"\nover the pin: {over or 'none'}")
    print("\n--- the paste-ready pins (lower them as you compress) ---")
    print(pin_block(m))


if __name__ == "__main__":
    _main()
