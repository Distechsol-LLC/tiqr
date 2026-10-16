"""Render a visitor badge as a foldable A4 sheet.

The badge is the left half of the sheet, cut off along the vertical line and folded in half
horizontally into a two-layer A6 badge. Two holes are punched through both layers at the top.

    ┌──────────┬──────────┐  <- sheet edge: punch holes here
    │   FRONT  │  scrap   │
    ├┄┄┄┄┄┄┄┄┄┄┤          │  <- fold, at the bottom of the badge
    │   BACK   │          │
    │  (180°)  │          │
    └──────────┴──────────┘  <- other end, same holes
                ↑ cut

The back is drawn rotated by 180°, because folding it flips the text.
"""

import os
import tempfile
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit  # pyright: ignore[reportUnknownVariableType]
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from tiqr.models import Ticket

_FONT = "TiQR-Geist"
_LOGOS = ("distechsol.webp", "suprema.webp")
_PAGE_WIDTH, _PAGE_HEIGHT = A4

# Geometry is in millimetres, measured from the top of the surface being drawn on.
_PAGE_MM = (_PAGE_WIDTH / mm, _PAGE_HEIGHT / mm)
_BADGE_MM = (_PAGE_MM[0] / 2, _PAGE_MM[1] / 2)
_MARGIN = 7
# The inkjet cannot print the bottom 14 mm of the sheet, where the back's header sits.
_EDGE_MARGIN = 18
_FOLD_MARGIN = 10
_HOLE_OFFSET = 8
_HOLE_SPACING = 60
_HOLE_RADIUS = 2.5

# Sampled from the logos.
_NAVY = colors.HexColor("#092a54")
_TURQUOISE = colors.HexColor("#099ba0")
_CRIMSON = colors.HexColor("#a71e48")
_MUTED = colors.HexColor("#71757b")
_PANEL = colors.HexColor("#e8e9ea")
_GUIDE = colors.HexColor("#babcbf")

# Labels are English because visitors include foreigners.
_EVENT_LABEL = "TiQR"
_TECH_LINE = "Suprema BioStar X"
# Geist ships one weight; bold adds a stroke of this many ems.
_BOLD_STROKE = 0.035
_NAME_SIZES = (8, 7, 6, 5, 4.2)
_TYPE_SIZES = (3.0, 2.6, 2.2)


def _asset(folder: str, name: str) -> bytes:
    return files("tiqr").joinpath("assets", folder, name).read_bytes()


def _font() -> TTFont:
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT, BytesIO(_asset("fonts", "Geist.ttf"))))  # pyright: ignore[reportUnknownMemberType]
    font = pdfmetrics.getFont(_FONT)
    if not isinstance(font, TTFont):
        raise TypeError(f"{_FONT} is registered as a non-TrueType font")
    return font


def _require_glyphs(text: str) -> None:
    supported: dict[int, float] = _font().face.charWidths
    missing = sorted({ord(char) for char in text if not char.isspace()} - supported.keys())
    if missing:
        codes = ", ".join(f"U+{code:04X}" for code in missing)
        raise ValueError(f"The packaged PDF font does not support these characters: {codes}")


def _width(text: str, size: float, tracking: float = 0) -> float:
    """Width in millimetres of text at a font size in millimetres, with letter spacing."""
    return pdfmetrics.stringWidth(text, _FONT, size * mm) / mm + tracking * max(len(text) - 1, 0)


def _wrap(text: str, size: float, width: float) -> list[str]:
    lines = cast(list[str], simpleSplit(text, _FONT, size * mm, width * mm))
    wrapped: list[str] = []
    for line in lines:
        if _width(line, size) <= width:
            wrapped.append(line)
            continue
        # A word wider than the line is broken between characters.
        part = ""
        for char in line:
            if part and _width(part + char, size) > width:
                wrapped.append(part)
                part = ""
            part += char
        if part:
            wrapped.append(part)
    return wrapped


