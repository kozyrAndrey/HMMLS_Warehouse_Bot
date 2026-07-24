import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.marking.handlers import (
    MARKING_DISCOUNTS,
    MARKING_DOCUMENT_NAME,
    TREND_PRICE_TYPE_WITH_DISCOUNTS,
    TREND_PRICE_TYPE_WITHOUT_DISCOUNTS,
    trend_export_discounts_received,
    trend_export_start,
)


class MarkingHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_starts_by_asking_about_discounts(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"marking_trend_price_type": "Устаревшее значение"})

        with patch("modules.marking.handlers.ensure_manager", return_value=True):
            state = await trend_export_start(update, context)

        self.assertEqual(state, MARKING_DISCOUNTS)
        self.assertNotIn("marking_trend_price_type", context.user_data)
        self.assertEqual(query.edit_message_text.await_args.args[0], "Есть ли сейчас скидки?")
        callbacks = [
            button.callback_data
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("marking:trend_export:discounts:yes", callbacks)
        self.assertIn("marking:trend_export:discounts:no", callbacks)

    async def test_yes_selects_old_price(self):
        await self.assert_price_type_selected(
            callback_data="marking:trend_export:discounts:yes",
            expected=TREND_PRICE_TYPE_WITH_DISCOUNTS,
        )

    async def test_no_selects_sale_price(self):
        await self.assert_price_type_selected(
            callback_data="marking:trend_export:discounts:no",
            expected=TREND_PRICE_TYPE_WITHOUT_DISCOUNTS,
        )

    async def assert_price_type_selected(self, callback_data, expected):
        query = SimpleNamespace(
            data=callback_data,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={})

        with patch("modules.marking.handlers.ensure_manager", return_value=True):
            state = await trend_export_discounts_received(update, context)

        self.assertEqual(state, MARKING_DOCUMENT_NAME)
        self.assertEqual(context.user_data["marking_trend_price_type"], expected)
        self.assertIn(f"цена «{expected}»", query.edit_message_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
