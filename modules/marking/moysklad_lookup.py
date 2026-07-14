import logging

from modules.marking.duplicate_chz import extract_gtin
from modules.marking.export import build_moysklad_client, response_rows
from modules.moysklad.client import MoySkladError


SIZE_NAMES = {"размер", "size"}
COUNTRY_NAMES = {"страна производства", "страна", "country"}


def find_marking_product_info(raw_code):
    gtin = extract_gtin(raw_code)
    if not gtin:
        return {}

    try:
        client = build_moysklad_client()
    except MoySkladError:
        logging.exception("Не удалось создать клиент МойСклад для поиска ЧЗ")
        return {}

    for entity_type in ("assortment", "variant", "product"):
        for row in lookup_rows_by_gtin(client, entity_type, gtin):
            if not barcode_matches(row, gtin):
                continue
            return product_info_from_row(client, row)

    return {}


def lookup_rows_by_gtin(client, entity_type, gtin):
    attempts = [
        {"filter": f"barcode={gtin}", "limit": 10, "expand": "country,product,product.country"},
        {"filter": f"barcode={gtin}", "limit": 10},
    ]
    for params in attempts:
        try:
            payload = client.list_entities(entity_type, params=params)
            rows = response_rows(payload)
            if rows:
                return rows
        except MoySkladError:
            logging.exception("Ошибка поиска товара в МойСклад: entity=%s", entity_type)
    return []


def barcode_matches(row, gtin):
    for barcode in row.get("barcodes") or []:
        if not isinstance(barcode, dict):
            continue
        for value in barcode.values():
            if str(value or "").strip() == gtin:
                return True
    return False


def product_info_from_row(client, row):
    product = expand_meta_object(client, row.get("product")) or {}
    country = country_name(client, row) or country_name(client, product)
    size = size_from_characteristics(row) or size_from_attributes(row) or size_from_attributes(product)
    model_name = str((product or {}).get("name") or row.get("name") or "").strip()

    return {
        "model_name": model_name,
        "size": size,
        "country": country,
    }


def expand_meta_object(client, value):
    if not isinstance(value, dict):
        return {}
    if value.get("name"):
        return value

    meta = value.get("meta") or {}
    href = meta.get("href")
    if not href:
        return value

    try:
        return client.get_href(href, params={"expand": "country"})
    except MoySkladError:
        logging.exception("Не удалось раскрыть ссылку МойСклад")
        return value


def country_name(client, row):
    direct = row.get("country")
    if isinstance(direct, dict):
        if direct.get("name"):
            return str(direct.get("name") or "").strip()
        expanded = expand_meta_object(client, direct)
        if expanded.get("name"):
            return str(expanded.get("name") or "").strip()

    value = attribute_value(row, COUNTRY_NAMES)
    return str(value or "").strip()


def size_from_characteristics(row):
    for item in row.get("characteristics") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name in SIZE_NAMES:
            return str(item.get("value") or "").strip()
    return ""


def size_from_attributes(row):
    value = attribute_value(row, SIZE_NAMES)
    return str(value or "").strip()


def attribute_value(row, wanted_names):
    for item in row.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name not in wanted_names:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            return value.get("name") or value.get("value") or ""
        return value
    return ""
