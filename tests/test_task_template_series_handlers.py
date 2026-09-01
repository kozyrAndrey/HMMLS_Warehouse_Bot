import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.tasks.handlers import (
    REG_ADD_TYPE,
    REG_ADD_WEEKDAY,
    REG_EDIT_WEEKDAY,
    regular_add_weekday_selected,
    regular_edit_weekday_selected,
    weekday_multiselect_keyboard,
)


class TaskTemplateSeriesHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_flow_toggles_several_weekdays_before_continuing(self):
        query = SimpleNamespace(
            data="regweekday:toggle:2",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={"regular_weekdays": [0]})

        state = await regular_add_weekday_selected(
            SimpleNamespace(callback_query=query), context,
        )

        self.assertEqual(state, REG_ADD_WEEKDAY)
        self.assertEqual(context.user_data["regular_weekdays"], [0, 2])
        labels = [
            button.text
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("✅ Понедельник", labels)
        self.assertIn("✅ Среда", labels)

        query.data = "regweekday:done"
        state = await regular_add_weekday_selected(
            SimpleNamespace(callback_query=query), context,
        )
        self.assertEqual(state, REG_ADD_TYPE)

    async def test_edit_flow_saves_complete_weekday_set_once(self):
        query = SimpleNamespace(
            data="regeditweekday:done",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={
            "edit_template_id": "tpl-1",
            "edit_template_weekdays": [1, 3, 5],
        })

        with patch(
            "modules.tasks.handlers.replace_task_template_series_weekdays",
        ) as replace_weekdays:
            state = await regular_edit_weekday_selected(
                SimpleNamespace(callback_query=query), context,
            )

        replace_weekdays.assert_called_once_with("tpl-1", {1, 3, 5})
        self.assertNotEqual(state, REG_EDIT_WEEKDAY)
        self.assertEqual(context.user_data, {})
        self.assertIn("Вторник, Четверг, Суббота", query.edit_message_text.await_args.args[0])

    def test_multiselect_keyboard_has_one_save_action(self):
        keyboard = weekday_multiselect_keyboard("regweekday", [0, 6])
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertEqual(callbacks.count("regweekday:done"), 1)
        self.assertIn("regweekday:toggle:0", callbacks)
        self.assertIn("regweekday:toggle:6", callbacks)


if __name__ == "__main__":
    unittest.main()
