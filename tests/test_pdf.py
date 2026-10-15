from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from tiqr import pdf
from tiqr.models import Role, Ticket, TicketState, UsageType
from tiqr.repository import SQLiteRepository
from tiqr.service import TicketService


@pytest.fixture
def ticket():
    now = datetime(2030, 1, 1, 8, tzinfo=UTC)
    owner = uuid4()
    return Ticket(
        id=uuid4(),
        external_id="1000000",
        qr_payload="TQR:300101-00001:ABCDEFGHIJKLMNO",
        readable_serial="TQR-300101-00001",
        visitor_name="Adam Tələbə",
        visitor_type="Qonaq",
        valid_from=now,
        valid_until=now + timedelta(hours=2),
        usage_type=UsageType.MULTI_USE,
        state=TicketState.ISSUED,
        created_by=owner,
        assigned_operator=owner,
        created_at=now,
    )


def test_pdf_is_one_a4_sheet_with_fields_unicode_font_and_two_logos(ticket, tmp_path):
    path = pdf.render_pdf(ticket, tmp_path / "nested", "Asia/Baku")
    assert path == tmp_path / "nested" / f"{ticket.id}.pdf"
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.count(b"/Type /Page\n") == 1
    assert ticket.readable_serial.encode("ascii") in data
    assert b"/ToUnicode" in data
    assert data.count(b"/Subtype /Image") == 2
    assert not list(path.parent.glob("*.tmp"))
    for name in ("distechsol.png", "suprema.png"):
        assert files("tiqr").joinpath("assets", name).read_bytes().startswith(b"\x89PNG")


def test_pdf_draws_unicode_name_without_loss(ticket, tmp_path, monkeypatch):
    texts = []
    original = Canvas.drawString

    def draw_string(self, x, y, text, *args, **kwargs):
        texts.append(text)
        return original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, "drawString", draw_string)
    pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    # The name and type are drawn on both sides of the badge.
    assert texts.count(ticket.visitor_name) == 2
    assert texts.count(ticket.visitor_type) == 2
    font = pdfmetrics.getFont(pdf._FONT)
    assert all(ord(character) in font.face.charWidths for character in ticket.visitor_name)


def test_qr_is_vector_with_payload_and_quiet_zone(ticket, tmp_path, monkeypatch):
    rectangles = []
    spans = []
    original_rect = Canvas.rect
    original_qr = pdf._draw_qr

    def rect(self, x, y, width, height, *args, **kwargs):
        rectangles.append((x, y, width, height, kwargs))
        return original_rect(self, x, y, width, height, *args, **kwargs)

    def draw_qr(canvas, payload, *args):
        start = len(rectangles)
        original_qr(canvas, payload, *args)
        spans.append((payload, start, len(rectangles)))

    monkeypatch.setattr(Canvas, "rect", rect)
    monkeypatch.setattr(pdf, "_draw_qr", draw_qr)
    pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    # Only the front carries a QR code.
    [(payload, start, end)] = spans
    assert payload == ticket.qr_payload
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(ticket.qr_payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    background, *modules = rectangles[start:end]
    assert len(modules) == sum(sum(row) for row in matrix)
    x, y, size, _, options = background
    assert options == {"stroke": 0, "fill": 1}
    cell = size / len(matrix)
    expected = {
        (round(x + column * cell, 5), round(y + (len(matrix) - row - 1) * cell, 5))
        for row, values in enumerate(matrix)
        for column, dark in enumerate(values)
        if dark
    }
    assert {(round(a, 5), round(b, 5)) for a, b, *_ in modules} == expected
    assert all(
        width == pytest.approx(cell) and height == pytest.approx(cell)
        for _, _, width, height, _ in modules
    )
    assert min(a for a, *_ in modules) >= x + 4 * cell
    assert min(b for _, b, *_ in modules) >= y + 4 * cell


def test_badge_is_the_left_half_with_the_back_rotated_for_folding(ticket, tmp_path, monkeypatch):
    moves = []
    original_translate, original_rotate = Canvas.translate, Canvas.rotate

    def translate(self, dx, dy):
        moves.append(("translate", dx, dy))
        return original_translate(self, dx, dy)

    def rotate(self, degrees):
        moves.append(("rotate", degrees))
        return original_rotate(self, degrees)

    monkeypatch.setattr(Canvas, "translate", translate)
    monkeypatch.setattr(Canvas, "rotate", rotate)
    pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    # The front is the upper half. The back is the lower half, turned 180 degrees about its own
    # corner so that folding it up and back leaves its text upright.
    # ReportLab also translates internally, for example for images; keep the sheet-level moves.
    moves = [move for move in moves if move[0] == "rotate" or move[2] == A4[1] / 2]
    assert moves == [
        ("translate", 0, A4[1] / 2),
        ("translate", A4[0] / 2, A4[1] / 2),
        ("rotate", 180),
    ]


def test_everything_on_the_badge_stays_inside_the_left_half(ticket, tmp_path, monkeypatch):
    long_ticket = replace(ticket, visitor_name="Əli " * 600, visitor_type="Visitor " * 600)
    drawn = []
    original = Canvas.drawString

    def draw_string(self, x, y, text, *args, **kwargs):
        drawn.append((x, text, self._fontsize))
        return original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, "drawString", draw_string)
    pdf.render_pdf(long_ticket, tmp_path, "Asia/Baku")
    margin = 7 * mm
    badge = [(x, text, size) for x, text, size in drawn if x < A4[0] / 2]
    assert len(badge) > 8
    # Sides are drawn in a local frame that is 105 mm wide, whichever way up they end up.
    assert all(margin <= x for x, *_ in badge)
    assert all(
        x + pdfmetrics.stringWidth(text, pdf._FONT, size) <= A4[0] / 2 - margin + 0.01
        for x, text, size in badge
    )


