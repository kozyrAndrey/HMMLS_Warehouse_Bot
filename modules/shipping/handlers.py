import asyncio
import logging
import uuid
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from core.keyboards import build_shipping_menu_keyboard
from modules.employees.roles import has_any_role
from modules.marking.export import build_moysklad_client
from modules.payroll.google_sheets import find_employee_for_telegram_user, get_employees, is_manager
from modules.shipping.excel import create_shipping_xlsx
from modules.shipping.service import (
    ShippingServiceError,
    ShippingValidationError,
    build_order_snapshot,
    create_or_replace_demand,
    inspect_order_demands,
    parse_marking_code,
    search_customer_orders,
)
from modules.shipping.storage import (
    get_shipping_by_order,
    list_shipping_records,
    save_shipping_record,
)


logger = logging.getLogger(__name__)
MSK_TZ = ZoneInfo("Europe/Moscow")

(
    SHIPPING_ORDER_NUMBER,
    SHIPPING_ORDER_CHOICE,
    SHIPPING_EXISTING_DEMAND,
    SHIPPING_SCAN,
    SHIPPING_COLLECTOR,
    SHIPPING_REVIEW,
) = range(6100, 6106)


def shipping_type_label(value):
    return "СДЭК" if value == "cdek" else "Самовывоз"


def current_employee(update):
    return find_employee_for_telegram_user(update.effective_user)


def cancel_keyboard(back=None):
    rows = []
    if back:
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"shipping:back:{back}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="shipping:cancel")])
    return InlineKeyboardMarkup(rows)


def review_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сохранить и создать отгрузку", callback_data="shipping:finish")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="shipping:back:collector")],
        [InlineKeyboardButton("❌ Отмена", callback_data="shipping:cancel")],
    ])


def draft(context):
    return context.user_data["shipping_draft"]


async def shipping_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shipping_type = query.data.rsplit(":", 1)[-1]
    context.user_data["shipping_draft"] = {"shipping_type": shipping_type}
    await query.edit_message_text(
        f"Отправление: {shipping_type_label(shipping_type)}\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Создать отправление", callback_data="shipping:action:create")],
            [InlineKeyboardButton("✏️ Изменить отправление", callback_data="shipping:action:edit")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="section:shipping")],
        ]),
    )
    return SHIPPING_ORDER_NUMBER


async def shipping_action_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft(context)["mode"] = query.data.rsplit(":", 1)[-1]
    await query.edit_message_text(
        "Отсканируйте или введите номер «Заказа покупателя» из МойСклад:",
        reply_markup=cancel_keyboard("type"),
    )
    return SHIPPING_ORDER_NUMBER


async def order_number_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("🔎 Ищу заказ в МойСклад…")
    try:
        orders = await asyncio.to_thread(
            search_customer_orders,
            build_moysklad_client(),
            update.message.text,
        )
    except (ShippingServiceError, ShippingValidationError) as error:
        await status.edit_text(f"⚠️ {error}\n\nВведите номер ещё раз:", reply_markup=cancel_keyboard("type"))
        return SHIPPING_ORDER_NUMBER
    except Exception:
        logger.exception("Ошибка поиска заказа МойСклад")
        await status.edit_text("⚠️ Не удалось выполнить поиск. Повторите позже.", reply_markup=cancel_keyboard("type"))
        return SHIPPING_ORDER_NUMBER
    if not orders:
        await status.edit_text("Заказ покупателя не найден. Проверьте номер и повторите ввод:", reply_markup=cancel_keyboard("type"))
        return SHIPPING_ORDER_NUMBER
    draft(context)["orders"] = orders
    if len(orders) == 1:
        return await prepare_order(status, context, orders[0], update.effective_user)
    rows = [
        [InlineKeyboardButton(str(order.get("name") or order.get("id")), callback_data=f"shipping:order:{index}")]
        for index, order in enumerate(orders)
    ]
    rows.extend(cancel_keyboard("order").inline_keyboard)
    await status.edit_text("Найдено несколько заказов. Выберите нужный:", reply_markup=InlineKeyboardMarkup(rows))
    return SHIPPING_ORDER_CHOICE


async def order_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        order = draft(context)["orders"][int(query.data.rsplit(":", 1)[-1])]
    except (KeyError, IndexError, ValueError):
        await query.edit_message_text("Список устарел. Начните заново.", reply_markup=build_shipping_menu_keyboard(is_manager(current_employee(update))))
        return ConversationHandler.END
    await query.edit_message_text("Загружаю состав заказа…")
    return await prepare_order(query.message, context, order, update.effective_user)


