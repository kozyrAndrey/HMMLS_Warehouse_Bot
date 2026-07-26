import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.consumables.handlers import (
    INVENTORY_EXIT_CONFIRM,
    RECEIPT_LAYOUT_PHOTOS,
    inventory_exit_requested,
    inventory_item_selected,
    inventory_session_keyboard,
    receipt_layout_photos_finished,
    send_completed_inventory_pdf_to_topic,
)
from modules.consumables.pdf_reports import create_consumables_stock_pdf


class ConsumablesInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_requires_at_least_one_layout_photo(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data={"receipt_layout_photo_file_ids": []})

        state = await receipt_layout_photos_finished(SimpleNamespace(callback_query=query), context)

        self.assertEqual(state, RECEIPT_LAYOUT_PHOTOS)
        self.assertIn("хотя бы одно фото", query.edit_message_text.await_args.args[0])

    async def test_cancel_inventory_keeps_saved_draft(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data={"inventory_session_id": "inventory-1"})

        state = await inventory_exit_requested(SimpleNamespace(callback_query=query), context)

        self.assertEqual(state, INVENTORY_EXIT_CONFIRM)
        self.assertEqual(context.user_data["inventory_session_id"], "inventory-1")
        self.assertIn("сохранен как черновик", query.edit_message_text.await_args.args[0])

    async def test_counted_item_shows_current_value_before_editing(self):
        query = SimpleNamespace(
            data="consinventoryitem:7",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={"inventory_session_id": "inventory-1"})

        with (
            patch("modules.consumables.handlers.get_consumable_item", return_value={"name": "Коробки"}),
            patch(
                "modules.consumables.handlers.get_inventory_session_items",
                return_value=[
                    {
                        "item_id": 7,
                        "counted": True,
                        "counted_quantity": 12,
                        "unit": "шт",
                    }
                ],
            ),
        ):
            await inventory_item_selected(SimpleNamespace(callback_query=query), context)

        self.assertIn("Текущее значение: 12 шт", query.edit_message_text.await_args.args[0])

    def test_stock_pdf_is_created(self):
        report_path = create_consumables_stock_pdf(
            [{"name": "Коробки", "current_quantity": 12, "unit": "шт"}],
            filename="consumables_stock_test.pdf",
        )
        try:
            self.assertTrue(report_path.exists())
            self.assertTrue(report_path.read_bytes().startswith(b"%PDF"))
        finally:
            report_path.unlink(missing_ok=True)

    def test_inventory_keyboard_keeps_checkmark_before_long_name(self):
        keyboard = inventory_session_keyboard(
            [
                {
                    "item_id": 1,
                    "item_name": "Очень длинное название расходника, которое не помещается в кнопку Telegram",
                    "unit": "шт",
                    "counted": True,
                    "counted_quantity": 12,
                }
            ]
        )

        self.assertTrue(keyboard.inline_keyboard[0][0].text.startswith("✅ "))

    async def test_completed_inventory_pdf_is_sent_to_consumables_topic(self):
        bot = SimpleNamespace(send_document=AsyncMock())
        context = SimpleNamespace(bot=bot)
        result = {
            "session": {"session_id": "inventory-test", "completed_by_name": "Сотрудник"},
            "records": [
                {
                    "item_name": "Коробки",
                    "system_quantity": 10,
                    "counted_quantity": 12,
                    "difference": 2,
                    "unit": "шт",
                    "counted_by_name": "Сотрудник",
                }
            ],
        }

        with (
            patch("modules.consumables.handlers.GROUP_CHAT_ID", "-100321"),
            patch("modules.consumables.handlers.CONSUMABLES_TOPIC_ID", "103"),
        ):
            status = await send_completed_inventory_pdf_to_topic(context, result)

        self.assertIn("отправлен", status)
        kwargs = bot.send_document.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100321)
        self.assertEqual(kwargs["message_thread_id"], 103)
        self.assertEqual(kwargs["filename"], "consumables_inventory_inventory-test.pdf")


if __name__ == "__main__":
    unittest.main()
