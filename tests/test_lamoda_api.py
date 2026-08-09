import unittest
from unittest.mock import AsyncMock, patch

import httpx

from modules.lamoda_fbs.client import LamodaClient, LamodaTemporaryError


class LamodaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_is_cached_and_orders_are_paginated(self):
        calls = {"token": 0, "orders": 0}

        async def handler(request):
            if request.url.path.endswith("/auth-token"):
                calls["token"] += 1
                return httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600})
            calls["orders"] += 1
            self.assertEqual(request.headers["Authorization"], "Bearer token-1")
            page = int(request.url.params["page"])
            return httpx.Response(200, json={
                "data": {"items": [{"orderId": f"order-{page}"}], "pagination": {"totalPages": 2}}
            })

        client = LamodaClient("id", "secret", "seller", "https://lamoda.test/api", transport=httpx.MockTransport(handler))
        try:
            rows = await client.list_orders()
            self.assertEqual([row["orderId"] for row in rows], ["order-1", "order-2"])
            self.assertEqual(calls, {"token": 1, "orders": 2})
        finally:
            await client.aclose()

    async def test_401_refreshes_token_once(self):
        calls = {"token": 0, "orders": 0}

        async def handler(request):
            if request.url.path.endswith("/auth-token"):
                calls["token"] += 1
                return httpx.Response(200, json={"access_token": f"token-{calls['token']}", "expires_in": 3600})
            calls["orders"] += 1
            if calls["orders"] == 1:
                return httpx.Response(401, json={"error": "expired"})
            self.assertEqual(request.headers["Authorization"], "Bearer token-2")
            return httpx.Response(200, json={"data": {"items": []}})

        client = LamodaClient("id", "secret", "seller", "https://lamoda.test/api", transport=httpx.MockTransport(handler))
        try:
            await client.list_orders()
            self.assertEqual(calls, {"token": 2, "orders": 2})
        finally:
            await client.aclose()

    async def test_safe_get_retries_503(self):
        calls = 0

        async def handler(request):
            nonlocal calls
            if request.url.path.endswith("/auth-token"):
                return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
            calls += 1
            if calls < 3:
                return httpx.Response(503, json={"error": "temporary"})
            return httpx.Response(200, json={"data": {"orderId": "1"}})

        client = LamodaClient("id", "secret", "seller", "https://lamoda.test/api", transport=httpx.MockTransport(handler))
        try:
            with patch("modules.lamoda_fbs.client.asyncio.sleep", new=AsyncMock()):
                result = await client.get_order("1")
            self.assertEqual(result["orderId"], "1")
            self.assertEqual(calls, 3)
        finally:
            await client.aclose()

    async def test_non_idempotent_post_is_not_retried_after_timeout(self):
        calls = 0

        async def handler(request):
            nonlocal calls
            if request.url.path.endswith("/auth-token"):
                return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
            calls += 1
            raise httpx.ReadTimeout("timeout", request=request)

        client = LamodaClient("id", "secret", "seller", "https://lamoda.test/api", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(LamodaTemporaryError) as caught:
                await client.create_shipment("2026-01-01T00:00:00Z", [])
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(calls, 1)
        finally:
            await client.aclose()

    async def test_non_idempotent_post_is_not_replayed_after_401(self):
        calls = {"token": 0, "shipment": 0}

        async def handler(request):
            if request.url.path.endswith("/auth-token"):
                calls["token"] += 1
                return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
            calls["shipment"] += 1
            return httpx.Response(401, json={"error": "expired"})

        client = LamodaClient("id", "secret", "seller", "https://lamoda.test/api", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(Exception):
                await client.create_shipment("2026-01-01T00:00:00Z", [])
            self.assertEqual(calls, {"token": 1, "shipment": 1})
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
