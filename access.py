# Пока доступ открыт всем пользователям.
# Позже здесь можно включить роли: admin, manager, warehouse, viewer.

USERS = {
    # 123456789: {"name": "Андрей", "role": "admin"},
}

ROLE_PERMISSIONS = {
    "admin": {"incoming", "last_records", "service"},
    "manager": {"incoming", "last_records"},
    "warehouse": {"incoming"},
    "viewer": {"last_records"},
}


def get_user_role(user_id):
    user = USERS.get(user_id)
    if not user:
        return "admin"  # Открытый режим на время разработки.
    return user.get("role", "viewer")


def has_permission(user_id, permission):
    role = get_user_role(user_id)
    return permission in ROLE_PERMISSIONS.get(role, set())
