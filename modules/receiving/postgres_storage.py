from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, desc, inspect, select
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


def init_receiving_storage():
    Base.metadata.create_all(get_engine(), tables=[IncomingGood.__table__])


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
