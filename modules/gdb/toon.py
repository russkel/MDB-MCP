"""Minimal TOON table encoder.

Emits the same dialect the headless GEF fork already uses and that the
advanced-binary-debugging skill documents: a header line `name[N]{col1,col2,...}:`
declaring N rows with named columns, followed by one indented row per record with
positional, comma-separated values.

This is intentionally tiny and dependency-free. The published `toon-format` PyPI
package (0.1.0) is a non-functional stub (`encode` raises NotImplementedError), and
the working upstream uses a slightly different dialect (`[N,]{...}`) than GEF — so we
match GEF locally for consistent, model-readable output.
"""

from typing import Any, Iterable, Mapping, Sequence


def _cell(value: Any) -> str:
    """Render one cell. Commas and newlines would break the positional row layout,
    so collapse them to spaces (matching GEF, which strips commas from operands)."""
    s = "" if value is None else str(value)
    return s.replace(",", " ").replace("\n", " ").replace("\r", " ")


def encode_table(name: str, columns: Sequence[str], rows: Iterable[Any],
                 max_rows: int | None = None) -> str:
    """Encode tabular data as a TOON table.

    `rows` is an iterable of either mappings (read by column name) or sequences
    (read positionally). If `max_rows` is set and there are more rows, the table is
    truncated and a trailing elision note is added so a cap never reads as "complete".
    """
    rows = list(rows)
    total = len(rows)
    truncated = max_rows is not None and total > max_rows
    shown = rows[:max_rows] if truncated else rows

    lines = [f"{name}[{total}]{{{','.join(columns)}}}:"]
    for row in shown:
        if isinstance(row, Mapping):
            vals = [_cell(row.get(c, "")) for c in columns]
        else:
            vals = [_cell(v) for v in row]
        lines.append("  " + ",".join(vals))
    if truncated:
        lines.append(f"  …[{total - max_rows} more rows elided — narrow the query]")
    return "\n".join(lines)


def encode_hexdump(base: int, data: bytes, width: int = 16) -> str:
    """Encode raw bytes as GEF-style `hex[N]{addr,bytes,ascii}:` rows."""
    rows = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        addr = hex(base + off)
        hexs = chunk.hex()
        ascii_ = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        rows.append([addr, hexs, f"`{ascii_}`"])
    return encode_table("hex", ["addr", "bytes", "ascii"], rows)
