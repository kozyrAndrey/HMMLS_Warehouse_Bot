import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH
from modules.receiving.products import CATEGORIES


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_table_columns(table_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    return columns


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incoming_goods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            username TEXT,
            category_id TEXT NOT NULL,
            category_name TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            size TEXT NOT NULL,
            packed INTEGER NOT NULL DEFAULT 0,
            defective INTEGER NOT NULL DEFAULT 0,
            rework INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cursor.execute("PRAGMA table_info(incoming_goods)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if "packed" not in existing_columns:
        cursor.execute("ALTER TABLE incoming_goods ADD COLUMN packed INTEGER NOT NULL DEFAULT 0")
    if "defective" not in existing_columns:
        cursor.execute("ALTER TABLE incoming_goods ADD COLUMN defective INTEGER NOT NULL DEFAULT 0")
    if "rework" not in existing_columns:
        cursor.execute("ALTER TABLE incoming_goods ADD COLUMN rework INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()


def save_incoming_good(user_id, username, category_id, product_id, size, packed, defective, rework):
    category_name = CATEGORIES[category_id]["name"]
    product_name = CATEGORIES[category_id]["products"][product_id]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(incoming_goods)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    columns = [
        "created_at",
        "user_id",
        "username",
        "category_id",
        "category_name",
        "product_id",
        "product_name",
        "size",
        "packed",
        "defective",
        "rework",
    ]

    values = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_id,
        username,
        category_id,
        category_name,
        product_id,
        product_name,
        size,
        packed,
        defective,
        rework,
    ]

    # Поддержка старой базы, где quantity был NOT NULL.
    if "quantity" in existing_columns:
        columns.append("quantity")
        values.append(packed + defective + rework)

    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(columns)

    cursor.execute(
        f"INSERT INTO incoming_goods ({column_names}) VALUES ({placeholders})",
        values,
    )

    conn.commit()
    conn.close()


def reset_local_db_with_backup():
    db_file = Path(DB_PATH)

    if db_file.exists():
        backup_file = db_file.with_name(
            f"warehouse_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        db_file.rename(backup_file)
    else:
        backup_file = None

    init_db()
    return backup_file
