"""Export employee shifts, hours and KPI calculations for the active payroll period."""

from collections import defaultdict
from pathlib import Path
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.payroll.google_sheets import get_active_period, get_employees, get_reports_in_period


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
TITLE_FILL = PatternFill("solid", fgColor="D9EAF7")
CURRENCY_FORMAT = '#,##0.00 [$₽-419]'


def style_sheet(sheet, header_row, widths):
    for cell in sheet[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(widths))}{sheet.max_row}"
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width


def main():
    period = get_active_period()
    if not period:
        raise RuntimeError("В базе не настроен активный расчётный период.")

    reports = get_reports_in_period(period["start_date"], period["end_date"])
    employees = {item["employee_id"]: item for item in get_employees() if item["is_active"]}
    totals = defaultdict(lambda: {"shifts": 0, "hours": 0.0, "kpi": 0.0})
    kpi_rows = []

    for report in reports:
        employee = report["employee"]
        employee_id = employee["employee_id"]
        employees.setdefault(employee_id, employee)
        total = totals[employee_id]
        total["shifts"] += 1
        total["hours"] += float(report["hours"] or 0)
        total["kpi"] += float(report["kpi_sum"] or 0)
        for item in report["kpi_items"]:
            qty = float(item.get("qty", 0) or 0)
            rate = float(item.get("rate", 0) or 0)
            kpi_rows.append([
                employee["full_name"], report["date"], item.get("kpi_id", ""),
                item.get("name", ""), qty, rate, float(item.get("sum", qty * rate) or 0),
            ])

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Свод по сотрудникам"
    summary.append(["Выгрузка по сотрудникам: смены, часы и KPI", "", "", "", "", ""])
    summary.append([f"Расчётный период: {period['start_date']} — {period['end_date']}", "", "", "", "", ""])
    summary.append([f"Режим оплаты: {period.get('payment_mode', '')}; период: {period.get('name', '')}", "", "", "", "", ""])
    summary.append([])
    summary.append(["№", "Сотрудник", "Количество смен", "Количество часов", "Среднее часов на смену", "Начислено по KPI, ₽"])
    for row in summary.iter_rows(min_row=1, max_row=3):
        for cell in row:
            cell.fill = TITLE_FILL
    summary["A1"].font = Font(bold=True, size=14)

    for number, employee in enumerate(sorted(employees.values(), key=lambda item: item["full_name"]), start=1):
        total = totals[employee["employee_id"]]
        average = total["hours"] / total["shifts"] if total["shifts"] else 0
        summary.append([number, employee["full_name"], total["shifts"], total["hours"], average, total["kpi"]])
        summary.cell(summary.max_row, 6).number_format = CURRENCY_FORMAT

    summary.append(["", "ИТОГО", f"=SUM(C6:C{summary.max_row})", f"=SUM(D6:D{summary.max_row})", "", f"=SUM(F6:F{summary.max_row})"])
    summary.cell(summary.max_row, 6).number_format = CURRENCY_FORMAT
    for cell in summary[summary.max_row]:
        cell.font = Font(bold=True)
        cell.fill = TITLE_FILL
    style_sheet(summary, 5, [6, 28, 18, 18, 25, 23])

    details = workbook.create_sheet("Расчёт KPI")
    details.append(["Детализация KPI по сданным ежедневным отчётам", "", "", "", "", "", ""])
    details.append([f"Расчётный период: {period['start_date']} — {period['end_date']}", "", "", "", "", "", ""])
    details.append([])
    details.append(["Сотрудник", "Дата отчёта", "ID KPI", "KPI", "Количество", "Ставка, ₽", "Начислено, ₽"])
    for row in details.iter_rows(min_row=1, max_row=2):
        for cell in row:
            cell.fill = TITLE_FILL
    details["A1"].font = Font(bold=True, size=14)
    for row in sorted(kpi_rows, key=lambda item: (item[0], item[1], item[3])):
        details.append(row)
        details.cell(details.max_row, 6).number_format = CURRENCY_FORMAT
        details.cell(details.max_row, 7).number_format = CURRENCY_FORMAT
    style_sheet(details, 4, [28, 16, 18, 35, 14, 16, 18])

    output_dir = PROJECT_ROOT / "reports"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"Выгрузка_сотрудники_KPI_{period['start_date']}-{period['end_date']}.xlsx"
    workbook.save(output_path)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
