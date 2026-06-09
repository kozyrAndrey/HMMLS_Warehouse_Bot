import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import CONSUMABLES_TOPIC_ID, GROUP_CHAT_ID
from core.keyboards import build_consumables_menu_keyboard
from modules.consumables.storage import (
    create_supply,
    get_pending_supplies,
    get_recent_organizations,
    get_supply,
    mark_supply_accepted,
)
from modules.payroll.google_sheets import find_employee_for_telegram_user, is_manager, money, safe_float


(
    SUPPLY_NAME,
    SUPPLY_ORGANIZATION,
    SUPPLY_ORGANIZATION_NEW,
    SUPPLY_AMOUNT,
    ACCEPT_SUPPLY,
    ACCEPT_LAYOUT_PHOTO,
    ACCEPT_DOCUMENT,
) = range(500, 507)


def current_employee_or_none(update):
    return find_employee_for_telegram_user(update.effective_user)


def current_employee_name(update):
    employee = current_employee_or_none(update)
    if employee:
        return employee["full_name"]
    user = update.effective_user
    return user.full_name or user.username or str(user.id)


def consumables_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")]])


def organization_keyboard(organizations=None):
    organizations = organizations if organizations is not None else get_recent_organizations()
    rows = []
    for index, organization in enumerate(organizations):
        rows.append([InlineKeyboardButton(organization, callback_data=f"consorg:{index}")])

    rows.append([InlineKeyboardButton("➕ Новая организация", callback_data="consorg:new")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def pending_supplies_keyboard():
    rows = []
    for supply in get_pending_supplies():
        rows.append(
            [
                InlineKeyboardButton(
                    f"#{supply['id']} {supply['consumable_name']} - {supply['organization']}",
                    callback_data=f"conssup:{supply['id']}",
                )
            ]
        )

    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")])
    return InlineKeyboardMarkup(rows)


def document_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Документа нет", callback_data="consdoc:none")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cons:cancel")],
        ]
    )


def parse_positive_amount(text):
    value = safe_float(text)
    if value <= 0:
        return None
    return value


def format_supply_line(supply):
    return (
        f"#{supply['id']} {supply['consumable_name']}\n"
        f"Организация: {supply['organization']}\n"
        f"Сумма к оплате: {money(supply['amount'])}"
    )


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


async def consumables_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    employee = current_employee_or_none(update)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🧾 Расходники",
            reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
        )
    else:
        await update.message.reply_text(
            "Действие отменено.",
            reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
        )

    return ConversationHandler.END


async def add_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    if not is_manager(employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    await query.edit_message_text("Введите название расходника:", reply_markup=consumables_back_keyboard())
    return SUPPLY_NAME


async def supply_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не должно быть пустым. Введите название расходника:")
        return SUPPLY_NAME

    context.user_data["supply_name"] = name
    context.user_data["organizations"] = get_recent_organizations()
    await update.message.reply_text(
        "Выберите организацию или добавьте новую:",
        reply_markup=organization_keyboard(context.user_data["organizations"]),
    )
    return SUPPLY_ORGANIZATION


async def supply_organization_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "consorg:new":
        await query.edit_message_text("Введите наименование организации:", reply_markup=consumables_back_keyboard())
        return SUPPLY_ORGANIZATION_NEW

    try:
        index = int(data.replace("consorg:", ""))
        organization = context.user_data.get("organizations", [])[index]
    except (ValueError, IndexError):
        await query.edit_message_text(
            "Организация не найдена. Выберите заново:",
            reply_markup=organization_keyboard(context.user_data.get("organizations", [])),
        )
        return SUPPLY_ORGANIZATION

    context.user_data["organization"] = organization
    await query.edit_message_text("Введите сумму к оплате:", reply_markup=consumables_back_keyboard())
    return SUPPLY_AMOUNT


async def supply_organization_new_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    organization = update.message.text.strip()
    if not organization:
        await update.message.reply_text("Организация не должна быть пустой. Введите наименование:")
        return SUPPLY_ORGANIZATION_NEW

    context.user_data["organization"] = organization
    await update.message.reply_text("Введите сумму к оплате:", reply_markup=consumables_back_keyboard())
    return SUPPLY_AMOUNT


async def supply_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_positive_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Введите сумму числом больше 0:")
        return SUPPLY_AMOUNT

    created_by = current_employee_name(update)
    supply = create_supply(
        consumable_name=context.user_data["supply_name"],
        organization=context.user_data["organization"],
        amount=amount,
        created_by_user_id=update.effective_user.id,
        created_by_name=created_by,
    )

    employee = current_employee_or_none(update)
    await update.message.reply_text(
        "Поставка добавлена ✅\n\n" + format_supply_line(supply),
        reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def accept_supply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    supplies = get_pending_supplies()
    if not supplies:
        await query.edit_message_text(
            "Нет поставок, ожидающих приемки.",
            reply_markup=build_consumables_menu_keyboard(manager=is_manager(current_employee_or_none(update))),
        )
        return ConversationHandler.END

    await query.edit_message_text("Выберите поставку:", reply_markup=pending_supplies_keyboard())
    return ACCEPT_SUPPLY


async def accept_supply_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supply_id = query.data.replace("conssup:", "")
    supply = get_supply(supply_id)
    if not supply or supply["status"] != "pending":
        await query.edit_message_text("Поставка не найдена или уже принята.", reply_markup=pending_supplies_keyboard())
        return ACCEPT_SUPPLY

    context.user_data["supply_id"] = supply["id"]
    await query.edit_message_text(
        "Отправьте фото разложенных расходников:",
        reply_markup=consumables_back_keyboard(),
    )
    return ACCEPT_LAYOUT_PHOTO


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


async def finish_acceptance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supply = get_supply(context.user_data.get("supply_id"))
    if not supply or supply["status"] != "pending":
        text = "Поставка не найдена или уже принята."
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        context.user_data.clear()
        return ConversationHandler.END

    accepted_by = current_employee_name(update)

    try:
        message_ids, topic_status = await send_acceptance_to_topic(context, supply, accepted_by)
    except Exception as error:
        logging.exception("Не удалось отправить приемку расходника в тему")
        message_ids = []
        topic_status = f"Приемка сохранена, но не отправлена в тему ⚠️\nОшибка: {error}"

    mark_supply_accepted(
        supply_id=supply["id"],
        accepted_by_user_id=update.effective_user.id,
        accepted_by_name=accepted_by,
        layout_photo_file_id=context.user_data["layout_photo_file_id"],
        closing_document_file_id=context.user_data.get("closing_document_file_id", ""),
        closing_document_kind=context.user_data.get("closing_document_kind", "none"),
        topic_message_ids=message_ids,
    )

    employee = current_employee_or_none(update)
    text = "Приемка расходника завершена ✅\n\n" + format_supply_line(supply) + f"\n\n{topic_status}"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=build_consumables_menu_keyboard(manager=is_manager(employee)),
        )

    context.user_data.clear()
    return ConversationHandler.END


def get_consumables_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_supply_start, pattern=r"^cons:add_supply$"),
            CallbackQueryHandler(accept_supply_start, pattern=r"^cons:accept_supply$"),
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
        },
        fallbacks=[CommandHandler("cancel", consumables_cancel)],
    )


def get_consumables_handlers():
    return [
        CallbackQueryHandler(consumables_menu, pattern=r"^section:consumables$"),
        get_consumables_conversation_handler(),
    ]
