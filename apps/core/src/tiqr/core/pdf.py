"""Render a visitor badge as a foldable A4 sheet, or a ticket on a small cut slip.

Badge mode prints the badge; ticket mode prints the ticket, described under `_draw_ticket`.

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
from dataclasses import dataclass
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit  # pyright: ignore[reportUnknownVariableType]
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from tiqr.core.languages import DEFAULT_LANGUAGES
from tiqr.core.models import Mode, Ticket, UsageType

_FONT = "TiQR-Geist"
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
# A ticket is its own page: a narrow slip, as cut ticket paper and receipt printers take.
_TICKET_MM = (80.0, 160.0)
_TICKET_FRAME = 3
_TICKET_MARGIN = 7

_MUTED = colors.HexColor("#71757b")
_PANEL = colors.HexColor("#e8e9ea")
_GUIDE = colors.HexColor("#babcbf")
# Tickets print in black only, so any printer gives the same slip.
_INK = colors.black

# Band, accent and stripe for each Skeleton theme: primary-800, primary-500 and secondary-500.
_THEME_COLORS: dict[str, tuple[str, str, str]] = {
    "catppuccin": ("#6476d1", "#7186ff", "#e977ca"),
    "cerberus": ("#064491", "#0770ef", "#7926cb"),
    "concord": ("#3b44cf", "#5865f2", "#ec439e"),
    "crimson": ("#8d0825", "#d21d3d", "#4785ae"),
    "dracula": ("#7452ad", "#bd92f9", "#fc79c4"),
    "fennec": ("#a9311b", "#f6530d", "#fecd8a"),
    "hamlindigo": ("#6e7ea3", "#a7bef3", "#a38e5e"),
    "legacy": ("#007752", "#11ba81", "#4f46e5"),
    "mint": ("#46a55c", "#66e985", "#7262f4"),
    "modern": ("#9d1b58", "#eb4999", "#00b7d6"),
    "mona": ("#5c349b", "#824fe1", "#2fa44f"),
    "nosh": ("#aa0019", "#dc0024", "#f5d2d2"),
    "nouveau": ("#998417", "#e6c830", "#0f72e3"),
    "pine": ("#6c5933", "#a0814d", "#57123c"),
    "reign": ("#e6e950", "#f4f861", "#f4f861"),
    "rocket": ("#017386", "#00b7d6", "#3a82f7"),
    "rose": ("#85516f", "#d87bac", "#383fd2"),
    "rosepine": ("#1d576e", "#317590", "#c5a9e6"),
    "sahara": ("#c0821f", "#eda92f", "#3ecbba"),
    "seafoam": ("#478d90", "#8acfca", "#203357"),
    "terminus": ("#3a00b6", "#5200ff", "#42fecf"),
    "vintage": ("#99430e", "#ea861d", "#98cea5"),
    "vox": ("#a68471", "#fbb48a", "#d0f96f"),
    "wintry": ("#1846ab", "#3a82f7", "#01a5ea"),
}
_BUILT_IN_THEME = "vintage"


@dataclass(frozen=True)
class _Palette:
    band: colors.Color
    accent: colors.Color
    stripe: colors.Color


def _palette(theme: str) -> _Palette:
    """The web app's colours for the theme; default, light and dark use the built-in vintage."""
    if theme not in _THEME_COLORS:
        theme = _BUILT_IN_THEME
    band, accent, stripe = _THEME_COLORS[theme]
    return _Palette(colors.HexColor(band), colors.HexColor(accent), colors.HexColor(stripe))


