import gzip
import ssl
import urllib.parse
import urllib.request

import certifi

from config import (
    MOYSKLAD_CA_BUNDLE,
    NIRGUNA_ATOL_ACCOUNT_ID,
    NIRGUNA_ATOL_BASE_URL,
    NIRGUNA_ATOL_COOKIE,
    NIRGUNA_ATOL_TOKEN,
    NIRGUNA_ATOL_UID,
    NIRGUNA_MARKING_BUTTON_ID,
)


class NirgunaError(RuntimeError):
    pass


def is_configured():
    return bool(NIRGUNA_ATOL_ACCOUNT_ID and NIRGUNA_ATOL_UID and NIRGUNA_ATOL_TOKEN)


class NirgunaAtolClient:
    def __init__(self):
        self.base_url = NIRGUNA_ATOL_BASE_URL.rstrip("/")
        self.ssl_context = ssl.create_default_context(
            cafile=MOYSKLAD_CA_BUNDLE or certifi.where()
        )

    def _read_response(self, response):
        body_bytes = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body_bytes = gzip.decompress(body_bytes)
        return body_bytes.decode("utf-8", errors="replace")

    def submit_marking_codes(self, order_id, codes):
        if not is_configured():
            raise NirgunaError(
                "Не настроены NIRGUNA_ATOL_ACCOUNT_ID, NIRGUNA_ATOL_UID или NIRGUNA_ATOL_TOKEN."
            )

        query = urllib.parse.urlencode(
            {
                "accountId": NIRGUNA_ATOL_ACCOUNT_ID,
                "uid": NIRGUNA_ATOL_UID,
                "entity": "customerorder",
                "token": NIRGUNA_ATOL_TOKEN,
                "objectId": order_id,
            }
        )
        url = f"{self.base_url}/1/knopki/click.php?{query}"

        form_items = [
            ("buttonId", NIRGUNA_MARKING_BUTTON_ID),
            ("popupFormParameters[var3][]", ""),
        ]
        for code in codes:
            form_items.append(("popupFormParameters[var3][1][]", code))

        data = urllib.parse.urlencode(form_items).encode("utf-8")
        headers = {
            "Accept": "text/html, */*; q=0.01",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0",
        }
        if NIRGUNA_ATOL_COOKIE:
            headers["Cookie"] = NIRGUNA_ATOL_COOKIE

        request = urllib.request.Request(
            url=url,
            data=data,
            method="POST",
            headers=headers,
        )

        try:
            with urllib.request.urlopen(request, timeout=30, context=self.ssl_context) as response:
                return self._read_response(response)
        except urllib.error.HTTPError as error:
            body = self._read_response(error)
            if error.code == 403:
                hint = (
                    "Доступ запрещён. Чаще всего это означает, что NIRGUNA_ATOL_TOKEN "
                    "устарел или backend Nirguna требует cookie/заголовки из браузерной сессии."
                )
                if not NIRGUNA_ATOL_COOKIE:
                    hint += " Если в успешном browser-запросе есть Cookie, добавьте его в NIRGUNA_ATOL_COOKIE."
                raise NirgunaError(f"Nirguna АТОЛ вернул ошибку 403. {hint}") from error

            raise NirgunaError(f"Nirguna АТОЛ вернул ошибку {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise NirgunaError(f"Не удалось подключиться к Nirguna АТОЛ: {error}") from error
