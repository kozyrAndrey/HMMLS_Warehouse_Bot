from pathlib import Path

bot_path = Path("bot.py")
bot = bot_path.read_text(encoding="utf-8")

if "from modules.tasks.google_sheets import init_tasks_sheet" not in bot:
    anchor = "from modules.schedule.google_sheets import init_schedule_sheet\n"
    if anchor not in bot:
        raise RuntimeError("Не найден импорт init_schedule_sheet в bot.py")
    bot = bot.replace(anchor, anchor + "from modules.tasks.google_sheets import init_tasks_sheet\n")

if "from modules.tasks.handlers import get_tasks_handlers, setup_tasks_jobs" not in bot:
    anchor = "from modules.schedule.handlers import get_schedule_handlers, setup_schedule_jobs\n"
    if anchor not in bot:
        raise RuntimeError("Не найден импорт schedule handlers в bot.py")
    bot = bot.replace(anchor, anchor + "from modules.tasks.handlers import get_tasks_handlers, setup_tasks_jobs\n")

if "tasks_ready = False" not in bot:
    anchor = '''    if not schedule_ready:
        logging.warning(
            "Модуль расписания не инициализирован. "
            "Проверьте OPERATIONS_GOOGLE_SHEET_ID и доступ service account к новой таблице."
        )

'''
    if anchor not in bot:
        raise RuntimeError("Не найден блок schedule_ready в bot.py")
    bot = bot.replace(anchor, anchor + '''    tasks_ready = False
    try:
        tasks_ready = init_tasks_sheet()
    except Exception:
        logging.exception("Не удалось инициализировать модуль задач")

    if not tasks_ready:
        logging.warning(
            "Модуль задач не инициализирован. "
            "Проверьте OPERATIONS_GOOGLE_SHEET_ID и доступ service account к operations-таблице."
        )

''')

if "for handler in get_tasks_handlers():" not in bot:
    anchor = '''    # Расписание.
    for handler in get_schedule_handlers():
        app.add_handler(handler)

    setup_schedule_jobs(app)
'''
    if anchor not in bot:
        raise RuntimeError("Не найден блок регистрации schedule handlers в bot.py")
    bot = bot.replace(anchor, '''    # Расписание.
    for handler in get_schedule_handlers():
        app.add_handler(handler)

    # Задачи.
    for handler in get_tasks_handlers():
        app.add_handler(handler)

    setup_schedule_jobs(app)
    setup_tasks_jobs(app)
''')

bot_path.write_text(bot, encoding="utf-8")

keyboard_path = Path("core/keyboards.py")
keyboard = keyboard_path.read_text(encoding="utf-8")

if 'callback_data="section:tasks"' not in keyboard:
    old = '''        [InlineKeyboardButton("💰 Расчет ЗП", callback_data="section:payroll")],
        [InlineKeyboardButton("📅 Расписание", callback_data="section:schedule")],
'''
    new = '''        [InlineKeyboardButton("💰 Расчет ЗП", callback_data="section:payroll")],
        [InlineKeyboardButton("📅 Расписание", callback_data="section:schedule")],
        [InlineKeyboardButton("🧩 Задачи", callback_data="section:tasks")],
'''
    if old not in keyboard:
        raise RuntimeError("Не найден блок главного меню в core/keyboards.py")
    keyboard = keyboard.replace(old, new)

keyboard_path.write_text(keyboard, encoding="utf-8")
print("Патч применен ✅")
