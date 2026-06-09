from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text, desc, distinct, select, text
from sqlalchemy.orm import Mapped, mapped_column

from modules.storage.postgres import Base, get_engine, session_scope


class ConsumableSupply(Base):
    __tablename__ = "consumable_supplies"
    __table_args__ = (
        Index("ix_consumable_supplies_status", "status"),
        Index("ix_consumable_supplies_created_at", "created_at"),
        Index("ix_consumable_supplies_organization", "organization"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    consumable_name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_by_user_id: Mapped[str | None] = mapped_column(String(100))
    created_by_name: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(100))
    accepted_by_name: Mapped[str | None] = mapped_column(String(255))
    layout_photo_file_id: Mapped[str | None] = mapped_column(Text)
    closing_document_file_id: Mapped[str | None] = mapped_column(Text)
    closing_document_kind: Mapped[str | None] = mapped_column(String(50))
    topic_message_ids: Mapped[str | None] = mapped_column(String(1000))


class ConsumableSupplier(Base):
    __tablename__ = "consumable_suppliers"
    __table_args__ = (
        Index("ix_consumable_suppliers_name", "name"),
        Index("ix_consumable_suppliers_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


def init_consumables_storage():
    Base.metadata.create_all(get_engine(), tables=[ConsumableSupply.__table__, ConsumableSupplier.__table__])
    ensure_consumables_columns()


def ensure_consumables_columns():
    statements = [
        "alter table consumable_supplies add column if not exists status varchar(50) not null default 'pending'",
        "alter table consumable_supplies add column if not exists created_by_user_id varchar(100)",
        "alter table consumable_supplies add column if not exists created_by_name varchar(255)",
        "alter table consumable_supplies add column if not exists accepted_at timestamp",
        "alter table consumable_supplies add column if not exists accepted_by_user_id varchar(100)",
        "alter table consumable_supplies add column if not exists accepted_by_name varchar(255)",
        "alter table consumable_supplies add column if not exists layout_photo_file_id text",
        "alter table consumable_supplies add column if not exists closing_document_file_id text",
        "alter table consumable_supplies add column if not exists closing_document_kind varchar(50)",
        "alter table consumable_supplies add column if not exists topic_message_ids varchar(1000)",
        "create index if not exists ix_consumable_supplies_status on consumable_supplies (status)",
        "create index if not exists ix_consumable_supplies_created_at on consumable_supplies (created_at)",
        "create index if not exists ix_consumable_supplies_organization on consumable_supplies (organization)",
        "alter table consumable_suppliers add column if not exists is_active boolean not null default true",
        "create unique index if not exists uq_consumable_suppliers_name on consumable_suppliers (name)",
        "create index if not exists ix_consumable_suppliers_is_active on consumable_suppliers (is_active)",
    ]

    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def supply_to_dict(supply):
    return {
        "id": supply.id,
        "created_at": supply.created_at,
        "consumable_name": supply.consumable_name,
        "organization": supply.organization,
        "amount": float(supply.amount or 0),
        "status": supply.status,
        "created_by_user_id": supply.created_by_user_id or "",
        "created_by_name": supply.created_by_name or "",
        "accepted_at": supply.accepted_at,
        "accepted_by_user_id": supply.accepted_by_user_id or "",
        "accepted_by_name": supply.accepted_by_name or "",
        "layout_photo_file_id": supply.layout_photo_file_id or "",
        "closing_document_file_id": supply.closing_document_file_id or "",
        "closing_document_kind": supply.closing_document_kind or "",
        "topic_message_ids": supply.topic_message_ids or "",
    }


def create_supply(consumable_name, organization, amount, created_by_user_id, created_by_name):
    with session_scope() as session:
        upsert_supplier_in_session(session, organization)
        supply = ConsumableSupply(
            consumable_name=consumable_name,
            organization=organization,
            amount=amount,
            created_by_user_id=str(created_by_user_id or ""),
            created_by_name=created_by_name,
        )
        session.add(supply)
        session.flush()
        return supply_to_dict(supply)


def upsert_supplier_in_session(session, name):
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return None

    supplier = (
        session.execute(
            select(ConsumableSupplier).where(ConsumableSupplier.name == normalized_name)
        )
        .scalars()
        .first()
    )

    if supplier:
        supplier.is_active = True
        return supplier

    supplier = ConsumableSupplier(name=normalized_name, is_active=True)
    session.add(supplier)
    return supplier


def get_recent_organizations(limit=12):
    with session_scope() as session:
        inactive_names = set(
            session.execute(
                select(ConsumableSupplier.name).where(ConsumableSupplier.is_active.is_(False))
            )
            .scalars()
            .all()
        )
        active_supplier_names = (
            session.execute(
                select(ConsumableSupplier.name)
                .where(ConsumableSupplier.is_active.is_(True))
                .order_by(ConsumableSupplier.name)
            )
            .scalars()
            .all()
        )
        supply_names = (
            session.execute(select(distinct(ConsumableSupply.organization)).order_by(ConsumableSupply.organization))
            .scalars()
            .all()
        )

    names = []
    for name in list(active_supplier_names) + list(supply_names):
        if not name or name in inactive_names or name in names:
            continue
        names.append(name)
        if len(names) >= limit:
            break

    return names


def get_pending_supplies(limit=30):
    return get_supplies(status="pending", limit=limit)


def get_accepted_supplies(limit=30):
    return get_supplies(status="accepted", limit=limit)


def get_supplies(status=None, limit=30):
    with session_scope() as session:
        statement = select(ConsumableSupply).order_by(desc(ConsumableSupply.id)).limit(limit)
        if status:
            statement = statement.where(ConsumableSupply.status == status)
        supplies = session.execute(statement).scalars().all()

    return [supply_to_dict(supply) for supply in supplies]


def get_supply(supply_id):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        return supply_to_dict(supply) if supply else None


def mark_supply_accepted(
    supply_id,
    accepted_by_user_id,
    accepted_by_name,
    layout_photo_file_id,
    closing_document_file_id="",
    closing_document_kind="none",
    topic_message_ids=None,
):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        if not supply:
            raise RuntimeError("Поставка не найдена.")
        if supply.status != "pending":
            raise RuntimeError("Эта поставка уже принята.")

        supply.status = "accepted"
        supply.accepted_at = datetime.now()
        supply.accepted_by_user_id = str(accepted_by_user_id or "")
        supply.accepted_by_name = accepted_by_name
        supply.layout_photo_file_id = layout_photo_file_id
        supply.closing_document_file_id = closing_document_file_id or ""
        supply.closing_document_kind = closing_document_kind or "none"
        supply.topic_message_ids = ",".join(str(message_id) for message_id in (topic_message_ids or []))

        session.flush()
        return supply_to_dict(supply)


def update_supply(supply_id, consumable_name=None, organization=None, amount=None):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        if not supply:
            raise RuntimeError("Поставка не найдена.")

        if consumable_name is not None:
            supply.consumable_name = consumable_name
        if organization is not None:
            supply.organization = organization
            upsert_supplier_in_session(session, organization)
        if amount is not None:
            supply.amount = amount

        session.flush()
        return supply_to_dict(supply)


def delete_supply(supply_id):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        if not supply:
            raise RuntimeError("Поставка не найдена.")

        result = supply_to_dict(supply)
        session.delete(supply)
        return result


def update_acceptance(
    supply_id,
    accepted_by_user_id,
    accepted_by_name,
    layout_photo_file_id,
    closing_document_file_id="",
    closing_document_kind="none",
    topic_message_ids=None,
):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        if not supply:
            raise RuntimeError("Поставка не найдена.")
        if supply.status != "accepted":
            raise RuntimeError("Эта поставка еще не принята.")

        supply.accepted_at = datetime.now()
        supply.accepted_by_user_id = str(accepted_by_user_id or "")
        supply.accepted_by_name = accepted_by_name
        supply.layout_photo_file_id = layout_photo_file_id
        supply.closing_document_file_id = closing_document_file_id or ""
        supply.closing_document_kind = closing_document_kind or "none"
        supply.topic_message_ids = ",".join(str(message_id) for message_id in (topic_message_ids or []))

        session.flush()
        return supply_to_dict(supply)


def clear_acceptance(supply_id):
    with session_scope() as session:
        supply = session.get(ConsumableSupply, int(supply_id))
        if not supply:
            raise RuntimeError("Поставка не найдена.")
        if supply.status != "accepted":
            raise RuntimeError("Эта поставка еще не принята.")

        result = supply_to_dict(supply)
        supply.status = "pending"
        supply.accepted_at = None
        supply.accepted_by_user_id = None
        supply.accepted_by_name = None
        supply.layout_photo_file_id = None
        supply.closing_document_file_id = None
        supply.closing_document_kind = None
        supply.topic_message_ids = None
        session.flush()
        return result


def split_message_ids(value):
    result = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


def get_active_suppliers(limit=50):
    return get_recent_organizations(limit=limit)


def deactivate_supplier(name):
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise RuntimeError("Поставщик не найден.")

    with session_scope() as session:
        supplier = (
            session.execute(
                select(ConsumableSupplier).where(ConsumableSupplier.name == normalized_name)
            )
            .scalars()
            .first()
        )

        if supplier:
            supplier.is_active = False
        else:
            session.add(ConsumableSupplier(name=normalized_name, is_active=False))

    return normalized_name
