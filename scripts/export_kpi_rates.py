"""Export the current KPI rates from the payroll database to an Excel file."""

from datetime import date
from pathlib import Path
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.payroll.google_sheets import get_kpi_items


def main():
    items = get_kpi_items(active_only=False)
    output_dir = PROJECT_ROOT / "reports"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"Выгрузка_ставок_KPI_{date.today():%Y-%m-%d}.xlsx"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ставки KPI"
    sheet.append(["Выгрузка ставок KPI", "", "", ""])
    sheet.append([f"Дата выгрузки: {date.today():%d.%m.%Y}", "", "", ""])
    sheet.append([])
    sheet.append(["№", "ID KPI", "Название", "Ставка, ₽ за единицу", "Статус"])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    title_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in sheet[1]:
        cell.font = Font(bold=True, size=14)
        cell.fill = title_fill
    for cell in sheet[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for number, item in enumerate(items, start=1):
        status = "Активен" if item["is_active"] else "Неактивен"
        sheet.append([number, item["kpi_id"], item["name"], item["rate"], status])
        rate_cell = sheet.cell(sheet.max_row, 4)
        rate_cell.number_format = '#,##0.00 [$₽-419]'
        if not item["is_active"]:
            for cell in sheet[sheet.max_row]:
                cell.font = Font(color="808080")

    sheet.freeze_panes = "A5"
    sheet.auto_filter.ref = f"A4:E{sheet.max_row}"
    widths = [6, 20, 38, 24, 14]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    workbook.save(output_path)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
