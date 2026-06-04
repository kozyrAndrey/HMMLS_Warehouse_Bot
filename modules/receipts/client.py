import json
import urllib.parse
import urllib.request


class MoyskladError(RuntimeError):
    pass


class MoyskladClient:
    BASE_URL = "https://api.moysklad.ru/api/remap/1.2"

    def __init__(self, token):
        self.token = token

    def _request(self, method, path, payload=None, params=None):
        if not self.token:
            raise MoyskladError("Не указан MOYSKLAD_API_TOKEN.")

        url = f"{self.BASE_URL}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json;charset=utf-8",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise MoyskladError(f"МойСклад API вернул ошибку {error.code}: {error_body}") from error
        except urllib.error.URLError as error:
            raise MoyskladError(f"Не удалось подключиться к МойСклад API: {error}") from error

        if not body:
            return {}

        return json.loads(body)

    def get_customer_order_metadata(self):
        return self._request("GET", "/entity/customerorder/metadata")

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

    def update_customer_order_attributes(self, order_id, attributes):
        return self._request(
            "PUT",
            f"/entity/customerorder/{order_id}",
            payload={"attributes": attributes},
        )
