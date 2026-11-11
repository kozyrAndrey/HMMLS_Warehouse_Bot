import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from modules.payroll.handlers import (
    maybe_add_late_warehouse_report_penalty,
    warehouse_report_deadline,
    warehouse_report_is_late,
)


MSK_TZ = ZoneInfo("Europe/Moscow")


class WarehouseReportDeadlineTests(unittest.TestCase):
    def test_deadline_is_one_hour_after_shift_end(self):
        deadline = warehouse_report_deadline("11.11.2026", "10:00-19:00")

        self.assertEqual(deadline, datetime(2026, 11, 11, 20, 0, tzinfo=MSK_TZ))
        self.assertFalse(
            warehouse_report_is_late(
                "11.11.2026",
                "10:00-19:00",
                datetime(2026, 11, 11, 20, 0, tzinfo=MSK_TZ),
            )
        )
        self.assertTrue(
            warehouse_report_is_late(
                "11.11.2026",
                "10:00-19:00",
                datetime(2026, 11, 11, 20, 1, tzinfo=MSK_TZ),
            )
        )

    def test_overnight_shift_deadline_uses_next_day(self):
        deadline = warehouse_report_deadline("11.11.2026", "18:00-02:00")

        self.assertEqual(deadline, datetime(2026, 11, 12, 3, 0, tzinfo=MSK_TZ))


class LateWarehouseReportPenaltyTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_report_creates_and_sends_automatic_penalty(self):
        employee = {"employee_id": "emp-1", "full_name": "Иван Иванов"}
        submitted_at = datetime(2026, 11, 11, 20, 30, tzinfo=MSK_TZ)
        context = SimpleNamespace(bot=SimpleNamespace())

        with (
            patch("modules.payroll.handlers.get_penalties_in_period", return_value=[]),
            patch("modules.payroll.handlers.get_employee_penalty_coefficient", return_value=1.35),
            patch("modules.payroll.handlers.append_penalty") as append_penalty,
            patch(
                "modules.payroll.handlers.send_penalty_to_topic",
                new=AsyncMock(return_value="ok"),
            ) as send_penalty,
        ):
            status = await maybe_add_late_warehouse_report_penalty(
                context,
                employee,
                "11.11.2026",
                "10:00-19:00",
                submitted_at=submitted_at,
            )

        append_penalty.assert_called_once()
        self.assertEqual(append_penalty.call_args.args[5], 675)
        self.assertEqual(append_penalty.call_args.args[6], "Бот (автоштраф)")
        send_penalty.assert_awaited_once()
        self.assertIn("Отчет склада позже срока", status)
        self.assertIn("675", status)

    async def test_existing_penalty_is_not_duplicated(self):
        employee = {"employee_id": "emp-1", "full_name": "Иван Иванов"}
        existing = [{
            "employee_id": "emp-1",
            "penalty_type": "Отчет склада позже срока",
        }]

        with (
            patch("modules.payroll.handlers.get_penalties_in_period", return_value=existing),
            patch("modules.payroll.handlers.append_penalty") as append_penalty,
            patch("modules.payroll.handlers.send_penalty_to_topic", new=AsyncMock()) as send_penalty,
        ):
            status = await maybe_add_late_warehouse_report_penalty(
                SimpleNamespace(bot=SimpleNamespace()),
                employee,
                "11.11.2026",
                "10:00-19:00",
                submitted_at=datetime(2026, 11, 11, 21, 0, tzinfo=MSK_TZ),
            )

        self.assertIsNone(status)
        append_penalty.assert_not_called()
        send_penalty.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
