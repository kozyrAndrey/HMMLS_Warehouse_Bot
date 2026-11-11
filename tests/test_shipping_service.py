import unittest

from modules.shipping.service import (
    ShippingValidationError,
    demand_payload,
    gtin_from_assortment,
    parse_marking_code,
)


VALID_GTIN = "04601234567893"
FULL_CODE = f"01{VALID_GTIN}21ABCDEFGHIJKLM91ABCD\x1d92SIGNATURE"


class ShippingServiceTests(unittest.TestCase):
    def test_only_explicit_gtin_marks_product(self):
        self.assertEqual(gtin_from_assortment({"barcodes": [{"ean13": "4601234567893"}]}), "")
        self.assertEqual(gtin_from_assortment({"barcodes": [{"gtin": VALID_GTIN}]}), VALID_GTIN)
        self.assertEqual(
            gtin_from_assortment({
                "barcodes": [{"ean13": "4601234567893"}],
                "characteristics": [{"name": "GTIN", "value": VALID_GTIN}],
            }),
            VALID_GTIN,
        )

    def test_datamatrix_format_and_gtin_are_checked(self):
        parsed = parse_marking_code(FULL_CODE, VALID_GTIN)
        self.assertEqual(parsed["short_code"], f"01{VALID_GTIN}21ABCDEFGHIJKLM")
        with self.assertRaisesRegex(ShippingValidationError, "не совпадает"):
            parse_marking_code(FULL_CODE, "04670332744239")

    def test_datamatrix_rejects_cyrillic_but_allows_mixed_latin_case(self):
        with self.assertRaisesRegex(ShippingValidationError, "кириллица"):
            parse_marking_code(FULL_CODE.replace("A", "А", 1), VALID_GTIN)
        parsed = parse_marking_code(FULL_CODE.replace("A", "a", 1), VALID_GTIN)
        self.assertEqual(parsed["gtin"], VALID_GTIN)

    def test_demand_payload_accepts_duplicate_codes_and_uses_short_cis(self):
        template = {
            "positions": {"rows": [{
                "quantity": 2,
                "assortment": {"meta": {"href": "https://example/entity/product/product-1"}},
            }]},
        }
        code = {
            "assortment_id": "product-1",
            "short_code": f"01{VALID_GTIN}21ABCDEFGHIJKLM",
        }
        payload = demand_payload(
            template,
            "11111111-1111-4111-8111-111111111111",
            [code, code],
        )
        self.assertEqual(payload["positions"][0]["trackingCodes"], [
            {"cis": code["short_code"], "type": "trackingcode"},
            {"cis": code["short_code"], "type": "trackingcode"},
        ])


if __name__ == "__main__":
    unittest.main()
