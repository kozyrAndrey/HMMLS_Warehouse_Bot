from collections import defaultdict

from payroll_google_sheets import (
    get_active_period,
    get_employees,
    get_expenses_in_period,
    get_penalties_in_period,
    get_reports_in_period,
    money,
)


def calculate_payroll_for_period(start_date, end_date):
    employees = {employee["employee_id"]: employee for employee in get_employees()}
    reports = get_reports_in_period(start_date, end_date)
    expenses = get_expenses_in_period(start_date, end_date)
    penalties = get_penalties_in_period(start_date, end_date)

    totals = {}

    for employee_id, employee in employees.items():
        totals[employee_id] = {
            "employee": employee,
            "hours": 0.0,
            "hourly_rate": employee["hourly_rate"],
            "hourly_pay": 0.0,
            "kpi_sum": 0.0,
            "fixed_half": employee["fixed_salary"] / 2,
            "expenses": 0.0,
            "penalties": 0.0,
            "salary_without_expenses": 0.0,
            "salary_with_expenses": 0.0,
            "reports_count": 0,
        }

    for report in reports:
        employee_id = report["employee"]["employee_id"]
        if employee_id not in totals:
            continue
        totals[employee_id]["hours"] += report["hours"]
        totals[employee_id]["kpi_sum"] += report["kpi_sum"]
        totals[employee_id]["reports_count"] += 1

    for expense in expenses:
        employee_id = expense["employee_id"]
        if employee_id in totals:
            totals[employee_id]["expenses"] += expense["amount"]

    for penalty in penalties:
        employee_id = penalty["employee_id"]
        if employee_id in totals:
            totals[employee_id]["penalties"] += penalty["amount"]

    for item in totals.values():
        item["hourly_pay"] = item["hours"] * item["hourly_rate"]
        item["salary_without_expenses"] = (
            item["hourly_pay"]
            + item["kpi_sum"]
            + item["fixed_half"]
            - item["penalties"]
        )
        item["salary_with_expenses"] = item["salary_without_expenses"] + item["expenses"]

    return totals


def format_employee_salary_block(item):
    employee = item["employee"]
    return "\n".join(
        [
            f"{employee['full_name']}",
            f"Часы: {money(item['hours'])}",
            f"Ставка: {money(item['hourly_rate'])}",
            f"Почасовая ЗП: {money(item['hourly_pay'])}",
            f"KPI: {money(item['kpi_sum'])}",
            f"Оклад / 2: {money(item['fixed_half'])}",
            f"Штрафы: {money(item['penalties'])}",
            f"ЗП без расходов: {money(item['salary_without_expenses'])}",
            f"Расходы: {money(item['expenses'])}",
            f"ЗП с расходами: {money(item['salary_with_expenses'])}",
        ]
    )


def build_personal_salary_text(employee, period=None):
    period = period or get_active_period()
    if not period:
        return "Активный расчетный период не настроен. Обратитесь к руководителю."

    totals = calculate_payroll_for_period(period["start_date"], period["end_date"])
    item = totals.get(employee["employee_id"])

    if not item:
        return "Данные по сотруднику не найдены."

    return "\n\n".join(
        [
            f"💰 ЗП за период: {period['name']}",
            f"Период: {period['start_date']} — {period['end_date']}",
            format_employee_salary_block(item),
        ]
    )


def build_full_payroll_text(period=None):
    period = period or get_active_period()
    if not period:
        return "Активный расчетный период не настроен."

    totals = calculate_payroll_for_period(period["start_date"], period["end_date"])

    managers = []
    warehouse = []

    for item in totals.values():
        employee = item["employee"]
        if employee.get("include_in_common_fund"):
            warehouse.append(item)
        else:
            managers.append(item)

    lines = [
        f"💰 Расчет ЗП за период: {period['name']}",
        f"Период: {period['start_date']} — {period['end_date']}",
    ]

    if managers:
        lines.append("\nРуководитель склада:")
        for item in managers:
            lines.append("\n" + format_employee_salary_block(item))

    warehouse_total_without_expenses = 0.0
    warehouse_total_with_expenses = 0.0

    if warehouse:
        lines.append("\nСклад:")
        for item in warehouse:
            warehouse_total_without_expenses += item["salary_without_expenses"]
            warehouse_total_with_expenses += item["salary_with_expenses"]
            lines.append("\n" + format_employee_salary_block(item))

    lines.extend(
        [
            "",
            f"Общий фонд склада без расходов: {money(warehouse_total_without_expenses)}",
            f"Общий фонд склада с расходами: {money(warehouse_total_with_expenses)}",
        ]
    )

    return "\n".join(lines)
