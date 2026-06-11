"""Server-side TOON formatting for the structured GDB tools.

Delegates to the official `toon-format` library (the working v0.9.x from GitHub —
the PyPI 0.1.0 is a non-functional stub) so the MCP server and the headless GEF fork
emit one identical dialect: `name[N]{cols}:` with 2-space-indented, comma-joined
rows and spec-conformant quoting. These thin wrappers add only what the library
doesn't: a stable column order, row truncation with a visible elision note, and the
hexdump row layout.
"""

from typing import Any, Iterable, Mapping, Sequence

from toon_format import encode as _encode


def encode_table(name: str, columns: Sequence[str], rows: Iterable[Any],
                 max_rows: int | None = None) -> str:
    """Encode tabular data as a named TOON table via the official encoder.

    `rows` is an iterable of mappings (read by column name) or sequences (read
    positionally, zipped to `columns`). Every row is materialised with all columns
    present so the library keeps the compact tabular form. If `max_rows` is set and
    exceeded, the table is truncated with a trailing note so a cap never reads as
    "complete".
    """
    rows = list(rows)
    total = len(rows)
    truncated = max_rows is not None and total > max_rows
    shown = rows[:max_rows] if truncated else rows

    dicts = []
    for r in shown:
        if isinstance(r, Mapping):
            dicts.append({c: r.get(c, "") for c in columns})
        else:
            dicts.append(dict(zip(columns, r)))

    out = _encode({name: dicts})
    if truncated:
        out += f"\n  …[{total - max_rows} more rows elided — narrow the query]"
    return out


def encode_hexdump(base: int, data: bytes, width: int = 16) -> str:
    """Encode raw bytes as a `hex[N]{addr,bytes,ascii}:` table. The ascii column is
    the raw printable rendering — the encoder quotes it when it contains structural
    characters, exactly as GEF's headless hexdump now does."""
    rows = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        rows.append({
            "addr": hex(base + off),
            "bytes": chunk.hex(),
            "ascii": "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk),
        })
    return encode_table("hex", ["addr", "bytes", "ascii"], rows)
