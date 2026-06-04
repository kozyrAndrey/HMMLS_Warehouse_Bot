import asyncio
from decimal import Decimal, InvalidOperation

from config import MOYSKLAD_API_TOKEN, MOYSKLAD_RECEIPT_LINK_ATTR_NAME
from modules.receipts.client import MoyskladClient, MoyskladError
from modules.receipts.nirguna_client import NirgunaAtolClient, is_configured as nirguna_is_configured


def get_client():
    return MoyskladClient(MOYSKLAD_API_TOKEN)


async def find_orders_by_name(order_name):
    return await asyncio.to_thread(get_client().find_customer_orders_by_name, order_name)


async def get_order_positions(order_id):
    return await asyncio.to_thread(get_client().get_customer_order_positions, order_id)


async def get_order_with_positions(order_id):
    client = get_client()
    order = await asyncio.to_thread(client.get_customer_order, order_id)
    positions = await asyncio.to_thread(client.get_customer_order_positions, order_id)
    return order, positions


async def get_receipt_link_attribute_meta():
    attributes = await asyncio.to_thread(get_client().get_customer_order_metadata_attributes)
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue

        if attribute.get("name") == MOYSKLAD_RECEIPT_LINK_ATTR_NAME:
            return attribute.get("meta")

    raise MoyskladError(
        f"В Заказе покупателя не найдено доп. поле «{MOYSKLAD_RECEIPT_LINK_ATTR_NAME}»."
    )


def get_attribute_value(order, attr_name):
    for attribute in order.get("attributes", []) or []:
        if attribute.get("name") == attr_name:
            return attribute.get("value")
    return ""


async def set_receipt_link_value(order_id, value):
    attr_meta = await get_receipt_link_attribute_meta()
    payload = [
        {
            "meta": attr_meta,
            "value": value,
        }
    ]
    return await asyncio.to_thread(get_client().update_customer_order_attributes, order_id, payload)


async def clear_receipt_link(order_id):
    return await set_receipt_link_value(order_id, "")


async def mark_receipt_error(order_id):
    return await set_receipt_link_value(order_id, "error")


def get_position_name(position):
    assortment = position.get("assortment") or {}
    return assortment.get("name") or position.get("name") or "Позиция"


def is_service_position(position):
    assortment = position.get("assortment") or {}
    meta = assortment.get("meta") or {}
    return meta.get("type") == "service"


def position_units_count(position):
    quantity = position.get("quantity", 0)
    try:
        quantity_float = float(quantity)
    except (TypeError, ValueError):
        return 0

    if quantity_float <= 0:
        return 0

    return int(quantity_float)


def allocate_chz_codes_to_positions(positions, codes):
    assignments = []
    code_index = 0

    for position in positions:
        if code_index >= len(codes):
            break

        if is_service_position(position):
            continue

        units_count = position_units_count(position)
        if units_count <= 0:
            continue

        position_codes = codes[code_index : code_index + units_count]
        if not position_codes:
            continue

        assignments.append(
            {
                "position": position,
                "codes": position_codes,
            }
        )
        code_index += len(position_codes)

    extra_codes = codes[code_index:]
    return assignments, extra_codes


def is_tracking_codes_unsupported_error(error):
    text = str(error)
    return "17108" in text or "не может содержать коды маркировки" in text


async def save_chz_codes_to_order(order_id, positions, codes):
    if not codes:
        return "Коды ЧЗ не вводились, запись кодов в МойСклад пропущена."

    if nirguna_is_configured():
        response = await asyncio.to_thread(
            NirgunaAtolClient().submit_marking_codes,
            order_id,
            codes,
        )
        if "Коды маркировки обновлены успешно" in response:
            return f"Коды ЧЗ отправлены в приложение АТОЛ/Nirguna: {len(codes)}."

        return (
            "Коды ЧЗ отправлены в приложение АТОЛ/Nirguna, но ответ не похож на успешный:\n"
            f"{response[:700]}"
        )

    assignments, extra_codes = allocate_chz_codes_to_positions(positions, codes)
    if not assignments:
        return "Не нашёл товарных позиций для записи кодов ЧЗ."

    client = get_client()
    result_lines = []

    for assignment in assignments:
        position = assignment["position"]
        position_codes = assignment["codes"]
        position_id = position.get("id")

        if not position_id:
            result_lines.append(f"{get_position_name(position)}: нет id позиции, коды не записаны.")
            continue

        try:
            existing_codes = await asyncio.to_thread(
                client.get_position_tracking_codes,
                "customerorder",
                order_id,
                position_id,
            )
        except MoyskladError as error:
            if is_tracking_codes_unsupported_error(error):
                return (
                    "Коды собраны в боте, но не записаны в Заказ покупателя: "
                    "стандартный JSON API МойСклад не поддерживает `trackingCodes` "
                    "для документа `customerorder`. Для автоматической записи нужно "
                    "найти API/endpoint самого решения «Кнопки»/АТОЛ или другой документ, "
                    "куда решение читает маркировку."
                )
            raise

        existing_cis = {
            code.get("cis")
            for code in existing_codes
            if isinstance(code, dict) and code.get("cis")
        }
        new_codes = [code for code in position_codes if code not in existing_cis]

        if new_codes:
            await asyncio.to_thread(
                client.upsert_position_tracking_codes,
                "customerorder",
                order_id,
                position_id,
                new_codes,
            )

        skipped_count = len(position_codes) - len(new_codes)
        line = f"{get_position_name(position)}: записано {len(new_codes)}"
        if skipped_count:
            line += f", уже было {skipped_count}"
        result_lines.append(line)

    if extra_codes:
        result_lines.append(
            f"Не записано лишних кодов: {len(extra_codes)}. "
            "Кодов больше, чем товарных единиц в заказе."
        )

    return "\n".join(result_lines)


def money(value):
    try:
        return f"{Decimal(value or 0) / Decimal(100):.2f}"
    except (InvalidOperation, TypeError):
        return "0.00"


def format_order_title(order):
    name = order.get("name", "-")
    moment = str(order.get("moment", ""))[:10]
    state = (order.get("state") or {}).get("name", "")
    agent = (order.get("agent") or {}).get("name", "")
    sum_value = money(order.get("sum", 0))

    lines = [f"Заказ: {name}", f"Сумма: {sum_value}"]
    if moment:
        lines.append(f"Дата: {moment}")
    if state:
        lines.append(f"Статус: {state}")
    if agent:
        lines.append(f"Клиент: {agent}")
    return "\n".join(lines)


def format_position(position, index):
    name = get_position_name(position)
    quantity = position.get("quantity", 0)
    price = money(position.get("price", 0))
    return f"{index}. {name}\n   Кол-во: {quantity}; цена: {price}"


def format_positions(positions):
    if not positions:
        return "В заказе нет позиций."

    return "\n".join(
        format_position(position, index)
        for index, position in enumerate(positions, start=1)
    )


def normalize_chz_code(text):
    return str(text or "").strip()
