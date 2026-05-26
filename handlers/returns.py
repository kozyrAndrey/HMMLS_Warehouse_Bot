import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import GROUP_CHAT_ID, RETURNS_TOPIC_ID, RETURN_CHZ_CHAT_ID, RETURN_CHZ_TOPIC_ID
from keyboards import (
    build_main_menu_keyboard,
    build_return_category_keyboard,
    build_return_models_keyboard,
    build_return_nav_keyboard,
    build_return_product_colors_keyboard,
    build_return_sizes_keyboard,
)
from products import CATEGORIES, SIZES


# ============================================================
# НАСТРОЙКИ УПОМИНАНИЙ
# ============================================================
# Замени на реальные Telegram username руководителей.
# Важно: username в Telegram не может содержать пробелы.
# Пример: "@warehouse_manager"

WAREHOUSE_MANAGER_MENTION = "@opulent_shooter"
SUPPORT_MANAGER_MENTION = "@meelxw1"

# ============================================================
# СОСТОЯНИЯ ДИАЛОГА
# ============================================================

(
    RET_PHOTO,
    RET_CHZ_PHOTO,  # legacy state, больше не используется как общий ЧЗ для СДЭК
    RET_COUNTERPARTY,
    RET_TRACK_NUMBER,
    RET_ITEMS_COUNT,
    RET_ITEM_CATEGORY,
    RET_ITEM_MODEL,
    RET_ITEM_PRODUCT,
    RET_ITEM_CHZ_PHOTO,
    RET_ITEM_SIZE,
    RET_ITEM_CONDITION,
    RET_ITEM_EXTRA_PHOTO,
    RET_ITEM_CONDITION_COMMENT,
) = range(100, 113)


# ============================================================
# СОСТОЯНИЯ ТОВАРА В ВОЗВРАТЕ
# ============================================================

RETURN_CONDITIONS = {
    "normal": {
        "label": "норм",
        "needs_photo": False,
        "needs_comment": False,
        "mentions": [],
    },
    "invoice_defect": {
        "label": "брак по накладной",
        "needs_photo": True,
        "needs_comment": True,
        "mentions": ["warehouse"],
        "photo_prompt": (
            "Отправьте фото переупакованного возврата по правилам "
            "для статуса «брак по накладной»."
        ),
        "comment_prompt": "Введите комментарий к браку по накладной:",
    },
    "invoice_rework": {
        "label": "доработка по накладной",
        "needs_photo": True,
        "needs_comment": True,
        "mentions": ["warehouse"],
        "photo_prompt": (
            "Отправьте фото переупакованного возврата по правилам "
            "для статуса «доработка по накладной»."
        ),
        "comment_prompt": "Введите комментарий к доработке по накладной:",
    },
    "not_invoice_defect": {
        "label": "брак не по накладной",
        "needs_photo": True,
        "needs_comment": True,
        "mentions": ["warehouse", "support"],
        "photo_prompt": (
            "Отправьте фото переупакованного возврата по правилам "
            "для статуса «брак НЕ по накладной»."
        ),
        "comment_prompt": "Введите комментарий к браку НЕ по накладной:",
    },
}


def build_return_condition_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Норм", callback_data="retcond:normal")],
            [InlineKeyboardButton("📄 Брак по накладной", callback_data="retcond:invoice_defect")],
            [InlineKeyboardButton("🛠 Доработка по накладной", callback_data="retcond:invoice_rework")],
            [InlineKeyboardButton("⚠️ Брак НЕ по накладной", callback_data="retcond:not_invoice_defect")],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
                InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
            ],
        ]
    )


def build_chz_photo_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("ЧЗ нет", callback_data="ret:chz_missing")],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
                InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
            ],
        ]
    )


