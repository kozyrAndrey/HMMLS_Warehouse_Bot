import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import ConversationHandler

from core.keyboards import (
    build_consumables_menu_keyboard,
    build_consumables_supplies_menu_keyboard,
    build_consumables_suppliers_menu_keyboard,
)
from modules.consumables.handlers import (
    ACCEPT_LAYOUT_PHOTO,
    ACCEPT_SUPPLY,
    accept_supply_selected,
    accept_supply_start,
    closing_document_caption_text,
    finish_acceptance,
    layout_photo_received,
    send_acceptance_to_topic,
    send_closing_document_to_workflow,
)


class ConsumablesAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    def test_supplies_section_is_available_to_regular_employees(self):
        keyboard = build_consumables_menu_keyboard(manager=False)
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("cons:module_supplies", callbacks)

    def test_regular_employees_see_only_acceptance_actions_in_supplies_section(self):
        keyboard = build_consumables_supplies_menu_keyboard(manager=False)
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("cons:accept_supply", callbacks)
        self.assertIn("cons:edit_acceptance", callbacks)
        self.assertIn("cons:delete_acceptance", callbacks)
        self.assertNotIn("cons:add_supply", callbacks)
        self.assertNotIn("cons:edit_supply", callbacks)
        self.assertNotIn("cons:delete_supply", callbacks)
        self.assertNotIn("cons:suppliers", callbacks)
        self.assertNotIn("cons:delete_supplier", callbacks)

    def test_managers_see_supply_and_acceptance_actions(self):
        keyboard = build_consumables_supplies_menu_keyboard(manager=True)
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("cons:accept_supply", callbacks)
        self.assertIn("cons:edit_acceptance", callbacks)
        self.assertIn("cons:delete_acceptance", callbacks)
        self.assertIn("cons:add_supply", callbacks)
        self.assertIn("cons:edit_supply", callbacks)
        self.assertIn("cons:delete_supply", callbacks)
        self.assertIn("cons:suppliers", callbacks)

    def test_supplier_management_menu_contains_all_actions(self):
        keyboard = build_consumables_suppliers_menu_keyboard()
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("cons:add_supplier", callbacks)
        self.assertIn("cons:edit_supplier", callbacks)
        self.assertIn("cons:delete_supplier", callbacks)

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
            patch(
                "modules.consumables.handlers.get_supplier",
                return_value={"closing_documents_delivery": "paper"},
            ),
            patch("modules.consumables.handlers.current_employee_name", return_value="Сотрудник склада"),
            patch(
                "modules.consumables.handlers.send_acceptance_to_topic",
                new=AsyncMock(return_value=([101], "Приемка отправлена в тему чата ✅")),
            ),
            patch(
                "modules.consumables.handlers.send_closing_document_to_workflow",
                new=AsyncMock(return_value=([], "Документ не прикреплен.")),
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
            document_workflow_message_ids=[],
        )
        result_text = message.reply_text.await_args.args[0]
        self.assertIn("Остатки пополнены:", result_text)
        self.assertIn("Карточка: +2 шт", result_text)

    def test_closing_document_caption_matches_required_template(self):
        supply = {
            "consumable_name": "Счет на оплату № 356 от 22 июня 2026 г.",
            "organization": "ИП Бакиров Динис Ирекович",
            "amount": 9540,
        }

        self.assertEqual(
            closing_document_caption_text(supply, edo=True),
            "Закрывающий документ отправлен по ЭДО\n"
            "2 - Счет на оплату № 356 от 22 июня 2026 г.\n"
            "3 - ИП Бакиров Динис Ирекович\n"
            "4 - 9 540,00",
        )

    async def test_edo_notification_is_sent_to_closing_documents_topic(self):
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)))
        context = SimpleNamespace(bot=bot, user_data={"supplier_documents_delivery": "edo"})
        supply = {"consumable_name": "Счет № 356", "organization": "ИП Бакиров", "amount": 9540}

        with (
            patch("modules.consumables.handlers.DOCUMENT_WORKFLOW_CHAT_ID", "-100123"),
            patch("modules.consumables.handlers.ACTS_CLOSING_DOCUMENTS_TOPIC_ID", "789"),
        ):
            message_ids, _ = await send_closing_document_to_workflow(context, supply)

        self.assertEqual(message_ids, [77])
        bot.send_message.assert_awaited_once_with(
            chat_id=-100123,
            message_thread_id=789,
            text=closing_document_caption_text(supply, edo=True),
        )

    async def test_paper_document_is_sent_to_closing_documents_topic(self):
        bot = SimpleNamespace(send_document=AsyncMock(return_value=SimpleNamespace(message_id=78)))
        context = SimpleNamespace(
            bot=bot,
            user_data={
                "supplier_documents_delivery": "paper",
                "closing_document_file_id": "closing-file",
                "closing_document_kind": "document",
            },
        )
        supply = {"consumable_name": "Счет № 356", "organization": "ИП Бакиров", "amount": 9540}

        with (
            patch("modules.consumables.handlers.DOCUMENT_WORKFLOW_CHAT_ID", "-100123"),
            patch("modules.consumables.handlers.ACTS_CLOSING_DOCUMENTS_TOPIC_ID", "789"),
        ):
            message_ids, _ = await send_closing_document_to_workflow(context, supply)

        self.assertEqual(message_ids, [78])
        bot.send_document.assert_awaited_once_with(
            chat_id=-100123,
            message_thread_id=789,
            document="closing-file",
            caption=closing_document_caption_text(supply),
        )

    async def test_edo_supplier_skips_document_upload_during_acceptance(self):
        message = SimpleNamespace(
            photo=[SimpleNamespace(file_id="layout-photo")],
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(user_data={"supply_id": 17})

        with (
            patch(
                "modules.consumables.handlers.get_supply",
                return_value={"id": 17, "organization": "ИП Бакиров"},
            ),
            patch(
                "modules.consumables.handlers.get_supplier",
                return_value={"closing_documents_delivery": "edo"},
            ),
            patch(
                "modules.consumables.handlers.finish_acceptance",
                new=AsyncMock(return_value=ConversationHandler.END),
            ) as finish,
        ):
            state = await layout_photo_received(update, context)

        self.assertEqual(state, ConversationHandler.END)
        self.assertEqual(context.user_data["supplier_documents_delivery"], "edo")
        self.assertEqual(context.user_data["closing_document_kind"], "none")
        finish.assert_awaited_once_with(update, context)
        message.reply_text.assert_not_awaited()

    async def test_acceptance_report_contains_only_layout_photo(self):
        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=91)),
            send_document=AsyncMock(),
        )
        context = SimpleNamespace(
            bot=bot,
            user_data={
                "layout_photo_file_id": "layout-photo",
                "closing_document_file_id": "closing-file",
                "closing_document_kind": "document",
                "supplier_documents_delivery": "paper",
            },
        )
        supply = {
            "id": 17,
            "consumable_name": "Счет № 356",
            "organization": "ИП Бакиров",
            "amount": 9540,
            "supply_items": [],
        }

        with (
            patch("modules.consumables.handlers.GROUP_CHAT_ID", "-100321"),
            patch("modules.consumables.handlers.CONSUMABLES_TOPIC_ID", "103"),
        ):
            message_ids, _ = await send_acceptance_to_topic(context, supply, "Сотрудник")

        self.assertEqual(message_ids, [91])
        self.assertEqual(bot.send_photo.await_count, 1)
        bot.send_document.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
