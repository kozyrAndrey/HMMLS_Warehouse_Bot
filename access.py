# ============================================================
# ДОСТУПЫ
# ============================================================
# Основные роли для модуля ЗП берутся из листа «Сотрудники».
# Этот файл оставлен как общий слой разрешений для старых модулей.

ROLE_PERMISSIONS = {
    "admin": {"incoming", "returns", "last_records", "service", "payroll"},
    "warehouse_manager": {"incoming", "returns", "last_records", "service", "payroll"},
    "warehouse_employee": {"incoming", "returns", "last_records", "payroll"},
    "viewer": {"last_records"},
}


def get_user_role(user_id):
    # Для старых модулей пока оставляем открытый режим.
    # В модуле ЗП сотрудник определяется через Google Таблицу «Сотрудники».
    return "admin"


def has_permission(user_id, permission):
    role = get_user_role(user_id)
    return permission in ROLE_PERMISSIONS.get(role, set())