# Labels are English because visitors include foreigners.
DEFAULT_TITLE = "TiQR"
_TECH_LINE = "Distechsol · Suprema BioStar X"
_LOGOS = ("distechsol.webp", "suprema.webp")
# The web app's built-in logo, shown on tickets for installs without a logo of their own.
_BUILT_IN_LOGO = "tiqr.png"
# Geist ships one weight; bold adds a stroke of this many ems.
_BOLD_STROKE = 0.035
_TITLE_SIZES = (3.6, 3.0, 2.5)
_NAME_SIZES = (8, 7, 6, 5, 4.2)
_TYPE_SIZES = (3.0, 2.6, 2.2)
_DETAIL_SIZES = (3.4, 3.0, 2.6)
_ADMITS_SIZES = (5.0, 4.4, 3.8)
_VALUE_SIZES = (5.0, 4.4, 3.8, 3.2)
_LABEL_SIZES = (2.2, 2.0, 1.8)
_LABEL_TRACKING = 0.3
_LABEL_SEPARATOR = " / "

# A ticket's field labels in each language the web app speaks, as its locales word them. They are
# written in capitals here because str.upper() gets Azerbaijani's dotted İ wrong.
_FIELD_LABELS: dict[str, dict[str, str]] = {
    "visitor_type": {
        "en": "VISITOR TYPE",
        "ru": "ТИП ПОСЕТИТЕЛЯ",
        "az": "ZİYARƏTÇİNİN NÖVÜ",
        "kk": "КЕЛУШІ ТҮРІ",
    },
    "ticket_type": {
        "en": "TICKET TYPE",
        "ru": "ТИП БИЛЕТА",
        "az": "BİLET NÖVÜ",
        "kk": "БИЛЕТ ТҮРІ",
    },
    "valid_from": {
        "en": "VALID FROM",
        "ru": "ДЕЙСТВУЕТ С",
        "az": "BAŞLAMA VAXTI",
        "kk": "ЖАРАМДЫ БАСЫНАН",
    },
    "valid_until": {
        "en": "VALID TO",
        "ru": "ДЕЙСТВУЕТ ДО",
        "az": "BİTMƏ VAXTI",
        "kk": "ЖАРАМДЫ АЯҒЫНА ДЕЙІН",
    },
}


def _asset(folder: str, name: str) -> bytes:
    return files("tiqr.core").joinpath("assets", folder, name).read_bytes()


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

    def outline(
        self, x: float, top: float, width: float, height: float, color: colors.Color, line: float
    ) -> None:
        self.canvas.saveState()
        self.canvas.setStrokeColor(color)
        self.canvas.setLineWidth(line * mm)
        self.canvas.rect(x * mm, self._y(top + height), width * mm, height * mm, stroke=1, fill=0)
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


def _draw_header(
    surface: _Surface,
    logos: list[ImageReader],
    title: str,
    palette: _Palette,
    *,
    width: float = _BADGE_MM[0],
    margin: float = _MARGIN,
    edge: float = _EDGE_MARGIN,
) -> float:
    """Draw the event band, stripes and logos; return how far down the header reaches."""
    left, right = margin, width - margin
    text_width = right - left

    band_height = 10
    surface.rect(left, edge, text_width, band_height, palette.band)
    size, label = _fit_line(title, _TITLE_SIZES, text_width - 2, 1.1)
    surface.centered(width / 2, edge + 2.3, label, size, colors.white, bold=True, tracking=1.1)
    stripe = 1.5
    top = edge + band_height
    surface.rect(left, top, text_width, stripe, palette.stripe)
    surface.rect(left, top + stripe, text_width, stripe, palette.accent)
    top += stripe * 2 + 3.5

    logo_height = 8
    distechsol, suprema = logos
    surface.image(distechsol, left, top, logo_height)
    suprema_width = _image_width(suprema, logo_height)
    surface.image(suprema, right - suprema_width, top, logo_height, radius=1.2)
    return top + logo_height + 4


def _draw_detail(
    surface: _Surface, left: float, top: float, lines: list[str], size: float, step: float
) -> None:
    """Draw the ticket type's lines in the muted colour, one line every `step`."""
    for line in lines:
        surface.text(left, top, line, size, _MUTED)
        top += step


