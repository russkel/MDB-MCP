"""Tests for the server-side TOON wrappers. encode_table/encode_hexdump delegate to
the official toon-format library; these cover our value-add (column order, truncation,
missing-key fill, hexdump layout) and confirm the dialect we expose."""

from toon_format import encode as lib_encode
from modules.gdb.toon import encode_table, encode_hexdump


def test_encode_table_from_dicts():
    out = encode_table("regs", ["reg", "val"],
                       [{"reg": "rax", "val": "0x0"}, {"reg": "rip", "val": "0x401136"}])
    assert out.splitlines() == [
        "regs[2]{reg,val}:",
        "  rax,0x0",
        "  rip,0x401136",
    ]


def test_encode_table_from_sequences_zips_to_columns():
    out = encode_table("m", ["a", "b"], [["1x", "2y"], ["3z", "4w"]])
    assert out == "m[2]{a,b}:\n  1x,2y\n  3z,4w"


def test_encode_table_empty_uses_bare_header():
    # Official dialect drops the {cols} braces for an empty table.
    assert encode_table("regs", ["reg", "val"], []) == "regs[0]:"


def test_encode_table_missing_key_filled_then_quoted_empty():
    out = encode_table("t", ["a", "b"], [{"a": "x"}])
    # missing 'b' -> "" -> the encoder quotes an empty string
    assert out == 't[1]{a,b}:\n  x,""'


def test_encode_table_quotes_and_escapes_structural_values():
    # commas/newlines are quoted+escaped by the spec encoder, not stripped
    out = encode_table("t", ["v"], [{"v": "/a,/b\n/c"}])
    assert out == lib_encode({"t": [{"v": "/a,/b\n/c"}]})
    row = out.splitlines()[1]
    assert row.strip().startswith('"') and "\\n" in row and "," in row


def test_encode_table_truncates_with_note():
    rows = [{"a": "v%d" % i} for i in range(10)]
    out = encode_table("t", ["a"], rows, max_rows=3)
    lines = out.splitlines()
    assert lines[0] == "t[3]{a}:"            # encodes the shown rows
    assert len(lines) == 1 + 3 + 1           # header + 3 rows + elision note
    assert "7 more rows elided" in lines[-1]


def test_encode_hexdump_rows_and_no_backticks():
    data = bytes(range(0x41, 0x53))  # 18 printable bytes -> 2 rows (16 + 2)
    out = encode_hexdump(0x1000, data)
    lines = out.splitlines()
    assert lines[0] == "hex[2]{addr,bytes,ascii}:"
    assert lines[1].strip().startswith("0x1000,")
    assert lines[2].strip().startswith("0x1010,")   # second row at base+16
    assert "`" not in out                            # ascii is no longer backtick-wrapped


def test_encode_hexdump_nonprintable_becomes_dot():
    out = encode_hexdump(0, bytes([0x00, 0x41, 0xff]))
    assert out == lib_encode({"hex": [{"addr": "0x0", "bytes": "0041ff", "ascii": ".A."}]})
    assert out.splitlines()[1].strip().endswith(".A.")  # bare, dots for non-printable


def test_encode_hexdump_empty_is_bare_header():
    assert encode_hexdump(0, b"") == "hex[0]:"