async def prepare_order(message, context, order, telegram_user, force_replace=False):
    current = find_employee_for_telegram_user(telegram_user)
    existing_record = await asyncio.to_thread(get_shipping_by_order, order_id=order.get("id"))
    mode = draft(context).get("mode")
    if mode == "edit":
        if not existing_record:
            await message.edit_text("В базе нет отправления для этого заказа.", reply_markup=build_shipping_menu_keyboard(is_manager(current)))
            return ConversationHandler.END
        if not is_manager(current) and str(existing_record.get("created_by_employee_id")) != str(current.get("employee_id")):
            await message.edit_text("Изменять чужое отправление может только руководитель.", reply_markup=build_shipping_menu_keyboard(False))
            return ConversationHandler.END
        force_replace = True
    try:
        client = build_moysklad_client()
        demands = await asyncio.to_thread(inspect_order_demands, client, order.get("id"))
        if demands and not force_replace:
            draft(context)["pending_order"] = order
            names = ", ".join(str(row.get("name") or row.get("id")) for row in demands)
            await message.edit_text(
                f"⚠️ Для заказа {order.get('name')} уже создана отгрузка: {names}.\n\n"
                "Если продолжить, старая отгрузка будет удалена, а после сборки создана новая.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚠️ Всё равно собрать", callback_data="shipping:existing:continue")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="shipping:back:order")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="shipping:cancel")],
                ]),
            )
            return SHIPPING_EXISTING_DEMAND
        prepared = await asyncio.to_thread(build_order_snapshot, client, order)
    except (ShippingServiceError, ShippingValidationError) as error:
        await message.edit_text(f"⚠️ Не удалось подготовить заказ: {error}", reply_markup=build_shipping_menu_keyboard(is_manager(current)))
        return ConversationHandler.END
    except Exception:
        logger.exception("Ошибка подготовки отправления")
        await message.edit_text("⚠️ Не удалось загрузить состав заказа.", reply_markup=build_shipping_menu_keyboard(is_manager(current)))
        return ConversationHandler.END

    shipping_type = draft(context)["shipping_type"]
    mode = draft(context)["mode"]
    context.user_data["shipping_draft"] = {
        "shipping_type": shipping_type,
        "mode": mode,
        "order": {"id": str(order.get("id") or ""), "name": str(order.get("name") or "")},
        "snapshot": prepared["snapshot"],
        "units": prepared["units"],
        "unit_index": 0,
        "codes": [],
        "replace_existing": bool(demands),
        "demand_sync_id": str(uuid.uuid4()),
    }
    if prepared["units"]:
        return await ask_current_code(message, context)
    return await show_collector(message, context, telegram_user)


async def existing_demand_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order = draft(context).get("pending_order")
    if not order:
        await query.edit_message_text("Состояние потеряно. Начните заново.", reply_markup=build_shipping_menu_keyboard(is_manager(current_employee(update))))
        return ConversationHandler.END
    await query.edit_message_text("Загружаю состав заказа…")
    return await prepare_order(query.message, context, order, update.effective_user, force_replace=True)


async def ask_current_code(message, context):
    data = draft(context)
    unit = data["units"][data["unit_index"]]
    await message.edit_text(
        f"Заказ {data['order']['name']}\n"
        f"Маркируемая единица {data['unit_index'] + 1} из {len(data['units'])}\n\n"
        f"{unit['name']}\nЕдиница {unit['unit_number']} из {unit['quantity']}\n"
        f"GTIN: {unit['gtin']}\n\nОтсканируйте полный DataMatrix Честного знака:",
        reply_markup=cancel_keyboard("scan" if data["unit_index"] else "order"),
    )
    return SHIPPING_SCAN


async def marking_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = draft(context)
        unit = data["units"][data["unit_index"]]
        parsed = parse_marking_code(update.message.text, unit["gtin"])
    except ShippingValidationError as error:
        await update.message.reply_text(f"⚠️ Код не принят: {error}\n\nОтсканируйте код повторно:", reply_markup=cancel_keyboard("scan" if draft(context)["unit_index"] else "order"))
        return SHIPPING_SCAN
    except (KeyError, IndexError):
        await update.message.reply_text("Состояние потеряно. Начните заново.", reply_markup=build_shipping_menu_keyboard(False))
        return ConversationHandler.END
    # По требованиям повторные коды допустимы: проверяются формат, GTIN и количество.
    data["codes"].append({**unit, **parsed, "product_name": unit["name"]})
    data["unit_index"] += 1
    status = await update.message.reply_text("Код принят ✅")
    if data["unit_index"] < len(data["units"]):
        return await ask_current_code(status, context)
    return await show_collector(status, context, update.effective_user)


