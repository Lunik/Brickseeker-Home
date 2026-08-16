"""CSV and PDF exports of the collection inventory.

Both read their value through `resolve_collection_price` — the same function the Collection row and
the Statistics total use — so an export can never quote a different number from the screen it was
generated on.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog, collection_repo
from .pricing import StoreAvailability, resolve_collection_price, resolve_collection_price_condition

CSV_HEADERS = [
    "Numéro",
    "Nom",
    "Année",
    "Thème",
    "Pièces",
    "Exemplaires",
    "Liste",
    "Condition",
    "Prix lego.com (€)",
    "Disponibilité",
    "Valeur estimée (€)",
    "Base de valorisation",
    "Prix payé (€)",
    "Valeur totale (€)",
]


async def _rows(session: AsyncSession) -> tuple[list[list[object]], float]:
    owned = await collection_repo.owned_sets(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)
    conditions = await collection_repo.condition_by_list_id(session)
    paid_prices = await collection_repo.paid_price_by_set_num(session)
    theme_names = await catalog.theme_names(session)

    rows: list[list[object]] = []
    total = 0.0
    for row in sorted(owned, key=lambda item: item.name.lower()):
        quotes = quotes_by_set.get(row.set_num, [])
        condition = conditions.get(row.current_list_id) if row.current_list_id else None
        availability = StoreAvailability.from_raw(row.store_availability)
        value = resolve_collection_price(row.store_price_eur, condition, availability, quotes)
        valued_condition = resolve_collection_price_condition(
            row.store_price_eur, condition, availability, quotes
        )
        line_total = (value or 0.0) * row.quantity
        total += line_total

        rows.append(
            [
                row.set_num,
                row.name,
                row.year or "",
                theme_names.get(row.theme_id, f"Thème #{row.theme_id}"),
                row.num_parts,
                row.quantity,
                row.current_list_name or "",
                (condition.display_name if condition else ""),
                _money(row.store_price_eur),
                availability.display_name,
                _money(value),
                (valued_condition.display_name if valued_condition else ""),
                _money(paid_prices.get(row.set_num)),
                _money(line_total if value is not None else None),
            ]
        )
    return rows, total


def _money(value: float | None) -> str:
    """Comma decimal separator: these exports are opened in a French locale spreadsheet, where a
    dot-decimal column imports as text."""
    return "" if value is None else f"{value:.2f}".replace(".", ",")


async def export_collection_csv(session: AsyncSession) -> bytes:
    rows, total = await _rows(session)
    buffer = io.StringIO()
    # Semicolon delimiter, for the same reason as the comma decimal separator above.
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS)
    writer.writerows(rows)
    writer.writerow([])
    writer.writerow(["Total", "", "", "", "", "", "", "", "", "", "", "", "", _money(total)])
    # BOM so Excel detects UTF-8 and renders the accents.
    return buffer.getvalue().encode("utf-8-sig")


async def export_collection_pdf(session: AsyncSession) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rows, total = await _rows(session)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Collection BrickSeeker",
    )
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell")
    cell.fontSize = 7
    cell.leading = 9

    # A PDF column set trimmed to what fits a landscape page and stays readable — the CSV is the
    # complete export, this one is for printing or sharing.
    columns = [0, 1, 2, 3, 4, 5, 6, 10, 13]
    header = [Paragraph(f"<b>{CSV_HEADERS[index]}</b>", cell) for index in columns]
    body = [[Paragraph(str(row[index]), cell) for index in columns] for row in rows]

    table = Table(
        [header, *body],
        repeatRows=1,
        colWidths=[22 * mm, 78 * mm, 14 * mm, 40 * mm, 16 * mm, 18 * mm, 32 * mm, 24 * mm, 24 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3000B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F5F7")]),
            ]
        )
    )

    generated = datetime.now(UTC).strftime("%d/%m/%Y")
    document.build(
        [
            Paragraph("<b>Collection BrickSeeker</b>", styles["Title"]),
            Paragraph(
                f"{len(rows)} set(s) — valeur estimée totale {total:,.2f} €".replace(",", " ")
                + f" — export du {generated}",
                styles["Normal"],
            ),
            Spacer(1, 6 * mm),
            table,
        ]
    )
    return buffer.getvalue()
