"""Create an employee KPI export from the active payroll period on production."""

import csv
from collections import defaultdict
from datetime import datetime
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import subprocess

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_HOST = "82.22.6.43"
DB_USER = "hmmls_bot"
DB_NAME = "hmmls_warehouse"
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
TITLE_FILL = PatternFill("solid", fgColor="D9EAF7")
CURRENCY_FORMAT = '#,##0.00 [$₽-419]'


def sql_rows(query, password):
    command = (
        f"PGPASSWORD={shlex.quote(password)} "
        f"psql -h localhost -U {DB_USER} -d {DB_NAME} --csv -c {shlex.quote(query)}"
    )
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", f"root@{PRODUCTION_HOST}", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return list(csv.DictReader(StringIO(result.stdout)))


def date_value(value):
    return datetime.strptime(value, "%d.%m.%Y")


def number(value):
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


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
    password = os.environ.get("PAYROLL_PRODUCTION_DB_PASSWORD")
    if not password:
        raise RuntimeError("Укажите пароль в PAYROLL_PRODUCTION_DB_PASSWORD.")

    periods = sql_rows(
        "select name, start_date, end_date, payment_mode from payroll_periods "
        "where lower(status) = 'active' order by row_number desc limit 1",
        password,
    )
    if not periods:
        raise RuntimeError("На production не найден активный расчётный период.")
    period = periods[0]
    start_date, end_date = period["start_date"], period["end_date"]
    start_sql, end_sql = date_value(start_date).strftime("%Y-%m-%d"), date_value(end_date).strftime("%Y-%m-%d")

    employees = sql_rows(
        "select employee_id, full_name from payroll_employees "
        "where lower(coalesce(is_active, 'true')) in ('true', '1', 'yes') order by full_name",
        password,
    )
    reports = sql_rows(
        "select employee_id, full_name, report_date, worked_hours, kpi_data, kpi_sum "
        "from payroll_reports where to_date(report_date, 'DD.MM.YYYY') "
        f"between date '{start_sql}' and date '{end_sql}' "
        "order by to_date(report_date, 'DD.MM.YYYY'), full_name",
        password,
    )

    employee_names = {row["employee_id"]: row["full_name"] for row in employees}
    totals = defaultdict(lambda: {"shifts": 0, "hours": 0.0, "kpi": 0.0})
    details = []
    for report in reports:
        employee_id = report["employee_id"]
        employee_names.setdefault(employee_id, report["full_name"])
        total = totals[employee_id]
        total["shifts"] += 1
        total["hours"] += number(report["worked_hours"])
        try:
            items = json.loads(report["kpi_data"] or "[]")
        except json.JSONDecodeError:
            items = []
        report_kpi_sum = 0.0
        for item in items:
            qty, rate = number(item.get("qty")), number(item.get("rate"))
            amount = number(item.get("sum")) or qty * rate
            report_kpi_sum += amount
            details.append([
                employee_names[employee_id], report["report_date"], item.get("kpi_id", ""),
                item.get("name", ""), qty, rate, amount,
            ])
        total["kpi"] += report_kpi_sum if items else number(report["kpi_sum"])

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Свод по сотрудникам"
    summary.append(["Выгрузка по сотрудникам: смены, часы и KPI", "", "", "", "", ""])
    summary.append([f"Production · период: {start_date} — {end_date}", "", "", "", "", ""])
    summary.append([f"Название периода: {period['name']}; режим оплаты: {period['payment_mode']}", "", "", "", "", ""])
    summary.append([])
    summary.append(["№", "Сотрудник", "Количество смен", "Количество часов", "Среднее часов на смену", "Начислено по KPI, ₽"])
    for row in summary.iter_rows(min_row=1, max_row=3):
        for cell in row:
            cell.fill = TITLE_FILL
    summary["A1"].font = Font(bold=True, size=14)

    for index, (employee_id, name) in enumerate(sorted(employee_names.items(), key=lambda item: item[1]), start=1):
        total = totals[employee_id]
        average = total["hours"] / total["shifts"] if total["shifts"] else 0
        summary.append([index, name, total["shifts"], total["hours"], average, total["kpi"]])
        summary.cell(summary.max_row, 6).number_format = CURRENCY_FORMAT
    last_data_row = summary.max_row
    summary.append(["", "ИТОГО", f"=SUM(C6:C{last_data_row})", f"=SUM(D6:D{last_data_row})", "", f"=SUM(F6:F{last_data_row})"])
    for cell in summary[summary.max_row]:
        cell.font = Font(bold=True)
        cell.fill = TITLE_FILL
    summary.cell(summary.max_row, 6).number_format = CURRENCY_FORMAT
    style_sheet(summary, 5, [6, 30, 18, 18, 25, 23])

    detail_sheet = workbook.create_sheet("Расчёт KPI")
    detail_sheet.append(["Детализация KPI по ежедневным отчётам", "", "", "", "", "", ""])
    detail_sheet.append([f"Production · период: {start_date} — {end_date}", "", "", "", "", "", ""])
    detail_sheet.append([])
    detail_sheet.append(["Сотрудник", "Дата отчёта", "ID KPI", "KPI", "Количество", "Ставка, ₽", "Начислено, ₽"])
    for row in detail_sheet.iter_rows(min_row=1, max_row=2):
        for cell in row:
            cell.fill = TITLE_FILL
    detail_sheet["A1"].font = Font(bold=True, size=14)
    for row in sorted(details, key=lambda item: (item[0], date_value(item[1]), item[3])):
        detail_sheet.append(row)
        detail_sheet.cell(detail_sheet.max_row, 6).number_format = CURRENCY_FORMAT
        detail_sheet.cell(detail_sheet.max_row, 7).number_format = CURRENCY_FORMAT
    style_sheet(detail_sheet, 4, [30, 16, 18, 35, 14, 16, 18])

    output_dir = PROJECT_ROOT / "reports"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"Выгрузка_сотрудники_KPI_production_{start_date}-{end_date}.xlsx"
    workbook.save(output_path)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
