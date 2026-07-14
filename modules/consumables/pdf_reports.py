from pathlib import Path
import tempfile

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from modules.consumables.storage import format_quantity


def register_consumables_font():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for font_path in candidates:
        if Path(font_path).exists():
            pdfmetrics.registerFont(TTFont("ConsumablesFont", font_path))
            return "ConsumablesFont"
    return "Helvetica"


def create_inventory_count_pdf(records, counted_by_name="", filename="consumables_inventory.pdf"):
    font_name = register_consumables_font()
    output_path = Path(tempfile.gettempdir()) / filename
    page_width, page_height = A4
    margin_x = 36
    margin_y = 36
    line_height = 14

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    pdf.setFont(font_name, 11)
    y = page_height - margin_y

    title = "Пересчет расходников"
    if counted_by_name:
        title += f" - {counted_by_name}"
    pdf.drawString(margin_x, y, title)
    y -= line_height * 2

    pdf.setFont(font_name, 9)
    for index, record in enumerate(records, start=1):
        diff = float(record["difference"] or 0)
        sign = "+" if diff > 0 else ""
        line = (
            f"{index}. {record['item_name']} | "
            f"Система: {format_quantity(record['system_quantity'])} {record['unit']} | "
            f"Факт: {format_quantity(record['counted_quantity'])} {record['unit']} | "
            f"Разница: {sign}{format_quantity(diff)}"
        )
        for chunk in wrap_pdf_line(line, 125):
            if y < margin_y:
                pdf.showPage()
                pdf.setFont(font_name, 9)
                y = page_height - margin_y
            pdf.drawString(margin_x, y, chunk)
            y -= line_height

    pdf.save()
    return output_path


def wrap_pdf_line(line, max_chars):
    chunks = []
    current = str(line)
    while len(current) > max_chars:
        chunks.append(current[:max_chars])
        current = current[max_chars:]
    chunks.append(current)
    return chunks
