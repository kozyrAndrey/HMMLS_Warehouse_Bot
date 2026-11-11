import re
import uuid
from decimal import Decimal, InvalidOperation

from modules.marking.duplicate_chz import GROUP_SEPARATOR, normalize_chz_text
from modules.moysklad.client import MoySkladError


PAGE_LIMIT = 100
GTIN_CHARACTERISTIC_NAMES = {"gtin", "гтин"}


class ShippingValidationError(ValueError):
    pass


class ShippingServiceError(RuntimeError):
    pass


def response_rows(payload):
    return payload.get("rows", []) if isinstance(payload, dict) else []


def all_pages(fetch_page, params=None):
    rows = []
    offset = 0
    while True:
        payload = fetch_page({**(params or {}), "limit": PAGE_LIMIT, "offset": offset})
        page = response_rows(payload)
        rows.extend(page)
        offset += len(page)
        size = int((payload.get("meta") or {}).get("size") or 0) if isinstance(payload, dict) else 0
        if not page or len(page) < PAGE_LIMIT or (size and offset >= size):
            return rows


def parse_order_number(value):
    value = str(value or "").strip()
    if not value:
        raise ShippingValidationError("Номер заказа не должен быть пустым.")
    if len(value) > 255:
        raise ShippingValidationError("Номер заказа слишком длинный.")
    return value


def search_customer_orders(client, query):
    query = parse_order_number(query)
    found = {}
    attempts = (
        {"filter": f"name={query}"},
        {"search": query},
    )
    try:
        for params in attempts:
            for order in all_pages(lambda page: client.list_entities("customerorder", page), params):
                order_id = str(order.get("id") or "").strip()
                if order_id:
                    found[order_id] = order
            if any(str(row.get("name") or "").strip() == query for row in found.values()):
                break
    except MoySkladError as error:
        raise ShippingServiceError(str(error)) from error

    exact = [row for row in found.values() if str(row.get("name") or "").strip() == query]
    rows = exact or [row for row in found.values() if query.casefold() in str(row.get("name") or "").casefold()]
    rows.sort(key=lambda row: str(row.get("name") or "").casefold())
    return rows


def entity_id(value):
    if not isinstance(value, dict):
        return ""
    if value.get("id"):
        return str(value["id"])
    href = str((value.get("meta") or {}).get("href") or "").rstrip("/")
    return href.rsplit("/", 1)[-1] if href else ""


def expanded_reference(client, value, cache):
    if not isinstance(value, dict):
        return {}
    href = str((value.get("meta") or {}).get("href") or "").strip()
    if value.get("barcodes") is not None and (value.get("name") or not href):
        return value
    if href:
        if href not in cache:
            cache[href] = client.get_href(href)
        return {**value, **(cache[href] or {})}
    return value


def normalize_gtin(value):
    value = str(value or "").strip()
    if len(value) == 13 and value.isdigit():
        value = "0" + value
    return value if len(value) == 14 and value.isdigit() else ""


def characteristic_gtin(assortment):
    for characteristic in (assortment or {}).get("characteristics") or []:
        name = str(characteristic.get("name") or "").strip().casefold()
        if name not in GTIN_CHARACTERISTIC_NAMES:
            continue
        value = characteristic.get("value")
        if isinstance(value, dict):
            value = value.get("name") or value.get("value")
        gtin = normalize_gtin(value)
        if gtin:
            return gtin
    return ""


def gtin_from_assortment(assortment):
    """EAN-13 без отдельного GTIN не делает позицию маркируемой."""
    characteristic = characteristic_gtin(assortment)
    if characteristic:
        return characteristic
    for barcode in (assortment or {}).get("barcodes") or []:
        if isinstance(barcode, dict) and barcode.get("gtin"):
            gtin = normalize_gtin(barcode["gtin"])
            if gtin:
                return gtin
    return ""


def integer_quantity(position):
    try:
        quantity = Decimal(str(position.get("quantity") or 0))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ShippingServiceError("В заказе указано некорректное количество товара.") from error
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise ShippingServiceError("Поддерживается только положительное целое количество товара.")
    return int(quantity)


def get_order_positions(client, order_id):
    try:
        return all_pages(
            lambda params: client.get_positions("customerorder", order_id, params=params),
            {"expand": "assortment,assortment.product"},
        )
    except MoySkladError as error:
        raise ShippingServiceError(str(error)) from error


