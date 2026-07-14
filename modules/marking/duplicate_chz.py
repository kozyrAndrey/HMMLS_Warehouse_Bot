import re
from pathlib import Path


GROUP_SEPARATOR = "\x1d"


class DuplicateChzError(RuntimeError):
    pass


def normalize_chz_text(value):
    text = str(value or "").strip()
    replacements = {
        "\\x1d": GROUP_SEPARATOR,
        "\\u001d": GROUP_SEPARATOR,
        "<GS>": GROUP_SEPARATOR,
        "[GS]": GROUP_SEPARATOR,
        "{GS}": GROUP_SEPARATOR,
        "␝": GROUP_SEPARATOR,
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text


def has_ai_parentheses(value):
    return bool(re.search(r"\(\d{2,4}\)", value or ""))


def to_bwipp_gs1_data(raw_code):
    code = normalize_chz_text(raw_code)
    if not code:
        raise DuplicateChzError("Код ЧЗ пустой.")

    if has_ai_parentheses(code):
        return code

    if not code.startswith("01") or len(code) < 18:
        raise DuplicateChzError(
            "Не удалось распознать GS1-структуру. Пришлите полный код в формате (01)...(21)...(91)...(92)..."
        )

    gtin = code[2:16]
    tail = code[16:]
    if not gtin.isdigit() or not tail.startswith("21"):
        raise DuplicateChzError(
            "Не удалось распознать GTIN и серийный номер. Пришлите код с AI в скобках: (01)...(21)..."
        )

    return "(01)" + gtin + _parse_variable_ai_tail(tail)


def extract_gs1_ai_values(raw_code):
    code = normalize_chz_text(raw_code)
    if not code:
        return {}

    if has_ai_parentheses(code):
        return dict(re.findall(r"\((\d{2,4})\)([^()]*)", code))

    if code.startswith("01") and len(code) >= 18:
        values = {"01": code[2:16]}
        tail = code[16:]
        for ai, value in re.findall(r"(21|91|92)(.*?)(?=91|92|$)", tail):
            values[ai] = value.strip(GROUP_SEPARATOR)
        return values

    return {}


def extract_gtin(raw_code):
    return extract_gs1_ai_values(raw_code).get("01", "")


def _parse_variable_ai_tail(tail):
    parts = []
    rest = tail

    while rest:
        if len(rest) < 2 or not rest[:2].isdigit():
            raise DuplicateChzError("Не удалось распознать AI в хвосте кода ЧЗ.")

        ai = rest[:2]
        rest = rest[2:]

        separator_index = rest.find(GROUP_SEPARATOR)
        if separator_index >= 0:
            value = rest[:separator_index]
            rest = rest[separator_index + 1:]
        elif ai == "21" and "91" in rest:
            marker = rest.find("91", 1)
            value = rest[:marker]
            rest = rest[marker:]
        elif ai == "91" and "92" in rest:
            marker = rest.find("92", 1)
            value = rest[:marker]
            rest = rest[marker:]
        else:
            value = rest
            rest = ""

        if not value:
            raise DuplicateChzError(f"AI {ai} без значения.")
        parts.append(f"({ai}){value}")

    return "".join(parts)


def create_duplicate_chz_pdf(raw_code, output_path, product_info=None):
    try:
        import treepoem
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as error:
        raise DuplicateChzError(
            "Не установлены библиотеки для генерации PDF/GS1 DataMatrix. Установите зависимости из requirements.txt."
        ) from error

    gs1_data = to_bwipp_gs1_data(raw_code)
    output_path = Path(output_path)

    try:
        barcode = treepoem.generate_barcode(
            barcode_type="gs1datamatrix",
            data=gs1_data,
            options={"parsefnc": True},
        )
        barcode = barcode.convert("RGB")
    except Exception as error:
        details = str(error)
        if "GS1badChecksum" in details or "Bad checksum" in details:
            raise DuplicateChzError(
                "Не удалось сгенерировать GS1 DataMatrix: в GTIN неверная контрольная цифра."
            ) from error
        raise DuplicateChzError(
            "Не удалось сгенерировать GS1 DataMatrix. Проверьте формат полного кода ЧЗ и наличие Ghostscript."
        ) from error

    image_path = output_path.with_suffix(".png")
    barcode.save(image_path)

    page_width, page_height = 58 * mm, 40 * mm
    qr_size = 27 * mm
    qr_x = 3 * mm
    qr_y = 7 * mm
    details_x = 32 * mm
    details_y = page_height - 7 * mm
    details_width = page_width - details_x - 2 * mm

    pdf = canvas.Canvas(str(output_path), pagesize=(page_width, page_height))
    pdf.setTitle("Дубликат ЧЗ")
    pdf.setFillColor(colors.black)
    pdf.drawImage(str(image_path), qr_x, qr_y, width=qr_size, height=qr_size, preserveAspectRatio=True, mask="auto")
    font_name = register_label_font(pdfmetrics, TTFont)
    draw_product_details(pdf, product_info or {}, short_code_text(raw_code), details_x, details_y, details_width, mm, font_name)
    pdf.showPage()
    pdf.save()

    try:
        image_path.unlink()
    except OSError:
        pass

    return output_path


def short_code_text(raw_code, limit=31):
    return normalize_chz_text(raw_code).replace(GROUP_SEPARATOR, "<GS>")[:limit]


def register_label_font(pdfmetrics, tt_font):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Unicode Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]

    for font_path in candidates:
        if Path(font_path).exists():
            pdfmetrics.registerFont(tt_font("MarkingLabelFont", font_path))
            return "MarkingLabelFont"
    return "Helvetica-Bold"


def draw_product_details(pdf, product_info, short_code, x, y, width, mm, font_name):
    lines = [
        str(product_info.get("model_name") or "").strip(),
        f"Размер: {str(product_info.get('size') or '').strip()}",
        f"Страна производства: {str(product_info.get('country') or '').strip()}",
        short_code,
    ]

    pdf.setFont(font_name, 5.2)
    line_height = 3.4 * mm
    current_y = y
    for index, line in enumerate(lines):
        wrapped = wrap_label_text(line, width, pdf)
        if index > 0:
            current_y -= 0.5 * mm
        for part in wrapped:
            pdf.drawString(x, current_y, part)
            current_y -= line_height


def wrap_label_text(value, width, pdf):
    words = str(value or "").split()
    if not words:
        return [""]

    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or pdf.stringWidth(candidate) <= width:
            current = candidate
            continue
        lines.extend(split_oversized_word(current, width, pdf))
        current = word

    if current:
        lines.extend(split_oversized_word(current, width, pdf))
    return lines


def split_oversized_word(value, width, pdf):
    if pdf.stringWidth(value) <= width:
        return [value]

    result = []
    current = ""
    for char in value:
        candidate = current + char
        if current and pdf.stringWidth(candidate) > width:
            result.append(current)
            current = char
        else:
            current = candidate
    if current:
        result.append(current)
    return result
