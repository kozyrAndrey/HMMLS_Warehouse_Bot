import logging
from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import CONSUMABLES_TOPIC_ID, DOCUMENT_WORKFLOW_CHAT_ID, GROUP_CHAT_ID, WAREHOUSE_INVOICES_TOPIC_ID
from core.keyboards import (
    build_consumables_counting_menu_keyboard,
    build_consumables_menu_keyboard,
    build_consumables_supplies_menu_keyboard,
)
from modules.consumables.storage import (
    apply_inventory_batch_counts,
    create_supply,
    clear_acceptance,
    add_consumable_movement,
    create_inventory_count,
    create_inventory_count_batch,
    deactivate_supplier,
    delete_supply,
    get_accepted_supplies,
    get_active_suppliers,
    get_consumable_item,
    get_consumable_items,
    get_inventory_batch_comparison,
    get_recent_consumable_movements,
    get_recent_inventory_batches,
    get_recent_inventory_counts,
    get_pending_supplies,
    get_product_consumable_rules,
    get_recent_organizations,
    get_supply,
    get_supplies,
    format_quantity,
    mark_supply_accepted,
    set_product_consumable_rule,
    split_message_ids,
    update_acceptance,
    update_supply,
    upsert_consumable_item,
)
from modules.consumables.pdf_reports import create_inventory_count_pdf
from modules.payroll.google_sheets import find_employee_for_telegram_user, is_manager, money, safe_float
from modules.receiving.products import CATEGORIES, SIZES


(
    SUPPLY_NAME,
    SUPPLY_ORGANIZATION,
    SUPPLY_ORGANIZATION_NEW,
    SUPPLY_AMOUNT,
    ACCEPT_SUPPLY,
    ACCEPT_LAYOUT_PHOTO,
    ACCEPT_DOCUMENT,
    SUPPLY_MANAGE_SELECT,
    SUPPLY_EDIT_FIELD,
    SUPPLY_EDIT_VALUE,
    SUPPLY_DELETE_CONFIRM,
    ACCEPTANCE_MANAGE_SELECT,
    ACCEPTANCE_DELETE_CONFIRM,
    SUPPLIER_DELETE_SELECT,
    SUPPLIER_DELETE_CONFIRM,
    ITEM_NAME,
    ITEM_UNIT,
    STOCK_ITEM_SELECT,
    STOCK_QUANTITY,
    RULE_CATEGORY,
    RULE_MODEL,
    RULE_PRODUCT,
    RULE_ITEM_SELECT,
    RULE_QUANTITY,
    SUPPLY_ITEM_SELECT,
    SUPPLY_ITEM_QUANTITY,
    SUPPLY_INVOICE_DOCUMENT,
    INVENTORY_ITEM_SELECT,
    INVENTORY_QUANTITY,
    INVENTORY_COMPARE_SELECT,
) = range(500, 530)


def current_employee_or_none(update):
    return find_employee_for_telegram_user(update.effective_user)


def current_employee_name(update):
    employee = current_employee_or_none(update)
    if employee:
        return employee["full_name"]
    user = update.effective_user
    return user.full_name or user.username or str(user.id)


def consumables_main_keyboard(update):
    return build_consumables_menu_keyboard(manager=is_manager(current_employee_or_none(update)))


def consumables_supplies_keyboard(update):
    return build_consumables_supplies_menu_keyboard(manager=is_manager(current_employee_or_none(update)))


def consumables_counting_keyboard(update):
    return build_consumables_counting_menu_keyboard(manager=is_manager(current_employee_or_none(update)))


def set_consumables_module(context, module):
    context.user_data.clear()
    context.user_data["consumables_module"] = module


def consumables_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")]])


def organization_keyboard(organizations=None, allow_new=True):
    organizations = organizations if organizations is not None else get_recent_organizations()
    rows = []
    for index, organization in enumerate(organizations):
        rows.append([InlineKeyboardButton(organization, callback_data=f"consorg:{index}")])

    if allow_new:
        rows.append([InlineKeyboardButton("➕ Новый поставщик", callback_data="consorg:new")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def supplies_keyboard(supplies, prefix):
    rows = []
    for supply in supplies:
        rows.append([InlineKeyboardButton(f"#{supply['id']}", callback_data=f"{prefix}:{supply['id']}")])

    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def pending_supplies_keyboard():
    return supplies_keyboard(get_pending_supplies(), "conssup")


def supplies_list_text(title, supplies):
    lines = [title]
    for supply in supplies:
        lines.extend(["", format_supply_line(supply)])
        if supply.get("status") == "accepted":
            accepted_at = supply.get("accepted_at")
            accepted_at_text = accepted_at.strftime("%d.%m.%Y %H:%M") if accepted_at else "-"
            lines.append(f"Принял: {supply.get('accepted_by_name') or '-'}")
            lines.append(f"Дата приемки: {accepted_at_text}")
    return "\n".join(lines)


def document_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Документа нет", callback_data="consdoc:none")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")],
        ]
    )


def supply_edit_field_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Название счета", callback_data="consfield:name")],
            [InlineKeyboardButton("Контрагент", callback_data="consfield:organization")],
            [InlineKeyboardButton("Сумма к оплате", callback_data="consfield:amount")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")],
        ]
    )


def confirm_keyboard(confirm_callback):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=confirm_callback)],
            [InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")],
        ]
    )