def build_order_snapshot(client, order):
    order_id = str(order.get("id") or "").strip()
    if not order_id:
        raise ShippingServiceError("У заказа отсутствует идентификатор МойСклад.")
    positions = get_order_positions(client, order_id)
    if not positions:
        raise ShippingServiceError("В заказе нет товарных позиций.")

    cache = {}
    snapshot = []
    units = []
    for position in positions:
        assortment = expanded_reference(client, position.get("assortment") or {}, cache)
        assortment_type = str((assortment.get("meta") or {}).get("type") or "").casefold()
        if assortment_type == "service":
            continue
        quantity = integer_quantity(position)
        gtin = gtin_from_assortment(assortment)
        name = str(assortment.get("name") or "Без названия").strip()
        item = {
            "position_id": str(position.get("id") or ""),
            "assortment_id": entity_id(assortment),
            "name": name,
            "quantity": quantity,
            "gtin": gtin,
            "marked": bool(gtin),
        }
        snapshot.append(item)
        if gtin:
            for unit_number in range(1, quantity + 1):
                units.append({**item, "unit_number": unit_number})
    if not snapshot:
        raise ShippingServiceError("В заказе нет товарных позиций; услуги и доставка пропущены.")
    return {"snapshot": snapshot, "units": units}


def gtin_check_digit_is_valid(gtin):
    value = str(gtin or "")
    if len(value) != 14 or not value.isdigit():
        return False
    total = sum(
        int(digit) * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(value[:-1]))
    )
    return (10 - total % 10) % 10 == int(value[-1])


def parenthesized_values(code):
    return {
        ai: value.strip(GROUP_SEPARATOR)
        for ai, value in re.findall(r"\((01|21|91|92)\)([^()]*)", code)
    }


def plain_values(code):
    if not code.startswith("01") or len(code) < 31 or code[16:18] != "21":
        raise ShippingValidationError("Код должен содержать AI 01 и AI 21.")
    gtin, serial = code[2:16], code[18:31]
    tail = code[31:].strip(GROUP_SEPARATOR)
    if not tail.startswith("91"):
        raise ShippingValidationError("В полном DataMatrix не найден AI 91.")
    crypto = tail[2:]
    if GROUP_SEPARATOR in crypto:
        value91, rest = crypto.split(GROUP_SEPARATOR, 1)
        rest = rest.lstrip(GROUP_SEPARATOR)
        if not rest.startswith("92"):
            raise ShippingValidationError("После AI 91 не найден AI 92.")
        value92 = rest[2:].strip(GROUP_SEPARATOR)
    else:
        marker = crypto.find("92", 1)
        if marker < 0:
            raise ShippingValidationError("После AI 91 не найден AI 92.")
        value91, value92 = crypto[:marker], crypto[marker + 2:]
    return {"01": gtin, "21": serial, "91": value91, "92": value92}


def parse_marking_code(raw_code, expected_gtin):
    normalized = normalize_chz_text(raw_code).strip()
    if not normalized:
        raise ShippingValidationError("Код маркировки пустой.")
    values = parenthesized_values(normalized) if "(01)" in normalized else plain_values(normalized)
    gtin = str(values.get("01") or "")
    serial = str(values.get("21") or "").strip(GROUP_SEPARATOR)
    if not gtin_check_digit_is_valid(gtin):
        raise ShippingValidationError("В DataMatrix указан некорректный GTIN.")
    if len(serial) != 13:
        raise ShippingValidationError("AI 21 должен содержать 13 символов.")
    if not values.get("91") or not values.get("92"):
        raise ShippingValidationError("Нужен полный DataMatrix с AI 91 и AI 92.")
    expected = normalize_gtin(expected_gtin)
    if gtin != expected:
        raise ShippingValidationError(f"GTIN кода {gtin} не совпадает с GTIN товара {expected}.")
    return {
        "raw_code": normalized,
        "short_code": f"01{gtin}21{serial}",
        "gtin": gtin,
        "serial": serial,
    }


def linked_demands(client, order):
    result = {}
    for reference in order.get("demands") or []:
        href = str(((reference or {}).get("meta") or {}).get("href") or "")
        if href:
            demand = client.get_href(href)
            if demand.get("id"):
                result[str(demand["id"])] = demand
    order_href = str((order.get("meta") or {}).get("href") or "")
    if order_href:
        try:
            for demand in all_pages(
                lambda params: client.list_entities("demand", params),
                {"filter": f"customerOrder={order_href}"},
            ):
                if demand.get("id"):
                    result[str(demand["id"])] = demand
        except MoySkladError:
            pass
    return list(result.values())


