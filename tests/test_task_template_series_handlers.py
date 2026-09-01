import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.tasks.handlers import (
    REG_ADD_TYPE,
    REG_ADD_WEEKDAY,
    REG_EDIT_FIELD,
    REG_EDIT_SELECT,
    REG_EDIT_WEEKDAY,
    REG_MANAGE_ACTION,
    regular_add_weekday_selected,
    regular_manage_action_selected,
    regular_manage_selected,
    regular_manage_start,
    regular_edit_weekday_selected,
    regular_template_series_list,
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

    def test_series_list_contains_each_template_once_with_all_days(self):
        templates = [
            {"template_id": "tpl-mon", "series_id": "series-1", "weekday": 0, "Описание": "Отправки"},
            {"template_id": "tpl-thu", "series_id": "series-1", "weekday": 3, "Описание": "Отправки"},
            {"template_id": "tpl-fri", "series_id": "series-2", "weekday": 4, "Описание": "Инвентаризация"},
        ]

        with patch("modules.tasks.handlers.get_task_templates", return_value=templates):
            result = regular_template_series_list()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["Описание"], "Отправки")
        self.assertEqual(result[0]["weekdays"], [0, 3])
        self.assertEqual(result[0]["Дни недели"], "Понедельник, Четверг")

    async def test_manage_starts_with_clickable_template_list_not_weekdays(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data={"old": "value"})
        templates = [{
            "template_id": "tpl-mon", "series_id": "series-1",
            "weekdays": [0, 3], "Описание": "Отправки",
        }]

        with patch(
            "modules.tasks.handlers.regular_template_series_list",
            return_value=templates,
        ):
            state = await regular_manage_start(
                SimpleNamespace(callback_query=query), context,
            )

        self.assertEqual(state, REG_EDIT_SELECT)
        callbacks = [
            button.callback_data
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        labels = [
            button.text
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("regmanage:tpl-mon", callbacks)
        self.assertFalse(any(callback.startswith("regeditday:") for callback in callbacks))
        self.assertIn("Отправки · Пн, Чт", labels)

    async def test_selected_template_offers_edit_and_delete_actions(self):
        template = {
            "template_id": "tpl-mon", "Описание": "Отправки",
            "Дни недели": "Понедельник, Четверг",
        }
        query = SimpleNamespace(
            data="regmanage:tpl-mon",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={})

        with patch("modules.tasks.handlers.get_task_template_by_id", return_value=template):
            state = await regular_manage_selected(
                SimpleNamespace(callback_query=query), context,
            )

        self.assertEqual(state, REG_MANAGE_ACTION)
        self.assertEqual(context.user_data["edit_template_id"], "tpl-mon")
        callbacks = [
            button.callback_data
            for row in query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("regmanageaction:edit", callbacks)
        self.assertIn("regmanageaction:delete", callbacks)

        query.data = "regmanageaction:edit"
        with patch("modules.tasks.handlers.get_task_template_by_id", return_value=template):
            state = await regular_manage_action_selected(
                SimpleNamespace(callback_query=query), context,
            )
        self.assertEqual(state, REG_EDIT_FIELD)


if __name__ == "__main__":
    unittest.main()
