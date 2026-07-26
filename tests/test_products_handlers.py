import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import ConversationHandler

from modules.products.handlers import (
    PRODUCT_ADD_CONFIRM,
    PRODUCT_ADD_CHZ_NAME,
    PRODUCT_ADD_GTIN,
    PRODUCT_ADD_RULE_SELECT,
    product_add_confirmed,
    product_add_category_selected,
    product_add_gtin_received,
    product_add_marking_selected,
)


class ProductWizardTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_category_is_selected_from_keyboard(self):
        query = SimpleNamespace(data="prodcat:hoodies", answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data={"product_add": {}})

        with patch("modules.products.handlers.CATEGORIES", {"hoodies": {"name": "Худи"}}):
            state = await product_add_category_selected(SimpleNamespace(callback_query=query), context)

        self.assertEqual(context.user_data["product_add"]["category_name"], "Худи")
        self.assertIn("модели", query.edit_message_text.await_args.args[0])
    async def test_marked_product_requests_base_honest_sign_name(self):
        query = SimpleNamespace(data="prodmark:yes", answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data={"product_add": {"sizes": ["S"]}})

        state = await product_add_marking_selected(SimpleNamespace(callback_query=query), context)

        self.assertEqual(state, PRODUCT_ADD_CHZ_NAME)
        self.assertTrue(context.user_data["product_add"]["is_marked"])
        self.assertIn("базовое название", query.edit_message_text.await_args.args[0])

    async def test_gtin_uses_base_name_with_size(self):
        message = SimpleNamespace(text="04670332744239", reply_text=AsyncMock())
        context = SimpleNamespace(
            user_data={
                "product_add": {
                    "sizes": ["S"],
                    "marking_index": 0,
                    "marking": [],
                    "chz_base_name": 'ХУДИ "TEST"',
                }
            }
        )

        with (
            patch("modules.products.handlers.get_honest_sign_product", return_value=None),
            patch("modules.products.handlers.prompt_product_rules", new=AsyncMock(return_value=PRODUCT_ADD_RULE_SELECT)),
        ):
            state = await product_add_gtin_received(SimpleNamespace(message=message), context)

        self.assertEqual(state, PRODUCT_ADD_RULE_SELECT)
        marking = context.user_data["product_add"]["marking"]
        self.assertEqual(marking[0]["size"], "S")
        self.assertEqual(marking[0]["honest_sign_name"], 'ХУДИ "TEST" S')

    async def test_confirmation_saves_catalog_marking_and_consumable_rule(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        context = SimpleNamespace(
            user_data={
                "product_add": {
                    "category_name": "Худи",
                    "model_name": "TEST HOODIE",
                    "color": "BLACK",
                    "is_marked": True,
                    "marking": [
                        {
                            "gtin": "04670332744239",
                            "size": "S",
                            "honest_sign_name": "TEST S",
                        }
                    ],
                    "consumable_rules": [
                        {"item_id": 7, "item_name": "Пакет", "unit": "шт", "quantity": 1},
                    ],
                }
            }
        )
        product = {
            "product_id": "custom_test",
            "product_name": "TEST HOODIE BLACK",
            "category_name": "Худи",
            "model_name": "TEST HOODIE",
            "color": "BLACK",
        }

        with (
            patch("modules.products.handlers.add_custom_product", return_value=product),
            patch("modules.products.handlers.upsert_honest_sign_products") as save_marking,
            patch("modules.products.handlers.set_product_consumable_rule") as save_rule,
        ):
            state = await product_add_confirmed(SimpleNamespace(callback_query=query), context)

        self.assertEqual(state, ConversationHandler.END)
        save_marking.assert_called_once_with([
            {"gtin": "04670332744239", "size": "S", "honest_sign_name": "TEST S"}
        ])
        save_rule.assert_called_once_with("custom_test", "TEST HOODIE BLACK", 7, 1)
        self.assertNotIn("product_add", context.user_data)


if __name__ == "__main__":
    unittest.main()