def test_oversized_name_and_type_are_cut_with_an_ellipsis_not_overflowed(ticket, tmp_path):
    long_ticket = replace(ticket, visitor_name="Əli " * 600, visitor_type="Visitor " * 600)
    size, lines = pdf._fit(long_ticket.visitor_name, pdf._NAME_SIZES, 91, 2)
    assert size == pdf._NAME_SIZES[-1]
    assert len(lines) == 2
    assert lines[-1].endswith("…")
    assert all(pdf._width(line, size) <= 91 for line in lines)
    size, line = pdf._fit_line(long_ticket.visitor_type, pdf._TYPE_SIZES, 85, 0.6)
    assert line.endswith("…")
    assert pdf._width(line, size, 0.6) <= 85
    assert pdf.render_pdf(long_ticket, tmp_path, "Asia/Baku").is_file()


def test_name_shrinks_before_it_is_cut():
    size, lines = pdf._fit("Məmmədhüseynzadə Əbdürrəhman Süleyman oğlu", pdf._NAME_SIZES, 91, 2)
    assert 4.2 <= size < 8
    assert not any(line.endswith("…") for line in lines)


def test_access_window_is_day_month_year_in_the_given_timezone(ticket):
    baku, utc = ZoneInfo("Asia/Baku"), ZoneInfo("UTC")
    assert pdf._window(ticket, baku) == "01.01.30 · 12:00 - 14:00"
    assert pdf._window(ticket, utc) == "01.01.30 · 08:00 - 10:00"
    overnight = replace(ticket, valid_until=ticket.valid_from + timedelta(days=2, hours=3))
    assert pdf._window(overnight, utc) == "01.01.30 · 08:00 - 03.01.30 · 11:00"
    # The day rolls over for the zone, not for UTC.
    late = replace(
        ticket,
        valid_from=datetime(2030, 3, 31, 22, tzinfo=UTC),
        valid_until=datetime(2030, 3, 31, 23, tzinfo=UTC),
    )
    assert pdf._window(late, baku) == "01.04.30 · 02:00 - 03:00"


def test_reprint_overwrites_same_path(ticket, tmp_path):
    first = pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    first.write_bytes(b"old-file")
    second = pdf.render_pdf(ticket, tmp_path, "UTC")
    assert first == second
    assert second.read_bytes().startswith(b"%PDF-")
    assert [entry.name for entry in tmp_path.iterdir()] == [f"{ticket.id}.pdf"]


def test_missing_assets_fail_strictly(ticket, tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "files", lambda package: tmp_path)
    with pytest.raises(FileNotFoundError):
        pdf.render_pdf(ticket, tmp_path / "out", "Asia/Baku")
    assert not (tmp_path / "out" / f"{ticket.id}.pdf").exists()


def test_invalid_timezone_fails_without_partial_pdf(ticket, tmp_path):
    with pytest.raises((ValueError, KeyError)):
        pdf.render_pdf(ticket, tmp_path, "Invalid/Timezone")
    assert not list(tmp_path.iterdir())


def test_unsupported_font_glyph_is_explicit_error(ticket, tmp_path):
    unsupported = replace(ticket, visitor_name="Guest \U0001f680")
    with pytest.raises(ValueError, match="U\\+1F680"):
        pdf.render_pdf(unsupported, tmp_path, "Asia/Baku")
    assert not list(tmp_path.iterdir())


def test_atomic_failure_preserves_existing_pdf_and_removes_temp(ticket, tmp_path, monkeypatch):
    destination = tmp_path / f"{ticket.id}.pdf"
    destination.write_bytes(b"existing-pdf")

    def save(self):
        Path(self._filename).write_bytes(b"partial-pdf")
        raise OSError("simulated write failure")

    monkeypatch.setattr(Canvas, "save", save)
    with pytest.raises(OSError, match="simulated write failure"):
        pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    assert destination.read_bytes() == b"existing-pdf"
    assert list(tmp_path.iterdir()) == [destination]


def test_replace_failure_preserves_destination(ticket, tmp_path, monkeypatch):
    destination = tmp_path / f"{ticket.id}.pdf"
    destination.write_bytes(b"existing-pdf")

    def replace(self, target):
        raise PermissionError("locked destination")

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(PermissionError, match="locked destination"):
        pdf.render_pdf(ticket, tmp_path, "Asia/Baku")
    assert destination.read_bytes() == b"existing-pdf"
    assert list(tmp_path.iterdir()) == [destination]


def test_render_failure_does_not_increment_domain_print_count(tmp_path, monkeypatch):
    now = datetime(2030, 1, 1, 8, tzinfo=UTC)
    repository = SQLiteRepository(":memory:")
    repository.initialize()
    try:
        service = TicketService(repository, "pdf-suite-signing-key", clock=lambda: now)
        actor = service.add_user("admin", "password", Role.ADMIN)
        ticket = service.create_ticket(
            actor,
            visitor_name="Guest",
            visitor_type="Visitor",
            valid_from=now,
            valid_until=now + timedelta(hours=1),
            usage_type=UsageType.MULTI_USE,
        )

        def save(self):
            raise OSError("disk full")

        monkeypatch.setattr(Canvas, "save", save)
        with pytest.raises(OSError, match="disk full"):
            service.print_ticket(actor, ticket.id, tmp_path, renderer=pdf.render_pdf)
        assert repository.get_ticket(ticket.id).print_count == 0
        assert not list(tmp_path.iterdir())
    finally:
        repository.close()
