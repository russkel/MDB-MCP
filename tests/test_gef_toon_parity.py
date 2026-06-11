"""Guards that the GEF fork's hand-ported `gef_toon` stays byte-compatible with the
official toon-format library. The two encoders live in different processes (GEF runs
in gdb's embedded Python, which can't import toon-format), so this extracts GEF's
self-contained TOON block and diffs it against the library on a battery of values."""

import os
import re
from typing import Any

import pytest
from toon_format import encode as lib_encode

GEF = os.path.expanduser("~/work/gef/gef.py")


def _load_gef_toon():
    """Exec just GEF's dependency-free TOON block (needs only `re`)."""
    src = open(GEF).read()
    start = src.index("_TOON_NUMERIC_RE = ")
    end = src.index("\n\n\n", src.index("def gef_toon"))
    ns: dict = {"re": re, "Any": Any}
    exec(src[start:end], ns)
    return ns["gef_toon"]


CASES = [
    ("regs", ["reg", "val", "sym"], [["rax", "0x401136", "main+0x13"], ["rsp", "0x7fff", ""]]),
    ("regs", ["reg", "val", "sym"], []),                       # empty -> name[0]:
    ("t", ["c"], [["[stack]"], ["[heap]"]]),                   # brackets -> quoted
    ("t", ["c"], [["12"], ["0123"], ["-3.14"], ["1e-6"]]),     # numeric-like -> quoted
    ("t", ["c"], [["true"], ["false"], ["null"]]),             # reserved literals -> quoted
    ("t", ["c"], [["a,b"], ['say "hi"'], ["back\\slash"]]),    # escaping
    ("t", ["c"], [["x:y"], ["-dash"], [" pad "]]),             # colon / list marker / edge ws
    ("hex", ["addr", "bytes", "ascii"], [["0x1000", "bf0a00", "..,.[A"]]),
    ("t", ["i", "v"], [[12, "0x0"]]),                          # real int stays bare
]


@pytest.mark.parametrize("name,fields,rows", CASES)
def test_gef_toon_matches_official_library(name, fields, rows):
    gef_toon = _load_gef_toon()
    mine = gef_toon(name, fields, rows)
    lib = lib_encode({name: [dict(zip(fields, r)) for r in rows]})
    assert mine == lib