def _draw_face(
    surface: _Surface,
    ticket: Ticket,
    logos: list[ImageReader],
    window: str,
    title: str,
    palette: _Palette,
    *,
    back: bool,
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

    header_bottom = _draw_header(surface, logos, title, palette)

    bar_height = 7
    bar_top = height - _FOLD_MARGIN - bar_height
    surface.rect(left, bar_top, text_width, bar_height, palette.band, radius=1.2)
    surface.centered(width / 2, bar_top + 1.3, _TECH_LINE, 3.2, colors.white)
    rule = bar_top - 2.5

    tracking = 0.6
    chip_height = 6.2
    type_size, visitor_type = _fit_line(ticket.visitor_type, _TYPE_SIZES, text_width - 6, tracking)
    chip_width = _width(visitor_type, type_size, tracking) + 6
    # The back's name sits closer to its type chip, so the two read as one label.
    label_gap = 1.5 if back else 3.5
    label_step = chip_height + label_gap
    # The front leaves room for the QR code, so its name gets two lines.
    name_size, name_lines = _fit(ticket.visitor_name, _NAME_SIZES, text_width, 3 if back else 2)
    name_step = name_size * 1.2
    # The back shows the ticket type under the name, in the muted colour, wrapping if it is long.
    detail_lines: list[str] = []
    detail_size = _DETAIL_SIZES[0]
    if back and ticket.ticket_type:
        detail_size, detail_lines = _fit(ticket.ticket_type, _DETAIL_SIZES, text_width * 0.66, 4)
    detail_step = detail_size * 1.2
    detail_gap = 2 if detail_lines else 0
    block_height = (
        label_step + name_step * len(name_lines) + detail_gap + detail_step * len(detail_lines)
    )

    top = header_bottom
    # On the back, the chip and name rise a little, so the locations text sits further below them.
    lift = 0
    if back:
        # No QR code below, so center the block instead of leaving a gap under it.
        top += max(0, (rule - header_bottom - block_height) / 2)
        lift = 2
    surface.rect(left, top - lift, chip_width, chip_height, palette.accent, radius=1.2)
    surface.text(
        left + 3,
        top - lift + 1.3,
        visitor_type,
        type_size,
        colors.white,
        bold=True,
        tracking=tracking,
    )
    top += label_step
    for line in name_lines:
        surface.text(left, top - lift, line, name_size, palette.band, bold=True)
        top += name_step
    if back:
        _draw_detail(surface, left, top + detail_gap, detail_lines, detail_size, detail_step)
        return

    _draw_code(surface, ticket, window, left, top, rule, palette)


def _draw_code(
    surface: _Surface,
    ticket: Ticket,
    window: str,
    left: float,
    top: float,
    rule: float,
    palette: _Palette,
) -> None:
    """Draw the visit window, then the QR code panel and serial, which only the front carries."""
    width, _ = _BADGE_MM
    text_width = width - _MARGIN * 2
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
        width / 2,
        panel_top + pad + qr_size + 1,
        ticket.readable_serial,
        4.4,
        palette.band,
        bold=True,
    )


def _draw_sheet(
    canvas: Canvas,
    ticket: Ticket,
    logos: list[ImageReader],
    zone: ZoneInfo,
    title: str,
    palette: _Palette,
) -> None:
    badge_width, badge_height = _BADGE_MM
    window = _window(ticket, zone)
    face = _Surface(canvas, badge_height)

    canvas.saveState()
    canvas.translate(0, badge_height * mm)
    _draw_face(face, ticket, logos, window, title, palette, back=False)
    canvas.restoreState()
    canvas.saveState()
    canvas.translate(badge_width * mm, badge_height * mm)
    canvas.rotate(180)
    _draw_face(face, ticket, logos, window, title, palette, back=True)
    canvas.restoreState()

    page = _Surface(canvas, _PAGE_MM[1])
    page.line((badge_width, 0), (badge_width, _PAGE_MM[1]), _GUIDE, 0.3, dash=(4, 2.5))
    page.line((0, badge_height), (badge_width, badge_height), palette.band, 0.3, dash=(8, 3))

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


