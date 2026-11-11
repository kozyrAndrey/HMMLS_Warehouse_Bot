from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


HEADERS = [
    "Дата и время сборки",
    "Номер заказа",
    "Тип отправления",
    "Ответственный сборщик",
    "Оформил в боте",
    "Состав заказа",
    "Количество товаров",
    "Маркируемых единиц",
    "GTIN",
    "Коды Честного знака",
    "Отгрузка МойСклад",
]


def shipping_type_label(value):
    return "СДЭК" if value == "cdek" else "Самовывоз"


def create_shipping_xlsx(records):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Отправления"
    worksheet.append(HEADERS)
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for record in records:
        snapshot = list(record.get("order_snapshot") or [])
        codes = list(record.get("marking_codes") or [])
        composition = "\n".join(
            f"{item.get('name', 'Без названия')} — {item.get('quantity', 0)} шт."
            + (f" (GTIN {item['gtin']})" if item.get("gtin") else "")
            for item in snapshot
        )
        gtins = "\n".join(dict.fromkeys(str(code.get("gtin") or "") for code in codes if code.get("gtin")))
        code_lines = "\n".join(
            f"{code.get('product_name') or code.get('name') or 'Товар'}: {code.get('raw_code') or code.get('short_code') or ''}"
            for code in codes
        )
        assembled_at = record.get("assembled_at")
        worksheet.append([
            assembled_at.strftime("%d.%m.%Y %H:%M:%S") if hasattr(assembled_at, "strftime") else str(assembled_at or ""),
            record.get("order_number", ""),
            shipping_type_label(record.get("shipping_type")),
            record.get("collector_name", ""),
            record.get("created_by_name", ""),
            composition,
            sum(int(item.get("quantity") or 0) for item in snapshot),
            len(codes),
            gtins,
            code_lines,
            record.get("moysklad_demand_name") or record.get("moysklad_demand_id") or "",
        ])
        for cell in worksheet[worksheet.max_row]:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    widths = [21, 20, 17, 28, 28, 60, 18, 22, 20, 75, 22]
    for column, width in zip(worksheet.iter_cols(min_row=1, max_row=1), widths):
        worksheet.column_dimensions[column[0].column_letter].width = width
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
