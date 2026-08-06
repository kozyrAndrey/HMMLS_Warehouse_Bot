import re
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.payroll.additional_pay import (
    ADDITIONAL_PAY_HEADERS,
    AdditionalPayValidationError,
    append_trend_island_payment,
    calculate_trend_island_pay,
    can_manage_additional_pay,
    previous_completed_week,
)
from modules.payroll.additional_pay_handlers import (
    format_warehouse_manager_notification,
    notify_warehouse_manager,
    setup_additional_pay_jobs,
    trend_island_weekly_reminder_job,
)
from modules.payroll.calculations import calculate_payroll_for_period
from modules.payroll.handlers import payroll_main_keyboard


class FakeWorksheet:
    def __init__(self):
        self.rows = []

    def get_all_records(self, numericise_ignore=None):
        return [dict(zip(ADDITIONAL_PAY_HEADERS, row)) for row in self.rows]

    def get_all_values(self):
        return [list(ADDITIONAL_PAY_HEADERS)] + [list(row) for row in self.rows]

    def append_row(self, row):
        self.rows.append(list(row))

    def update(self, a1_range, values):
        match = re.match(r"^A(\d+):T\d+$", a1_range)
        if not match:
            raise AssertionError(f"Unexpected range: {a1_range}")
        self.rows[int(match.group(1)) - 2] = list(values[0])

    def delete_rows(self, row_number):
        del self.rows[int(row_number) - 2]


def warehouse_manager():
    return {
        "employee_id": "warehouse-manager",
        "full_name": "Руководитель склада",
        "role": "warehouse_manager",
        "hourly_rate": 0,
        "fixed_salary": 0,
        "include_in_common_fund": False,
        "is_active": True,
        "telegram_user_id": "100",
    }


class AdditionalPayRuleTests(unittest.TestCase):
    def test_trend_island_formula_includes_weekly_rate_and_error_penalty(self):
        result = calculate_trend_island_pay(2, 500)

        self.assertEqual(result["gross_amount"], 5500)
        self.assertEqual(result["total_amount"], 5000)
        self.assertEqual(calculate_trend_island_pay(0)["total_amount"], 0)

    def test_error_penalty_cannot_turn_additional_pay_negative(self):
        with self.assertRaisesRegex(AdditionalPayValidationError, "не может превышать"):
            calculate_trend_island_pay(1, 4000)

    def test_previous_week_is_always_monday_to_sunday(self):
        week_start, week_end = previous_completed_week("06.08.2026")

        self.assertEqual(week_start.strftime("%d.%m.%Y"), "27.07.2026")
        self.assertEqual(week_end.strftime("%d.%m.%Y"), "02.08.2026")

    def test_only_brand_manager_and_admin_can_manage_additional_pay(self):
        self.assertTrue(can_manage_additional_pay({"role": "brand_manager"}))
        self.assertTrue(can_manage_additional_pay({"role": "admin"}))
        self.assertFalse(can_manage_additional_pay({"role": "warehouse_manager"}))

        restricted_callbacks = {
            button.callback_data
            for row in payroll_main_keyboard(
                manager=True,
                additional_pay_manager=False,
            ).inline_keyboard
            for button in row
        }
        allowed_callbacks = {
            button.callback_data
            for row in payroll_main_keyboard(
                manager=True,
                additional_pay_manager=True,
            ).inline_keyboard
            for button in row
        }
        self.assertNotIn("pay:additional_pay", restricted_callbacks)
        self.assertIn("pay:additional_pay", allowed_callbacks)

    def test_only_one_trend_island_record_is_allowed_per_employee_and_week(self):
        worksheet = FakeWorksheet()
        kwargs = {
            "employee": warehouse_manager(),
            "week_start": "27.07.2026",
            "quantity": 2,
            "has_errors": True,
            "error_comment": "Ошибка в документах",
            "error_penalty": 500,
            "comment": "Проверено",
            "assigned_by": "Бренд-менеджер",
        }
        with patch(
            "modules.payroll.additional_pay.get_worksheet",
            return_value=worksheet,
        ):
            item = append_trend_island_payment(**kwargs)
            with self.assertRaisesRegex(AdditionalPayValidationError, "уже существует"):
                append_trend_island_payment(**kwargs)

        self.assertEqual(item["accrual_date"], "02.08.2026")
        self.assertEqual(item["unit_rate"], 2000)
        self.assertEqual(item["weekly_rate"], 1500)
        self.assertEqual(item["total_amount"], 5000)

    def test_payment_is_included_by_week_end_date(self):
        employee = warehouse_manager()
        payment = {
            "employee_id": employee["employee_id"],
            "position_name": "Trend Island",
            "week_start": "10.08.2026",
            "week_end": "16.08.2026",
            "quantity": 2,
            "error_penalty": 0,
            "total_amount": 5500,
        }
        with (
            patch("modules.payroll.calculations.get_employees", return_value=[employee]),
            patch("modules.payroll.calculations.get_reports_in_period", return_value=[]),
            patch("modules.payroll.calculations.get_expenses_in_period", return_value=[]),
            patch("modules.payroll.calculations.get_penalties_in_period", return_value=[]),
            patch("modules.payroll.calculations.get_bonuses_in_period", return_value=[]),
            patch(
                "modules.payroll.calculations.get_additional_payments_in_period",
                return_value=[payment],
            ) as get_payments,
            patch("modules.payroll.calculations.get_vacations_in_period", return_value=[]),
            patch("modules.payroll.calculations.SALARY_FIXED_PARTS", {}),
        ):
            total = calculate_payroll_for_period("16.08.2026", "31.08.2026")[employee["employee_id"]]

        get_payments.assert_called_once_with("16.08.2026", "31.08.2026")
        self.assertEqual(total["additional_pay_total"], 5500)
        self.assertEqual(total["salary_without_expenses"], 5500)


class FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def run_daily(self, callback, **kwargs):
        self.jobs.append((callback, kwargs))


class AdditionalPayReminderTests(unittest.IsolatedAsyncioTestCase):
    def test_reminder_is_scheduled_for_thirteen_moscow_time(self):
        queue = FakeJobQueue()
        setup_additional_pay_jobs(SimpleNamespace(job_queue=queue))

        self.assertEqual(len(queue.jobs), 1)
        callback, kwargs = queue.jobs[0]
        self.assertIs(callback, trend_island_weekly_reminder_job)
        self.assertEqual((kwargs["time"].hour, kwargs["time"].minute), (13, 0))
        self.assertEqual(kwargs["time"].tzinfo.key, "Europe/Moscow")

    async def test_monday_reminder_goes_only_to_brand_manager_and_admin(self):
        employees = [
            warehouse_manager(),
            {
                "employee_id": "brand",
                "full_name": "Руководитель бренда",
                "role": "brand_manager",
                "telegram_user_id": "200",
                "is_active": True,
            },
            {
                "employee_id": "admin",
                "full_name": "Администратор",
                "role": "admin",
                "telegram_user_id": "300",
                "is_active": True,
            },
        ]
        bot = SimpleNamespace(send_message=AsyncMock())
        mocked_datetime = SimpleNamespace()
        mocked_datetime.now = lambda tz: datetime(2026, 8, 10, 10, 0, tzinfo=tz)

        with (
            patch(
                "modules.payroll.additional_pay_handlers.datetime",
                mocked_datetime,
            ),
            patch(
                "modules.payroll.additional_pay_handlers.get_employees",
                return_value=employees,
            ),
            patch(
                "modules.payroll.additional_pay_handlers.find_trend_island_payment",
                return_value=None,
            ),
        ):
            await trend_island_weekly_reminder_job(SimpleNamespace(bot=bot))

        self.assertEqual(bot.send_message.await_count, 2)
        chat_ids = {
            call.kwargs["chat_id"] for call in bot.send_message.await_args_list
        }
        self.assertEqual(chat_ids, {200, 300})

    async def test_saved_payment_report_is_sent_to_warehouse_manager(self):
        item = {
            "position_name": "Trend Island",
            "week_start": "27.07.2026",
            "week_end": "02.08.2026",
            "quantity": 2,
            "unit_rate": 2000,
            "weekly_rate": 1500,
            "gross_amount": 5500,
            "has_errors": True,
            "error_comment": "Ошибка в документах",
            "error_penalty": 500,
            "total_amount": 5000,
            "comment": "Проверено",
            "assigned_by": "Руководитель бренда",
        }
        bot = SimpleNamespace(send_message=AsyncMock())

        warning = await notify_warehouse_manager(
            SimpleNamespace(bot=bot),
            warehouse_manager(),
            item,
        )

        self.assertEqual(warning, "")
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.kwargs["chat_id"], 100)
        report = bot.send_message.await_args.kwargs["text"]
        self.assertEqual(report, format_warehouse_manager_notification(item))
        self.assertIn("27.07.2026 — 02.08.2026", report)
        self.assertIn("Штраф за ошибки: 500 ₽", report)
        self.assertIn("Итого начислено: 5000 ₽", report)


if __name__ == "__main__":
    unittest.main()