def suppliers_keyboard(suppliers):
    rows = []
    for index, supplier in enumerate(suppliers):
        rows.append([InlineKeyboardButton(supplier, callback_data=f"conssupplier:{index}")])

    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def consumable_items_keyboard(items, prefix):
    rows = []
    for item in items:
        rows.append([InlineKeyboardButton(item["name"], callback_data=f"{prefix}:{item['item_id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def button_text(value, limit=58):
    value = str(value)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def supply_items_keyboard(context):
    selected = context.user_data.get("supply_items", {})
    rows = []
    for item in get_consumable_items(active_only=True):
        selected_item = selected.get(str(item["item_id"]))
        suffix = ""
        if selected_item:
            suffix = f" - {format_quantity(selected_item['quantity'])} {item['unit']} ✅"
        rows.append([InlineKeyboardButton(button_text(item["name"] + suffix), callback_data=f"conssupplyitem:{item['item_id']}")])
    if selected:
        rows.append([InlineKeyboardButton("✅ Дальше", callback_data="conssupplyitems:done")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def supply_items_text(context):
    selected = context.user_data.get("supply_items", {})
    lines = ["Выберите расходник из списка."]
    if selected:
        lines.extend(["", "В поставке:"])
        for item in selected.values():
            lines.append(f"{item['item_name']}: {format_quantity(item['quantity'])} {item['unit']}")
    return "\n".join(lines)


def inventory_count_keyboard(context):
    counts = context.user_data.get("inventory_counts", {})
    rows = []
    for item in context.user_data.get("inventory_items", get_consumable_items(active_only=True)):
        value = counts.get(str(item["item_id"]))
        suffix = f" - {format_quantity(value)} {item['unit']} ✅" if value is not None else ""
        rows.append([InlineKeyboardButton(button_text(item["name"] + suffix), callback_data=f"consinventoryitem:{item['item_id']}")])
    if counts:
        rows.append([InlineKeyboardButton("✅ Пересчет окончен", callback_data="consinventory:finish")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def inventory_quantity_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К пересчету", callback_data="consinventory:back")]])


def inventory_count_text(context):
    counts = context.user_data.get("inventory_counts", {})
    return f"🔢 Пересчет расходников\n\nЗаполнено: {len(counts)}"


def comparison_is_large(diff, current_quantity):
    diff = abs(float(diff or 0))
    current_quantity = abs(float(current_quantity or 0))
    if diff >= 10:
        return True
    if current_quantity > 0 and diff / current_quantity >= 0.2:
        return True
    return False


def comparison_text(records, selected_ids):
    if not records:
        return "⚖️ Сравнение\n\nНет данных для сравнения."
    lines = ["⚖️ Сравнение", ""]
    for record in records:
        diff = float(record["current_difference"] or 0)
        sign = "+" if diff > 0 else ""
        marker = " 🟡" if comparison_is_large(diff, record["current_quantity"]) else ""
        chosen = "✓ " if int(record["item_id"]) in selected_ids else ""
        item_name = button_text(record["item_name"], limit=32)
        lines.append(
            f"{chosen}{item_name}: бот {format_quantity(record['current_quantity'])} {record['unit']}, "
            f"факт {format_quantity(record['counted_quantity'])} {record['unit']}, "
            f"разница {sign}{format_quantity(diff)}{marker}"
        )
    lines.append("")
    lines.append("Выберите строки, которые нужно заменить фактическим значением сотрудника.")
    return "\n".join(lines)


def comparison_keyboard(records, selected_ids):
    rows = []
    for record in records:
        diff = float(record["current_difference"] or 0)
        if diff == 0:
            continue
        item_id = int(record["item_id"])
        prefix = "✅ " if item_id in selected_ids else ""
        rows.append([InlineKeyboardButton(button_text(prefix + record["item_name"]), callback_data=f"conscompare:toggle:{item_id}")])
    if selected_ids:
        rows.append([InlineKeyboardButton("✅ Применить выбранное", callback_data="conscompare:apply")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def consumable_category_keyboard():
    rows = [
        [InlineKeyboardButton(category_data["name"], callback_data=f"conscat:{category_id}")]
        for category_id, category_data in CATEGORIES.items()
    ]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def consumable_models_keyboard(category_id):
    rows = [
        [InlineKeyboardButton(model_data["name"], callback_data=f"consmodel:{model_id}")]
        for model_id, model_data in CATEGORIES[category_id]["models"].items()
    ]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def consumable_products_keyboard(category_id, model_id):
    rows = []
    for variant_data in CATEGORIES[category_id]["models"][model_id]["variants"].values():
        text = "Выбрать" if variant_data["color"] == "ONE COLOR" else variant_data["color"]
        rows.append([InlineKeyboardButton(text, callback_data=f"consprod:{variant_data['id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def parse_positive_amount(text):
    value = safe_float(text)
    if value <= 0:
        return None
    return value


def format_supply_line(supply):
    lines = [
        f"#{supply['id']} {supply['consumable_name']}",
        f"Контрагент: {supply['organization']}",
        f"Сумма к оплате: {money(supply['amount'])}",
    ]
    if supply.get("supply_items"):
        lines.append("Состав:")
        for item in supply["supply_items"]:
            lines.append(f"- {item['item_name']}: {format_quantity(item['quantity'])} {item.get('unit') or 'шт'}")
    return "\n".join(lines)


def format_acceptance_text(supply, accepted_by, has_document):
    document_text = "есть" if has_document else "документа нет"
    return "\n".join(
        [
            "📥 Приемка расходника",
            "",
            format_supply_line(supply),
            "",
            f"Принял: {accepted_by}",
            f"Закрывающий документ: {document_text}",
        ]
    )


def format_stock_text(items):
    if not items:
        return "📊 Остатки расходников\n\nРасходники пока не заведены."

    lines = ["📊 Остатки расходников", ""]
    for item in items:
        lines.append(f"{item['name']}: {format_quantity(item['current_quantity'])} {item['unit']}")
    return "\n".join(lines)


def format_movements_text(movements):
    if not movements:
        return "🧾 Движения расходников\n\nДвижений пока нет."

    lines = ["🧾 Последние движения расходников", ""]
    for movement in movements:
        created = movement["created_at"].strftime("%d.%m.%Y %H:%M") if movement.get("created_at") else ""
        delta = format_quantity(movement["quantity_delta"])
        sign = "+" if float(movement["quantity_delta"] or 0) > 0 else ""
        lines.append(f"{created} · {movement['item_name']}: {sign}{delta}")
        if movement.get("comment"):
            lines.append(movement["comment"])
    return "\n".join(lines)


def format_inventory_counts_text(records):
    if not records:
        return "📋 Последние пересчеты\n\nПересчетов пока нет."
    lines = ["📋 Последние пересчеты", ""]
    for record in records:
        created = record["created_at"].strftime("%d.%m.%Y %H:%M") if record.get("created_at") else ""
        diff = float(record["difference"] or 0)
        sign = "+" if diff > 0 else ""
        lines.append(f"{created} · {record['item_name']}")
        lines.append(
            f"Система: {format_quantity(record['system_quantity'])} {record['unit']} · "
            f"Факт: {format_quantity(record['counted_quantity'])} {record['unit']} · "
            f"Расхождение: {sign}{format_quantity(diff)}"
        )
        if record.get("counted_by_name"):
            lines.append(f"Считал: {record['counted_by_name']}")
        lines.append("")
    return "\n".join(lines).strip()


def format_rules_text(product_name, rules):
    lines = [f"⚙️ Нормы расходников\n\nТовар: {product_name}", ""]
    if not rules:
        lines.append("Для этого товара нормы пока не настроены.")
    else:
        for rule in rules:
            lines.append(f"{rule['item_name']}: {format_quantity(rule['quantity_per_unit'])} {rule['unit']} на 1 шт.")
    return "\n".join(lines)


async def consumables_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    await query.edit_message_text(
        "🧾 Расходники",
        reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
    )
    return ConversationHandler.END


async def consumables_supplies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")
    await query.edit_message_text("📦 Поставки расходников", reply_markup=consumables_supplies_keyboard(update))
    return ConversationHandler.END


async def consumables_counting_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    await query.edit_message_text("🔢 Пересчет расходников", reply_markup=consumables_counting_keyboard(update))
    return ConversationHandler.END


async def consumables_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    module = context.user_data.get("consumables_module")
    context.user_data.clear()
    if module == "supplies":
        text = "📦 Поставки расходников"
        keyboard = consumables_supplies_keyboard(update)
    elif module == "counting":
        text = "🔢 Пересчет расходников"
        keyboard = consumables_counting_keyboard(update)
    else:
        text = "🧾 Расходники"
        keyboard = consumables_main_keyboard(update)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text("Действие отменено.", reply_markup=keyboard)

    return ConversationHandler.END


async def add_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    employee = current_employee_or_none(update)
    if not is_manager(employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    items = get_consumable_items(active_only=True)
    if not items:
        await query.edit_message_text(
            "Список расходников пуст. Сначала добавьте расходники в учет.",
            reply_markup=consumables_supplies_keyboard(update),
        )
        return ConversationHandler.END

    context.user_data["supply_items"] = {}
    await query.edit_message_text(supply_items_text(context), reply_markup=supply_items_keyboard(context))
    return SUPPLY_ITEM_SELECT


async def supply_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не должно быть пустым. Введите наименование счета:")
        return SUPPLY_NAME

    context.user_data["supply_name"] = name
    context.user_data["organizations"] = get_active_suppliers()
    await update.message.reply_text(
        "Выберите поставщика:",
        reply_markup=organization_keyboard(context.user_data["organizations"], allow_new=True),
    )
    return SUPPLY_ORGANIZATION


async def supply_organization_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "consorg:new":
        await query.edit_message_text("Введите наименование нового поставщика:", reply_markup=consumables_back_keyboard())
        return SUPPLY_ORGANIZATION_NEW

    try:
        index = int(data.replace("consorg:", ""))
        organization = context.user_data.get("organizations", [])[index]
    except (ValueError, IndexError):
        await query.edit_message_text(
            "Поставщик не найден. Выберите заново:",
            reply_markup=organization_keyboard(context.user_data.get("organizations", []), allow_new=True),
        )
        return SUPPLY_ORGANIZATION

    context.user_data["organization"] = organization
    await query.edit_message_text("Введите сумму к оплате:", reply_markup=consumables_back_keyboard())
    return SUPPLY_AMOUNT


async def supply_organization_new_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    organization = update.message.text.strip()
    if not organization:
        await update.message.reply_text("Название поставщика не должно быть пустым. Введите наименование:")
        return SUPPLY_ORGANIZATION_NEW

    context.user_data["organization"] = organization
    await update.message.reply_text("Введите сумму к оплате:", reply_markup=consumables_back_keyboard())
    return SUPPLY_AMOUNT


async def supply_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_positive_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Введите сумму числом больше 0:")
        return SUPPLY_AMOUNT

    context.user_data["supply_amount"] = amount
    await update.message.reply_text(
        "Отправьте файл счета PDF, документом или фото.",
        reply_markup=consumables_back_keyboard(),
    )
    return SUPPLY_INVOICE_DOCUMENT


async def supply_invoice_document_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        invoice_file_id = update.message.photo[-1].file_id
        invoice_kind = "photo"
    elif update.message.document:
        invoice_file_id = update.message.document.file_id
        invoice_kind = "document"
    else:
        await update.message.reply_text(
            "Отправьте счет PDF, документом или фото.",
            reply_markup=consumables_back_keyboard(),
        )
        return SUPPLY_INVOICE_DOCUMENT

    created_by = current_employee_name(update)
    supply = create_supply(
        consumable_name=context.user_data["supply_name"],
        organization=context.user_data["organization"],
        amount=context.user_data["supply_amount"],
        supply_items=list(context.user_data.get("supply_items", {}).values()),
        created_by_user_id=update.effective_user.id,
        created_by_name=created_by,
        invoice_document_file_id=invoice_file_id,
        invoice_document_kind=invoice_kind,
    )

    try:
        invoice_status = await send_invoice_to_document_workflow_topic(
            context,
            supply=supply,
            invoice_file_id=invoice_file_id,
            invoice_kind=invoice_kind,
        )
    except Exception as error:
        logging.exception("Не удалось отправить счет расходников в документооборот")
        invoice_status = f"Счет не отправлен в документооборот ⚠️\nОшибка: {error}"

    text = "Поставка создана ✅\n\n" + format_supply_line(supply)
    text += "\n\nОстатки будут пополнены после приемки поставки."
    text += f"\n\n{invoice_status}"

    await update.message.reply_text(text, reply_markup=consumables_supplies_keyboard(update))
    context.user_data.clear()
    return ConversationHandler.END


async def supply_invoice_wrong_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте счет PDF, документом или фото.",
        reply_markup=consumables_back_keyboard(),
    )
    return SUPPLY_INVOICE_DOCUMENT


async def stock_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["consumables_module"] = "counting"
    await query.edit_message_text(
        format_stock_text(get_consumable_items(active_only=True)),
        reply_markup=consumables_counting_keyboard(update),
    )
    return ConversationHandler.END


async def movements_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["consumables_module"] = "counting"
    await query.edit_message_text(
        format_movements_text(get_recent_consumable_movements(limit=20)),
        reply_markup=consumables_counting_keyboard(update),
    )
    return ConversationHandler.END


async def inventory_recent_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["consumables_module"] = "counting"
    await query.edit_message_text(
        format_inventory_counts_text(get_recent_inventory_counts(limit=20)),
        reply_markup=consumables_counting_keyboard(update),
    )
    return ConversationHandler.END


async def inventory_count_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    items = get_consumable_items(active_only=True)
    if not items:
        await query.edit_message_text("Расходники пока не заведены.", reply_markup=consumables_counting_keyboard(update))
        return ConversationHandler.END
    context.user_data["inventory_items"] = items
    context.user_data["inventory_counts"] = {}
    await query.edit_message_text(inventory_count_text(context), reply_markup=inventory_count_keyboard(context))
    return INVENTORY_ITEM_SELECT


async def inventory_item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["inventory_item_id"] = int(query.data.replace("consinventoryitem:", ""))
    item = get_consumable_item(context.user_data["inventory_item_id"])
    item_name = item["name"] if item else "Расходник"
    await query.edit_message_text(f"Введите фактическое количество:\n\n{item_name}", reply_markup=inventory_quantity_keyboard())
    return INVENTORY_QUANTITY


async def inventory_back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(inventory_count_text(context), reply_markup=inventory_count_keyboard(context))
    return INVENTORY_ITEM_SELECT


async def inventory_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity = safe_float(update.message.text)
    if quantity < 0:
        await update.message.reply_text("Введите число от 0 и выше:")
        return INVENTORY_QUANTITY
    context.user_data.setdefault("inventory_counts", {})[str(context.user_data["inventory_item_id"])] = quantity
    context.user_data.pop("inventory_item_id", None)
    await update.message.reply_text(inventory_count_text(context), reply_markup=inventory_count_keyboard(context))
    return INVENTORY_ITEM_SELECT


async def inventory_count_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    counts = context.user_data.get("inventory_counts", {})
    if not counts:
        await query.edit_message_text(inventory_count_text(context), reply_markup=inventory_count_keyboard(context))
        return INVENTORY_ITEM_SELECT

    counted_by = current_employee_name(update)
    batch = create_inventory_count_batch(
        counts,
        counted_by_user_id=update.effective_user.id,
        counted_by_name=counted_by,
    )
    pdf_path = create_inventory_count_pdf(
        batch["records"],
        counted_by_name=counted_by,
        filename=f"consumables_inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
    )
    topic_status = "PDF не отправлен: GROUP_CHAT_ID не настроен."
    if GROUP_CHAT_ID:
        kwargs = {"chat_id": int(GROUP_CHAT_ID)}
        if CONSUMABLES_TOPIC_ID:
            kwargs["message_thread_id"] = int(CONSUMABLES_TOPIC_ID)
        with open(pdf_path, "rb") as file:
            await context.bot.send_document(
                **kwargs,
                document=file,
                filename=pdf_path.name,
                caption=f"🔢 Пересчет расходников\nСотрудник: {counted_by}",
            )
        topic_status = "PDF отправлен в тему расходников ✅"

    context.user_data.clear()
    await query.edit_message_text(
        f"Пересчет сохранен ✅\nЗаполнено позиций: {len(batch['records'])}\n{topic_status}",
        reply_markup=consumables_counting_keyboard(update),
    )
    return ConversationHandler.END


async def inventory_compare_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    if not is_manager(current_employee_or_none(update)):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END
    batches = get_recent_inventory_batches(limit=1)
    if not batches:
        await query.edit_message_text("Пересчетов для сравнения пока нет.", reply_markup=consumables_counting_keyboard(update))
        return ConversationHandler.END
    batch_id = batches[0]["batch_id"]
    records = get_inventory_batch_comparison(batch_id)
    context.user_data["comparison_batch_id"] = batch_id
    context.user_data["comparison_records"] = records
    context.user_data["comparison_selected_ids"] = set()
    await query.edit_message_text(comparison_text(records, set()), reply_markup=comparison_keyboard(records, set()))
    return INVENTORY_COMPARE_SELECT


async def inventory_compare_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.replace("conscompare:toggle:", ""))
    selected_ids = context.user_data.setdefault("comparison_selected_ids", set())
    if item_id in selected_ids:
        selected_ids.remove(item_id)
    else:
        selected_ids.add(item_id)
    records = context.user_data.get("comparison_records", [])
    await query.edit_message_text(comparison_text(records, selected_ids), reply_markup=comparison_keyboard(records, selected_ids))
    return INVENTORY_COMPARE_SELECT


async def inventory_compare_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_ids = context.user_data.get("comparison_selected_ids", set())
    if not selected_ids:
        records = context.user_data.get("comparison_records", [])
        await query.edit_message_text(comparison_text(records, selected_ids), reply_markup=comparison_keyboard(records, selected_ids))
        return INVENTORY_COMPARE_SELECT
    movements = apply_inventory_batch_counts(
        context.user_data["comparison_batch_id"],
        selected_ids,
        created_by_user_id=update.effective_user.id,
        created_by_name=current_employee_name(update),
    )
    context.user_data.clear()
    lines = ["Сравнение применено ✅", "", f"Обновлено позиций: {len(movements)}"]
    for movement in movements:
        sign = "+" if float(movement["quantity_delta"] or 0) > 0 else ""
        lines.append(f"{movement['item_name']}: {sign}{format_quantity(movement['quantity_delta'])}")
    await query.edit_message_text("\n".join(lines), reply_markup=consumables_counting_keyboard(update))
    return ConversationHandler.END


async def add_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    if not is_manager(current_employee_or_none(update)):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END
    await query.edit_message_text("Введите название расходника для учета:", reply_markup=consumables_back_keyboard())
    return ITEM_NAME


async def item_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не должно быть пустым. Введите название расходника:")
        return ITEM_NAME
    context.user_data["item_name"] = name
    await update.message.reply_text("Введите единицу измерения. Например: шт", reply_markup=consumables_back_keyboard())
    return ITEM_UNIT


async def item_unit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unit = update.message.text.strip() or "шт"
    item = upsert_consumable_item(context.user_data["item_name"], unit)
    context.user_data.clear()
    await update.message.reply_text(
        f"Расходник добавлен в учет ✅\n\n{item['name']}, единица: {item['unit']}",
        reply_markup=build_consumables_counting_menu_keyboard(manager=True),
    )
    return ConversationHandler.END


async def add_stock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    if not is_manager(current_employee_or_none(update)):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END
    items = get_consumable_items(active_only=True)
    if not items:
        await query.edit_message_text("Сначала добавьте расходник в учет.", reply_markup=build_consumables_counting_menu_keyboard(manager=True))
        return ConversationHandler.END
    await query.edit_message_text("Выберите расходник для пополнения:", reply_markup=consumable_items_keyboard(items, "consstockitem"))
    return STOCK_ITEM_SELECT


async def stock_item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["stock_item_id"] = int(query.data.replace("consstockitem:", ""))
    await query.edit_message_text("Введите количество, которое нужно добавить к остатку:", reply_markup=consumables_back_keyboard())
    return STOCK_QUANTITY


async def stock_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity = safe_float(update.message.text)
    if quantity <= 0:
        await update.message.reply_text("Введите число больше 0:")
        return STOCK_QUANTITY
    employee_name = current_employee_name(update)
    movement = add_consumable_movement(
        item_id=context.user_data["stock_item_id"],
        quantity_delta=quantity,
        source="manual_stock",
        comment="Ручное пополнение остатка",
        created_by_user_id=update.effective_user.id,
        created_by_name=employee_name,
    )
    context.user_data.clear()
    await update.message.reply_text(
        f"Остаток пополнен ✅\n\n{movement['item_name']}: +{format_quantity(quantity)}",
        reply_markup=build_consumables_counting_menu_keyboard(manager=True),
    )
    return ConversationHandler.END


async def set_rule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "counting")
    if not is_manager(current_employee_or_none(update)):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END
    await query.edit_message_text("Выберите группу товара:", reply_markup=consumable_category_keyboard())
    return RULE_CATEGORY


async def rule_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_id = query.data.replace("conscat:", "")
    if category_id not in CATEGORIES:
        await query.edit_message_text("Группа не найдена.", reply_markup=build_consumables_counting_menu_keyboard(manager=True))
        return ConversationHandler.END
    context.user_data["rule_category_id"] = category_id
    await query.edit_message_text("Выберите модель:", reply_markup=consumable_models_keyboard(category_id))
    return RULE_MODEL


async def rule_model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    model_id = query.data.replace("consmodel:", "")
    category_id = context.user_data.get("rule_category_id")
    if not category_id or model_id not in CATEGORIES[category_id]["models"]:
        await query.edit_message_text("Модель не найдена.", reply_markup=build_consumables_counting_menu_keyboard(manager=True))
        return ConversationHandler.END
    context.user_data["rule_model_id"] = model_id
    variants = CATEGORIES[category_id]["models"][model_id]["variants"]
    if len(variants) == 1:
        product_id = next(iter(variants.values()))["id"]
        return await finish_rule_product_selection(query, context, product_id)
    await query.edit_message_text("Выберите цвет / вариант:", reply_markup=consumable_products_keyboard(category_id, model_id))
    return RULE_PRODUCT


async def rule_product_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.replace("consprod:", "")
    return await finish_rule_product_selection(query, context, product_id)


async def finish_rule_product_selection(query, context, product_id):
    category_id = context.user_data.get("rule_category_id")
    product_name = CATEGORIES[category_id]["products"].get(product_id, "")
    if not product_name:
        await query.edit_message_text("Товар не найден.", reply_markup=build_consumables_counting_menu_keyboard(manager=True))
        return ConversationHandler.END
    context.user_data["rule_product_id"] = product_id
    context.user_data["rule_product_name"] = product_name
    items = get_consumable_items(active_only=True)
    if not items:
        await query.edit_message_text("Сначала добавьте расходник в учет.", reply_markup=build_consumables_counting_menu_keyboard(manager=True))
        return ConversationHandler.END
    await query.edit_message_text(
        format_rules_text(product_name, get_product_consumable_rules(product_id))
        + "\n\nВыберите расходник для настройки нормы:",
        reply_markup=consumable_items_keyboard(items, "consruleitem"),
    )
    return RULE_ITEM_SELECT


async def rule_item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["rule_item_id"] = int(query.data.replace("consruleitem:", ""))
    await query.edit_message_text("Введите норму расходника на 1 упакованную единицу товара:", reply_markup=consumables_back_keyboard())
    return RULE_QUANTITY


async def rule_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity = safe_float(update.message.text)
    if quantity <= 0:
        await update.message.reply_text("Введите число больше 0:")
        return RULE_QUANTITY
    rule = set_product_consumable_rule(
        product_id=context.user_data["rule_product_id"],
        product_name=context.user_data["rule_product_name"],
        item_id=context.user_data["rule_item_id"],
        quantity_per_unit=quantity,
    )
    await update.message.reply_text(
        "Норма сохранена ✅\n\n"
        f"{rule['product_name']}\n"
        f"{rule['item_name']}: {format_quantity(rule['quantity_per_unit'])} {rule['unit']} на 1 шт.",
        reply_markup=build_consumables_counting_menu_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def accept_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    supplies = get_pending_supplies()
    if not supplies:
        await query.edit_message_text(
            "Нет поставок, ожидающих приемки.",
            reply_markup=consumables_supplies_keyboard(update),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        supplies_list_text("Выберите поставку:", supplies),
        reply_markup=supplies_keyboard(supplies, "conssup"),
    )
    return ACCEPT_SUPPLY


async def accept_supply_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply_id = query.data.replace("conssup:", "")
    supply = get_supply(supply_id)
    if not supply or supply["status"] != "pending":
        supplies = get_pending_supplies()
        await query.edit_message_text(
            supplies_list_text("Поставка не найдена или уже принята. Выберите заново:", supplies),
            reply_markup=supplies_keyboard(supplies, "conssup"),
        )
        return ACCEPT_SUPPLY

    context.user_data["supply_id"] = supply["id"]
    await query.edit_message_text(
        "Отправьте фото разложенных расходников:",
        reply_markup=consumables_back_keyboard(),
    )
    return ACCEPT_LAYOUT_PHOTO


async def supply_item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.replace("conssupplyitem:", ""))
    item = get_consumable_item(item_id)
    if not item or not item.get("is_active"):
        await query.edit_message_text("Расходник не найден.", reply_markup=supply_items_keyboard(context))
        return SUPPLY_ITEM_SELECT
    context.user_data["supply_item_id"] = item["item_id"]
    await query.edit_message_text(
        f"Введите количество:\n\n{item['name']}\nЕдиница: {item['unit']}",
        reply_markup=consumables_back_keyboard(),
    )
    return SUPPLY_ITEM_QUANTITY


async def supply_item_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity = safe_float(update.message.text)
    if quantity <= 0:
        await update.message.reply_text("Введите число больше 0:")
        return SUPPLY_ITEM_QUANTITY
    item = get_consumable_item(context.user_data.get("supply_item_id"))
    if not item:
        await update.message.reply_text("Расходник не найден.", reply_markup=supply_items_keyboard(context))
        return SUPPLY_ITEM_SELECT
    context.user_data.setdefault("supply_items", {})[str(item["item_id"])] = {
        "item_id": item["item_id"],
        "item_name": item["name"],
        "unit": item["unit"],
        "quantity": quantity,
    }
    context.user_data.pop("supply_item_id", None)
    await update.message.reply_text(supply_items_text(context), reply_markup=supply_items_keyboard(context))
    return SUPPLY_ITEM_SELECT


async def supply_items_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not context.user_data.get("supply_items"):
        await query.edit_message_text(supply_items_text(context), reply_markup=supply_items_keyboard(context))
        return SUPPLY_ITEM_SELECT
    await query.edit_message_text("Введите наименование счета:", reply_markup=consumables_back_keyboard())
    return SUPPLY_NAME


async def layout_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Нужно отправить фото разложенных расходников:")
        return ACCEPT_LAYOUT_PHOTO

    context.user_data["layout_photo_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text(
        "Отправьте скан-копию закрывающего документа или нажмите «Документа нет».",
        reply_markup=document_keyboard(),
    )
    return ACCEPT_DOCUMENT


async def layout_photo_wrong_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Нужно отправить именно фото разложенных расходников:",
        reply_markup=consumables_back_keyboard(),
    )
    return ACCEPT_LAYOUT_PHOTO


async def acceptance_document_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["closing_document_file_id"] = update.message.photo[-1].file_id
        context.user_data["closing_document_kind"] = "photo"
    elif update.message.document:
        context.user_data["closing_document_file_id"] = update.message.document.file_id
        context.user_data["closing_document_kind"] = "document"
    else:
        await update.message.reply_text(
            "Отправьте фото/файл закрывающего документа или нажмите «Документа нет».",
            reply_markup=document_keyboard(),
        )
        return ACCEPT_DOCUMENT

    return await finish_acceptance(update, context)


async def acceptance_document_wrong_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте фото/файл закрывающего документа или нажмите «Документа нет».",
        reply_markup=document_keyboard(),
    )
    return ACCEPT_DOCUMENT


async def acceptance_document_missing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["closing_document_file_id"] = ""
    context.user_data["closing_document_kind"] = "none"
    return await finish_acceptance(update, context)


async def send_acceptance_to_topic(context: ContextTypes.DEFAULT_TYPE, supply, accepted_by):
    if not GROUP_CHAT_ID:
        return [], "GROUP_CHAT_ID не настроен, сообщение в тему не отправлено."

    message_thread_id = int(CONSUMABLES_TOPIC_ID) if CONSUMABLES_TOPIC_ID else None
    common_kwargs = {"chat_id": int(GROUP_CHAT_ID)}
    if message_thread_id is not None:
        common_kwargs["message_thread_id"] = message_thread_id

    closing_file_id = context.user_data.get("closing_document_file_id", "")
    closing_kind = context.user_data.get("closing_document_kind", "none")
    message_ids = []

    first_message = await context.bot.send_photo(
        **common_kwargs,
        photo=context.user_data["layout_photo_file_id"],
        caption=format_acceptance_text(supply, accepted_by, bool(closing_file_id)),
    )
    message_ids.append(first_message.message_id)

    if closing_file_id and closing_kind == "photo":
        message = await context.bot.send_photo(
            **common_kwargs,
            photo=closing_file_id,
            caption="Скан-копия закрывающего документа",
        )
        message_ids.append(message.message_id)
    elif closing_file_id and closing_kind == "document":
        message = await context.bot.send_document(
            **common_kwargs,
            document=closing_file_id,
            caption="Скан-копия закрывающего документа",
        )
        message_ids.append(message.message_id)

    return message_ids, "Приемка отправлена в тему чата ✅"


def invoice_caption_text(supply):
    items_text = "; ".join(
        f"{escape(str(item['item_name']))} {format_quantity(item['quantity'])} {escape(str(item.get('unit') or 'шт'))}"
        for item in supply.get("supply_items", [])
    )
    return "\n".join(
        [
            f"1 - {items_text}.",
            f"2 - {escape(str(supply['consumable_name']))}",
            f"<b>3 - {escape(str(supply['organization']))}</b>",
            f"<b>4 - {format_quantity(supply['amount'])}</b>",
        ]
    )


async def send_invoice_to_document_workflow_topic(context: ContextTypes.DEFAULT_TYPE, supply, invoice_file_id, invoice_kind):
    if not DOCUMENT_WORKFLOW_CHAT_ID:
        return "Счет не отправлен в документооборот: DOCUMENT_WORKFLOW_CHAT_ID не настроен."

    kwargs = {"chat_id": int(DOCUMENT_WORKFLOW_CHAT_ID)}
    if WAREHOUSE_INVOICES_TOPIC_ID:
        kwargs["message_thread_id"] = int(WAREHOUSE_INVOICES_TOPIC_ID)

    caption = invoice_caption_text(supply)
    if invoice_kind == "photo":
        await context.bot.send_photo(
            **kwargs,
            photo=invoice_file_id,
            caption=caption,
            parse_mode="HTML",
        )
    else:
        await context.bot.send_document(
            **kwargs,
            document=invoice_file_id,
            caption=caption,
            parse_mode="HTML",
        )

    return "Счет отправлен в документооборот ✅"


async def delete_topic_messages(context: ContextTypes.DEFAULT_TYPE, supply):
    if not GROUP_CHAT_ID:
        return

    for message_id in split_message_ids(supply.get("topic_message_ids")):
        try:
            await context.bot.delete_message(chat_id=int(GROUP_CHAT_ID), message_id=message_id)
        except Exception:
            logging.exception("Не удалось удалить сообщение приемки расходника из темы")


async def finish_acceptance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supply = get_supply(context.user_data.get("supply_id"))
    mode = context.user_data.get("acceptance_mode", "create")
    expected_status = "accepted" if mode == "edit" else "pending"
    if not supply or supply["status"] != expected_status:
        text = "Поставка не найдена или уже принята."
        if mode == "edit":
            text = "Приемка не найдена или уже удалена."
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        context.user_data.clear()
        return ConversationHandler.END

    accepted_by = current_employee_name(update)

    if mode == "edit":
        await delete_topic_messages(context, supply)

    try:
        message_ids, topic_status = await send_acceptance_to_topic(context, supply, accepted_by)
    except Exception as error:
        logging.exception("Не удалось отправить приемку расходника в тему")
        message_ids = []
        topic_status = f"Приемка сохранена, но не отправлена в тему ⚠️\nОшибка: {error}"

    if mode == "edit":
        update_acceptance(
            supply_id=supply["id"],
            accepted_by_user_id=update.effective_user.id,
            accepted_by_name=accepted_by,
            layout_photo_file_id=context.user_data["layout_photo_file_id"],
            closing_document_file_id=context.user_data.get("closing_document_file_id", ""),
            closing_document_kind=context.user_data.get("closing_document_kind", "none"),
            topic_message_ids=message_ids,
        )
    else:
        supply = mark_supply_accepted(
            supply_id=supply["id"],
            accepted_by_user_id=update.effective_user.id,
            accepted_by_name=accepted_by,
            layout_photo_file_id=context.user_data["layout_photo_file_id"],
            closing_document_file_id=context.user_data.get("closing_document_file_id", ""),
            closing_document_kind=context.user_data.get("closing_document_kind", "none"),
            topic_message_ids=message_ids,
        )

    result_title = "Приемка расходника изменена ✅" if mode == "edit" else "Приемка расходника завершена ✅"
    text = result_title + "\n\n" + format_supply_line(supply) + f"\n\n{topic_status}"
    if mode != "edit" and supply.get("supply_items"):
        stock_lines = [
            f"{item['item_name']}: +{format_quantity(item['quantity'])} {item.get('unit') or 'шт'}"
            for item in supply["supply_items"]
        ]
        text += "\n\nОстатки пополнены:\n" + "\n".join(stock_lines)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=consumables_supplies_keyboard(update),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=consumables_supplies_keyboard(update),
        )

    context.user_data.clear()
    return ConversationHandler.END


async def edit_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    employee = current_employee_or_none(update)
    if not is_manager(employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    supplies = get_supplies()
    if not supplies:
        await query.edit_message_text("Поставок пока нет.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        return ConversationHandler.END

    context.user_data["supply_manage_action"] = "edit"
    await query.edit_message_text(
        supplies_list_text("Выберите поставку для изменения:", supplies),
        reply_markup=supplies_keyboard(supplies, "consmanage"),
    )
    return SUPPLY_MANAGE_SELECT


async def delete_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    employee = current_employee_or_none(update)
    if not is_manager(employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    supplies = get_supplies()
    if not supplies:
        await query.edit_message_text("Поставок пока нет.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        return ConversationHandler.END

    context.user_data["supply_manage_action"] = "delete"
    await query.edit_message_text(
        supplies_list_text("Выберите поставку для удаления:", supplies),
        reply_markup=supplies_keyboard(supplies, "consmanage"),
    )
    return SUPPLY_MANAGE_SELECT


async def supply_manage_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply_id = query.data.replace("consmanage:", "")
    supply = get_supply(supply_id)
    if not supply:
        await query.edit_message_text("Поставка не найдена.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        return ConversationHandler.END

    context.user_data["supply_id"] = supply["id"]

    if context.user_data.get("supply_manage_action") == "delete":
        await query.edit_message_text(
            "Удалить поставку?\n\n" + format_supply_line(supply),
            reply_markup=confirm_keyboard("conssupplydelete:yes"),
        )
        return SUPPLY_DELETE_CONFIRM

    await query.edit_message_text(
        "Что изменить?\n\n" + format_supply_line(supply),
        reply_markup=supply_edit_field_keyboard(),
    )
    return SUPPLY_EDIT_FIELD


async def supply_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    field = query.data.replace("consfield:", "")
    context.user_data["supply_edit_field"] = field

    prompts = {
        "name": "Введите новое название счета:",
        "organization": "Введите новое название контрагента:",
        "amount": "Введите новую сумму к оплате:",
    }
    await query.edit_message_text(prompts.get(field, "Введите новое значение:"), reply_markup=consumables_back_keyboard())
    return SUPPLY_EDIT_VALUE


async def supply_edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    field = context.user_data.get("supply_edit_field")
    if not value:
        await update.message.reply_text("Значение не должно быть пустым. Введите еще раз:")
        return SUPPLY_EDIT_VALUE

    kwargs = {}
    if field == "name":
        kwargs["consumable_name"] = value
    elif field == "organization":
        kwargs["organization"] = value
    elif field == "amount":
        amount = parse_positive_amount(value)
        if amount is None:
            await update.message.reply_text("Введите сумму числом больше 0:")
            return SUPPLY_EDIT_VALUE
        kwargs["amount"] = amount
    else:
        await update.message.reply_text("Поле не найдено.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        context.user_data.clear()
        return ConversationHandler.END

    supply = update_supply(context.user_data["supply_id"], **kwargs)

    topic_status = ""
    if supply["status"] == "accepted" and supply.get("layout_photo_file_id"):
        await delete_topic_messages(context, supply)
        context.user_data["layout_photo_file_id"] = supply["layout_photo_file_id"]
        context.user_data["closing_document_file_id"] = supply.get("closing_document_file_id", "")
        context.user_data["closing_document_kind"] = supply.get("closing_document_kind", "none")
        try:
            message_ids, topic_status = await send_acceptance_to_topic(context, supply, supply.get("accepted_by_name") or "-")
            update_acceptance(
                supply_id=supply["id"],
                accepted_by_user_id=supply.get("accepted_by_user_id", ""),
                accepted_by_name=supply.get("accepted_by_name", ""),
                layout_photo_file_id=supply["layout_photo_file_id"],
                closing_document_file_id=supply.get("closing_document_file_id", ""),
                closing_document_kind=supply.get("closing_document_kind", "none"),
                topic_message_ids=message_ids,
            )
            topic_status = f"\n\n{topic_status}"
        except Exception as error:
            logging.exception("Не удалось обновить сообщение приемки после изменения поставки")
            topic_status = f"\n\nПоставка изменена, но сообщение приемки в теме не обновлено ⚠️\nОшибка: {error}"

    await update.message.reply_text(
        "Поставка изменена ✅\n\n" + format_supply_line(supply) + topic_status,
        reply_markup=build_consumables_supplies_menu_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def supply_delete_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply = get_supply(context.user_data.get("supply_id"))
    if not supply:
        await query.edit_message_text("Поставка не найдена.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        context.user_data.clear()
        return ConversationHandler.END

    await delete_topic_messages(context, supply)
    deleted = delete_supply(supply["id"])
    await query.edit_message_text(
        "Поставка удалена ✅\n\n" + format_supply_line(deleted),
        reply_markup=build_consumables_supplies_menu_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def edit_acceptance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    supplies = get_accepted_supplies()
    if not supplies:
        await query.edit_message_text(
            "Принятых поставок пока нет.",
            reply_markup=consumables_supplies_keyboard(update),
        )
        return ConversationHandler.END

    context.user_data["acceptance_manage_action"] = "edit"
    await query.edit_message_text(
        supplies_list_text("Выберите приемку для изменения:", supplies),
        reply_markup=supplies_keyboard(supplies, "consacc"),
    )
    return ACCEPTANCE_MANAGE_SELECT


async def delete_acceptance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    supplies = get_accepted_supplies()
    if not supplies:
        await query.edit_message_text(
            "Принятых поставок пока нет.",
            reply_markup=consumables_supplies_keyboard(update),
        )
        return ConversationHandler.END

    context.user_data["acceptance_manage_action"] = "delete"
    await query.edit_message_text(
        supplies_list_text("Выберите приемку для удаления:", supplies),
        reply_markup=supplies_keyboard(supplies, "consacc"),
    )
    return ACCEPTANCE_MANAGE_SELECT


async def acceptance_manage_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply = get_supply(query.data.replace("consacc:", ""))
    if not supply or supply["status"] != "accepted":
        await query.edit_message_text("Приемка не найдена.", reply_markup=consumables_supplies_keyboard(update))
        return ConversationHandler.END

    context.user_data["supply_id"] = supply["id"]

    if context.user_data.get("acceptance_manage_action") == "delete":
        await query.edit_message_text(
            "Удалить приемку и вернуть поставку в ожидание приемки?\n\n" + format_supply_line(supply),
            reply_markup=confirm_keyboard("consaccdelete:yes"),
        )
        return ACCEPTANCE_DELETE_CONFIRM

    context.user_data["acceptance_mode"] = "edit"
    await query.edit_message_text(
        "Отправьте новое фото разложенных расходников:",
        reply_markup=consumables_back_keyboard(),
    )
    return ACCEPT_LAYOUT_PHOTO


async def acceptance_delete_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply = get_supply(context.user_data.get("supply_id"))
    if not supply or supply["status"] != "accepted":
        await query.edit_message_text("Приемка не найдена.", reply_markup=consumables_supplies_keyboard(update))
        context.user_data.clear()
        return ConversationHandler.END

    await delete_topic_messages(context, supply)
    cleared = clear_acceptance(supply["id"])
    await query.edit_message_text(
        "Приемка удалена ✅\nПоставка снова доступна для приемки.\n\n" + format_supply_line(cleared),
        reply_markup=consumables_supplies_keyboard(update),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def delete_supplier_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_consumables_module(context, "supplies")

    employee = current_employee_or_none(update)
    if not is_manager(employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    suppliers = get_active_suppliers()
    if not suppliers:
        await query.edit_message_text("Активных поставщиков пока нет.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        return ConversationHandler.END

    context.user_data["suppliers"] = suppliers
    await query.edit_message_text(
        "Выберите поставщика, которого нужно убрать из выбора:",
        reply_markup=suppliers_keyboard(suppliers),
    )
    return SUPPLIER_DELETE_SELECT


async def supplier_delete_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.replace("conssupplier:", ""))
        supplier = context.user_data.get("suppliers", [])[index]
    except (ValueError, IndexError):
        await query.edit_message_text("Поставщик не найден.", reply_markup=build_consumables_supplies_menu_keyboard(manager=True))
        return ConversationHandler.END

    context.user_data["supplier_name"] = supplier
    await query.edit_message_text(
        f"Удалить поставщика из выбора?\n\n{supplier}\n\nИстория поставок сохранится.",
        reply_markup=confirm_keyboard("conssupplierdelete:yes"),
    )
    return SUPPLIER_DELETE_CONFIRM


async def supplier_delete_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supplier = deactivate_supplier(context.user_data.get("supplier_name"))
    await query.edit_message_text(
        f"Поставщик удален из выбора ✅\n\n{supplier}",
        reply_markup=build_consumables_supplies_menu_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


def get_consumables_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(stock_view, pattern=r"^cons:stock$"),
            CallbackQueryHandler(movements_view, pattern=r"^cons:movements$"),
            CallbackQueryHandler(inventory_count_start, pattern=r"^cons:inventory_count$"),
            CallbackQueryHandler(inventory_recent_view, pattern=r"^cons:inventory_recent$"),
            CallbackQueryHandler(inventory_compare_start, pattern=r"^cons:inventory_compare$"),
            CallbackQueryHandler(add_supply_start, pattern=r"^cons:add_supply$"),
            CallbackQueryHandler(add_item_start, pattern=r"^cons:add_item$"),
            CallbackQueryHandler(add_stock_start, pattern=r"^cons:add_stock$"),
            CallbackQueryHandler(set_rule_start, pattern=r"^cons:set_rule$"),
            CallbackQueryHandler(accept_supply_start, pattern=r"^cons:accept_supply$"),
            CallbackQueryHandler(edit_supply_start, pattern=r"^cons:edit_supply$"),
            CallbackQueryHandler(delete_supply_start, pattern=r"^cons:delete_supply$"),
            CallbackQueryHandler(edit_acceptance_start, pattern=r"^cons:edit_acceptance$"),
            CallbackQueryHandler(delete_acceptance_start, pattern=r"^cons:delete_acceptance$"),
            CallbackQueryHandler(delete_supplier_start, pattern=r"^cons:delete_supplier$"),
        ],
        states={
            SUPPLY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, supply_name_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_ORGANIZATION: [
                CallbackQueryHandler(supply_organization_selected, pattern=r"^consorg:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_ORGANIZATION_NEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, supply_organization_new_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, supply_amount_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_INVOICE_DOCUMENT: [
                MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, supply_invoice_document_received),
                MessageHandler(filters.ALL & ~filters.COMMAND, supply_invoice_wrong_message),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_ITEM_SELECT: [
                CallbackQueryHandler(supply_item_selected, pattern=r"^conssupplyitem:"),
                CallbackQueryHandler(supply_items_done, pattern=r"^conssupplyitems:done$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_ITEM_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, supply_item_quantity_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ACCEPT_SUPPLY: [
                CallbackQueryHandler(accept_supply_selected, pattern=r"^conssup:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ACCEPT_LAYOUT_PHOTO: [
                MessageHandler(filters.PHOTO, layout_photo_received),
                MessageHandler(filters.ALL & ~filters.COMMAND, layout_photo_wrong_message),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ACCEPT_DOCUMENT: [
                MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, acceptance_document_received),
                MessageHandler(filters.ALL & ~filters.COMMAND, acceptance_document_wrong_message),
                CallbackQueryHandler(acceptance_document_missing, pattern=r"^consdoc:none$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_MANAGE_SELECT: [
                CallbackQueryHandler(supply_manage_selected, pattern=r"^consmanage:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_EDIT_FIELD: [
                CallbackQueryHandler(supply_edit_field_selected, pattern=r"^consfield:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, supply_edit_value_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLY_DELETE_CONFIRM: [
                CallbackQueryHandler(supply_delete_confirmed, pattern=r"^conssupplydelete:yes$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ACCEPTANCE_MANAGE_SELECT: [
                CallbackQueryHandler(acceptance_manage_selected, pattern=r"^consacc:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ACCEPTANCE_DELETE_CONFIRM: [
                CallbackQueryHandler(acceptance_delete_confirmed, pattern=r"^consaccdelete:yes$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLIER_DELETE_SELECT: [
                CallbackQueryHandler(supplier_delete_selected, pattern=r"^conssupplier:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            SUPPLIER_DELETE_CONFIRM: [
                CallbackQueryHandler(supplier_delete_confirmed, pattern=r"^conssupplierdelete:yes$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, item_name_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            ITEM_UNIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, item_unit_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            STOCK_ITEM_SELECT: [
                CallbackQueryHandler(stock_item_selected, pattern=r"^consstockitem:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            STOCK_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stock_quantity_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            RULE_CATEGORY: [
                CallbackQueryHandler(rule_category_selected, pattern=r"^conscat:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            RULE_MODEL: [
                CallbackQueryHandler(rule_model_selected, pattern=r"^consmodel:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            RULE_PRODUCT: [
                CallbackQueryHandler(rule_product_selected, pattern=r"^consprod:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            RULE_ITEM_SELECT: [
                CallbackQueryHandler(rule_item_selected, pattern=r"^consruleitem:"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            RULE_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rule_quantity_received),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            INVENTORY_ITEM_SELECT: [
                CallbackQueryHandler(inventory_item_selected, pattern=r"^consinventoryitem:"),
                CallbackQueryHandler(inventory_count_finish, pattern=r"^consinventory:finish$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
            INVENTORY_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, inventory_quantity_received),
                CallbackQueryHandler(inventory_back_to_list, pattern=r"^consinventory:back$"),
                CallbackQueryHandler(inventory_back_to_list, pattern=r"^cons:cancel$"),
            ],
            INVENTORY_COMPARE_SELECT: [
                CallbackQueryHandler(inventory_compare_toggle, pattern=r"^conscompare:toggle:"),
                CallbackQueryHandler(inventory_compare_apply, pattern=r"^conscompare:apply$"),
                CallbackQueryHandler(consumables_cancel, pattern=r"^cons:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", consumables_cancel)],
    )


def get_consumables_handlers():
    return [
        CallbackQueryHandler(consumables_menu, pattern=r"^section:consumables$"),
        CallbackQueryHandler(consumables_supplies_menu, pattern=r"^cons:module_supplies$"),
        CallbackQueryHandler(consumables_counting_menu, pattern=r"^cons:module_counting$"),
        get_consumables_conversation_handler(),
    ]
