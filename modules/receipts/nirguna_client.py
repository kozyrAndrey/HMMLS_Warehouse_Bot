import gzip
import ssl
import urllib.parse
import urllib.request

import certifi

from config import (
    MOYSKLAD_CA_BUNDLE,
    NIRGUNA_ATOL_ACCOUNT_ID,
    NIRGUNA_ATOL_BASE_URL,
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
        request = urllib.request.Request(
            url=url,
            data=data,
            method="POST",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30, context=self.ssl_context) as response:
                return self._read_response(response)
        except urllib.error.HTTPError as error:
            body = self._read_response(error)
            raise NirgunaError(f"Nirguna АТОЛ вернул ошибку {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise NirgunaError(f"Не удалось подключиться к Nirguna АТОЛ: {error}") from error