# Whom a ticket admits, worded as the web app's locales word its usage types, in capitals.
_USAGE_WORDS: dict[str, dict[UsageType, str]] = {
    "en": {UsageType.ONE_TIME: "ONE-TIME", UsageType.MULTI_USE: "MULTI-USE"},
    "ru": {UsageType.ONE_TIME: "ОДНОРАЗОВЫЙ", UsageType.MULTI_USE: "МНОГОРАЗОВЫЙ"},
    "az": {UsageType.ONE_TIME: "BİRDƏFƏLİK", UsageType.MULTI_USE: "ÇOXDƏFƏLİK"},
    "kk": {UsageType.ONE_TIME: "БІР РЕТТІК", UsageType.MULTI_USE: "КӨП РЕТТІК"},
}


def _russian_people(count: int) -> str:
    """Человек takes its genitive singular after 2-4 (but not 12-14), and stays put otherwise."""
    few = count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}
    return "ЧЕЛОВЕКА" if few else "ЧЕЛОВЕК"


def _admits(ticket: Ticket, language: str = "en") -> str:
    """Whom the ticket admits in a language (en, ru, az or kk): its usage, or a group's size."""
    if ticket.usage_type != UsageType.GROUP:
        return _USAGE_WORDS[language][UsageType(ticket.usage_type)]
    count = ticket.group_size
    group = {
        "en": f"GROUP · {count} {'PERSON' if count == 1 else 'PEOPLE'}",
        "ru": f"ГРУППА · {count} {_russian_people(count)}",
        # Azerbaijani and Kazakh nouns stay singular after a number.
        "az": f"QRUP · {count} NƏFƏR",
        "kk": f"ТОП · {count} АДАМ",
    }
    return group[language]


def _ticket_language(languages: tuple[str, ...], language: str | None) -> str:
    """The language whom the ticket admits is written in: `language` when the install offers it,
    else the install's first language; either way as its bare code, such as ru."""
    offered = [code.partition("-")[0] for code in languages]
    wanted = (language or "").partition("-")[0].lower()
    return wanted if wanted in offered else offered[0]


def _ticket_logo(path: Path | None) -> ImageReader | None:
    """The install's logo (its `logo_path`, as the installer wrote it) in greyscale on white paper,
    or the built-in logo when the install has none.

    None when the install's logo is an SVG: Pillow cannot read SVG, so it is left off the ticket
    rather than swapped for another image.
    """
    if path is not None and path.suffix.lower() == ".svg":
        return None
    data = path.read_bytes() if path is not None else _asset("images", _BUILT_IN_LOGO)
    with Image.open(BytesIO(data)) as source:
        rgba = source.convert("RGBA")
    paper = Image.new("RGBA", rgba.size, "white")
    paper.alpha_composite(rgba)
    return ImageReader(paper.convert("L"))


def _field_label(field: str, languages: tuple[str, ...]) -> str:
    """The field's label in each language, in the install's order, such as `TICKET TYPE / ...`."""
    labels = _FIELD_LABELS[field]
    return _LABEL_SEPARATOR.join(labels[code.partition("-")[0]] for code in languages)


def _fit_label(label: str, width: float) -> tuple[float, list[str]]:
    """Fit a label on as few lines as it can, shrinking before it wraps; never cut it."""
    for lines_allowed in (1, 2, 3, 4):
        for size in _LABEL_SIZES:
            lines = _wrap_label(label, size, width)
            if len(lines) <= lines_allowed:
                return size, lines
    size = _LABEL_SIZES[-1]
    return size, _wrap_label(label, size, width)


