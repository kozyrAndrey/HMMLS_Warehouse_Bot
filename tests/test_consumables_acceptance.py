import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import ConversationHandler

from modules.consumables.handlers import (
    ACCEPT_LAYOUT_PHOTO,
    ACCEPT_SUPPLY,
    accept_supply_selected,
    accept_supply_start,
    finish_acceptance,
)


class ConsumablesAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_acceptance_starts_with_pending_supplies(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={})
        supplies = [{"id": 17, "status": "pending", "consumable_name": "Коробки"}]

        with (
            patch("modules.consumables.handlers.get_pending_supplies", return_value=supplies),
            patch("modules.consumables.handlers.supplies_list_text", return_value="Выберите поставку"),
            patch("modules.consumables.handlers.supplies_keyboard", return_value="keyboard") as keyboard,
        ):
            state = await accept_supply_start(update, context)

        self.assertEqual(state, ACCEPT_SUPPLY)
        self.assertEqual(context.user_data, {"consumables_module": "supplies"})
        keyboard.assert_called_once_with(supplies, "conssup")
        query.edit_message_text.assert_awaited_once_with("Выберите поставку", reply_markup="keyboard")

    async def test_acceptance_reports_when_no_pending_supplies(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={})

        with (
            patch("modules.consumables.handlers.get_pending_supplies", return_value=[]),
            patch("modules.consumables.handlers.consumables_supplies_keyboard", return_value="menu"),
        ):
            state = await accept_supply_start(update, context)

        self.assertEqual(state, ConversationHandler.END)
        query.edit_message_text.assert_awaited_once_with(
            "Нет поставок, ожидающих приемки.",
            reply_markup="menu",
        )

    async def test_pending_supply_selection_requests_layout_photo(self):
        query = SimpleNamespace(
            data="conssup:17",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"consumables_module": "supplies"})
        supply = {"id": 17, "status": "pending", "consumable_name": "Коробки"}

        with (
            patch("modules.consumables.handlers.get_supply", return_value=supply),
            patch("modules.consumables.handlers.consumables_back_keyboard", return_value="cancel"),
        ):
            state = await accept_supply_selected(update, context)

        self.assertEqual(state, ACCEPT_LAYOUT_PHOTO)
        self.assertEqual(context.user_data["supply_id"], 17)
        query.edit_message_text.assert_awaited_once_with(
            "Отправьте фото разложенных расходников:",
            reply_markup="cancel",
        )

    async def test_finishing_acceptance_adds_supply_items_to_stock(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            callback_query=None,
            message=message,
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(
            user_data={
                "supply_id": 17,
                "layout_photo_file_id": "layout-photo",
                "closing_document_file_id": "",
                "closing_document_kind": "none",
            }
        )
        pending_supply = {
            "id": 17,
            "status": "pending",
            "consumable_name": "Счет № 403",
            "organization": "ИП Бакиров",
            "amount": 470,
            "supply_items": [{"item_id": 1, "item_name": "Карточка", "quantity": 2, "unit": "шт"}],
        }
        accepted_supply = {**pending_supply, "status": "accepted"}

        with (
            patch("modules.consumables.handlers.get_supply", return_value=pending_supply),
            patch("modules.consumables.handlers.current_employee_name", return_value="Сотрудник склада"),
            patch(
                "modules.consumables.handlers.send_acceptance_to_topic",
                new=AsyncMock(return_value=([101], "Приемка отправлена в тему чата ✅")),
            ),
            patch("modules.consumables.handlers.mark_supply_accepted", return_value=accepted_supply) as mark_accepted,
            patch("modules.consumables.handlers.consumables_supplies_keyboard", return_value="menu"),
        ):
            state = await finish_acceptance(update, context)

        self.assertEqual(state, ConversationHandler.END)
        mark_accepted.assert_called_once_with(
            supply_id=17,
            accepted_by_user_id=42,
            accepted_by_name="Сотрудник склада",
            layout_photo_file_id="layout-photo",
            closing_document_file_id="",
            closing_document_kind="none",
            topic_message_ids=[101],
        )
        result_text = message.reply_text.await_args.args[0]
        self.assertIn("Остатки пополнены:", result_text)
        self.assertIn("Карточка: +2 шт", result_text)


if __name__ == "__main__":
    unittest.main()