def get_return_type(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.get("return_type", "cdek")


def is_cdek_return(context: ContextTypes.DEFAULT_TYPE):
    return get_return_type(context) == "cdek"


def get_return_type_label(context: ContextTypes.DEFAULT_TYPE):
    return "СДЭК" if is_cdek_return(context) else "Шоу-рум"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def get_employee_full_name_for_user(user):
    """Возвращает ФИО сотрудника из модуля ЗП по Telegram user_id/username.

    Если сотрудник не найден или Google Таблица временно недоступна,
    используем Telegram full_name как безопасный fallback.
    """
    try:
        from payroll_google_sheets import find_employee_for_telegram_user

        employee = find_employee_for_telegram_user(user)
        if employee and employee.get("full_name"):
            return employee["full_name"]
    except Exception:
        logging.exception("Не удалось получить ФИО сотрудника из Google Таблицы ЗП")

    # Fallback по локальному payroll_config.py, чтобы не зависеть полностью от Google Sheets.
    try:
        from payroll_config import PAYROLL_EMPLOYEES, normalize_username

        telegram_user_id = str(user.id)
        username = normalize_username(user.username)

        for employee in PAYROLL_EMPLOYEES:
            if str(employee.get("telegram_user_id", "")).strip() == telegram_user_id:
                return employee.get("full_name") or user.full_name

        if username:
            for employee in PAYROLL_EMPLOYEES:
                if normalize_username(employee.get("telegram_username", "")) == username:
                    return employee.get("full_name") or user.full_name
    except Exception:
        logging.exception("Не удалось получить ФИО сотрудника из payroll_config.py")

    return user.full_name or user.username or str(user.id)


async def send_chz_photo_to_topic(context: ContextTypes.DEFAULT_TYPE, user, photo_file_id):
    if not RETURN_CHZ_CHAT_ID:
        return "RETURN_CHZ_CHAT_ID не настроен."

    common_kwargs = {
        "chat_id": int(RETURN_CHZ_CHAT_ID),
        "photo": photo_file_id,
        "caption": (
            "Фото маркировки «Честный знак» по возврату\n"
            f"Сотрудник: {get_employee_full_name_for_user(user)}"
        ),
    }

    if RETURN_CHZ_TOPIC_ID:
        common_kwargs["message_thread_id"] = int(RETURN_CHZ_TOPIC_ID)

    await context.bot.send_photo(**common_kwargs)
    return "Фото ЧЗ отправлено в отдельную тему ✅"


async def send_item_chz_photo_to_topic(context: ContextTypes.DEFAULT_TYPE, user, photo_file_id):
    if not RETURN_CHZ_CHAT_ID:
        return "RETURN_CHZ_CHAT_ID не настроен."

    product_name = get_current_item_product_name(context)
    counterparty = context.user_data.get("return_counterparty", "")
    track_number = context.user_data.get("return_track_number", "")

    caption_lines = [
        "Фото маркировки «Честный знак» по товару в возврате",
        f"Тип возврата: {get_return_type_label(context)}",
        f"Сотрудник: {get_employee_full_name_for_user(user)}",
        f"ФИО контрагента: {counterparty}",
    ]

    if is_cdek_return(context) and track_number:
        caption_lines.append(f"Трек-номер: {track_number}")

    caption_lines.append(f"Товар: {product_name}")

    common_kwargs = {
        "chat_id": int(RETURN_CHZ_CHAT_ID),
        "photo": photo_file_id,
        "caption": "\n".join(caption_lines),
    }

    if RETURN_CHZ_TOPIC_ID:
        common_kwargs["message_thread_id"] = int(RETURN_CHZ_TOPIC_ID)

    await context.bot.send_photo(**common_kwargs)
    return "Фото ЧЗ по товару отправлено в отдельную тему ✅"


def parse_positive_number(text):
    text = text.strip()

    if not text.isdigit():
        return None

    value = int(text)

    if value <= 0:
        return None

    return value


def get_return_items(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.setdefault("return_items", [])


def get_current_item(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.setdefault("return_current_item", {})


def clear_current_item(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["return_current_item"] = {}


def current_item_number(context: ContextTypes.DEFAULT_TYPE):
    return len(get_return_items(context)) + 1


def total_items_count(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.get("return_items_count", 0)


def get_current_item_product_name(context: ContextTypes.DEFAULT_TYPE):
    current_item = get_current_item(context)

    category_id = current_item.get("category_id")
    product_id = current_item.get("product_id")

    if not category_id or not product_id:
        return ""

    return CATEGORIES[category_id]["products"][product_id]


def append_current_item(context: ContextTypes.DEFAULT_TYPE):
    current_item = get_current_item(context)

    category_id = current_item.get("category_id")
    model_id = current_item.get("model_id")
    product_id = current_item.get("product_id")
    size = current_item.get("size")
    condition_key = current_item.get("condition_key")
    extra_photo_file_id = current_item.get("extra_photo_file_id")
    condition_comment = current_item.get("condition_comment", "")
    chz_photo_file_id = current_item.get("chz_photo_file_id", "")
    chz_status = current_item.get("chz_status", "")

    if not category_id or not model_id or not product_id or not size or not condition_key:
        raise RuntimeError("Не все данные товара заполнены.")

    if not chz_status:
        raise RuntimeError("Не указана информация по Честному знаку товара.")

    condition = RETURN_CONDITIONS[condition_key]

    if condition.get("needs_photo") and not extra_photo_file_id:
        raise RuntimeError("Для выбранного состояния нужно фото переупакованного возврата.")

    if condition.get("needs_comment") and not condition_comment:
        raise RuntimeError("Для выбранного состояния нужен комментарий.")

    items = get_return_items(context)
    items.append(
        {
            "category_id": category_id,
            "model_id": model_id,
            "product_id": product_id,
            "size": size,
            "chz_status": chz_status,
            "chz_photo_file_id": chz_photo_file_id,
            "condition_key": condition_key,
            "condition_label": condition["label"],
            "condition_comment": condition_comment,
            "extra_photo_file_id": extra_photo_file_id,
        }
    )

    clear_current_item(context)


async def send_or_edit_text(target, text, reply_markup=None):
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=reply_markup)
    else:
        await target.reply_text(text, reply_markup=reply_markup)


async def ask_next_item_or_finish(target, context: ContextTypes.DEFAULT_TYPE, user):
    items = get_return_items(context)
    total = total_items_count(context)

    if len(items) < total:
        next_item_no = len(items) + 1

        step_text = "Шаг 5/6" if is_cdek_return(context) else "Шаг 3/4"

        await send_or_edit_text(
            target,
            (
                f"{step_text}. Товар {next_item_no} из {total}.\n\n"
                "Выберите группу товара:"
            ),
            reply_markup=build_return_category_keyboard(),
        )

        return RET_ITEM_CATEGORY

    summary_text = format_return_summary(context, user)

    try:
        send_status = await send_return_to_topic(
            context=context,
            caption=summary_text,
        )
    except Exception as error:
        logging.exception("Не удалось отправить возврат в тему чата")
        send_status = f"Не удалось отправить сообщение в тему чата ⚠️\nОшибка: {error}"

    await send_or_edit_text(
        target,
        (
            "Возврат оформлен ✅\n\n"
            f"{summary_text}\n\n"
            f"{send_status}\n\n"
            "Выберите следующее действие:"
        ),
        reply_markup=build_main_menu_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.END


# ============================================================
# ОТМЕНА
# ============================================================

async def return_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    text = "Оформление возврата отменено. Данные не сохранены и не отправлены."

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text + "\n\nГлавное меню:",
            reply_markup=build_main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=build_main_menu_keyboard(),
        )

    return ConversationHandler.END


# ============================================================
# СТАРТ ВОЗВРАТА
# ============================================================

async def return_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    if query.data.endswith(":showroom"):
        context.user_data["return_type"] = "showroom"
        await query.edit_message_text(
            "↩️ Возврат из шоу-рума\n\n"
            "Шаг 1/4. Введите ФИО контрагента:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_COUNTERPARTY

    context.user_data["return_type"] = "cdek"

    await query.edit_message_text(
        "↩️ Возврат СДЭК\n\n"
        "Шаг 1/6. Отправьте фото накладной.",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_PHOTO


async def return_back_from_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "Главное меню:",
        reply_markup=build_main_menu_keyboard(),
    )

    return ConversationHandler.END


async def invoice_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Пожалуйста, отправьте именно фото накладной.",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_PHOTO

    context.user_data["return_invoice_photo_file_id"] = update.message.photo[-1].file_id

    await update.message.reply_text(
        "Шаг 2/6. Введите ФИО контрагента:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_COUNTERPARTY


async def back_to_invoice_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_invoice_photo_file_id", None)
    context.user_data.pop("return_chz_photo_file_id", None)
    context.user_data.pop("return_chz_status", None)

    await query.edit_message_text(
        "Шаг 1/6. Отправьте фото накладной заново:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_PHOTO


async def chz_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Пожалуйста, отправьте именно фото маркировки «Честный знак» "
            "или нажмите кнопку «ЧЗ нет».",
            reply_markup=build_chz_photo_keyboard(),
        )
        return RET_CHZ_PHOTO

    chz_photo_file_id = update.message.photo[-1].file_id
    context.user_data["return_chz_photo_file_id"] = chz_photo_file_id
    context.user_data["return_chz_status"] = "Фото отправлено"

    try:
        chz_status = await send_chz_photo_to_topic(
            context=context,
            user=update.effective_user,
            photo_file_id=chz_photo_file_id,
        )
    except Exception as error:
        logging.exception("Не удалось отправить фото ЧЗ в отдельную тему")
        chz_status = f"Фото ЧЗ сохранено, но не отправлено в отдельную тему ⚠️\nОшибка: {error}"

    await update.message.reply_text(
        f"{chz_status}\n\nШаг 3/7. Введите ФИО контрагента:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_COUNTERPARTY


async def chz_missing_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["return_chz_status"] = "ЧЗ нет"
    context.user_data.pop("return_chz_photo_file_id", None)

    await query.edit_message_text(
        "ЧЗ отмечен как отсутствующий.\n\n"
        "Шаг 3/7. Введите ФИО контрагента:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_COUNTERPARTY


async def back_to_chz_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_chz_photo_file_id", None)
    context.user_data.pop("return_chz_status", None)

    await query.edit_message_text(
        "Шаг 2/7. Отправьте фото маркировки «Честный знак» "
        "или нажмите кнопку «ЧЗ нет»:",
        reply_markup=build_chz_photo_keyboard(),
    )

    return RET_CHZ_PHOTO


async def back_from_counterparty_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_cdek_return(context):
        return await back_to_invoice_photo(update, context)

    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    await query.edit_message_text(
        "Главное меню:",
        reply_markup=build_main_menu_keyboard(),
    )

    return ConversationHandler.END


# ============================================================
# ФИО
# ============================================================

async def counterparty_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counterparty = update.message.text.strip()

    if not counterparty:
        await update.message.reply_text(
            "ФИО не должно быть пустым. Введите ФИО контрагента:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_COUNTERPARTY

    context.user_data["return_counterparty"] = counterparty

    if is_cdek_return(context):
        await update.message.reply_text(
            "Шаг 3/6. Введите трек-номер числом:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_TRACK_NUMBER

    await update.message.reply_text(
        "Шаг 2/4. Введите количество вещей в возврате:",
        reply_markup=build_return_nav_keyboard(),
    )
    return RET_ITEMS_COUNT


async def back_to_counterparty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_counterparty", None)

    await query.edit_message_text(
        "Шаг 2/6. Введите ФИО контрагента заново:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_COUNTERPARTY


# ============================================================
# ТРЕК-НОМЕР
# ============================================================

async def track_number_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_number = update.message.text.strip()

    if not track_number.isdigit():
        await update.message.reply_text(
            "Трек-номер должен содержать только цифры. Введите ещё раз:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_TRACK_NUMBER

    context.user_data["return_track_number"] = track_number

    await update.message.reply_text(
        "Шаг 4/6. Введите количество товаров в возврате:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_ITEMS_COUNT


async def back_to_track_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_track_number", None)

    await query.edit_message_text(
        "Шаг 3/6. Введите трек-номер заново:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_TRACK_NUMBER


async def back_from_items_count_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_cdek_return(context):
        return await back_to_track_number(update, context)

    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_items_count", None)
    context.user_data.pop("return_items", None)
    clear_current_item(context)

    await query.edit_message_text(
        "Шаг 1/4. Введите ФИО контрагента заново:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_COUNTERPARTY


# ============================================================
# КОЛИЧЕСТВО ТОВАРОВ
# ============================================================

async def items_count_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = parse_positive_number(update.message.text)

    if value is None:
        await update.message.reply_text(
            "Количество товаров должно быть целым числом больше 0. Введите ещё раз:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_ITEMS_COUNT

    if value > 30:
        await update.message.reply_text(
            "Для теста максимум 30 товаров в одном возврате. Введите число от 1 до 30:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_ITEMS_COUNT

    context.user_data["return_items_count"] = value
    context.user_data["return_items"] = []
    clear_current_item(context)

    step_text = "Шаг 5/6" if is_cdek_return(context) else "Шаг 3/4"

    await update.message.reply_text(
        f"{step_text}. Товар 1 из {value}.\n\n"
        "Выберите группу товара:",
        reply_markup=build_return_category_keyboard(),
    )

    return RET_ITEM_CATEGORY


async def back_to_items_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("return_items_count", None)
    context.user_data.pop("return_items", None)
    clear_current_item(context)

    await query.edit_message_text(
        "Шаг 4/6. Введите количество товаров в возврате заново:",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_ITEMS_COUNT


# ============================================================
# ВЫБОР ТОВАРОВ
# ============================================================

async def return_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category_id = query.data.replace("retcat:", "")

    if category_id not in CATEGORIES:
        await query.edit_message_text(
            "Такой группы нет. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    current_item = get_current_item(context)
    current_item.clear()
    current_item["category_id"] = category_id

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"Группа: {CATEGORIES[category_id]['name']}\n\n"
        "Выберите модель:",
        reply_markup=build_return_models_keyboard(category_id),
    )

    return RET_ITEM_MODEL


async def back_from_item_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = get_return_items(context)

    if not items:
        context.user_data.pop("return_items_count", None)
        clear_current_item(context)

        await query.edit_message_text(
            "Шаг 4/6. Введите количество товаров в возврате заново:",
            reply_markup=build_return_nav_keyboard(),
        )

        return RET_ITEMS_COUNT

    items.pop()
    clear_current_item(context)

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Шаг 5/6. Товар {item_no} из {total}.\n\n"
        "Выберите группу товара заново:",
        reply_markup=build_return_category_keyboard(),
    )

    return RET_ITEM_CATEGORY


async def return_model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    model_id = query.data.replace("retmodel:", "")

    current_item = get_current_item(context)
    category_id = current_item.get("category_id")

    if not category_id or category_id not in CATEGORIES:
        await query.edit_message_text(
            "Группа не выбрана. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    models = CATEGORIES[category_id]["models"]

    if model_id not in models:
        await query.edit_message_text(
            "Такой модели нет. Выберите модель:",
            reply_markup=build_return_models_keyboard(category_id),
        )
        return RET_ITEM_MODEL

    current_item["model_id"] = model_id

    variants = models[model_id]["variants"]

    if len(variants) == 1:
        variant_data = list(variants.values())[0]
        product_id = variant_data["id"]

        current_item["product_id"] = product_id

        item_no = current_item_number(context)
        total = total_items_count(context)

        await query.edit_message_text(
            f"Товар {item_no} из {total}\n"
            f"Товар: {variant_data['name']}\n\n"
            "Выберите размер:",
            reply_markup=build_return_sizes_keyboard(),
        )

        return RET_ITEM_SIZE

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"Модель: {models[model_id]['name']}\n\n"
        "Выберите цвет / вариант:",
        reply_markup=build_return_product_colors_keyboard(category_id, model_id),
    )

    return RET_ITEM_PRODUCT


async def back_to_return_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    clear_current_item(context)

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}.\n\n"
        "Выберите группу товара заново:",
        reply_markup=build_return_category_keyboard(),
    )

    return RET_ITEM_CATEGORY


async def return_product_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = query.data.replace("retprod:", "")

    current_item = get_current_item(context)
    category_id = current_item.get("category_id")
    model_id = current_item.get("model_id")

    if not category_id or not model_id:
        await query.edit_message_text(
            "Модель не выбрана. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    products = CATEGORIES[category_id]["products"]

    if product_id not in products:
        await query.edit_message_text(
            "Такого товара нет. Выберите цвет / вариант:",
            reply_markup=build_return_product_colors_keyboard(category_id, model_id),
        )
        return RET_ITEM_PRODUCT

    current_item["product_id"] = product_id
    current_item.pop("chz_photo_file_id", None)
    current_item.pop("chz_status", None)

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"Товар: {products[product_id]}\n\n"
        "Отправьте фото маркировки «Честный знак» по этому товару "
        "или нажмите кнопку «ЧЗ нет»:",
        reply_markup=build_chz_photo_keyboard(),
    )

    return RET_ITEM_CHZ_PHOTO


async def back_to_return_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    category_id = current_item.get("category_id")

    if not category_id or category_id not in CATEGORIES:
        await query.edit_message_text(
            "Группа не выбрана. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    current_item.pop("model_id", None)
    current_item.pop("product_id", None)

    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"Группа: {CATEGORIES[category_id]['name']}\n\n"
        "Выберите модель заново:",
        reply_markup=build_return_models_keyboard(category_id),
    )

    return RET_ITEM_MODEL


async def item_chz_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Пожалуйста, отправьте именно фото маркировки «Честный знак» "
            "или нажмите кнопку «ЧЗ нет».",
            reply_markup=build_chz_photo_keyboard(),
        )
        return RET_ITEM_CHZ_PHOTO

    current_item = get_current_item(context)
    chz_photo_file_id = update.message.photo[-1].file_id
    current_item["chz_photo_file_id"] = chz_photo_file_id
    current_item["chz_status"] = "Фото отправлено"

    try:
        chz_status = await send_item_chz_photo_to_topic(
            context=context,
            user=update.effective_user,
            photo_file_id=chz_photo_file_id,
        )
    except Exception as error:
        logging.exception("Не удалось отправить фото ЧЗ по товару в отдельную тему")
        chz_status = f"Фото ЧЗ сохранено, но не отправлено в отдельную тему ⚠️\nОшибка: {error}"

    product_name = get_current_item_product_name(context)
    item_no = current_item_number(context)
    total = total_items_count(context)

    await update.message.reply_text(
        f"{chz_status}\n\n"
        f"Товар {item_no} из {total}\n"
        f"Товар: {product_name}\n\n"
        "Выберите размер:",
        reply_markup=build_return_sizes_keyboard(),
    )

    return RET_ITEM_SIZE


async def item_chz_missing_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    current_item["chz_status"] = "ЧЗ нет"
    current_item.pop("chz_photo_file_id", None)

    product_name = get_current_item_product_name(context)
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"ЧЗ по товару отмечен как отсутствующий.\n\n"
        f"Товар {item_no} из {total}\n"
        f"Товар: {product_name}\n\n"
        "Выберите размер:",
        reply_markup=build_return_sizes_keyboard(),
    )

    return RET_ITEM_SIZE


async def return_size_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    size = query.data.replace("retsize:", "")

    if size not in SIZES:
        await query.edit_message_text(
            "Такого размера нет. Выберите размер:",
            reply_markup=build_return_sizes_keyboard(),
        )
        return RET_ITEM_SIZE

    current_item = get_current_item(context)
    category_id = current_item.get("category_id")
    model_id = current_item.get("model_id")
    product_id = current_item.get("product_id")

    if not category_id or not model_id or not product_id:
        await query.edit_message_text(
            "Данные товара потерялись. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    current_item["size"] = size

    product_name = CATEGORIES[category_id]["products"][product_id]
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"{product_name} — размер {size}\n\n"
        "Выберите состояние товара:",
        reply_markup=build_return_condition_keyboard(),
    )

    return RET_ITEM_CONDITION


async def back_to_return_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    category_id = current_item.get("category_id")
    model_id = current_item.get("model_id")

    if not category_id or not model_id:
        await query.edit_message_text(
            "Модель не выбрана. Выберите группу:",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    current_item.pop("product_id", None)
    current_item.pop("chz_photo_file_id", None)
    current_item.pop("chz_status", None)

    variants = CATEGORIES[category_id]["models"][model_id]["variants"]

    item_no = current_item_number(context)
    total = total_items_count(context)

    if len(variants) == 1:
        current_item.pop("model_id", None)

        await query.edit_message_text(
            f"Товар {item_no} из {total}\n"
            f"Группа: {CATEGORIES[category_id]['name']}\n\n"
            "Выберите модель заново:",
            reply_markup=build_return_models_keyboard(category_id),
        )

        return RET_ITEM_MODEL

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n\n"
        "Выберите цвет / вариант заново:",
        reply_markup=build_return_product_colors_keyboard(category_id, model_id),
    )

    return RET_ITEM_PRODUCT


# ============================================================
# СОСТОЯНИЕ, ДОП. ФОТО И КОММЕНТАРИЙ К ТОВАРУ
# ============================================================

async def return_condition_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    condition_key = query.data.replace("retcond:", "")

    if condition_key not in RETURN_CONDITIONS:
        await query.edit_message_text(
            "Такого состояния нет. Выберите состояние товара:",
            reply_markup=build_return_condition_keyboard(),
        )
        return RET_ITEM_CONDITION

    current_item = get_current_item(context)
    current_item["condition_key"] = condition_key

    condition = RETURN_CONDITIONS[condition_key]

    if not condition["needs_photo"]:
        try:
            append_current_item(context)
        except Exception as error:
            logging.exception("Не удалось добавить товар в возврат")
            await query.edit_message_text(
                f"Не удалось добавить товар ⚠️\nОшибка: {error}",
                reply_markup=build_return_category_keyboard(),
            )
            return RET_ITEM_CATEGORY

        return await ask_next_item_or_finish(query, context, query.from_user)

    product_name = get_current_item_product_name(context)
    size = current_item.get("size", "")
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"{product_name} — размер {size}\n"
        f"Состояние: {condition['label']}\n\n"
        f"{condition['photo_prompt']}",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_ITEM_EXTRA_PHOTO


async def back_to_return_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    current_item.pop("size", None)
    current_item.pop("condition_key", None)
    current_item.pop("extra_photo_file_id", None)
    current_item.pop("condition_comment", None)

    product_name = get_current_item_product_name(context)
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"Товар: {product_name}\n\n"
        "Выберите размер заново:",
        reply_markup=build_return_sizes_keyboard(),
    )

    return RET_ITEM_SIZE


async def extra_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Пожалуйста, отправьте именно фото переупакованного возврата.",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_ITEM_EXTRA_PHOTO

    current_item = get_current_item(context)
    current_item["extra_photo_file_id"] = update.message.photo[-1].file_id

    condition_key = current_item.get("condition_key")
    condition = RETURN_CONDITIONS.get(condition_key, {})

    product_name = get_current_item_product_name(context)
    size = current_item.get("size", "")
    item_no = current_item_number(context)
    total = total_items_count(context)

    await update.message.reply_text(
        f"Товар {item_no} из {total}\n"
        f"{product_name} — размер {size}\n"
        f"Состояние: {condition.get('label', '')}\n\n"
        f"{condition.get('comment_prompt', 'Введите комментарий к товару:')}",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_ITEM_CONDITION_COMMENT


async def back_to_return_condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    current_item.pop("condition_key", None)
    current_item.pop("extra_photo_file_id", None)
    current_item.pop("condition_comment", None)

    product_name = get_current_item_product_name(context)
    size = current_item.get("size", "")
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"{product_name} — размер {size}\n\n"
        "Выберите состояние товара заново:",
        reply_markup=build_return_condition_keyboard(),
    )

    return RET_ITEM_CONDITION


async def condition_comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()

    if not comment:
        await update.message.reply_text(
            "Комментарий не должен быть пустым. Введите комментарий:",
            reply_markup=build_return_nav_keyboard(),
        )
        return RET_ITEM_CONDITION_COMMENT

    current_item = get_current_item(context)
    current_item["condition_comment"] = comment

    try:
        append_current_item(context)
    except Exception as error:
        logging.exception("Не удалось добавить товар в возврат")
        await update.message.reply_text(
            f"Не удалось добавить товар ⚠️\nОшибка: {error}",
            reply_markup=build_return_category_keyboard(),
        )
        return RET_ITEM_CATEGORY

    return await ask_next_item_or_finish(update.message, context, update.effective_user)


async def back_to_extra_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_item = get_current_item(context)
    current_item.pop("extra_photo_file_id", None)
    current_item.pop("condition_comment", None)

    condition_key = current_item.get("condition_key")
    condition = RETURN_CONDITIONS.get(condition_key, {})

    product_name = get_current_item_product_name(context)
    size = current_item.get("size", "")
    item_no = current_item_number(context)
    total = total_items_count(context)

    await query.edit_message_text(
        f"Товар {item_no} из {total}\n"
        f"{product_name} — размер {size}\n"
        f"Состояние: {condition.get('label', '')}\n\n"
        f"{condition.get('photo_prompt', 'Отправьте фото переупакованного возврата.')}",
        reply_markup=build_return_nav_keyboard(),
    )

    return RET_ITEM_EXTRA_PHOTO


# ============================================================
# ФИНАЛЬНЫЙ ТЕКСТ И ОТПРАВКА В ТЕМУ
# ============================================================

def get_required_mentions(items):
    mentions = []

    for item in items:
        condition_key = item.get("condition_key")
        condition = RETURN_CONDITIONS.get(condition_key, {})

        for mention_type in condition.get("mentions", []):
            if mention_type == "warehouse" and WAREHOUSE_MANAGER_MENTION not in mentions:
                mentions.append(WAREHOUSE_MANAGER_MENTION)

            if mention_type == "support" and SUPPORT_MANAGER_MENTION not in mentions:
                mentions.append(SUPPORT_MANAGER_MENTION)

    return mentions


def format_return_summary(context: ContextTypes.DEFAULT_TYPE, user):
    counterparty = context.user_data.get("return_counterparty", "")
    track_number = context.user_data.get("return_track_number", "")
    items = get_return_items(context)

    employee_full_name = get_employee_full_name_for_user(user)
    return_type_label = get_return_type_label(context)

    lines = [
        f"Тип возврата: {return_type_label}",
        f"Сотрудник: {employee_full_name}",
        f"ФИО контрагента: {counterparty}",
    ]

    if is_cdek_return(context):
        lines.append(f"Трек-номер: {track_number}")

    lines.extend(
        [
            f"Количество товаров: {len(items)}",
            "",
            "Товары:",
        ]
    )

    for index, item in enumerate(items, start=1):
        category_id = item["category_id"]
        product_id = item["product_id"]
        size = item["size"]
        condition_label = item["condition_label"]
        condition_comment = item.get("condition_comment", "")
        chz_status = item.get("chz_status", "")

        product_name = CATEGORIES[category_id]["products"][product_id]

        item_line = f"{index}. {product_name} — размер {size}, ЧЗ: {chz_status}, {condition_label}"

        if condition_comment and condition_comment != "-":
            item_line += f", комментарий: {condition_comment}"

        lines.append(item_line)

    mentions = get_required_mentions(items)

    if mentions:
        lines.append("")
        lines.extend(mentions)

    return "\n".join(lines)

def get_return_photo_file_ids(context: ContextTypes.DEFAULT_TYPE):
    photo_file_ids = []

    invoice_photo_file_id = context.user_data.get("return_invoice_photo_file_id")

    if invoice_photo_file_id:
        photo_file_ids.append(invoice_photo_file_id)

    for item in get_return_items(context):
        extra_photo_file_id = item.get("extra_photo_file_id")

        if extra_photo_file_id:
            photo_file_ids.append(extra_photo_file_id)

    return photo_file_ids


def split_into_chunks(items, chunk_size):
    for index in range(0, len(items), chunk_size):
        yield items[index:index + chunk_size]


async def send_return_to_topic(context: ContextTypes.DEFAULT_TYPE, caption):
    if not GROUP_CHAT_ID:
        return "Тема чата не настроена: GROUP_CHAT_ID пустой."

    chat_id = int(GROUP_CHAT_ID)
    message_thread_id = int(RETURNS_TOPIC_ID) if RETURNS_TOPIC_ID else None

    photo_file_ids = get_return_photo_file_ids(context)

    final_caption = caption

    if not photo_file_ids:
        await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            text=final_caption,
        )
        return "Сообщение отправлено в тему чата ✅"

    if len(final_caption) > 1000:
        final_caption = final_caption[:950] + "\n\n...текст обрезан, товаров слишком много."

    common_kwargs = {
        "chat_id": chat_id,
    }

    if message_thread_id is not None:
        common_kwargs["message_thread_id"] = message_thread_id

    if len(photo_file_ids) == 1:
        await context.bot.send_photo(
            **common_kwargs,
            photo=photo_file_ids[0],
            caption=final_caption,
        )
        return "Сообщение отправлено в тему чата ✅"

    first_chunk = True

    for chunk in split_into_chunks(photo_file_ids, 10):
        media = []

        for index, photo_file_id in enumerate(chunk):
            if first_chunk and index == 0:
                media.append(InputMediaPhoto(media=photo_file_id, caption=final_caption))
            else:
                media.append(InputMediaPhoto(media=photo_file_id))

        await context.bot.send_media_group(
            **common_kwargs,
            media=media,
        )

        first_chunk = False

    return "Сообщение отправлено в тему чата ✅"


# ============================================================
# CONVERSATION HANDLER
# ============================================================

def get_returns_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(return_start, pattern=r"^menu:return(:cdek|:showroom)?$"),
        ],
        states={
            RET_PHOTO: [
                MessageHandler(filters.PHOTO, invoice_photo_received),
                CallbackQueryHandler(return_back_from_photo, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_COUNTERPARTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, counterparty_received),
                CallbackQueryHandler(back_from_counterparty_step, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_TRACK_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, track_number_received),
                CallbackQueryHandler(back_to_counterparty, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEMS_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, items_count_received),
                CallbackQueryHandler(back_from_items_count_step, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_CATEGORY: [
                CallbackQueryHandler(return_category_selected, pattern=r"^retcat:"),
                CallbackQueryHandler(back_from_item_category, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_MODEL: [
                CallbackQueryHandler(return_model_selected, pattern=r"^retmodel:"),
                CallbackQueryHandler(back_to_return_category, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_PRODUCT: [
                CallbackQueryHandler(return_product_selected, pattern=r"^retprod:"),
                CallbackQueryHandler(back_to_return_model, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_CHZ_PHOTO: [
                MessageHandler(filters.PHOTO, item_chz_photo_received),
                CallbackQueryHandler(item_chz_missing_selected, pattern=r"^ret:chz_missing$"),
                CallbackQueryHandler(back_to_return_product, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_SIZE: [
                CallbackQueryHandler(return_size_selected, pattern=r"^retsize:"),
                CallbackQueryHandler(back_to_return_product, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_CONDITION: [
                CallbackQueryHandler(return_condition_selected, pattern=r"^retcond:"),
                CallbackQueryHandler(back_to_return_size, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_EXTRA_PHOTO: [
                MessageHandler(filters.PHOTO, extra_photo_received),
                CallbackQueryHandler(back_to_return_condition, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
            RET_ITEM_CONDITION_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, condition_comment_received),
                CallbackQueryHandler(back_to_extra_photo, pattern=r"^ret:back$"),
                CallbackQueryHandler(return_cancel, pattern=r"^ret:cancel$"),
            ],
        },
        fallbacks=[],
    )