def _wrap_label(label: str, size: float, width: float) -> list[str]:
    """Wrap a label between its languages first, and inside one only when it alone is too wide."""
    lines: list[str] = []
    for part in label.split(_LABEL_SEPARATOR):
        joined = f"{lines[-1]}{_LABEL_SEPARATOR}{part}" if lines else part
        if lines and _width(joined, size, _LABEL_TRACKING) <= width:
            lines[-1] = joined
        elif _width(part, size, _LABEL_TRACKING) <= width:
            lines.append(part)
        else:
            lines.extend(_wrap(part, size, width - _LABEL_TRACKING * len(part)))
    return lines


def _draw_field(
    surface: _Surface,
    left: float,
    top: float,
    width: float,
    label: tuple[float, list[str]],
    lines: list[tuple[str, float, bool]],
    label_rows: int = 0,
) -> float:
    """Draw a cheque field: a small label, its value lines, then a rule; return the rule's top.

    `label_rows` reserves that many label lines, so fields side by side keep their values level.
    """
    label_size, label_lines = label
    step = label_size * 1.2
    for row, line in enumerate(label_lines):
        surface.text(left, top + row * step, line, label_size, _INK, tracking=_LABEL_TRACKING)
    top += step * max(len(label_lines), label_rows) + label_size * 0.25
    for line, size, bold in lines:
        surface.text(left, top, line, size, _INK, bold=bold)
        top += size * 1.2
    top += 0.8
    surface.line((left, top), (left + width, top), _INK, 0.2)
    return top


def _draw_ticket(
    canvas: Canvas,
    ticket: Ticket,
    logo: ImageReader | None,
    zone: ZoneInfo,
    languages: tuple[str, ...],
    language: str,
) -> None:
    """Draw a ticket on its slip in black only, laid out like a cheque, top to bottom: the logo
    (when the install has one), whom it admits, visitor type, ticket type, validity, then the QR
    code and serial below a tear line.

    A ticket names no visitor, shows no price and carries no partner logos. Field labels are in
    each of the install's `languages`, in its order, since visitors may read any of them; whom it
    admits is in `language`, the one the operator's app is in.
    """
    width, height = _TICKET_MM
    surface = _Surface(canvas, height)
    frame, margin = _TICKET_FRAME, _TICKET_MARGIN
    left, right = margin, width - margin
    text_width = right - left
    surface.outline(frame, frame, width - frame * 2, height - frame * 2, _INK, 0.5)

    top, logo_height = margin, 12.0
    if logo is not None:
        pixels_wide, pixels_high = logo.getSize()
        drawn = min(logo_height, text_width * pixels_high / pixels_wide)
        surface.image(
            logo, (width - _image_width(logo, drawn)) / 2, top + (logo_height - drawn) / 2, drawn
        )
        top += logo_height + 2.5
        surface.line((left, top), (right, top), _INK, 0.6)
        surface.line((left, top + 0.9), (right, top + 0.9), _INK, 0.2)
        top += 3.5

    # Whom it admits is white on a black bar, the first thing a gatekeeper reads.
    bar_height = 10
    surface.rect(left, top, text_width, bar_height, _INK, radius=1)
    size, admits = _fit_line(_admits(ticket, language), _ADMITS_SIZES, text_width - 4, 0.8)
    surface.centered(
        width / 2,
        top + (bar_height - size) / 2,
        admits,
        size,
        colors.white,
        bold=True,
        tracking=0.8,
    )
    top += bar_height + 4

    # Long types wrap rather than lose words; the QR code below gives up some room.
    size, lines = _fit(ticket.visitor_type, _VALUE_SIZES, text_width, 2)
    top = _draw_field(
        surface,
        left,
        top,
        text_width,
        _fit_label(_field_label("visitor_type", languages), text_width),
        [(line, size, True) for line in lines],
    )
    if ticket.ticket_type:
        size, lines = _fit(ticket.ticket_type, _VALUE_SIZES[1:], text_width, 3)
        top = _draw_field(
            surface,
            left,
            top + 3,
            text_width,
            _fit_label(_field_label("ticket_type", languages), text_width),
            [(line, size, True) for line in lines],
        )

    gap = 6
    column = (text_width - gap) / 2
    validity = (("valid_from", ticket.valid_from), ("valid_until", ticket.valid_until))
    labels = [_fit_label(_field_label(field, languages), column) for field, _ in validity]
    # Both labels share one size and one height, so the two dates line up.
    size = min(label_size for label_size, _ in labels)
    labels = [
        (size, _wrap_label(_field_label(field, languages), size, column)) for field, _ in validity
    ]
    rows = max(len(label_lines) for _, label_lines in labels)
    bottoms: list[float] = []
    for index, ((_, moment), label) in enumerate(zip(validity, labels, strict=True)):
        local = moment.astimezone(zone)
        lines = [(f"{local:%d.%m.%Y}", 4.4, True), (f"{local:%H:%M}", 3.6, False)]
        x = left + index * (column + gap)
        bottoms.append(_draw_field(surface, x, top + 3, column, label, lines, rows))
    top = max(bottoms) + 4

    # A tear line keeps the code apart from the details, as on a cheque's stub.
    surface.line((frame, top), (width - frame, top), _INK, 0.25, dash=(1.5, 1.2))

    # The QR code stays black on white: the reader needs the contrast. Its quiet zone is the gap
    # below the tear line.
    serial_size, serial_gap = 4.0, 1.5
    room_top, room_bottom = top + 0.5, height - margin + 1
    qr_size = min(56, room_bottom - room_top - serial_gap - serial_size * 1.2)
    qr_top = room_top + (room_bottom - room_top - qr_size - serial_gap - serial_size * 1.2) / 2
    surface.qr(ticket.qr_payload, (width - qr_size) / 2, qr_top, qr_size)
    surface.centered(
        width / 2,
        qr_top + qr_size + serial_gap,
        ticket.readable_serial,
        serial_size,
        _INK,
        bold=True,
        tracking=0.4,
    )