def warehouse_employees():
    return [
        employee for employee in get_employees(include_inactive=False)
        if has_any_role(employee, {"warehouse_employee", "warehouse_manager"})
    ]


async def show_collector(message, context, telegram_user):
    employees = warehouse_employees()
    current = find_employee_for_telegram_user(telegram_user)
    rows = []
    if current and any(str(row["employee_id"]) == str(current["employee_id"]) for row in employees):
        rows.append([InlineKeyboardButton("👤 Я", callback_data=f"shipping:collector:{current['employee_id']}")])
    rows.extend([
        [InlineKeyboardButton(employee["full_name"], callback_data=f"shipping:collector:{employee['employee_id']}")]
        for employee in employees
    ])
    rows.extend(cancel_keyboard("scan" if draft(context)["units"] else "order").inline_keyboard)
    await message.edit_text("Кто собирал заказ?", reply_markup=InlineKeyboardMarkup(rows))
    return SHIPPING_COLLECTOR


async def collector_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.rsplit(":", 1)[-1]
    employee = next((row for row in warehouse_employees() if str(row["employee_id"]) == employee_id), None)
    if not employee:
        await query.answer("Сотрудник недоступен.", show_alert=True)
        return SHIPPING_COLLECTOR
    draft(context)["collector"] = {"employee_id": employee_id, "full_name": employee["full_name"]}
    return await show_review(query.message, context)


async def show_review(message, context):
    data = draft(context)
    total = sum(int(item["quantity"]) for item in data["snapshot"])
    await message.edit_text(
        "Проверьте отправление:\n\n"
        f"Заказ: {data['order']['name']}\n"
        f"Тип: {shipping_type_label(data['shipping_type'])}\n"
        f"Товаров: {total}\n"
        f"Маркируемых единиц: {len(data['units'])}\n"
        f"Кодов ЧЗ: {len(data['codes'])}\n"
        f"Сборщик: {data['collector']['full_name']}\n\n"
        "После подтверждения бот создаст отгрузку в МойСклад.",
        reply_markup=review_keyboard(),
    )
    return SHIPPING_REVIEW


async def shipping_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = draft(context)
    if data.get("finishing"):
        await query.answer("Отгрузка уже создаётся.")
        return SHIPPING_REVIEW
    await query.answer()
    data["finishing"] = True
    if len(data.get("codes") or []) != len(data.get("units") or []):
        data.pop("finishing", None)
        await query.edit_message_text(
            "⚠️ Количество кодов ЧЗ не совпадает с количеством маркируемых товаров. "
            "Вернитесь назад и завершите сканирование.",
            reply_markup=review_keyboard(),
        )
        return SHIPPING_REVIEW
    await query.edit_message_text("Создаю отгрузку в МойСклад…")
    try:
        demand = await asyncio.to_thread(
            create_or_replace_demand,
            build_moysklad_client(),
            data["order"]["id"],
            data["demand_sync_id"],
            data["codes"],
            data["replace_existing"],
        )
    except Exception as error:
        logger.exception("Не удалось создать отгрузку МойСклад")
        data.pop("finishing", None)
        await query.edit_message_text(f"⚠️ Не удалось создать отгрузку: {error}", reply_markup=review_keyboard())
        return SHIPPING_REVIEW

    operator = current_employee(update) or {}
    now = datetime.now(MSK_TZ).replace(tzinfo=None)
    try:
        await asyncio.to_thread(save_shipping_record, {
            "moysklad_order_id": data["order"]["id"],
            "order_number": data["order"]["name"],
            "shipping_type": data["shipping_type"],
            "order_snapshot": data["snapshot"],
            "marking_codes": data["codes"],
            "collector_employee_id": data["collector"]["employee_id"],
            "collector_name": data["collector"]["full_name"],
            "created_by_employee_id": str(operator.get("employee_id") or ""),
            "created_by_name": str(operator.get("full_name") or update.effective_user.full_name or update.effective_user.id),
            "created_by_user_id": str(update.effective_user.id),
            "moysklad_demand_id": str(demand.get("id") or ""),
            "moysklad_demand_name": str(demand.get("name") or ""),
            "assembled_at": now,
        })
    except Exception as error:
        logger.exception("Отгрузка создана, но локальная запись не сохранена")
        data.pop("finishing", None)
        await query.edit_message_text(
            f"⚠️ Отгрузка {demand.get('name') or demand.get('id')} создана в МойСклад, но БД не обновлена: {error}\n\n"
            "Можно повторить сохранение — дубликат отгрузки не создастся.",
            reply_markup=review_keyboard(),
        )
        return SHIPPING_REVIEW
    context.user_data.pop("shipping_draft", None)
    await query.edit_message_text(
        f"Отправление сохранено ✅\n\nЗаказ: {data['order']['name']}\n"
        f"Отгрузка МойСклад: {demand.get('name') or demand.get('id')}\n"
        f"Сборщик: {data['collector']['full_name']}\nКодов ЧЗ: {len(data['codes'])}",
        reply_markup=build_shipping_menu_keyboard(is_manager(operator)),
    )
    return ConversationHandler.END


