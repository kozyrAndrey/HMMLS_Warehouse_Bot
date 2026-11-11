from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, Integer, JSON, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from modules.storage.postgres import Base, get_engine, session_scope


MSK_TZ = ZoneInfo("Europe/Moscow")


def now_msk_naive():
    return datetime.now(MSK_TZ).replace(tzinfo=None)


class ShippingRecord(Base):
    __tablename__ = "shipping_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moysklad_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    shipping_type: Mapped[str] = mapped_column(String(30), nullable=False)
    order_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    marking_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    collector_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    collector_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    moysklad_demand_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    moysklad_demand_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    assembled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_msk_naive)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_msk_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_msk_naive)


def init_shipping_storage():
    Base.metadata.create_all(get_engine(), tables=[ShippingRecord.__table__])
    return True


def record_to_dict(row):
    if not row:
        return None
    return {
        "id": row.id,
        "moysklad_order_id": row.moysklad_order_id,
        "order_number": row.order_number,
        "shipping_type": row.shipping_type,
        "order_snapshot": list(row.order_snapshot or []),
        "marking_codes": list(row.marking_codes or []),
        "collector_employee_id": row.collector_employee_id,
        "collector_name": row.collector_name,
        "created_by_employee_id": row.created_by_employee_id,
        "created_by_name": row.created_by_name,
        "created_by_user_id": row.created_by_user_id,
        "moysklad_demand_id": row.moysklad_demand_id,
        "moysklad_demand_name": row.moysklad_demand_name,
        "assembled_at": row.assembled_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_shipping_by_order(order_id=None, order_number=None):
    with session_scope() as session:
        statement = select(ShippingRecord)
        if order_id:
            statement = statement.where(ShippingRecord.moysklad_order_id == str(order_id))
        elif order_number:
            statement = statement.where(ShippingRecord.order_number == str(order_number))
        else:
            return None
        return record_to_dict(session.scalars(statement.limit(1)).first())


def save_shipping_record(data):
    order_id = str(data.get("moysklad_order_id") or "").strip()
    if not order_id:
        raise ValueError("Не указан идентификатор заказа МойСклад.")
    now = now_msk_naive()
    with session_scope() as session:
        row = session.scalars(
            select(ShippingRecord).where(ShippingRecord.moysklad_order_id == order_id).limit(1)
        ).first()
        created = row is None
        if row is None:
            row = ShippingRecord(moysklad_order_id=order_id, created_at=now)
            session.add(row)
        for field in (
            "order_number", "shipping_type", "order_snapshot", "marking_codes",
            "collector_employee_id", "collector_name", "created_by_employee_id",
            "created_by_name", "created_by_user_id", "moysklad_demand_id",
            "moysklad_demand_name", "assembled_at",
        ):
            setattr(row, field, data.get(field))
        row.updated_at = now
        session.flush()
        result = record_to_dict(row)
        result["created"] = created
        return result


def list_shipping_records(start_at=None, end_at=None, shipping_type=None, collector_employee_id=None):
    with session_scope() as session:
        statement = select(ShippingRecord)
        if start_at is not None:
            statement = statement.where(ShippingRecord.assembled_at >= start_at)
        if end_at is not None:
            statement = statement.where(ShippingRecord.assembled_at <= end_at)
        if shipping_type:
            statement = statement.where(ShippingRecord.shipping_type == str(shipping_type))
        if collector_employee_id:
            statement = statement.where(
                ShippingRecord.collector_employee_id == str(collector_employee_id)
            )
        rows = session.scalars(
            statement.order_by(ShippingRecord.assembled_at.desc(), ShippingRecord.id.desc())
        ).all()
        return [record_to_dict(row) for row in rows]