def render_pdf(  # noqa: PLR0913 - the ticket and where it goes, then branding by keyword
    ticket: Ticket,
    output_dir: Path,
    timezone: str,
    *,
    title: str = DEFAULT_TITLE,
    theme: str = "default",
    mode: Mode = Mode.BADGE,
    logo: Path | None = None,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    language: str | None = None,
) -> Path:
    """Render the badge, or the ticket in ticket mode; `title` is the app name (TIQR_APP_NAME).

    The badge prints in `theme`'s colours with the partner logos in its header band. The ticket
    prints in black with the install's `logo` (its logo_path) in greyscale on top when it has one,
    its field labels in each of `languages` (codes such as en-US), in that order, and whom it admits
    in `language` (such as ru) when that is one of them, else in the first.
    """
    zone = ZoneInfo(timezone)
    is_ticket = Mode(mode) == Mode.TICKET
    logos = [] if is_ticket else [ImageReader(BytesIO(_asset("images", n))) for n in _LOGOS]
    ticket_logo = _ticket_logo(logo) if is_ticket else None
    # Validate before creating any file, so a failure leaves no debris.
    _require_glyphs(ticket.visitor_name + ticket.visitor_type + (ticket.ticket_type or "") + title)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{ticket.id}.pdf"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ticket.id}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        size = (_TICKET_MM[0] * mm, _TICKET_MM[1] * mm) if is_ticket else A4
        canvas = Canvas(str(temporary), pagesize=size, pageCompression=0)
        canvas.setTitle(ticket.readable_serial)
        if is_ticket:
            _draw_ticket(
                canvas, ticket, ticket_logo, zone, languages, _ticket_language(languages, language)
            )
        else:
            _draw_sheet(canvas, ticket, logos, zone, title, _palette(theme))
        canvas.save()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
