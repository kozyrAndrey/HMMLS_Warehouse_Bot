import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import ConversationHandler

from modules.payroll.handlers import (
    finish_create_report,
    finish_edit_report,
    send_daily_report_to_private_target,
)


def warehouse_manager():
    return {
        "employee_id": "emp_manager",
        "full_name": "Руководитель склада",
        "telegram_user_id": "42",
        "role": "warehouse_manager",
        "hourly_rate": 500,
    }


def report_model():
    return {
        "date": "16.07.2026",
        "employee": warehouse_manager(),
        "interval": "10:00-19:00",
        "hours": 8,
        "tasks": "Управление складом",
        "kpi_items": [],
        "manager_report": None,
    }


class PayrollManagerReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_callback_message_is_reused_for_report(self):
        edited_message = SimpleNamespace(chat_id=42, message_id=101)
        query = SimpleNamespace(
            message=SimpleNamespace(chat_id=42, message_id=101),
            edit_message_text=AsyncMock(return_value=edited_message),
        )

        data = await send_daily_report_to_private_target(query, report_model(), "menu")

        self.assertEqual(data, {"chat_id": 42, "thread_id": "", "message_id": 101})
        query.edit_message_text.assert_awaited_once()
        self.assertEqual(query.edit_message_text.await_args.kwargs["reply_markup"], "menu")

    async def test_own_manager_report_produces_only_one_bot_message(self):
        sent_message = SimpleNamespace(chat_id=42, message_id=202)
        target = SimpleNamespace(reply_text=AsyncMock(return_value=sent_message))
        context = SimpleNamespace(
            user_data={
                "employee_id": "emp_manager",
                "report_date": "16.07.2026",
                "interval": "10:00-19:00",
                "hours": 8,
                "tasks": "Управление складом",
                "kpi_items": [],
            },
            bot=SimpleNamespace(send_message=AsyncMock()),
        )
        telegram_user = SimpleNamespace(id=42)

        with (
            patch("modules.payroll.handlers.get_employee_by_id", return_value=warehouse_manager()),
            patch(
                "modules.payroll.google_sheets.get_employee_by_id",
                return_value=warehouse_manager(),
            ),
            patch(
                "modules.payroll.handlers.find_employee_for_telegram_user",
                return_value=warehouse_manager(),
            ),
            patch("modules.payroll.handlers.append_daily_report") as append_report,
        ):
            state = await finish_create_report(target, context, telegram_user)

        self.assertEqual(state, ConversationHandler.END)
        target.reply_text.assert_awaited_once()
        context.bot.send_message.assert_not_awaited()
        self.assertEqual(context.user_data, {})
        telegram_data = append_report.call_args.args[-1]
        self.assertEqual(
            telegram_data,
            {"chat_id": 42, "thread_id": "", "message_id": 202},
        )

    async def test_own_edited_report_reuses_current_bot_message(self):
        edited_message = SimpleNamespace(chat_id=42, message_id=303)
        query = SimpleNamespace(
            message=SimpleNamespace(chat_id=42, message_id=303),
            edit_message_text=AsyncMock(return_value=edited_message),
        )
        report_data = {
            "report_id": "report_1",
            "Дата": "16.07.2026",
            "employee_id": "emp_manager",
            "ФИО": "Руководитель склада",
            "telegram_user_id": "42",
            "Рабочий промежуток": "10:00-19:00",
            "Отработано часов": 8,
            "Задачи": "Управление складом",
            "KPI данные": "[]",
            "KPI сумма": 0,
            "telegram_chat_id": "42",
            "telegram_message_id": "100",
        }
        context = SimpleNamespace(
            user_data={"edit_row_index": 2, "edit_report_data": report_data},
            bot=SimpleNamespace(send_message=AsyncMock()),
        )
        telegram_user = SimpleNamespace(id=42)

        with (
            patch("modules.payroll.handlers.get_employee_by_id", return_value=warehouse_manager()),
            patch(
                "modules.payroll.google_sheets.get_employee_by_id",
                return_value=warehouse_manager(),
            ),
            patch(
                "modules.payroll.handlers.find_employee_for_telegram_user",
                return_value=warehouse_manager(),
            ),
            patch(
                "modules.payroll.handlers.delete_old_report_message",
                new=AsyncMock(return_value=True),
            ),
            patch("modules.payroll.handlers.update_daily_report") as update_report,
        ):
            state = await finish_edit_report(query, context, telegram_user)

        self.assertEqual(state, ConversationHandler.END)
        query.edit_message_text.assert_awaited_once()
        context.bot.send_message.assert_not_awaited()
        self.assertEqual(context.user_data, {})
        saved_report = update_report.call_args.args[1]
        self.assertEqual(saved_report["telegram_chat_id"], 42)
        self.assertEqual(saved_report["telegram_message_id"], 303)


if __name__ == "__main__":
    unittest.main()
