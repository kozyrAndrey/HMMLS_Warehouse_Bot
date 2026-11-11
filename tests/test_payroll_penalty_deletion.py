import unittest
from unittest.mock import patch

from modules.payroll.google_sheets import PENALTY_HEADERS, delete_penalty
from modules.payroll.handlers import payroll_main_keyboard


class FakeWorksheet:
    def __init__(self, values):
        self.values = values
        self.deleted_rows = []

    def get_all_values(self):
        return self.values

    def delete_rows(self, row_index):
        self.deleted_rows.append(row_index)


class PenaltyDeletionTests(unittest.TestCase):
    def test_manager_menu_contains_penalty_delete_action(self):
        callbacks = [
            button.callback_data
            for row in payroll_main_keyboard(manager=True).inline_keyboard
            for button in row
        ]
        self.assertIn("pay:delete_penalty", callbacks)
        employee_callbacks = [
            button.callback_data
            for row in payroll_main_keyboard(manager=False).inline_keyboard
            for button in row
        ]
        self.assertNotIn("pay:delete_penalty", employee_callbacks)

    def test_delete_penalty_uses_unique_id_and_returns_deleted_record(self):
        row = [
            "penalty-1", "11.11.2026", "emp-1", "Сотрудник", "Отчет позже срока",
            "Отчет склада позже срока", "Опоздание", "500", "Руководитель",
            "11.11.2026 20:00:00",
        ]
        worksheet = FakeWorksheet([PENALTY_HEADERS, row])
        with patch("modules.payroll.google_sheets.get_worksheet", return_value=worksheet):
            deleted = delete_penalty("penalty-1")

        self.assertEqual(worksheet.deleted_rows, [2])
        self.assertEqual(deleted["penalty_id"], "penalty-1")
        self.assertEqual(deleted["full_name"], "Сотрудник")
        self.assertEqual(deleted["amount"], 500)
        self.assertEqual(deleted["penalty_type"], "Отчет склада позже срока")

    def test_delete_penalty_does_not_remove_another_record(self):
        row = [
            "penalty-1", "11.11.2026", "emp-1", "Сотрудник", "Категория",
            "Тип", "Комментарий", "500", "Руководитель", "11.11.2026 20:00:00",
        ]
        worksheet = FakeWorksheet([PENALTY_HEADERS, row])
        with patch("modules.payroll.google_sheets.get_worksheet", return_value=worksheet):
            deleted = delete_penalty("another-penalty")

        self.assertIsNone(deleted)
        self.assertEqual(worksheet.deleted_rows, [])


if __name__ == "__main__":
    unittest.main()