async def shipping_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target = query.data.rsplit(":", 1)[-1]
    if target == "type":
        context.user_data.pop("shipping_draft", None)
        await query.edit_message_text("🚚 Отправления:", reply_markup=build_shipping_menu_keyboard(is_manager(current_employee(update))))
        return ConversationHandler.END
    if target == "order":
        data = draft(context)
        shipping_type, mode = data["shipping_type"], data["mode"]
        context.user_data["shipping_draft"] = {"shipping_type": shipping_type, "mode": mode}
        await query.edit_message_text("Отсканируйте или введите номер заказа:", reply_markup=cancel_keyboard("type"))
        return SHIPPING_ORDER_NUMBER
    if target == "scan":
        data = draft(context)
        if data["unit_index"] > 0:
            data["unit_index"] -= 1
            if data["codes"]:
                data["codes"].pop()
        return await ask_current_code(query.message, context)
    if target == "collector":
        return await show_collector(query.message, context, update.effective_user)
    return SHIPPING_REVIEW


async def shipping_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("shipping_draft", None)
    await query.edit_message_text("Операция отменена. Данные не изменены.", reply_markup=build_shipping_menu_keyboard(is_manager(current_employee(update))))
    return ConversationHandler.END


async def export_shipping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee = current_employee(update)
    if not is_manager(employee):
        await query.answer("Выгрузка доступна только руководителям.", show_alert=True)
        return
    await query.edit_message_text("Формирую Excel…")
    try:
        records = await asyncio.to_thread(list_shipping_records)
        if not records:
            await query.edit_message_text("В базе пока нет отправлений.", reply_markup=build_shipping_menu_keyboard(True))
            return
        content = await asyncio.to_thread(create_shipping_xlsx, records)
        filename = f"Отправления_{datetime.now(MSK_TZ):%Y%m%d_%H%M%S}.xlsx"
        await query.message.reply_document(
            document=InputFile(BytesIO(content), filename=filename),
            caption=f"Выгружено отправлений: {len(records)}.",
        )
        await query.edit_message_text("Excel сформирован ✅", reply_markup=build_shipping_menu_keyboard(True))
    except Exception as error:
        logger.exception("Ошибка выгрузки отправлений")
        await query.edit_message_text(f"⚠️ Не удалось сформировать Excel: {error}", reply_markup=build_shipping_menu_keyboard(True))


def get_shipping_handlers():
    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(shipping_type_selected, pattern=r"^shipping:type:(cdek|pickup)$"),
        ],
        states={
            SHIPPING_ORDER_NUMBER: [
                CallbackQueryHandler(shipping_action_selected, pattern=r"^shipping:action:(create|edit)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_number_received),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
            SHIPPING_ORDER_CHOICE: [
                CallbackQueryHandler(order_selected, pattern=r"^shipping:order:\d+$"),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
            SHIPPING_EXISTING_DEMAND: [
                CallbackQueryHandler(existing_demand_continue, pattern=r"^shipping:existing:continue$"),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
            SHIPPING_SCAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, marking_code_received),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
            SHIPPING_COLLECTOR: [
                CallbackQueryHandler(collector_selected, pattern=r"^shipping:collector:"),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
            SHIPPING_REVIEW: [
                CallbackQueryHandler(shipping_finish, pattern=r"^shipping:finish$"),
                CallbackQueryHandler(shipping_back, pattern=r"^shipping:back:"),
                CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(shipping_cancel, pattern=r"^shipping:cancel$")],
    )
    return [conversation, CallbackQueryHandler(export_shipping, pattern=r"^shipping:export$")]
