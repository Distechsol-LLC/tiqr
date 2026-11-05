from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from tiqr.core import pdf
from tiqr.core.models import Ticket, TicketState, UsageType
from tiqr.core.settings import BRANDING_FILE

BAKU = "Asia/Baku"
HALF_WIDTH, HALF_HEIGHT = A4[0] / 2, A4[1] / 2
START = datetime(2030, 1, 1, 8, tzinfo=UTC)


@pytest.fixture
def ticket():
    owner = uuid4()
    return Ticket(
        id=uuid4(),
        external_id="1000000",
        qr_payload="TQR:300101-00001:ABCDEFGHIJKLMNO",
        readable_serial="TQR-300101-00001",
        visitor_name="Adam Tələbə",
        visitor_type="Qonaq",
        valid_from=START,
        valid_until=START + timedelta(hours=2),
        usage_type=UsageType.MULTI_USE,
        state=TicketState.ISSUED,
        created_by=owner,
        assigned_operator=owner,
        created_at=START,
    )


# The project root is each test's tmp_path, so its branding file sits there too
def outputs(directory):
    return [path for path in directory.iterdir() if path.name != BRANDING_FILE]


@pytest.fixture
def render(ticket, tmp_path):
    def render(subject=ticket, zone=BAKU, into=tmp_path):
        return pdf.render_pdf(subject, into, zone)

    return render


@pytest.fixture
def spy(monkeypatch):
    """Wrap a method and collect `record(self, *args, **kwargs)` into a list, which is returned."""

    def spy(owner, name, record, calls=None):
        calls = [] if calls is None else calls
        original = getattr(owner, name)

        def wrapper(self, *args, **kwargs):
            calls.append(record(self, *args, **kwargs))
            return original(self, *args, **kwargs)

        monkeypatch.setattr(owner, name, wrapper)
        return calls

    return spy


@pytest.fixture
def strings(spy):
    """Every string drawn on the sheet, as (x, text, font size)."""
    return spy(Canvas, "drawString", lambda c, x, y, text, **_: (x, text, c._fontsize))


def test_renders_one_a4_page_with_unicode_font_and_partner_logos(ticket, render, tmp_path):
    path = render(into=tmp_path / "nested")
    data = path.read_bytes()
    assert path == tmp_path / "nested" / f"{ticket.id}.pdf"
    assert data.startswith(b"%PDF-")
    assert data.count(b"/Type /Page\n") == 1
    assert data.count(b"/Subtype /Image") == 2
    assert b"/ToUnicode" in data
    assert ticket.readable_serial.encode() in data
    assert list(path.parent.iterdir()) == [path]


def test_name_and_type_are_drawn_on_both_sides(ticket, render, strings):
    render()
    texts = [text for _, text, _ in strings]
    assert texts.count(ticket.visitor_name) == texts.count(ticket.visitor_type) == 2
    glyphs = pdfmetrics.getFont(pdf._FONT).face.charWidths
    assert all(ord(char) in glyphs for char in ticket.visitor_name)


def test_back_shows_the_ticket_type_only_once_and_wraps_when_long(ticket, render, strings):
    ticket_type = "Gündəlik keçid " * 8
    render(replace(ticket, ticket_type=ticket_type))
    pieces = [(text, size) for _, text, size in strings if text and text in ticket_type]
    assert len(pieces) >= 2
    assert all(size < pdf._NAME_SIZES[0] * mm for _, size in pieces)


def test_front_does_not_show_the_ticket_type(ticket, render, strings):
    render(replace(ticket, ticket_type="Day pass"))
    assert [text for _, text, _ in strings].count("Day pass") == 1


def test_qr_is_vector_with_payload_and_quiet_zone(ticket, render, spy, monkeypatch):
    rects = spy(Canvas, "rect", lambda _, x, y, w, h, **kw: (x, y, w, h, kw))
    spans = []
    draw_qr = pdf._draw_qr

    def span(canvas, payload, *args):
        start = len(rects)
        draw_qr(canvas, payload, *args)
        spans.append((payload, rects[start:]))

    monkeypatch.setattr(pdf, "_draw_qr", span)
    render()

    [(payload, (background, *modules))] = spans  # only the front carries a QR code
    assert payload == ticket.qr_payload
    x, y, size, _, options = background
    assert options == {"stroke": 0, "fill": 1}

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(payload)
    code.make(fit=True)
    matrix = code.get_matrix()
    cell = size / len(matrix)
    expected = {
        (round(x + column * cell, 5), round(y + (len(matrix) - row - 1) * cell, 5))
        for row, values in enumerate(matrix)
        for column, dark in enumerate(values)
        if dark
    }
    assert {(round(mx, 5), round(my, 5)) for mx, my, *_ in modules} == expected
    assert len(modules) == len(expected)
    assert all(w == pytest.approx(cell) and h == pytest.approx(cell) for *_, w, h, _ in modules)


def test_badge_is_the_upper_half_with_the_back_turned_for_folding(render, spy):
    moves = spy(Canvas, "translate", lambda _, dx, dy: ("translate", dx, dy))
    spy(Canvas, "rotate", lambda _, degrees: ("rotate", degrees), moves)
    render()
    # ReportLab also translates internally, for example for images.
    assert [m for m in moves if m[0] == "rotate" or m[2] == HALF_HEIGHT] == [
        ("translate", 0, HALF_HEIGHT),
        ("translate", HALF_WIDTH, HALF_HEIGHT),
        ("rotate", 180),
    ]


