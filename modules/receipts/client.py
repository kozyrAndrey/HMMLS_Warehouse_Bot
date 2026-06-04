import gzip
import json
import ssl
import urllib.parse
import urllib.request

import certifi

from config import MOYSKLAD_CA_BUNDLE


class MoyskladError(RuntimeError):
    pass


class MoyskladClient:
    BASE_URL = "https://api.moysklad.ru/api/remap/1.2"

    def __init__(self, token):
        self.token = token
        self.ssl_context = ssl.create_default_context(
            cafile=MOYSKLAD_CA_BUNDLE or certifi.where()
        )

    def _request(self, method, path, payload=None, params=None):
        if not self.token:
            raise MoyskladError("Не указан MOYSKLAD_API_TOKEN.")

        url = f"{self.BASE_URL}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;charset=utf-8",
            "Accept-Encoding": "gzip",
        }

        if data is not None:
            headers["Content-Type"] = "application/json;charset=utf-8"

        request = urllib.request.Request(
            url=url,
            data=data,
            method=method,
            headers=headers,
        )

        try:
            with urllib.request.urlopen(request, timeout=30, context=self.ssl_context) as response:
                body_bytes = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body_bytes = gzip.decompress(body_bytes)
                body = body_bytes.decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body_bytes = error.read()
            if error.headers.get("Content-Encoding") == "gzip":
                error_body_bytes = gzip.decompress(error_body_bytes)
            error_body = error_body_bytes.decode("utf-8", errors="replace")
            raise MoyskladError(f"МойСклад API вернул ошибку {error.code}: {error_body}") from error
        except ssl.SSLCertVerificationError as error:
            raise MoyskladError(
                "Не удалось проверить SSL-сертификат МойСклад. "
                "По умолчанию бот использует certifi; если в сети есть корпоративный "
                "сертификат, укажите путь к нему в MOYSKLAD_CA_BUNDLE."
            ) from error
        except urllib.error.URLError as error:
            raise MoyskladError(f"Не удалось подключиться к МойСклад API: {error}") from error

        if not body:
            return {}

        return json.loads(body)

    def get_customer_order_metadata(self):
        return self._request("GET", "/entity/customerorder/metadata")

    def get_customer_order_metadata_attributes(self):
        data = self._request("GET", "/entity/customerorder/metadata/attributes")
        return data.get("rows", [])

    def find_customer_orders_by_name(self, name, limit=10):
        data = self._request(
            "GET",
            "/entity/customerorder",
            params={
                "search": name,
                "limit": limit,
                "expand": "agent,organization,state",
            },
        )

        rows = data.get("rows", [])
        exact = [row for row in rows if str(row.get("name", "")).strip() == name.strip()]
        return exact or rows

    def get_customer_order(self, order_id):
        return self._request(
            "GET",
            f"/entity/customerorder/{order_id}",
            params={"expand": "agent,organization,state"},
        )

    def get_customer_order_positions(self, order_id):
        data = self._request(
            "GET",
            f"/entity/customerorder/{order_id}/positions",
            params={"expand": "assortment"},
        )
        return data.get("rows", [])

    def get_position_tracking_codes(self, entity_type, entity_id, position_id):
        data = self._request(
            "GET",
            f"/entity/{entity_type}/{entity_id}/positions/{position_id}/trackingCodes",
        )
        return data.get("rows", [])

    def upsert_position_tracking_codes(self, entity_type, entity_id, position_id, codes):
        payload = [
            {
                "cis": code,
                "type": "trackingcode",
            }
            for code in codes
        ]
        return self._request(
            "POST",
            f"/entity/{entity_type}/{entity_id}/positions/{position_id}/trackingCodes",
            payload=payload,
        )

    def update_customer_order_attributes(self, order_id, attributes):
        return self._request(
            "PUT",
            f"/entity/customerorder/{order_id}",
            payload={"attributes": attributes},
        )
