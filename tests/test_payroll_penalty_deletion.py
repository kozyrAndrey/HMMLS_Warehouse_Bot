import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.payroll.google_sheets import PENALTY_HEADERS, delete_penalty
from modules.payroll.handlers import (
    delete_penalty_topic_messages,
    penalties_keyboard,
    payroll_main_keyboard,
    send_penalty_to_topic,
)


class FakeWorksheet:
    def __init__(self, values):
        self.values = values
        self.deleted_rows = []

    def get_all_values(self):
        return self.values

    def delete_rows(self, row_index):
        self.deleted_rows.append(row_index)


class PenaltyDeletionTests(unittest.TestCase):
    def test_manager_menu_opens_penalties_module(self):
        callbacks = [
            button.callback_data
            for row in payroll_main_keyboard(manager=True).inline_keyboard
            for button in row
        ]
        self.assertIn("pay:penalties", callbacks)
        self.assertNotIn("pay:add_penalty", callbacks)
        self.assertNotIn("pay:delete_penalty", callbacks)
        penalty_callbacks = [
            button.callback_data
            for row in penalties_keyboard().inline_keyboard
            for button in row
        ]
        self.assertIn("pay:add_penalty", penalty_callbacks)
        self.assertIn("pay:delete_penalty", penalty_callbacks)
        employee_callbacks = [
            button.callback_data
            for row in payroll_main_keyboard(manager=False).inline_keyboard
            for button in row
        ]
        self.assertNotIn("pay:penalties", employee_callbacks)

    def test_delete_penalty_uses_unique_id_and_returns_deleted_record(self):
        row = [
            "penalty-1", "11.11.2026", "emp-1", "Сотрудник", "Отчет позже срока",
            "Отчет склада позже срока", "Опоздание", "500", "Руководитель",
            "11.11.2026 20:00:00", "-100123", "77", "[301, 302]",
        ]
        worksheet = FakeWorksheet([PENALTY_HEADERS, row])
        with patch("modules.payroll.google_sheets.get_worksheet", return_value=worksheet):
            deleted = delete_penalty("penalty-1")

        self.assertEqual(worksheet.deleted_rows, [2])
        self.assertEqual(deleted["penalty_id"], "penalty-1")
        self.assertEqual(deleted["full_name"], "Сотрудник")
        self.assertEqual(deleted["amount"], 500)
        self.assertEqual(deleted["penalty_type"], "Отчет склада позже срока")
        self.assertEqual(deleted["telegram_message_ids"], [301, 302])

    def test_delete_penalty_does_not_remove_another_record(self):
        row = [
            "penalty-1", "11.11.2026", "emp-1", "Сотрудник", "Категория",
            "Тип", "Комментарий", "500", "Руководитель", "11.11.2026 20:00:00",
            "-100123", "77", "[301]",
        ]
        worksheet = FakeWorksheet([PENALTY_HEADERS, row])
        with patch("modules.payroll.google_sheets.get_worksheet", return_value=worksheet):
            deleted = delete_penalty("another-penalty")

        self.assertIsNone(deleted)
        self.assertEqual(worksheet.deleted_rows, [])


class PenaltyTopicMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_sent_penalty_returns_message_location(self):
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=501)))
        context = SimpleNamespace(bot=bot)
        employee = {"full_name": "Сотрудник"}

        with (
            patch("modules.payroll.handlers.GROUP_CHAT_ID", "-100123"),
            patch("modules.payroll.handlers.PAYROLL_PENALTIES_TOPIC_ID", "77"),
        ):
            delivery = await send_penalty_to_topic(
                context, employee, "11.11.2026", "Категория", "Тип", "Комментарий",
                500, "Руководитель",
            )

        self.assertEqual(delivery["chat_id"], -100123)
        self.assertEqual(delivery["thread_id"], 77)
        self.assertEqual(delivery["message_ids"], [501])

    async def test_delete_penalty_removes_all_topic_messages(self):
        bot = SimpleNamespace(delete_message=AsyncMock())
        context = SimpleNamespace(bot=bot)

        status = await delete_penalty_topic_messages(context, {
            "telegram_chat_id": "-100123",
            "telegram_message_ids": [301, 302],
        })

        self.assertEqual(bot.delete_message.await_count, 2)
        bot.delete_message.assert_any_await(chat_id=-100123, message_id=301)
        bot.delete_message.assert_any_await(chat_id=-100123, message_id=302)
        self.assertIn("удалено", status)


if __name__ == "__main__":
    unittest.main()
