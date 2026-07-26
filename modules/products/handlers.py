from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from core.keyboards import build_products_menu_keyboard
from modules.consumables.storage import get_consumable_items, set_product_consumable_rule
from modules.marking.storage import get_honest_sign_product, normalize_gtin, upsert_honest_sign_products
from modules.payroll.google_sheets import find_employee_for_telegram_user, is_manager
from modules.receiving.products import CATEGORIES, SIZES, add_custom_product


(
    PRODUCT_ADD_CATEGORY,
    PRODUCT_ADD_MODEL,
    PRODUCT_ADD_COLOR,
    PRODUCT_ADD_SIZES,
    PRODUCT_ADD_MARKED,
    PRODUCT_ADD_CHZ_NAME,
    PRODUCT_ADD_GTIN,
    PRODUCT_ADD_RULE_SELECT,
    PRODUCT_ADD_RULE_QUANTITY,
    PRODUCT_ADD_CONFIRM,
) = range(1700, 1710)


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")]])


def product_categories_keyboard():
    rows = []
    for category_id, category in sorted(CATEGORIES.items(), key=lambda item: item[1]["name"]):
        rows.append([InlineKeyboardButton(category["name"][:58], callback_data=f"prodcat:{category_id}")])
    rows.extend(
        [
            [InlineKeyboardButton("➕ Новая группа", callback_data="prodcat:new")],
            [InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def product_sizes_keyboard(selected_sizes):
    rows = []
    for size in SIZES:
        marker = "✅ " if size in selected_sizes else ""
        rows.append([InlineKeyboardButton(marker + size, callback_data=f"prodsize:{size}")])
    rows.extend(
        [
            [InlineKeyboardButton("➡️ Далее", callback_data="prodsize:done")],
            [InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def product_marking_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏷 Да, маркируемый", callback_data="prodmark:yes")],
            [InlineKeyboardButton("📦 Нет, немаркируемый", callback_data="prodmark:no")],
            [InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")],
        ]
    )


def product_rules_keyboard(items, rules):
    rules_by_item = {int(rule["item_id"]): rule for rule in rules}
    rows = []
    for item in items:
        rule = rules_by_item.get(int(item["item_id"]))
        suffix = f" ✅ {rule['quantity']} {item['unit']}" if rule else ""
        rows.append(
            [
                InlineKeyboardButton(
                    (item["name"] + suffix)[:58],
                    callback_data=f"prodrule:{item['item_id']}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton("➡️ Далее", callback_data="prodrule:done")],
            [InlineKeyboardButton("Пропустить нормы", callback_data="prodrule:skip")],
            [InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def product_confirm_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Создать товар", callback_data="prodconfirm:yes")],
            [InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")],
        ]
    )


def product_preview_text(data):
    lines = [
        "Новый товар",
        "",
        f"Группа: {data.get('category_name')}",
        f"Модель: {data.get('model_name')}",
        f"Цвет / вариант: {data.get('color')}",
        "Размеры: " + ", ".join(data.get("sizes", [])),
    ]
    if data.get("is_marked"):
        lines.extend(["", f"Название ЧЗ: {data.get('chz_base_name')}", "GTIN:"])
        for item in data.get("marking", []):
            lines.append(f"• {item['size']}: {item['gtin']} — {item['honest_sign_name']}")
    else:
        lines.append("Маркировка: немаркируемый товар")
    rules = data.get("consumable_rules", [])
    if rules:
        lines.extend(["", "Нормы расходников:"])
        lines.extend(f"• {rule['item_name']}: {rule['quantity']} {rule['unit']}" for rule in rules)
    else:
        lines.append("Нормы расходников: не заданы")
    return "\n".join(lines)


async def prompt_product_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_consumable_items(active_only=True)
    data = context.user_data["product_add"]
    if not items:
        if update.callback_query:
            await update.callback_query.edit_message_text(product_preview_text(data), reply_markup=product_confirm_keyboard())
        else:
            await update.message.reply_text(product_preview_text(data), reply_markup=product_confirm_keyboard())
        return PRODUCT_ADD_CONFIRM
    text = "Выберите расходник и укажите норму на одну единицу товара. Можно выбрать несколько."
    markup = product_rules_keyboard(items, data.get("consumable_rules", []))
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return PRODUCT_ADD_RULE_SELECT


def current_employee(update: Update):
    return find_employee_for_telegram_user(update.effective_user)


def ensure_manager(update: Update):
    return is_manager(current_employee(update))


async def product_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not ensure_manager(update):
        await query.edit_message_text("⛔️ Управление товарами доступно только руководителям.")
        return ConversationHandler.END

    context.user_data["product_add"] = {}
    await query.edit_message_text(
        "Выберите группу товара или добавьте новую:",
        reply_markup=product_categories_keyboard(),
    )
    return PRODUCT_ADD_CATEGORY


async def product_add_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_id = query.data.replace("prodcat:", "")
    if category_id == "new":
        await query.edit_message_text("Введите название новой группы товара:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_CATEGORY
    category = CATEGORIES.get(category_id)
    if not category:
        await query.edit_message_text("Группа не найдена. Выберите группу заново:", reply_markup=product_categories_keyboard())
        return PRODUCT_ADD_CATEGORY
    context.user_data["product_add"]["category_name"] = category["name"]
    await query.edit_message_text("Введите название модели:", reply_markup=cancel_keyboard())
    return PRODUCT_ADD_MODEL


async def product_add_category_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_name = (update.message.text or "").strip()
    if not category_name:
        await update.message.reply_text("Введите непустое название группы:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_CATEGORY

    context.user_data["product_add"]["category_name"] = category_name
    await update.message.reply_text(
        "Введите название модели:",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_MODEL


async def product_add_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    model_name = (update.message.text or "").strip()
    if not model_name:
        await update.message.reply_text("Введите непустое название модели:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_MODEL

    context.user_data["product_add"]["model_name"] = model_name
    await update.message.reply_text(
        "Введите цвет / вариант.\n\n"
        "Если цвета нет, отправьте «-».",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_COLOR


async def product_add_color_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    color = (update.message.text or "").strip()
    if color == "-":
        color = "ONE COLOR"

    data = context.user_data.get("product_add") or {}
    data["color"] = color
    data["sizes"] = []
    data["marking"] = []
    data["consumable_rules"] = []
    await update.message.reply_text(
        "Выберите размеры новой позиции:",
        reply_markup=product_sizes_keyboard(data["sizes"]),
    )
    return PRODUCT_ADD_SIZES


async def product_add_size_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data["product_add"]
    size = query.data.replace("prodsize:", "")
    if size == "done":
        if not data.get("sizes"):
            await query.edit_message_text(
                "Выберите хотя бы один размер.",
                reply_markup=product_sizes_keyboard(data.get("sizes", [])),
            )
            return PRODUCT_ADD_SIZES
        await query.edit_message_text(
            "Товар маркируемый?",
            reply_markup=product_marking_keyboard(),
        )
        return PRODUCT_ADD_MARKED
    selected_sizes = data.setdefault("sizes", [])
    if size in selected_sizes:
        selected_sizes.remove(size)
    else:
        selected_sizes.append(size)
    await query.edit_message_text(
        "Выберите размеры новой позиции:",
        reply_markup=product_sizes_keyboard(selected_sizes),
    )
    return PRODUCT_ADD_SIZES


async def product_add_marking_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data["product_add"]
    data["is_marked"] = query.data == "prodmark:yes"
    if not data["is_marked"]:
        return await prompt_product_rules(update, context)
    await query.edit_message_text(
        "Введите базовое название Честного Знака без размера. Бот добавит размер к названию автоматически:",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_CHZ_NAME


async def product_add_chz_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Введите непустое базовое название Честного Знака:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_CHZ_NAME
    data = context.user_data["product_add"]
    data["chz_base_name"] = name
    data["marking_index"] = 0
    await update.message.reply_text(
        f"Введите GTIN для размера {data['sizes'][0]}:",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_GTIN


async def product_add_gtin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["product_add"]
    index = data["marking_index"]
    size = data["sizes"][index]
    try:
        gtin = normalize_gtin(update.message.text)
    except ValueError as error:
        await update.message.reply_text(f"{error} Введите GTIN для размера {size}:")
        return PRODUCT_ADD_GTIN
    if gtin in {item["gtin"] for item in data["marking"]} or get_honest_sign_product(gtin):
        await update.message.reply_text(f"GTIN {gtin} уже есть в справочнике. Введите другой GTIN:")
        return PRODUCT_ADD_GTIN
    data["marking"].append(
        {
            "gtin": gtin,
            "size": size,
            "honest_sign_name": f"{data['chz_base_name']} {size}",
        }
    )
    index += 1
    data["marking_index"] = index
    if index < len(data["sizes"]):
        await update.message.reply_text(f"Введите GTIN для размера {data['sizes'][index]}:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_GTIN
    data.pop("marking_index", None)
    return await prompt_product_rules(update, context)


async def product_add_rule_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data["product_add"]
    action = query.data.replace("prodrule:", "")
    if action in {"done", "skip"}:
        if action == "skip":
            data["consumable_rules"] = []
        await query.edit_message_text(product_preview_text(data), reply_markup=product_confirm_keyboard())
        return PRODUCT_ADD_CONFIRM
    item = next(
        (item for item in get_consumable_items(active_only=True) if str(item["item_id"]) == action),
        None,
    )
    if not item:
        await query.edit_message_text("Расходник не найден.", reply_markup=cancel_keyboard())
        return ConversationHandler.END
    data["pending_rule_item"] = item
    await query.edit_message_text(
        f"Введите норму «{item['name']}» на одну единицу товара ({item['unit']}):",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_RULE_QUANTITY


async def product_add_rule_quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = float((update.message.text or "").replace(",", "."))
    except ValueError:
        quantity = 0
    if quantity <= 0:
        await update.message.reply_text("Введите норму числом больше нуля:", reply_markup=cancel_keyboard())
        return PRODUCT_ADD_RULE_QUANTITY
    data = context.user_data["product_add"]
    item = data.pop("pending_rule_item")
    rules = [rule for rule in data["consumable_rules"] if rule["item_id"] != item["item_id"]]
    rules.append(
        {
            "item_id": item["item_id"],
            "item_name": item["name"],
            "unit": item["unit"],
            "quantity": quantity,
        }
    )
    data["consumable_rules"] = rules
    return await prompt_product_rules(update, context)


async def product_add_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data.get("product_add") or {}
    try:
        product = add_custom_product(
            category_name=data["category_name"],
            model_name=data["model_name"],
            color=data["color"],
        )
        if data.get("is_marked"):
            upsert_honest_sign_products(data["marking"])
        else:
            upsert_honest_sign_products(
                [{"gtin": None, "honest_sign_name": data["model_name"], "size": ""}]
            )
        for rule in data.get("consumable_rules", []):
            set_product_consumable_rule(
                product["product_id"],
                product["product_name"],
                rule["item_id"],
                rule["quantity"],
            )
    except Exception as error:
        await query.edit_message_text(
            f"Не удалось создать товар: {error}",
            reply_markup=build_products_menu_keyboard(),
        )
        context.user_data.pop("product_add", None)
        return ConversationHandler.END
    context.user_data.pop("product_add", None)
    await query.edit_message_text(
        "Товар добавлен ✅\n\n"
        f"Группа: {product['category_name']}\n"
        f"Модель: {product['model_name']}\n"
        f"Цвет / вариант: {product['color']}\n"
        f"Название: {product['product_name']}",
        reply_markup=build_products_menu_keyboard(),
    )
    return ConversationHandler.END


async def products_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("product_add", None)
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Действие отменено.", reply_markup=build_products_menu_keyboard())
    elif update.message:
        await update.message.reply_text("Действие отменено.", reply_markup=build_products_menu_keyboard())
    return ConversationHandler.END


def get_product_handlers():
    conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(product_add_start, pattern=r"^prodadmin:add$")],
        states={
            PRODUCT_ADD_CATEGORY: [
                CallbackQueryHandler(product_add_category_selected, pattern=r"^prodcat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_category_received),
            ],
            PRODUCT_ADD_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_model_received)],
            PRODUCT_ADD_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_color_received)],
            PRODUCT_ADD_SIZES: [CallbackQueryHandler(product_add_size_selected, pattern=r"^prodsize:")],
            PRODUCT_ADD_MARKED: [CallbackQueryHandler(product_add_marking_selected, pattern=r"^prodmark:(yes|no)$")],
            PRODUCT_ADD_CHZ_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_chz_name_received)],
            PRODUCT_ADD_GTIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_gtin_received)],
            PRODUCT_ADD_RULE_SELECT: [CallbackQueryHandler(product_add_rule_selected, pattern=r"^prodrule:")],
            PRODUCT_ADD_RULE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_rule_quantity_received)],
            PRODUCT_ADD_CONFIRM: [CallbackQueryHandler(product_add_confirmed, pattern=r"^prodconfirm:yes$")],
        },
        fallbacks=[CallbackQueryHandler(products_cancel, pattern=r"^prodadmin:cancel$")],
        name="products_management",
        persistent=False,
    )
    return [conversation]
