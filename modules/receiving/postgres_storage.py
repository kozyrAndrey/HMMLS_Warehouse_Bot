from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, desc, inspect, select, text
from sqlalchemy.orm import Mapped, mapped_column

from modules.receiving.products import CATEGORIES
from modules.storage.postgres import Base, check_connection, get_engine, session_scope


class IncomingGood(Base):
    __tablename__ = "incoming_goods"
    __table_args__ = (
        Index("ix_incoming_goods_record_date", "record_date"),
        Index("ix_incoming_goods_product_id", "product_id"),
        Index("ix_incoming_goods_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    packed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    defective: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rework: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime)
    exported_by: Mapped[str | None] = mapped_column(String(255))
    export_id: Mapped[str | None] = mapped_column(String(100))
    export_chat_id: Mapped[str | None] = mapped_column(String(100))
    export_thread_id: Mapped[str | None] = mapped_column(String(100))
    export_message_ids: Mapped[str | None] = mapped_column(String(1000))


def init_receiving_storage():
    Base.metadata.create_all(get_engine(), tables=[IncomingGood.__table__])
    ensure_receiving_columns()


def ensure_receiving_columns():
    statements = [
        "alter table incoming_goods add column if not exists exported boolean not null default false",
        "alter table incoming_goods add column if not exists exported_at timestamp",
        "alter table incoming_goods add column if not exists exported_by varchar(255)",
        "alter table incoming_goods add column if not exists export_id varchar(100)",
        "alter table incoming_goods add column if not exists export_chat_id varchar(100)",
        "alter table incoming_goods add column if not exists export_thread_id varchar(100)",
        "alter table incoming_goods add column if not exists export_message_ids varchar(1000)",
        "create index if not exists ix_incoming_goods_exported on incoming_goods (exported)",
        "create index if not exists ix_incoming_goods_export_id on incoming_goods (export_id)",
    ]

    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_table_columns(table_name):
    inspector = inspect(get_engine())
    return {column["name"] for column in inspector.get_columns(table_name)}


def get_receiving_db_status():
    version = check_connection()
    columns = sorted(get_table_columns(IncomingGood.__tablename__))
    return version, columns


def get_last_records_text(limit=10):
    with session_scope() as session:
        records = (
            session.execute(
                select(IncomingGood)
                .order_by(desc(IncomingGood.id))
                .limit(limit)
            )
            .scalars()
            .all()
        )

    if not records:
        return "Пока нет записей в PostgreSQL."

    lines = [f"📋 Последние {min(limit, len(records))} записей из PostgreSQL:"]

    for record in records:
        lines.append(
            f"\n{record.record_date.strftime('%d.%m.%Y')}\n"
            f"Пользователь: {record.username or '-'}\n"
            f"Группа: {record.category_name}\n"
            f"Модель: {record.product_name}\n"
            f"Размер: {record.size}\n"
            f"Упаковано: {record.packed}\n"
            f"Брак: {record.defective}\n"
            f"Доработка: {record.rework}"
        )

    return "\n".join(lines)


def split_message_ids(value):
    if not value:
        return []

    result = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue

    return result


def parse_report_date(value):
    return datetime.strptime(str(value).strip(), "%d.%m.%Y").date()


def record_to_dict(record):
    return {
        "row_number": record.id,
        "date": record.record_date.strftime("%d.%m.%Y"),
        "user_id": str(record.user_id or ""),
        "username": record.username or "",
        "category_name": record.category_name,
        "product_name": record.product_name,
        "size": record.size,
        "packed": int(record.packed or 0),
        "defective": int(record.defective or 0),
        "rework": int(record.rework or 0),
        "exported": bool(record.exported),
        "exported_at": record.exported_at.strftime("%d.%m.%Y %H:%M:%S") if record.exported_at else "",
        "exported_by": record.exported_by or "",
        "export_id": record.export_id or "",
        "export_chat_id": record.export_chat_id or "",
        "export_thread_id": record.export_thread_id or "",
        "export_message_ids": record.export_message_ids or "",
    }


def get_unexported_receiving_records(limit=15):
    with session_scope() as session:
        records = (
            session.execute(
                select(IncomingGood)
                .where(IncomingGood.exported.is_(False))
                .order_by(desc(IncomingGood.id))
                .limit(limit)
            )
            .scalars()
            .all()
        )

    return [record_to_dict(record) for record in records]


def get_receiving_record_by_row(row_number):
    with session_scope() as session:
        record = session.get(IncomingGood, int(row_number))
        return record_to_dict(record) if record else None


def delete_unexported_receiving_record(row_number):
    with session_scope() as session:
        record = session.get(IncomingGood, int(row_number))

        if not record:
            raise RuntimeError("Запись не найдена.")

        if record.exported:
            raise RuntimeError("Эта запись уже выгружена в отчет, ее нельзя удалить.")

        result = record_to_dict(record)
        session.delete(record)

    return result


def has_unexported_receiving_records_for_date(report_date):
    parsed_date = parse_report_date(report_date)

    with session_scope() as session:
        record = session.execute(
            select(IncomingGood.id)
            .where(
                IncomingGood.record_date == parsed_date,
                IncomingGood.exported.is_(False),
            )
            .limit(1)
        ).first()

    return record is not None


def mark_receiving_rows_exported(
    report_date,
    exported_by,
    export_id,
    chat_id,
    thread_id,
    message_ids,
):
    parsed_date = parse_report_date(report_date)
    now_value = datetime.now()
    message_ids_text = ",".join(str(message_id) for message_id in message_ids)

    with session_scope() as session:
        records = (
            session.execute(
                select(IncomingGood)
                .where(
                    IncomingGood.record_date == parsed_date,
                    IncomingGood.exported.is_(False),
                )
            )
            .scalars()
            .all()
        )

        for record in records:
            record.exported = True
            record.exported_at = now_value
            record.exported_by = exported_by
            record.export_id = export_id
            record.export_chat_id = str(chat_id)
            record.export_thread_id = str(thread_id)
            record.export_message_ids = message_ids_text

        return len(records)


def build_receiving_report_text(report_date, exported_by=None, only_unexported=True):
    parsed_date = parse_report_date(report_date)
    header_lines = [f"Дата: {report_date}"]

    if exported_by:
        header_lines.append(f"Выгрузил: {exported_by}")

    with session_scope() as session:
        statement = select(IncomingGood).where(IncomingGood.record_date == parsed_date)

        if only_unexported:
            statement = statement.where(IncomingGood.exported.is_(False))

        records = session.execute(statement).scalars().all()

    grouped = defaultdict(lambda: defaultdict(lambda: {
        "packed": 0,
        "defective": 0,
        "rework": 0,
    }))

    total_packed = 0
    total_defective = 0
    total_rework = 0

    for record in records:
        grouped[record.product_name][record.size]["packed"] += record.packed
        grouped[record.product_name][record.size]["defective"] += record.defective
        grouped[record.product_name][record.size]["rework"] += record.rework

        total_packed += record.packed
        total_defective += record.defective
        total_rework += record.rework

    if not grouped:
        if only_unexported:
            return "\n".join(header_lines) + "\n\nНет невыгруженных записей за эту дату."

        return "\n".join(header_lines) + "\n\nНет записей за эту дату."

    lines = header_lines + [""]

    for product_name in sorted(grouped.keys()):
        lines.append(product_name)

        for size in sorted(grouped[product_name].keys()):
            packed = grouped[product_name][size]["packed"]
            defective = grouped[product_name][size]["defective"]
            rework = grouped[product_name][size]["rework"]
            total = packed + defective + rework

            lines.append(
                f"{size}: упаковано - {packed}, "
                f"брак - {defective}, "
                f"доработка - {rework}, "
                f"общее - {total}"
            )

        lines.append("")

    grand_total = total_packed + total_defective + total_rework

    lines.extend(
        [
            f"Общее упаковано: {total_packed}",
            f"Общее брак: {total_defective}",
            f"Общее доработка: {total_rework}",
            f"Общее: {grand_total}",
        ]
    )

    return "\n".join(lines)


def make_export_group(export_id, records):
    first = records[0]

    total_packed = sum(record.packed for record in records)
    total_defective = sum(record.defective for record in records)
    total_rework = sum(record.rework for record in records)

    return {
        "export_id": export_id,
        "date": first.record_date.strftime("%d.%m.%Y"),
        "exported_at": first.exported_at.strftime("%d.%m.%Y %H:%M:%S") if first.exported_at else "",
        "exported_by": first.exported_by or "",
        "chat_id": first.export_chat_id or "",
        "thread_id": first.export_thread_id or "",
        "message_ids": split_message_ids(first.export_message_ids),
        "row_count": len(records),
        "row_numbers": [record.id for record in records],
        "total_packed": total_packed,
        "total_defective": total_defective,
        "total_rework": total_rework,
        "total": total_packed + total_defective + total_rework,
        "last_row_number": max(record.id for record in records),
    }


def get_exported_receiving_report_groups(limit=10):
    with session_scope() as session:
        records = (
            session.execute(
                select(IncomingGood)
                .where(
                    IncomingGood.exported.is_(True),
                    IncomingGood.export_id.is_not(None),
                    IncomingGood.export_message_ids.is_not(None),
                )
                .order_by(desc(IncomingGood.id))
            )
            .scalars()
            .all()
        )

    groups = defaultdict(list)

    for record in records:
        if record.export_id and record.export_message_ids:
            groups[record.export_id].append(record)

    result = [make_export_group(export_id, rows) for export_id, rows in groups.items()]
    result.sort(key=lambda item: item["last_row_number"], reverse=True)

    return result[:limit]


def get_exported_receiving_report_by_export_id(export_id):
    groups = get_exported_receiving_report_groups(limit=1000)

    for group in groups:
        if group["export_id"] == export_id:
            return group

    return None


def unmark_receiving_rows_by_export_id(export_id):
    with session_scope() as session:
        records = (
            session.execute(
                select(IncomingGood).where(IncomingGood.export_id == str(export_id).strip())
            )
            .scalars()
            .all()
        )

        for record in records:
            record.exported = False
            record.exported_at = None
            record.exported_by = None
            record.export_id = None
            record.export_chat_id = None
            record.export_thread_id = None
            record.export_message_ids = None

        return len(records)


def save_incoming_good(
    user_id,
    username,
    category_id,
    product_id,
    size,
    packed,
    defective,
    rework,
    record_date,
):
    category_name = CATEGORIES[category_id]["name"]
    product_name = CATEGORIES[category_id]["products"][product_id]
    parsed_record_date = datetime.strptime(record_date, "%d.%m.%Y").date()

    with session_scope() as session:
        session.add(
            IncomingGood(
                record_date=parsed_record_date,
                user_id=user_id,
                username=username,
                category_id=category_id,
                category_name=category_name,
                product_id=product_id,
                product_name=product_name,
                size=size,
                packed=packed,
                defective=defective,
                rework=rework,
            )
        )
