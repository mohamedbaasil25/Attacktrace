"""Minimal single-page PDF writer (no dependency): text in the built-in Helvetica fonts, filled and
stroked rectangles, lines. Text is reduced to ASCII because the base-14 fonts only cover Latin-1."""

A4 = (595.0, 842.0)
# Code points (not literals) so the source stays plain ASCII.
_ASCII = str.maketrans(
    {
        0x2192: "->",  # right arrow
        0x00B7: "-",  # middle dot
        0x03C3: "sigma",
        0x2013: "-",  # en dash
        0x2014: "-",  # em dash
        0x00D7: "x",  # multiplication sign
        0x2265: ">=",
        0x2264: "<=",
        0x2019: "'",
        0x201C: '"',
        0x201D: '"',
    }
)
CHAR_W = 0.56  # average Helvetica advance in em, a little generous so wrapped lines never overflow


def ascii_text(s: str) -> str:
    return s.translate(_ASCII).encode("ascii", "replace").decode("ascii")


def _escape(s: str) -> str:
    return ascii_text(s).replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def text_width(s: str, size: float) -> float:
    return len(ascii_text(s)) * size * CHAR_W


def wrap(s: str, size: float, width: float) -> list[str]:
    """Greedy word wrap to `width` points."""
    lines: list[str] = []
    cur = ""
    for word in ascii_text(s).split():
        trial = f"{cur} {word}".strip()
        if cur and text_width(trial, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return [*lines, cur] if cur else lines


class Page:
    """Top-left origin helpers over PDF's bottom-left coordinates."""

    def __init__(self) -> None:
        self.w, self.h = A4
        self._ops: list[str] = []

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self._ops.append(f"BT /{font} {size:g} Tf {x:.1f} {self.h - y:.1f} Td ({_escape(s)}) Tj ET")

    def rect(
        self, x: float, y: float, w: float, h: float, gray: float | None = None, line: bool = False
    ) -> None:
        """Fill with a gray level (0 black .. 1 white) and/or stroke the outline."""
        ops = []
        if gray is not None:
            ops.append(f"{gray:.2f} g")
        ops.append(f"{x:.1f} {self.h - y - h:.1f} {w:.1f} {h:.1f} re")
        ops.append(("B" if gray is not None else "S") if line else "f")
        self._ops.append(" ".join(ops) + (" 0 g" if gray is not None else ""))

    def hline(self, x1: float, x2: float, y: float, width: float = 0.5) -> None:
        self._ops.append(f"{width:g} w {x1:.1f} {self.h - y:.1f} m {x2:.1f} {self.h - y:.1f} l S")

    def build(self) -> bytes:
        content = "\n".join(self._ops).encode("ascii")
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.w:g} {self.h:g}] "
                "/Contents 6 0 R /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> >>"
            ).encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objs) + 1,
            xref,
        )
        return bytes(out)