def _ellipsize(line: str, size: float, width: float, tracking: float = 0) -> str:
    while line and _width(line + "…", size, tracking) > width:
        line = line[:-1].rstrip()
    return line + "…"


def _fit(
    text: str, sizes: tuple[float, ...], width: float, max_lines: int
) -> tuple[float, list[str]]:
    """Pick the largest size whose wrapped text fits in max_lines, cutting only as a last resort."""
    for size in sizes:
        lines = _wrap(text, size, width)
        if len(lines) <= max_lines:
            return size, lines
    size = sizes[-1]
    lines = _wrap(text, size, width)[:max_lines]
    lines[-1] = _ellipsize(lines[-1], size, width)
    return size, lines


def _fit_line(
    text: str, sizes: tuple[float, ...], width: float, tracking: float
) -> tuple[float, str]:
    """Like _fit for a single line with letter spacing."""
    for size in sizes:
        if _width(text, size, tracking) <= width:
            return size, text
    return sizes[-1], _ellipsize(text, sizes[-1], width, tracking)


def _window(ticket: Ticket, zone: ZoneInfo) -> str:
    start = ticket.valid_from.astimezone(zone)
    end = ticket.valid_until.astimezone(zone)

    if start.date() == end.date():
        return f"{start:%d.%m.%y} · {start:%H:%M} — {end:%H:%M}"
    return f"{start:%d.%m.%y} · {start:%H:%M} — {end:%d.%m.%y} · {end:%H:%M}"


def _image_width(image: ImageReader, height: float) -> float:
    pixels_wide, pixels_high = image.getSize()
    return height * pixels_wide / pixels_high


class _Surface:
    """Draws in millimetres from the top-left corner; PDF's origin is bottom-left."""

    def __init__(self, canvas: Canvas, height: float) -> None:
        self.canvas = canvas
        self.height = height

    def _y(self, top: float) -> float:
        return (self.height - top) * mm

    def rect(
        self,
        x: float,
        top: float,
        width: float,
        height: float,
        color: colors.Color,
        radius: float = 0,
    ) -> None:
        self.canvas.setFillColor(color)
        if radius:
            self.canvas.roundRect(
                x * mm,
                self._y(top + height),
                width * mm,
                height * mm,
                radius * mm,
                stroke=0,
                fill=1,
            )
        else:
            self.canvas.rect(
                x * mm, self._y(top + height), width * mm, height * mm, stroke=0, fill=1
            )

    def line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        color: colors.Color,
        width: float,
        dash: tuple[float, float] | None = None,
    ) -> None:
        self.canvas.saveState()
        self.canvas.setStrokeColor(color)
        self.canvas.setLineWidth(width * mm)
        if dash is not None:
            self.canvas.setDash(dash[0] * mm, dash[1] * mm)
        self.canvas.line(start[0] * mm, self._y(start[1]), end[0] * mm, self._y(end[1]))
        self.canvas.restoreState()

    def circle(
        self, x: float, top: float, radius: float, color: colors.Color, width: float
    ) -> None:
        self.canvas.saveState()
        self.canvas.setStrokeColor(color)
        self.canvas.setLineWidth(width * mm)
        self.canvas.circle(x * mm, self._y(top), radius * mm, stroke=1, fill=0)
        self.canvas.restoreState()

    def text(
        self,
        x: float,
        top: float,
        text: str,
        size: float,
        color: colors.Color,
        *,
        bold: bool = False,
        tracking: float = 0,
    ) -> None:
        """Draw text whose line box starts at `top`; the size is in mm."""
        baseline = top + size * _font().face.ascent / 1000
        self.canvas.saveState()
        self.canvas.setFont(_FONT, size * mm)
        self.canvas.setFillColor(color)
        if bold:
            self.canvas.setStrokeColor(color)
            self.canvas.setLineWidth(size * mm * _BOLD_STROKE)
        self.canvas.drawString(
            x * mm, self._y(baseline), text, mode=2 if bold else None, charSpace=tracking * mm
        )
        self.canvas.restoreState()

    def centered(
        self,
        center: float,
        top: float,
        text: str,
        size: float,
        color: colors.Color,
        *,
        bold: bool = False,
        tracking: float = 0,
    ) -> None:
        left = center - _width(text, size, tracking) / 2
        self.text(left, top, text, size, color, bold=bold, tracking=tracking)

    def image(
        self, image: ImageReader, x: float, top: float, height: float, radius: float = 0
    ) -> None:
        """Draw an image scaled to a height, optionally with rounded corners."""
        width = _image_width(image, height)
        self.canvas.saveState()
        if radius:
            clip = self.canvas.beginPath()
            clip.roundRect(x * mm, self._y(top + height), width * mm, height * mm, radius * mm)  # pyright: ignore[reportUnknownMemberType]
            self.canvas.clipPath(clip, stroke=0, fill=0)  # pyright: ignore[reportUnknownMemberType]
        self.canvas.drawImage(  # pyright: ignore[reportUnknownMemberType]
            image, x * mm, self._y(top + height), width=width * mm, height=height * mm, mask="auto"
        )
        self.canvas.restoreState()

    def qr(self, payload: str, x: float, top: float, size: float) -> None:
        _draw_qr(self.canvas, payload, x * mm, self._y(top + size), size * mm)


