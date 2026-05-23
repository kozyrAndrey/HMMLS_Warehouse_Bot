# ============================================================
# НАСТРОЙКИ МОДУЛЯ ЗП
# ============================================================
# Здесь хранятся стартовые справочники сотрудников и KPI.
# При первом запуске модуль создаст/заполнит листы в Google Таблице.
# После этого ставки, роли и user_id можно редактировать прямо в листе «Сотрудники».

PAYROLL_EMPLOYEES = [
    {
        "employee_id": "emp001",
        "full_name": "Андрей Козырь",
        "telegram_user_id": "413489632",
        "telegram_username": "opulent_shooter",
        "role": "warehouse_manager",
        "hourly_rate": 437.5,
        "fixed_salary": 70000,
        "include_in_common_fund": False,
        "is_active": True,
    },
    {
        "employee_id": "emp002",
        "full_name": "Дмитрий Тарасов",
        "telegram_user_id": "927075259",
        "telegram_username": "adafagahajakal",
        "role": "warehouse_employee",
        "hourly_rate": 437.5,
        "fixed_salary": 40000,
        "include_in_common_fund": True,
        "is_active": True,
    },
    {
        "employee_id": "emp003",
        "full_name": "Константин Рогов",
        "telegram_user_id": "1152528155",
        "telegram_username": "kstyaaaa",
        "role": "warehouse_employee",
        "hourly_rate": 312.5,
        "fixed_salary": 0,
        "include_in_common_fund": True,
        "is_active": True,
    },
    {
        "employee_id": "emp004",
        "full_name": "Лев Грунверг",
        "telegram_user_id": "854197803",
        "telegram_username": "fadexdf",
        "role": "warehouse_employee",
        "hourly_rate": 312.5,
        "fixed_salary": 0,
        "include_in_common_fund": True,
        "is_active": True,
    },
    {
        "employee_id": "emp005",
        "full_name": "Егор Репин",
        "telegram_user_id": "597723397",
        "telegram_username": "whereareyo0o",
        "role": "warehouse_employee",
        "hourly_rate": 312.5,
        "fixed_salary": 0,
        "include_in_common_fund": True,
        "is_active": True,
    },
    {
        "employee_id": "emp006",
        "full_name": "Файсал Сабер",
        "telegram_user_id": "5223200693",
        "telegram_username": "hamza_sam",
        "role": "warehouse_employee",
        "hourly_rate": 312.5,
        "fixed_salary": 0,
        "include_in_common_fund": True,
        "is_active": True,
    },
    {
        "employee_id": "emp007",
        "full_name": "Никита Комаричев",
        "telegram_user_id": "272117327",
        "telegram_username": "rokiothegoat",
        "role": "warehouse_employee",
        "hourly_rate": 312.5,
        "fixed_salary": 0,
        "include_in_common_fund": True,
        "is_active": True,
    },
]

PAYROLL_KPI = [
    {"kpi_id": "kpi001", "name": "Упаковка 1 слой / шарфы", "rate": 15, "is_active": True},
    {"kpi_id": "kpi002", "name": "Упаковка 2 слой", "rate": 20, "is_active": True},
    {"kpi_id": "kpi003", "name": "Упаковка 3 слой", "rate": 25, "is_active": True},
    {"kpi_id": "kpi004", "name": "Упаковка больших сумок", "rate": 15, "is_active": True},
    {"kpi_id": "kpi005", "name": "Упаковка маленьких сумок", "rate": 10, "is_active": True},
    {"kpi_id": "kpi006", "name": "Упаковка Ремни", "rate": 15, "is_active": True},
    {"kpi_id": "kpi007", "name": "Отправка", "rate": 25, "is_active": True},
    {"kpi_id": "kpi008", "name": "Сток", "rate": 10, "is_active": True},
    {"kpi_id": "kpi009", "name": "УПД для стока", "rate": 1000, "is_active": True},
    {"kpi_id": "kpi010", "name": "Пресс", "rate": 100, "is_active": True},
    {"kpi_id": "kpi011", "name": "Возврат", "rate": 10, "is_active": True},
    {"kpi_id": "kpi012", "name": "Инвент", "rate": 1000, "is_active": True},
]

# Лист для отдельной аналитики по KPI за день.
# Важно: порядок колонок здесь совпадает с порядком в Google Таблице.
KPI_DAILY_COLUMNS = [
    "Упаковка 1 Cлой",
    "Упаковка 2 Слой",
    "Упаковка 3 Слой",
    "Упаковка больших сумок",
    "Упаковка маленьких сумок",
    "Упаковка Ремни",
    "Отправка",
    "Сток",
    "УПД для стока",
    "Пресс",
    "Возврат",
    "Инвент",
]

# Соответствие KPI из справочника колонкам листа «KPI за день».
KPI_DAILY_COLUMN_BY_KPI_ID = {
    "kpi001": "Упаковка 1 Cлой",
    "kpi002": "Упаковка 2 Слой",
    "kpi003": "Упаковка 3 Слой",
    "kpi004": "Упаковка больших сумок",
    "kpi005": "Упаковка маленьких сумок",
    "kpi006": "Упаковка Ремни",
    "kpi007": "Отправка",
    "kpi008": "Сток",
    "kpi009": "УПД для стока",
    "kpi010": "Пресс",
    "kpi011": "Возврат",
    "kpi012": "Инвент",
}

# Разбивка окладной части для красивой ведомости.
# Суммы здесь указываются уже за один расчетный период, то есть за половину месяца.
SALARY_FIXED_PARTS = {
    "emp001": [
        {"label": "оклад склад", "amount": 25000},
        {"label": "оклад чз", "amount": 10000},
    ],
    "emp002": [
        {"label": "оклад ОС", "amount": 15000},
        {"label": "оклад чеки", "amount": 5000},
    ],
}

MANAGER_ROLES = {"warehouse_manager", "admin"}
EMPLOYEE_ROLES = {"warehouse_employee", "warehouse_manager", "admin"}


def normalize_username(username):
    return (username or "").strip().lstrip("@").lower()
