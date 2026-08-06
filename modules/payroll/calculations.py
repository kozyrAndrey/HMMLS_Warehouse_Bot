from modules.payroll.config import (
    PENALTY_BONUS_EMPLOYEE_ID,
    PENALTY_BONUS_RATE,
    SALARY_FIXED_PARTS,
)
from modules.payroll.google_sheets import (
    get_active_period,
    get_bonuses_in_period,
    get_employees,
    get_expenses_in_period,
    get_penalties_in_period,
    get_reports_in_period,
    money,
    normalize_payment_mode,
    normalize_shift_type,
    paid_hours_for_report,
    PAYMENT_MODE_SHIFT,
    SHIFT_TYPE_HALF,
)
from modules.payroll.vacations import get_vacations_in_period, vacation_amount_for_period
from modules.payroll.additional_pay import get_additional_payments_in_period


def calculate_payroll_for_period(start_date, end_date, payment_mode="hourly"):
    payment_mode = normalize_payment_mode(payment_mode)
    employees = {employee["employee_id"]: employee for employee in get_employees()}
    reports = get_reports_in_period(start_date, end_date)
    expenses = get_expenses_in_period(start_date, end_date)
    penalties = get_penalties_in_period(start_date, end_date)
    bonuses = get_bonuses_in_period(start_date, end_date)
    additional_payments = get_additional_payments_in_period(start_date, end_date)
    vacations = get_vacations_in_period(start_date, end_date)

    totals = {}

    for employee_id, employee in employees.items():
        fixed_parts = get_salary_fixed_parts(employee)
        fixed_half = sum(part["amount"] for part in fixed_parts)

        totals[employee_id] = {
            "employee": employee,
            "hours": 0.0,
            "paid_hours": 0.0,
            "payment_mode": payment_mode,
            "hourly_rate": employee["hourly_rate"],
            "hourly_pay": 0.0,
            "kpi_sum": 0.0,
            "warehouse_gross": 0.0,
            "fixed_parts": fixed_parts,
            "fixed_half": fixed_half,
            "expenses": 0.0,
            "penalties": 0.0,
            "bonuses": 0.0,
            "additional_payments": [],
            "additional_pay_total": 0.0,
            "vacation_days": 0,
            "vacation_pay": 0.0,
            "vacations": [],
            "penalty_bonus": 0.0,
            "salary_without_expenses": 0.0,
            "salary_with_expenses": 0.0,
            "reports_count": 0,
            "full_shifts": 0,
            "half_shifts": 0,
        }

    for report in reports:
        employee_id = report["employee"]["employee_id"]
        if employee_id not in totals:
            continue
        totals[employee_id]["hours"] += report["hours"]
        totals[employee_id]["paid_hours"] += paid_hours_for_report(
            report["hours"],
            payment_mode,
            report.get("shift_type"),
        )
        if payment_mode == PAYMENT_MODE_SHIFT:
            if normalize_shift_type(report.get("shift_type")) == SHIFT_TYPE_HALF:
                totals[employee_id]["half_shifts"] += 1
            else:
                # Старые отчеты без типа смены сохраняют прежнюю оплату как полная смена.
                totals[employee_id]["full_shifts"] += 1
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

    for bonus in bonuses:
        employee_id = bonus["employee_id"]
        if employee_id in totals:
            totals[employee_id]["bonuses"] += bonus["amount"]

    for payment in additional_payments:
        employee_id = payment["employee_id"]
        if employee_id in totals:
            totals[employee_id]["additional_payments"].append(payment)
            totals[employee_id]["additional_pay_total"] += payment["total_amount"]

    for vacation in vacations:
        employee_id = vacation["employee_id"]
        if employee_id not in totals:
            continue
        days, amount = vacation_amount_for_period(vacation, start_date, end_date)
        if not days:
            continue
        totals[employee_id]["vacation_days"] += days
        totals[employee_id]["vacation_pay"] += amount
        totals[employee_id]["vacations"].append({**vacation, "period_days": days, "period_amount": amount})

    penalty_bonus_base = sum(
        penalty["amount"]
        for penalty in penalties
        if penalty["employee_id"] != PENALTY_BONUS_EMPLOYEE_ID
    )
    if PENALTY_BONUS_EMPLOYEE_ID in totals:
        totals[PENALTY_BONUS_EMPLOYEE_ID]["penalty_bonus"] = penalty_bonus_base * PENALTY_BONUS_RATE

    for item in totals.values():
        item["hourly_pay"] = item["paid_hours"] * item["hourly_rate"]
        item["warehouse_gross"] = item["hourly_pay"] + item["kpi_sum"]
        item["salary_without_expenses"] = (
            item["warehouse_gross"]
            + item["fixed_half"]
            + item["penalty_bonus"]
            + item["bonuses"]
            + item["additional_pay_total"]
            + item["vacation_pay"]
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


def format_vacation_details(vacations):
    lines = []
    for vacation in vacations:
        lines.append(
            "Отпуск: "
            f"{vacation['start_date']} — {vacation['end_date']} · "
            f"{vacation['period_days']} дн. · "
            f"ставка {money(vacation['hourly_rate'])} · "
            f"{money(vacation['period_amount'])}"
        )
    return lines


def format_employee_salary_block(item):
    employee = item["employee"]
    lines = [
        f"{employee['full_name']}",
        f"Часы: {money(item['hours'])}",
    ]

    if item.get("payment_mode") == PAYMENT_MODE_SHIFT:
        lines.append(f"Полных смен: {item['full_shifts']}")
        lines.append(f"Половин смен: {item['half_shifts']}")
        lines.append(f"Оплачиваемые часы: {money(item['paid_hours'])}")

    lines.extend(
        [
            f"Ставка: {money(item['hourly_rate'])}",
            f"Почасовая ЗП: {money(item['hourly_pay'])}",
            f"KPI: {money(item['kpi_sum'])}",
            f"Оклад / 2: {money(item['fixed_half'])}",
            f"Штрафы: {money(item['penalties'])}",
        ]
    )

    if item["bonuses"]:
        lines.append(f"Премиальные: {money(item['bonuses'])}")

    if item["additional_payments"]:
        lines.append(f"Доп. начисления: {money(item['additional_pay_total'])}")
        lines.extend(format_additional_pay_details(item["additional_payments"]))

    if item["vacation_pay"]:
        lines.append(f"Отпускные ({item['vacation_days']} дн.): {money(item['vacation_pay'])}")
        lines.extend(format_vacation_details(item["vacations"]))

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


def build_personal_salary_text(employee, period=None, show_bonus_details=False):
    period = period or get_active_period()
    if not period:
        return "Активный расчетный период не настроен. Обратитесь к руководителю."

    totals = calculate_payroll_for_period(
        period["start_date"],
        period["end_date"],
        period.get("payment_mode"),
    )
    item = totals.get(employee["employee_id"])

    if not item:
        return "Данные по сотруднику не найдены."

    lines = [
        f"💰 ЗП за период: {period['start_date']} — {period['end_date']}",
        "",
        employee["full_name"],
        f"Штрафы: {money(item['penalties'])}",
    ]

    if item.get("payment_mode") == PAYMENT_MODE_SHIFT:
        lines.extend(
            [
                f"Фактические часы: {money(item['hours'])}",
                f"Полных смен: {item['full_shifts']}",
                f"Половин смен: {item['half_shifts']}",
                f"Оплачиваемые часы: {money(item['paid_hours'])}",
                f"Ставка: {money(item['hourly_rate'])}",
                f"Оплата смен: {money(item['hourly_pay'])}",
            ]
        )

    if item["penalty_bonus"]:
        lines.append(f"Бонус от штрафов: {money(item['penalty_bonus'])}")

    if show_bonus_details and item["bonuses"]:
        lines.append(f"Премиальные: {money(item['bonuses'])}")

    if item["additional_payments"]:
        lines.append(f"Доп. начисления: {money(item['additional_pay_total'])}")
        lines.extend(format_additional_pay_details(item["additional_payments"]))

    if item["vacation_pay"]:
        lines.append(f"Отпускные ({item['vacation_days']} дн.): {money(item['vacation_pay'])}")
        lines.extend(format_vacation_details(item["vacations"]))

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


def format_additional_pay_details(payments):
    result = []
    for payment in payments:
        details = (
            f"{payment['position_name']}: {payment['quantity']} поставк., "
            f"{short_date(payment['week_start'])}–{short_date(payment['week_end'])}"
        )
        if payment.get("error_penalty"):
            details += f", штраф {money(payment['error_penalty'])}"
        result.append(f"Доп. начисление — {details}: {money(payment['total_amount'])}")
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

    bonuses = item.get("bonuses", 0)
    if bonuses:
        parts.append(f"{money_pretty(bonuses)} (премиальные)")

    for payment in item.get("additional_payments", []):
        label = (
            f"{payment['position_name']}: {payment['quantity']} поставк., "
            f"{short_date(payment['week_start'])}–{short_date(payment['week_end'])}"
        )
        if payment.get("error_penalty"):
            label += f", штраф {money_pretty(payment['error_penalty'])}"
        parts.append(f"{money_pretty(payment['total_amount'])} ({label})")

    vacation_pay = item.get("vacation_pay", 0)
    if vacation_pay:
        parts.append(f"{money_pretty(vacation_pay)} (отпускные)")

    if expenses:
        parts.append(f"{money_pretty(expenses)} (расходы)")
    else:
        parts.append(f"{money_pretty(0)} (расходы)")

    result = f"{employee['full_name']}: " + " + ".join(parts) + f" = {money_pretty(item['salary_with_expenses'])}"
    if item.get("payment_mode") == PAYMENT_MODE_SHIFT:
        result += (
            "\n"
            f"Факт: {money_pretty(item['hours'])} ч.; "
            f"полных смен: {item['full_shifts']}; "
            f"половин смен: {item['half_shifts']}; "
            f"оплачено: {money_pretty(item['paid_hours'])} ч.; "
            f"ставка: {money_pretty(item['hourly_rate'])}; "
            f"оплата смен: {money_pretty(item['hourly_pay'])}"
        )
    return result


def build_full_payroll_text(period=None):
    period = period or get_active_period()
    if not period:
        return "Активный расчетный период не настроен."

    totals = calculate_payroll_for_period(
        period["start_date"],
        period["end_date"],
        period.get("payment_mode"),
    )

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