def inspect_order_demands(client, order_id):
    try:
        order = client.get_entity("customerorder", str(order_id))
        return linked_demands(client, order)
    except MoySkladError as error:
        raise ShippingServiceError(str(error)) from error


def reference_meta(value):
    meta = dict((value or {}).get("meta") or {}) if isinstance(value, dict) else {}
    return {"meta": meta} if meta.get("href") else value


def demand_payload(template, sync_id, codes):
    payload = dict(template or {})
    for key in ("meta", "id", "accountId", "created", "updated", "deleted", "printed", "published", "sum", "payedSum", "files"):
        payload.pop(key, None)
    container = payload.pop("positions", {}) or {}
    source_positions = container.get("rows") or [] if isinstance(container, dict) else container
    codes_by_assortment = {}
    for code in codes:
        codes_by_assortment.setdefault(str(code.get("assortment_id") or ""), []).append(code["short_code"])
    positions = []
    for source in source_positions:
        position = dict(source or {})
        for key in ("meta", "id", "accountId", "overhead", "trackingCodes", "trackingCodes1162"):
            position.pop(key, None)
        position["assortment"] = reference_meta(position.get("assortment"))
        assortment_id = entity_id(position.get("assortment") or {})
        available_codes = codes_by_assortment.get(assortment_id, [])
        try:
            quantity = int(Decimal(str(position.get("quantity") or 0)))
        except (InvalidOperation, TypeError, ValueError):
            quantity = 0
        marking_codes = available_codes[:quantity]
        remaining_codes = available_codes[quantity:]
        if remaining_codes:
            codes_by_assortment[assortment_id] = remaining_codes
        else:
            codes_by_assortment.pop(assortment_id, None)
        if marking_codes:
            position["trackingCodes"] = [
                {"cis": code, "type": "trackingcode"}
                for code in marking_codes
            ]
        positions.append(position)
    if any(codes_by_assortment.values()):
        raise ShippingServiceError("Не удалось сопоставить часть кодов ЧЗ позициям отгрузки.")
    payload["positions"] = positions
    for key in ("agent", "organization", "store", "group", "owner", "customerOrder", "salesChannel", "contract", "project", "state", "organizationAccount", "agentAccount"):
        if key in payload:
            payload[key] = reference_meta(payload[key])
    payload["syncId"] = str(uuid.UUID(str(sync_id)))
    payload["applicable"] = True
    return payload


def create_or_replace_demand(client, order_id, sync_id, codes, replace_existing=False):
    try:
        order = client.get_entity("customerorder", str(order_id))
        order_meta = dict(order.get("meta") or {})
        if not order_meta.get("href"):
            raise ShippingServiceError("У заказа отсутствуют метаданные МойСклад.")
        demands = linked_demands(client, order)
        current = next((row for row in demands if str(row.get("syncId") or "") == str(sync_id)), None)
        old = [row for row in demands if row is not current]
        if old and not replace_existing:
            raise ShippingServiceError("Для заказа уже существует отгрузка.")
        if current:
            if old and not replace_existing:
                raise ShippingServiceError("Для заказа уже существует другая отгрузка.")
            if not current.get("applicable"):
                current = client.update_entity("demand", current["id"], {"applicable": True})
            for demand in old:
                if demand.get("applicable"):
                    client.update_entity("demand", demand["id"], {"applicable": False})
                client.move_entity_to_trash("demand", demand["id"])
            return current

        template = client.put("entity/demand/new", {"customerOrder": {"meta": order_meta}})
        changed = []
        for demand in old:
            if demand.get("applicable"):
                client.update_entity("demand", demand["id"], {"applicable": False})
                changed.append(demand)
        try:
            created = client.create_entity("demand", demand_payload(template, sync_id, codes))
        except Exception:
            for demand in changed:
                try:
                    client.update_entity("demand", demand["id"], {"applicable": True})
                except MoySkladError:
                    pass
            raise
        for demand in old:
            client.move_entity_to_trash("demand", demand["id"])
        return created
    except ShippingServiceError:
        raise
    except (MoySkladError, ValueError) as error:
        raise ShippingServiceError(str(error)) from error
