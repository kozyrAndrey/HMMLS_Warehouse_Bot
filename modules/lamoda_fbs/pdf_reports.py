from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

def merge_pdfs(parts):
    writer = PdfWriter()
    for content in parts:
        reader = PdfReader(BytesIO(content))
        for page in reader.pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _font_name():
    name = "LamodaDejaVu"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    candidates = [
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ]
    for path in candidates:
        if path.exists():
            pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
    return "Helvetica"


def _draw_lines(pdf, lines, *, title=None):
    font = _font_name()
    width, height = A4
    y = height - 18 * mm
    if title:
        pdf.setFont(font, 14)
        pdf.drawString(15 * mm, y, title)
        y -= 10 * mm
    pdf.setFont(font, 9)
    for line in lines:
        if y < 15 * mm:
            pdf.showPage()
            pdf.setFont(font, 9)
            y = height - 15 * mm
        pdf.drawString(15 * mm, y, str(line)[:125])
        y -= 5 * mm


def create_manifest_pdf(manifest, shipment_id=""):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    lines = []
    if shipment_id:
        lines.append(f"Отгрузка Lamoda: {shipment_id}")
    for cargo in manifest:
        lines.extend([
            "",
            f"Грузовое место №{cargo['local_number']} · Lamoda palletId: {cargo.get('pallet_id') or '—'}",
        ])
        for pack in cargo["packs"]:
            lines.append(
                f"  {pack['pack_number']} · заказ {pack['order_id']} · item {pack['item_id']} · "
                f"{pack.get('product_name') or 'без названия'} · {pack.get('size') or '—'} · {pack.get('sku') or '—'}"
            )
    _draw_lines(pdf, lines, title="Состав грузовых мест Lamoda FBS")
    pdf.save()
    return output.getvalue()


EXPORT_HEADERS = [
    "Партия", "Отгрузка", "Дата", "Заказ", "itemId", "packNumber",
    "Товар", "Размер", "SKU", "GTIN", "КИЗ",
]
REINTRO_EXTRA_HEADERS = [
    "Дата вывода", "Дата приёмки", "Состояние", "Причина брака",
    "returnItemId", "Статус возврата",
]


def create_marking_xlsx(rows, batch_type):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Коды Lamoda"
    headers = EXPORT_HEADERS + (REINTRO_EXTRA_HEADERS if batch_type == "REINTRODUCTION" else [])
    sheet.append(headers)
    for row in rows:
        values = [
            row.get("batch_id"), row.get("shipment_id"), row.get("date"), row.get("order_id"),
            row.get("item_id"), row.get("pack_number"), row.get("product_name"), row.get("size"),
            row.get("sku"), row.get("gtin"), row.get("raw_code"),
        ]
        if batch_type == "REINTRODUCTION":
            values.extend([
                row.get("withdrawn_at"), row.get("return_received_at"), row.get("condition"),
                row.get("defect_reason"), row.get("return_item_id"), row.get("return_status"),
            ])
        sheet.append(values)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def create_marking_pdf(rows, batch_type):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    label = "Возврат в оборот" if batch_type == "REINTRODUCTION" else "Вывод из оборота"
    lines = []
    for index, row in enumerate(rows, 1):
        lines.extend([
            f"{index}. Заказ {row.get('order_id')} · pack {row.get('pack_number')} · item {row.get('item_id')}",
            f"   {row.get('product_name') or '—'} · размер {row.get('size') or '—'} · SKU {row.get('sku') or '—'}",
            f"   GTIN {row.get('gtin') or '—'}",
        ])
        raw_code = str(row.get("raw_code") or "—")
        for offset in range(0, len(raw_code), 100):
            lines.append(("   КИЗ: " if offset == 0 else "        ") + raw_code[offset:offset + 100])
    _draw_lines(pdf, lines, title=f"Lamoda · {label} · партия №{rows[0].get('batch_id') if rows else '—'}")
    pdf.save()
    return output.getvalue()
