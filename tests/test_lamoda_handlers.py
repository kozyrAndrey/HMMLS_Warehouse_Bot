import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from modules.lamoda_fbs.handlers import _send_return_report, marking_open, show_lamoda_menu
from modules.lamoda_fbs.jobs import lamoda_marking_reminder_job, setup_lamoda_jobs


def callback_update(user_id=7):
    query = SimpleNamespace(
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
        data="",
    )
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, full_name="Сотрудник", username="worker"),
    )


class LamodaHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_opening_section_clears_temporary_state(self):
        update = callback_update()
        context = SimpleNamespace(user_data={"old": "value"})
        await show_lamoda_menu(update, context)
        self.assertEqual(context.user_data, {})
        keyboard = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        self.assertIn("lamoda:assembly:start", callbacks)
        self.assertIn("lamoda:returns", callbacks)

    async def test_employee_cannot_open_marking_operations(self):
        update = callback_update()
        context = SimpleNamespace(user_data={})
        with patch("modules.lamoda_fbs.handlers._is_lamoda_manager", return_value=False):
            await marking_open(update, context)
        update.callback_query.answer.assert_awaited_once()
        self.assertTrue(update.callback_query.answer.await_args.kwargs["show_alert"])
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_normal_return_uses_configured_topic_without_manager_mention(self):
        bot = SimpleNamespace(send_photo=AsyncMock(), send_media_group=AsyncMock())
        context = SimpleNamespace(bot=bot)
        data = self._return_data(condition="NORMAL", problematic=False)
        with (
            patch("modules.lamoda_fbs.handlers.GROUP_CHAT_ID", "-100123"),
            patch("modules.lamoda_fbs.handlers.LAMODA_RETURNS_TOPIC_ID", "77"),
            patch("modules.lamoda_fbs.handlers._mentions_for_roles", return_value="@boss"),
        ):
            await _send_return_report(context, data, 1)
        kwargs = bot.send_photo.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100123)
        self.assertEqual(kwargs["message_thread_id"], 77)
        self.assertNotIn("@boss", kwargs["caption"])

    async def test_defect_return_mentions_brand_warehouse_and_operations(self):
        bot = SimpleNamespace(send_photo=AsyncMock(), send_media_group=AsyncMock())
        context = SimpleNamespace(bot=bot)
        data = self._return_data(condition="DEFECT", problematic=False)
        data["defect_reason"] = "Пятно"
        with (
            patch("modules.lamoda_fbs.handlers.GROUP_CHAT_ID", "-100123"),
            patch("modules.lamoda_fbs.handlers.LAMODA_RETURNS_TOPIC_ID", "77"),
            patch(
                "modules.lamoda_fbs.handlers.get_employees",
                return_value=[
                    {"employee_id": "brand", "roles": ["brand_manager"], "telegram_username": "brand_boss"},
                    {"employee_id": "warehouse", "roles": ["warehouse_manager", "admin"], "telegram_username": "warehouse_boss"},
                    {"employee_id": "operator", "roles": ["warehouse_employee", "operations"], "telegram_username": "operator"},
                    {"employee_id": "worker", "roles": ["warehouse_employee"], "telegram_username": "worker"},
                ],
            ),
        ):
            await _send_return_report(context, data, 2)
        caption = bot.send_photo.await_args.kwargs["caption"]
        self.assertIn("@brand_boss", caption)
        self.assertIn("@warehouse_boss", caption)
        self.assertIn("@operator", caption)
        self.assertNotIn("@worker", caption)

    @staticmethod
    def _return_data(condition, problematic):
        return {
            "condition": condition,
            "problematic": problematic,
            "problem_reason": "",
            "employee_name": "Сотрудник",
            "label_photo": "label-file-id",
            "defect_photos": [],
            "kiz_matches": True,
            "pack": {
                "order_id": "ORDER-1", "pack_number": "PACK-1",
                "product_name": "Футболка", "size": "M",
            },
        }


class LamodaJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminder_is_sent_only_to_manager_rows_returned_by_storage(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(bot=bot)
        with (
            patch("modules.lamoda_fbs.jobs.pending_counts", return_value={"WAITING_WITHDRAWAL": 2}),
            patch("modules.lamoda_fbs.jobs.get_warehouse_managers", return_value=[
                {"telegram_user_id": "42", "role": "warehouse_manager", "is_active": True},
            ]),
        ):
            await lamoda_marking_reminder_job(context)
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.kwargs["chat_id"], 42)

    def test_jobs_have_stable_names_and_are_not_registered_twice(self):
        class FakeQueue:
            def __init__(self):
                self.jobs = {}

            def get_jobs_by_name(self, name):
                return tuple(self.jobs.get(name, []))

            def run_repeating(self, callback, **kwargs):
                self.jobs.setdefault(kwargs["name"], []).append((callback, kwargs))

            def run_daily(self, callback, **kwargs):
                self.jobs.setdefault(kwargs["name"], []).append((callback, kwargs))

        queue = FakeQueue()
        app = SimpleNamespace(job_queue=queue)
        setup_lamoda_jobs(app)
        setup_lamoda_jobs(app)
        self.assertEqual(len(queue.jobs["lamoda_status_sync"]), 1)
        self.assertEqual(len(queue.jobs["lamoda_marking_reminder"]), 1)


if __name__ == "__main__":
    unittest.main()
