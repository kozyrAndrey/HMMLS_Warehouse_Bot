from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


HEADERS = [
    "Дата и время сборки",
    "Номер заказа",
    "Тип отправления",
    "Ответственный сборщик",
    "Оформил в боте",
    "Название изделия",
    "Количество",
    "GTIN",
    "Количество кодов ЧЗ",
    "Полный код маркировки",
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
        assembled_at = record.get("assembled_at")
        for item in snapshot:
            position_id = str(item.get("position_id") or "")
            assortment_id = str(item.get("assortment_id") or "")
            item_name = str(item.get("name") or "Без названия")
            item_gtin = str(item.get("gtin") or "")
            matching_codes = [
                code for code in codes
                if (
                    position_id
                    and str(code.get("position_id") or "") == position_id
                ) or (
                    not position_id
                    and assortment_id
                    and str(code.get("assortment_id") or "") == assortment_id
                ) or (
                    not position_id
                    and not assortment_id
                    and str(code.get("product_name") or code.get("name") or "") == item_name
                    and str(code.get("gtin") or "") == item_gtin
                )
            ]
            full_codes = "\n".join(
                str(code.get("raw_code") or code.get("short_code") or "")
                for code in matching_codes
            )
            worksheet.append([
                assembled_at.strftime("%d.%m.%Y %H:%M:%S") if hasattr(assembled_at, "strftime") else str(assembled_at or ""),
                record.get("order_number", ""),
                shipping_type_label(record.get("shipping_type")),
                record.get("collector_name", ""),
                record.get("created_by_name", ""),
                item_name,
                int(item.get("quantity") or 0),
                item_gtin,
                len(matching_codes),
                full_codes,
                record.get("moysklad_demand_name") or record.get("moysklad_demand_id") or "",
            ])
            for cell in worksheet[worksheet.max_row]:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            worksheet.row_dimensions[worksheet.max_row].height = max(18, 15 * max(1, len(matching_codes)))

    widths = [21, 20, 17, 28, 28, 42, 14, 20, 20, 75, 22]
    for column, width in zip(worksheet.iter_cols(min_row=1, max_row=1), widths):
        worksheet.column_dimensions[column[0].column_letter].width = width
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
