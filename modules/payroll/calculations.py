from modules.payroll.config import (
    PENALTY_BONUS_EMPLOYEE_ID,
    PENALTY_BONUS_RATE,
    SALARY_FIXED_PARTS,
)
from modules.payroll.google_sheets import (
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
        fixed_parts = get_salary_fixed_parts(employee)
        fixed_half = sum(part["amount"] for part in fixed_parts)

        totals[employee_id] = {
            "employee": employee,
            "hours": 0.0,
            "hourly_rate": employee["hourly_rate"],
            "hourly_pay": 0.0,
            "kpi_sum": 0.0,
            "warehouse_gross": 0.0,
            "fixed_parts": fixed_parts,
            "fixed_half": fixed_half,
            "expenses": 0.0,
            "penalties": 0.0,
            "penalty_bonus": 0.0,
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

    penalty_bonus_base = sum(
        penalty["amount"]
        for penalty in penalties
        if penalty["employee_id"] != PENALTY_BONUS_EMPLOYEE_ID
    )
    if PENALTY_BONUS_EMPLOYEE_ID in totals:
        totals[PENALTY_BONUS_EMPLOYEE_ID]["penalty_bonus"] = penalty_bonus_base * PENALTY_BONUS_RATE

    for item in totals.values():
        item["hourly_pay"] = item["hours"] * item["hourly_rate"]
        item["warehouse_gross"] = item["hourly_pay"] + item["kpi_sum"]
        item["salary_without_expenses"] = (
            item["warehouse_gross"]
            + item["fixed_half"]
            + item["penalty_bonus"]
            - item["penalties"]
        )
        item["salary_with_expenses"] = item["salary_without_expenses"] + item["expenses"]

    return totals


def get_salary_fixed_parts(employee):
    employee_id = employee["employee_id"]

    if employee_id in SALARY_FIXED_PARTS:
        return [
            {
                "label": part["label"],
                "amount": float(part.get("amount", 0) or 0),
            }
            for part in SALARY_FIXED_PARTS[employee_id]
        ]

    fixed_half = float(employee.get("fixed_salary", 0) or 0) / 2

    if fixed_half <= 0:
        return []

    return [
        {
            "label": "оклад",
            "amount": fixed_half,
        }
    ]


def money_pretty(value):
    value = float(value or 0)
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def short_date(value):
    parts = str(value).split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return str(value)


def format_employee_salary_block(item):
    employee = item["employee"]
    lines = [
        f"{employee['full_name']}",
        f"Часы: {money(item['hours'])}",
        f"Ставка: {money(item['hourly_rate'])}",
        f"Почасовая ЗП: {money(item['hourly_pay'])}",
        f"KPI: {money(item['kpi_sum'])}",
        f"Оклад / 2: {money(item['fixed_half'])}",
        f"Штрафы: {money(item['penalties'])}",
    ]

    if item["penalty_bonus"]:
        lines.append(f"Бонус от штрафов: {money(item['penalty_bonus'])}")

    lines.extend(
        [
            f"ЗП без расходов: {money(item['salary_without_expenses'])}",
            f"Расходы: {money(item['expenses'])}",
            f"ЗП с расходами: {money(item['salary_with_expenses'])}",
        ]
    )

    return "\n".join(lines)


def build_personal_salary_text(employee, period=None):
    period = period or get_active_period()
    if not period:
        return "Активный расчетный период не настроен. Обратитесь к руководителю."

    totals = calculate_payroll_for_period(period["start_date"], period["end_date"])
    item = totals.get(employee["employee_id"])

    if not item:
        return "Данные по сотруднику не найдены."

    lines = [
        f"💰 ЗП за период: {period['start_date']} — {period['end_date']}",
        "",
        employee["full_name"],
        f"Штрафы: {money(item['penalties'])}",
    ]

    if item["penalty_bonus"]:
        lines.append(f"Бонус от штрафов: {money(item['penalty_bonus'])}")

    lines.extend(
        [
            f"ЗП без расходов: {money(item['salary_without_expenses'])}",
            f"Расходы: {money(item['expenses'])}",
            f"ЗП с расходами: {money(item['salary_with_expenses'])}",
        ]
    )

    return "\n".join(lines)


def format_fixed_parts(parts):
    result = []
    for part in parts:
        amount = float(part.get("amount", 0) or 0)
        if amount:
            result.append(f"{money_pretty(amount)} ({part['label']})")
    return result


def format_payroll_statement_line(item):
    employee = item["employee"]
    penalties = item["penalties"]
    expenses = item["expenses"]
    warehouse_after_penalties = item["warehouse_gross"] - penalties

    parts = [f"{money_pretty(warehouse_after_penalties)} (склад"]

    if penalties:
        parts[0] += f" - {money_pretty(penalties)} штрафы"

    parts[0] += ")"

    parts.extend(format_fixed_parts(item.get("fixed_parts", [])))

    penalty_bonus = item.get("penalty_bonus", 0)
    if penalty_bonus:
        parts.append(f"{money_pretty(penalty_bonus)} (40% штрафов)")

    if expenses:
        parts.append(f"{money_pretty(expenses)} (расходы)")
    else:
        parts.append(f"{money_pretty(0)} (расходы)")

    return f"{employee['full_name']}: " + " + ".join(parts) + f" = {money_pretty(item['salary_with_expenses'])}"


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

    lines = []

    if managers:
        lines.append("Руководитель склада:")
        for item in managers:
            lines.append(format_payroll_statement_line(item))
        lines.append("")

    lines.append("зарплаты склада + расходы + штрафы")
    lines.append(f"с {short_date(period['start_date'])} по {short_date(period['end_date'])}")

    warehouse_total = 0.0

    for item in warehouse:
        warehouse_total += item["salary_with_expenses"]
        lines.append(format_payroll_statement_line(item))
        lines.append("")

    lines.append(f"ОБЩИЙ ИТОГ: {money_pretty(warehouse_total)}")

    return "\n".join(lines).strip()
