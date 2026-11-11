import unittest
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from modules.shipping.excel import create_shipping_xlsx
from modules.shipping.storage import ShippingRecord, get_shipping_by_order, save_shipping_record


class ShippingStorageExcelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        ShippingRecord.metadata.create_all(self.engine, tables=[ShippingRecord.__table__])

        @contextmanager
        def test_scope():
            with Session(self.engine, expire_on_commit=False) as session:
                yield session
                session.commit()

        self.scope_patch = patch("modules.shipping.storage.session_scope", test_scope)
        self.scope_patch.start()

    def tearDown(self):
        self.scope_patch.stop()
        self.engine.dispose()

    @staticmethod
    def data(shipping_type="cdek"):
        return {
            "moysklad_order_id": "order-1",
            "order_number": "mind-100",
            "shipping_type": shipping_type,
            "order_snapshot": [
                {"position_id": "p1", "name": "Куртка", "quantity": 2, "gtin": "04601234567893"},
                {"position_id": "p2", "name": "Ремень", "quantity": 1, "gtin": ""},
            ],
            "marking_codes": [
                {"position_id": "p1", "product_name": "Куртка", "gtin": "04601234567893", "raw_code": "FULL-1"},
                {"position_id": "p1", "product_name": "Куртка", "gtin": "04601234567893", "raw_code": "FULL-2"},
            ],
            "collector_employee_id": "emp-1",
            "collector_name": "Сборщик",
            "created_by_employee_id": "emp-2",
            "created_by_name": "Оператор",
            "created_by_user_id": "42",
            "moysklad_demand_id": "demand-1",
            "moysklad_demand_name": "00001",
            "assembled_at": datetime(2026, 11, 11, 12, 30),
        }

    def test_repeat_save_updates_single_order_record(self):
        save_shipping_record(self.data())
        save_shipping_record(self.data("pickup"))
        record = get_shipping_by_order(order_id="order-1")
        self.assertEqual(record["shipping_type"], "pickup")

    def test_excel_uses_one_sheet_and_one_row_per_order_position(self):
        save_shipping_record(self.data())
        content = create_shipping_xlsx([get_shipping_by_order(order_id="order-1")])
        workbook = load_workbook(BytesIO(content))
        self.assertEqual(workbook.sheetnames, ["Отправления"])
        sheet = workbook["Отправления"]
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(sheet["B2"].value, "mind-100")
        self.assertEqual(sheet["B3"].value, "mind-100")
        self.assertEqual(sheet["F2"].value, "Куртка")
        self.assertEqual(sheet["F3"].value, "Ремень")
        self.assertEqual(sheet["G2"].value, 2)
        self.assertEqual(sheet["I2"].value, 2)
        self.assertEqual(sheet["J2"].value, "FULL-1\nFULL-2")
        self.assertIsNone(sheet["J3"].value)


if __name__ == "__main__":
    unittest.main()
