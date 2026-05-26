from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from products import CATEGORIES, SIZES


def build_start_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 Старт", callback_data="menu:start")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# ГЛАВНОЕ МЕНЮ: ВЫБОР РАЗДЕЛА
# ============================================================

def build_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📦 Отчет оприходований", callback_data="section:receiving")],
        [InlineKeyboardButton("↩️ Возвраты", callback_data="section:returns")],
        [InlineKeyboardButton("💰 Расчет ЗП", callback_data="section:payroll")],
        [InlineKeyboardButton("📅 Расписание", callback_data="section:schedule")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_receiving_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Оприходовать товар", callback_data="menu:add")],
        [InlineKeyboardButton("📋 Последние записи", callback_data="menu:last")],
        [InlineKeyboardButton("📤 Выгрузка отчета", callback_data="report:choose_date")],
        [InlineKeyboardButton("🗑 Удалить запись", callback_data="recvdel:choose")],
        [InlineKeyboardButton("🧹 Удалить отчет из темы", callback_data="recvrepdel:choose")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_returns_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚚 СДЭК", callback_data="menu:return:cdek")],
        [InlineKeyboardButton("🏬 Шоу-рум", callback_data="menu:return:showroom")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_report_date_keyboard():
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    today_text = today.strftime("%d.%m.%Y")
    yesterday_text = yesterday.strftime("%d.%m.%Y")

    keyboard = [
        [InlineKeyboardButton(today_text, callback_data=f"report:date:{today_text}")],
        [InlineKeyboardButton(yesterday_text, callback_data=f"report:date:{yesterday_text}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="section:receiving")],
    ]

    return InlineKeyboardMarkup(keyboard)


def build_incoming_date_keyboard():
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    today_text = today.strftime("%d.%m.%Y")
    yesterday_text = yesterday.strftime("%d.%m.%Y")

    keyboard = [
        [InlineKeyboardButton(today_text, callback_data=f"incdate:{today_text}")],
        [InlineKeyboardButton(yesterday_text, callback_data=f"incdate:{yesterday_text}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="section:receiving")],
    ]

    return InlineKeyboardMarkup(keyboard)

# ============================================================
# ОПРИХОДОВАНИЕ: ГРУППА → МОДЕЛЬ → ЦВЕТ → РАЗМЕР
# ============================================================

def build_category_keyboard():
    keyboard = []

    for category_id, category_data in CATEGORIES.items():
        keyboard.append(
            [InlineKeyboardButton(category_data["name"], callback_data=f"cat:{category_id}")]
        )

    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")])
    return InlineKeyboardMarkup(keyboard)


def build_models_keyboard(category_id):
    keyboard = []
    models = CATEGORIES[category_id]["models"]

    for model_id, model_data in models.items():
        keyboard.append(
            [InlineKeyboardButton(model_data["name"], callback_data=f"model:{model_id}")]
        )

    keyboard.append([InlineKeyboardButton("⬅️ Назад к группам", callback_data="back:categories")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:start")])
    return InlineKeyboardMarkup(keyboard)


def build_product_colors_keyboard(category_id, model_id):
    keyboard = []
    variants = CATEGORIES[category_id]["models"][model_id]["variants"]

    for variant_data in variants.values():
        color = variant_data["color"]
        text = "Выбрать" if color == "ONE COLOR" else color

        keyboard.append(
            [InlineKeyboardButton(text, callback_data=f"prod:{variant_data['id']}")]
        )

    keyboard.append([InlineKeyboardButton("⬅️ Назад к моделям", callback_data="back:models")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:start")])
    return InlineKeyboardMarkup(keyboard)


def build_sizes_keyboard():
    keyboard = []

    row = []
    for size in SIZES:
        row.append(InlineKeyboardButton(size, callback_data=f"size:{size}"))

        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ Назад к цветам", callback_data="back:colors")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:start")])
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# КНОПКИ ДЛЯ ВОЗВРАТОВ
# ============================================================

def build_return_nav_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
                InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
            ]
        ]
    )


def build_return_category_keyboard():
    keyboard = []

    for category_id, category_data in CATEGORIES.items():
        keyboard.append(
            [InlineKeyboardButton(category_data["name"], callback_data=f"retcat:{category_id}")]
        )

    keyboard.append(
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
            InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_return_models_keyboard(category_id):
    keyboard = []
    models = CATEGORIES[category_id]["models"]

    for model_id, model_data in models.items():
        keyboard.append(
            [InlineKeyboardButton(model_data["name"], callback_data=f"retmodel:{model_id}")]
        )

    keyboard.append(
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
            InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_return_product_colors_keyboard(category_id, model_id):
    keyboard = []
    variants = CATEGORIES[category_id]["models"][model_id]["variants"]

    for variant_data in variants.values():
        color = variant_data["color"]
        text = "Выбрать" if color == "ONE COLOR" else color

        keyboard.append(
            [InlineKeyboardButton(text, callback_data=f"retprod:{variant_data['id']}")]
        )

    keyboard.append(
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
            InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_return_sizes_keyboard():
    keyboard = []

    row = []
    for size in SIZES:
        row.append(InlineKeyboardButton(size, callback_data=f"retsize:{size}"))

        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="ret:back"),
            InlineKeyboardButton("❌ Отмена", callback_data="ret:cancel"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)
