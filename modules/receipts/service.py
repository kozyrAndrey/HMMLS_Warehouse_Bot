import asyncio
from decimal import Decimal, InvalidOperation

from config import MOYSKLAD_API_TOKEN, MOYSKLAD_RECEIPT_LINK_ATTR_NAME
from modules.receipts.client import MoyskladClient, MoyskladError


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
    metadata = await asyncio.to_thread(get_client().get_customer_order_metadata)
    for attribute in metadata.get("attributes", []):
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
    assortment = position.get("assortment") or {}
    name = assortment.get("name") or position.get("name") or "Позиция"
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