def _draw_qr(canvas: Canvas, payload: str, x: float, y: float, size: float) -> None:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    count = len(matrix)
    cell = size / count
    canvas.setFillColor(colors.white)
    canvas.rect(x, y, size, size, stroke=0, fill=1)
    canvas.setFillColor(colors.black)
    for row, values in enumerate(matrix):
        bottom = y + (count - row - 1) * cell
        for column, dark in enumerate(values):
            if dark:
                canvas.rect(x + column * cell, bottom, cell, cell, stroke=0, fill=1)


def _draw_header(surface: _Surface, logos: list[ImageReader]) -> float:
    """Draw the event band, stripes and logos; return how far down the header reaches."""
    width, _ = _BADGE_MM
    left, right = _MARGIN, width - _MARGIN
    text_width = right - left

    band_height = 10
    surface.rect(left, _EDGE_MARGIN, text_width, band_height, _NAVY)
    surface.centered(
        width / 2, _EDGE_MARGIN + 2.3, _EVENT_LABEL, 3.6, colors.white, bold=True, tracking=1.1
    )
    stripe = 1.5
    top = _EDGE_MARGIN + band_height
    surface.rect(left, top, text_width, stripe, _TURQUOISE)
    surface.rect(left, top + stripe, text_width, stripe, _CRIMSON)
    top += stripe * 2 + 3.5

    logo_height = 8
    distechsol, suprema = logos
    surface.image(distechsol, left, top, logo_height)
    suprema_width = _image_width(suprema, logo_height)
    surface.image(suprema, right - suprema_width, top, logo_height, radius=1.2)
    return top + logo_height + 4