def test_everything_on_the_badge_stays_inside_the_left_half(ticket, render, strings):
    render(replace(ticket, visitor_name="Əli " * 600, visitor_type="Visitor " * 600))
    margin = 7 * mm
    badge = [(x, text, size) for x, text, size in strings if x < HALF_WIDTH]
    assert len(badge) > 8
    assert all(
        x >= margin and x + pdfmetrics.stringWidth(text, pdf._FONT, size) <= HALF_WIDTH - margin
        for x, text, size in badge
    )


def test_name_shrinks_before_it_is_cut():
    size, lines = pdf._fit("Məmmədhüseynzadə Əbdürrəhman Süleyman oğlu", pdf._NAME_SIZES, 91, 2)
    assert pdf._NAME_SIZES[-1] <= size < pdf._NAME_SIZES[0]
    assert not any(line.endswith("…") for line in lines)


def test_oversized_name_and_type_are_cut_with_an_ellipsis():
    size, lines = pdf._fit("Əli " * 600, pdf._NAME_SIZES, 91, 2)
    assert size == pdf._NAME_SIZES[-1]
    assert len(lines) == 2
    assert lines[-1].endswith("…")
    assert all(pdf._width(line, size) <= 91 for line in lines)

    size, line = pdf._fit_line("Visitor " * 600, pdf._TYPE_SIZES, 85, 0.6)
    assert size == pdf._TYPE_SIZES[-1]
    assert line.endswith("…")
    assert pdf._width(line, size, 0.6) <= 85


@pytest.mark.parametrize(
    ("start", "end", "zone", "expected"),
    [
        (START, START + timedelta(hours=2), BAKU, "01.01.30 · 12:00 — 14:00"),
        (START, START + timedelta(hours=2), "UTC", "01.01.30 · 08:00 — 10:00"),
        (START, START + timedelta(days=2, hours=3), "UTC", "01.01.30 · 08:00 — 03.01.30 · 11:00"),
        # The day rolls over for the zone, not for UTC.
        (
            datetime(2030, 3, 31, 22, tzinfo=UTC),
            datetime(2030, 3, 31, 23, tzinfo=UTC),
            BAKU,
            "01.04.30 · 02:00 — 03:00",
        ),
    ],
    ids=["same-day", "utc", "overnight", "zone-rollover"],
)
def test_access_window_is_day_month_year_in_the_given_zone(ticket, start, end, zone, expected):
    window = pdf._window(replace(ticket, valid_from=start, valid_until=end), ZoneInfo(zone))
    assert window == expected


def test_reprint_overwrites_the_same_path(ticket, render, tmp_path):
    first = render()
    first.write_bytes(b"old-file")
    assert render(zone="UTC") == first
    assert first.read_bytes().startswith(b"%PDF-")
    assert outputs(tmp_path) == [first]


@pytest.mark.parametrize(
    ("changes", "zone", "error", "match"),
    [
        ({}, "Invalid/Timezone", (ValueError, KeyError), None),
        ({"visitor_name": "Guest \U0001f680"}, BAKU, ValueError, r"U\+1F680"),
    ],
    ids=["invalid-timezone", "unsupported-glyph"],
)
def test_invalid_input_fails_before_anything_is_written(
    ticket, render, tmp_path, changes, zone, error, match
):
    with pytest.raises(error, match=match):
        render(replace(ticket, **changes), zone, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_missing_assets_fail_strictly(render, tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "files", lambda package: tmp_path)
    monkeypatch.setattr(pdfmetrics, "getRegisteredFontNames", list)
    with pytest.raises(FileNotFoundError):
        render(into=tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("owner", "name", "error"),
    [(Canvas, "save", OSError("disk full")), (Path, "replace", PermissionError("locked"))],
    ids=["save", "replace"],
)
def test_write_failure_keeps_the_existing_pdf_and_leaves_no_temp_file(
    ticket, render, tmp_path, monkeypatch, owner, name, error
):
    destination = tmp_path / f"{ticket.id}.pdf"
    destination.write_bytes(b"existing-pdf")

    def fail(*_):
        raise error

    monkeypatch.setattr(owner, name, fail)
    with pytest.raises(type(error), match=str(error)):
        render()
    assert destination.read_bytes() == b"existing-pdf"
    assert outputs(tmp_path) == [destination]


def test_render_failure_does_not_increment_the_print_count(
    service, accounts, clock, tmp_path, monkeypatch
):
    actor = accounts["admin"]
    service.create_visitor_type(actor, "Visitor")
    ticket = service.create_ticket(
        actor,
        visitor_name="Guest",
        visitor_type="Visitor",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.MULTI_USE,
    )

    def fail(self):
        raise OSError("disk full")

    monkeypatch.setattr(Canvas, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        service.print_ticket(actor, ticket.id, tmp_path, renderer=pdf.render_pdf)
    assert service.repository.get_ticket(ticket.id).print_count == 0
    assert not outputs(tmp_path)
