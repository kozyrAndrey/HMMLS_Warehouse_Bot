from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from core.keyboards import build_products_menu_keyboard
from modules.payroll.google_sheets import find_employee_for_telegram_user, is_manager
from modules.receiving.products import add_custom_product


(
    PRODUCT_ADD_CATEGORY,
    PRODUCT_ADD_MODEL,
    PRODUCT_ADD_COLOR,
) = range(1700, 1703)


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="prodadmin:cancel")]])


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
        "Введите группу товара.\n\n"
        "Если такая группа уже есть, напишите ее название точно так же.",
        reply_markup=cancel_keyboard(),
    )
    return PRODUCT_ADD_CATEGORY


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
    try:
        product = add_custom_product(
            category_name=data.get("category_name", ""),
            model_name=data.get("model_name", ""),
            color=color,
        )
    except Exception as error:
        await update.message.reply_text(
            f"Не удалось добавить товар: {error}",
            reply_markup=build_products_menu_keyboard(),
        )
        context.user_data.pop("product_add", None)
        return ConversationHandler.END

    context.user_data.pop("product_add", None)
    await update.message.reply_text(
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
            PRODUCT_ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_category_received)],
            PRODUCT_ADD_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_model_received)],
            PRODUCT_ADD_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_color_received)],
        },
        fallbacks=[CallbackQueryHandler(products_cancel, pattern=r"^prodadmin:cancel$")],
        name="products_management",
        persistent=False,
    )
    return [conversation]