def _draw_face(
    surface: _Surface, ticket: Ticket, logos: list[ImageReader], window: str, *, back: bool
) -> None:
    """Draw one side of the badge: holes at the top, fold at the bottom.

    The back has name and type but no QR code, so the name is readable when the badge turns around.
    """
    width, height = _BADGE_MM
    left, right = _MARGIN, width - _MARGIN
    text_width = right - left

    # Holes go through both layers, so only the front gets guide circles.
    if not back:
        for x in (width / 2 - _HOLE_SPACING / 2, width / 2 + _HOLE_SPACING / 2):
            surface.circle(x, _HOLE_OFFSET, _HOLE_RADIUS, _GUIDE, 0.25)

    header_bottom = _draw_header(surface, logos)

    bar_height = 7
    bar_top = height - _FOLD_MARGIN - bar_height
    surface.rect(left, bar_top, text_width, bar_height, _NAVY, radius=1.2)
    surface.centered(width / 2, bar_top + 1.3, _TECH_LINE, 3.2, colors.white)
    rule = bar_top - 2.5

    tracking = 0.6
    chip_height = 6.2
    type_size, visitor_type = _fit_line(ticket.visitor_type, _TYPE_SIZES, text_width - 6, tracking)
    chip_width = _width(visitor_type, type_size, tracking) + 6
    label_step = chip_height + 3.5
    # The front leaves room for the QR code, so its name gets two lines.
    name_size, name_lines = _fit(ticket.visitor_name, _NAME_SIZES, text_width, 3 if back else 2)
    name_step = name_size * 1.2
    block_height = label_step + name_step * len(name_lines)

    top = header_bottom
    if back:
        # No QR code below, so center the block instead of leaving a gap under it.
        top += max(0, (rule - header_bottom - block_height) / 2)
    surface.rect(left, top, chip_width, chip_height, _CRIMSON, radius=1.2)
    surface.text(
        left + 3, top + 1.3, visitor_type, type_size, colors.white, bold=True, tracking=tracking
    )
    top += label_step
    for line in name_lines:
        surface.text(left, top, line, name_size, _NAVY, bold=True)
        top += name_step
    if back:
        return

    window_top = rule - 2.5 - 4.4
    surface.text(left, window_top, window, 3.2, _MUTED)

    # The QR code stays black on white: the reader needs the contrast.
    panel_top = top + 3
    room = window_top - 3 - panel_top
    pad, serial_height = 3, 7
    qr_size = min(42, room - pad * 2 - serial_height)
    panel_height = qr_size + pad * 2 + serial_height
    panel_top += (room - panel_height) / 2
    surface.rect(left, panel_top, text_width, panel_height, _PANEL, radius=2)
    surface.qr(ticket.qr_payload, (width - qr_size) / 2, panel_top + pad, qr_size)
    surface.centered(
        width / 2, panel_top + pad + qr_size + 1, ticket.readable_serial, 4.4, _NAVY, bold=True
    )


def _draw_sheet(canvas: Canvas, ticket: Ticket, logos: list[ImageReader], zone: ZoneInfo) -> None:
    badge_width, badge_height = _BADGE_MM
    window = _window(ticket, zone)
    face = _Surface(canvas, badge_height)

    canvas.saveState()
    canvas.translate(0, badge_height * mm)
    _draw_face(face, ticket, logos, window, back=False)
    canvas.restoreState()
    canvas.saveState()
    canvas.translate(badge_width * mm, badge_height * mm)
    canvas.rotate(180)
    _draw_face(face, ticket, logos, window, back=True)
    canvas.restoreState()

    page = _Surface(canvas, _PAGE_MM[1])
    page.line((badge_width, 0), (badge_width, _PAGE_MM[1]), _GUIDE, 0.3, dash=(4, 2.5))
    page.line((0, badge_height), (badge_width, badge_height), _NAVY, 0.3, dash=(8, 3))

    # Instructions go in the scrap half.
    hint_x = badge_width + 6
    left_indent = "    "
    hints = (
        (8, "← punch two holes along this edge"),
        (20, left_indent + "this half is scrap;"),
        (25, left_indent + "cut along the line on the left"),
        (badge_height - 6, "← fold here;"),
        (badge_height + 1, left_indent + "the fold ends up at the bottom"),
        (_PAGE_MM[1] - 20, "← same holes through this end"),
    )
    for top, hint in hints:
        page.text(hint_x, top, hint, 3.4, _MUTED)


def render_pdf(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
    zone = ZoneInfo(timezone)
    logos = [ImageReader(BytesIO(_asset("images", name))) for name in _LOGOS]
    # Validate before creating any file, so a failure leaves no debris.
    _require_glyphs(ticket.visitor_name + ticket.visitor_type)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{ticket.id}.pdf"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ticket.id}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        canvas = Canvas(str(temporary), pagesize=A4, pageCompression=0)
        canvas.setTitle(ticket.readable_serial)
        _draw_sheet(canvas, ticket, logos, zone)
        canvas.save()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
