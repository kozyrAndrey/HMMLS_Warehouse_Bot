import unittest
from unittest.mock import patch

from modules.payroll import drivers
from modules.payroll.calculations import build_full_payroll_text


class FakeWorksheet:
    def __init__(self, headers):
        self.headers = headers
        self.rows = []

    def get_all_records(self, numericise_ignore=None):
        return [dict(zip(self.headers, row)) for row in self.rows]

    def append_row(self, row):
        self.rows.append(list(row))

    def delete_rows(self, row_number):
        del self.rows[int(row_number) - 2]


class DriverStorageTests(unittest.TestCase):
    def setUp(self):
        self.driver_ws = FakeWorksheet(drivers.DRIVER_HEADERS)
        self.payment_ws = FakeWorksheet(drivers.DRIVER_PAYMENT_HEADERS)

        def worksheet(name):
            return self.driver_ws if name == drivers.DRIVERS_SHEET else self.payment_ws

        self.worksheet_patch = patch("modules.payroll.drivers.get_worksheet", side_effect=worksheet)
        self.worksheet_patch.start()

    def tearDown(self):
        self.worksheet_patch.stop()

    def test_create_select_and_filter_driver_payments(self):
        driver = drivers.create_driver("Иван Иванов", "+79990000000", created_by="Менеджер")
        self.assertEqual(drivers.get_driver(driver["driver_id"])["full_name"], "Иван Иванов")

        included = drivers.add_driver_payment(driver, "05.09.2026", 3500, "Доставка", "Менеджер")
        drivers.add_driver_payment(driver, "20.09.2026", 1000, "Поздняя", "Менеджер")

        actual = drivers.get_driver_payments("01.09.2026", "15.09.2026")
        self.assertEqual([item["driver_payment_id"] for item in actual], [included["driver_payment_id"]])

    def test_driver_payment_has_separate_total_in_payroll_statement(self):
        payment = {
            "driver_name": "Иван Иванов", "amount": 3500,
            "date": "05.09.2026", "comment": "Доставка",
        }
        period = {"start_date": "01.09.2026", "end_date": "15.09.2026", "payment_mode": "hourly"}
        with (
            patch("modules.payroll.calculations.calculate_payroll_for_period", return_value={}),
            patch("modules.payroll.drivers.get_driver_payments", return_value=[payment]),
        ):
            text = build_full_payroll_text(period)

        self.assertIn("Водители:", text)
        self.assertIn("Иван Иванов: 3 500,00", text)
        self.assertIn("ИТОГО ВОДИТЕЛИ: 3 500,00", text)
        self.assertIn("ОБЩИЙ ИТОГ: 0,00", text)
