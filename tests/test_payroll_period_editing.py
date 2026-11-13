import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.payroll.google_sheets import PERIOD_HEADERS, update_period
from modules.payroll.handlers import (
    PERIOD_EDIT_FIELD,
    PERIOD_EDIT_SELECT,
    period_edit_period_selected,
    period_edit_start,
    period_edit_value_received,
)


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = [list(row) for row in rows]
        self.updated_range = None

    def get_all_values(self):
        return [list(row) for row in self.rows]

    def update(self, cell_range, values):
        self.updated_range = cell_range
        row_number = int(cell_range.split(":", 1)[0][1:])
        self.rows[row_number - 1] = list(values[0])


def period(period_id, name, start_date, end_date, status):
    return {
        "period_id": period_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "payment_mode": "hourly",
        "status": status,
        "created_by": "Руководитель",
        "created_at": "01.11.2026 10:00:00",
        "updated_at": "01.11.2026 10:00:00",
    }


class PayrollPeriodStorageTests(unittest.TestCase):
    def test_closed_period_is_updated_by_id_without_changing_status(self):
        worksheet = FakeWorksheet([
            PERIOD_HEADERS,
            [
                "period-old",
                "1-я половина ноября",
                "30.10.2026",
                "12.10.2026",
                "hourly",
                "closed",
                "Руководитель",
                "01.11.2026 10:00:00",
                "01.11.2026 10:00:00",
            ],
            [
                "period-current",
                "2-я половина ноября",
                "13.11.2026",
                "30.11.2026",
                "hourly",
                "active",
                "Руководитель",
                "13.11.2026 10:00:00",
                "13.11.2026 10:00:00",
            ],
        ])

        with patch("modules.payroll.google_sheets.get_worksheet", return_value=worksheet):
            self.assertTrue(update_period("period-old", end_date="12.11.2026"))

        updated = dict(zip(PERIOD_HEADERS, worksheet.rows[1]))
        current = dict(zip(PERIOD_HEADERS, worksheet.rows[2]))
        self.assertEqual(worksheet.updated_range, "A2:I2")
        self.assertEqual(updated["Дата конца"], "12.11.2026")
        self.assertEqual(updated["Статус"], "closed")
        self.assertEqual(current["Дата конца"], "30.11.2026")


class PayrollPeriodHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_flow_lists_active_and_closed_periods(self):
        periods = [
            period("period-old", "1-я половина ноября", "30.10.2026", "12.10.2026", "closed"),
            period("period-current", "2-я половина ноября", "13.11.2026", "30.11.2026", "active"),
        ]
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={})

        with (
            patch("modules.payroll.handlers.current_employee_or_none", return_value={"role": "manager"}),
            patch("modules.payroll.handlers.is_manager", return_value=True),
            patch("modules.payroll.handlers.get_periods", return_value=periods),
        ):
            state = await period_edit_start(update, context)

        self.assertEqual(state, PERIOD_EDIT_SELECT)
        callbacks = [
            button.callback_data
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("periodeditselect:period-old", callbacks)
        self.assertIn("periodeditselect:period-current", callbacks)

    async def test_closed_period_can_be_selected_and_edited(self):
        old_period = period(
            "period-old",
            "1-я половина ноября",
            "30.10.2026",
            "12.10.2026",
            "closed",
        )
        query = SimpleNamespace(
            data="periodeditselect:period-old",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"periods_to_edit": {"period-old": old_period}})

        with (
            patch("modules.payroll.handlers.current_employee_or_none", return_value={"role": "manager"}),
            patch("modules.payroll.handlers.is_manager", return_value=True),
        ):
            state = await period_edit_period_selected(update, context)

        self.assertEqual(state, PERIOD_EDIT_FIELD)
        self.assertEqual(context.user_data["period_edit_id"], "period-old")
        self.assertIn("Статус: закрытый", query.edit_message_text.await_args.args[0])

        message = SimpleNamespace(text="12.11.2026", reply_text=AsyncMock())
        update = SimpleNamespace(message=message)
        context.user_data["period_edit_field"] = "end"
        corrected = {**old_period, "end_date": "12.11.2026"}
        with (
            patch("modules.payroll.handlers.update_period", return_value=True) as update_period_mock,
            patch("modules.payroll.handlers.get_periods", return_value=[corrected]),
        ):
            await period_edit_value_received(update, context)

        update_period_mock.assert_called_once_with("period-old", end_date="12.11.2026")
        self.assertIn("12.11.2026", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
