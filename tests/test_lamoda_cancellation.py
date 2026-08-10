import unittest
from datetime import date

from modules.lamoda_fbs.email_cancellations import (
    RETURNS,
    SHIPMENT,
    cancellation_email,
    count_outbound_orders,
    count_ready_returns,
    normalize_status,
)


class LamodaCancellationTests(unittest.TestCase):
    def test_status_normalization_supports_api_spelling_variants(self):
        self.assertEqual(normalize_status("Ready for shipment"), "READY_FOR_SHIPMENT")
        self.assertEqual(normalize_status("ready_for_shipment"), "READY_FOR_SHIPMENT")

    def test_outbound_count_includes_new_and_already_prepared_orders(self):
        orders = [
            {"status": "confirmed"},
            {"status": "AWAITING_SHIPMENT"},
            {"status": "Ready for shipment"},
            {"status": "SHIPPED_TO_WH"},
            {"status": "CANCELED"},
        ]
        self.assertEqual(count_outbound_orders(orders), 3)

    def test_only_ready_to_return_items_prevent_return_cancellation(self):
        rows = [
            {"status": "CREATED"},
            {"status": "READY_TO_RETURN"},
            {"status": "SHIPPED"},
        ]
        self.assertEqual(count_ready_returns(rows), 1)

    def test_separate_email_templates_are_clear(self):
        service_date = date(2026, 8, 11)
        shipment_subject, shipment_body = cancellation_email(SHIPMENT, service_date)
        returns_subject, returns_body = cancellation_email(RETURNS, service_date)

        self.assertEqual(shipment_subject, "Отмена забора отгрузки на 11.08.2026")
        self.assertIn("отсутствием заказов", shipment_body)
        self.assertEqual(returns_subject, "Отмена забора возвратов на 11.08.2026")
        self.assertIn("готовых к возврату", returns_body)


if __name__ == "__main__":
    unittest.main()
