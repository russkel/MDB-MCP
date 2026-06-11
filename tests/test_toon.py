from modules.gdb.toon import encode_table, encode_hexdump


def test_encode_table_from_dicts():
    out = encode_table("regs", ["reg", "val"],
                       [{"reg": "rax", "val": "0x0"}, {"reg": "rip", "val": "0x401136"}])
    assert out.splitlines() == [
        "regs[2]{reg,val}:",
        "  rax,0x0",
        "  rip,0x401136",
    ]


def test_encode_table_from_sequences():
    out = encode_table("m", ["a", "b"], [["1", "2"], ["3", "4"]])
    assert out == "m[2]{a,b}:\n  1,2\n  3,4"


def test_encode_table_missing_key_is_blank():
    out = encode_table("t", ["a", "b"], [{"a": "x"}])
    assert out == "t[1]{a,b}:\n  x,"


def test_encode_table_sanitizes_commas_and_newlines():
    # commas/newlines in a value would break the positional layout -> collapsed to spaces
    out = encode_table("t", ["path"], [{"path": "/a,/b\n/c"}])
    assert out == "t[1]{path}:\n  /a /b /c"


def test_encode_table_truncates_with_note():
    rows = [{"a": str(i)} for i in range(10)]
    out = encode_table("t", ["a"], rows, max_rows=3)
    lines = out.splitlines()
    assert lines[0] == "t[10]{a}:"          # count reflects the true total, not the cap
    assert len(lines) == 1 + 3 + 1          # header + 3 rows + elision note
    assert "7 more rows elided" in lines[-1]


def test_encode_hexdump_rows_and_ascii():
    data = bytes(range(0x20, 0x32))  # 18 printable bytes -> 2 rows (16 + 2)
    out = encode_hexdump(0x1000, data)
    lines = out.splitlines()
    assert lines[0] == "hex[2]{addr,bytes,ascii}:"
    assert lines[1].startswith("  0x1000,")
    assert lines[2].startswith("  0x1010,")          # second row at base+16
    assert lines[1].endswith("`")                    # ascii is backtick-wrapped


def test_encode_hexdump_nonprintable_becomes_dot():
    out = encode_hexdump(0, bytes([0x00, 0x41, 0xff]))
    # 0x00 and 0xff -> '.', 0x41 -> 'A'
    assert out.endswith("`.A.`")
