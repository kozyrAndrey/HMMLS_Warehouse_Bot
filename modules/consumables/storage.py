from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, desc, distinct, select, text
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


def init_consumables_storage():
    Base.metadata.create_all(get_engine(), tables=[ConsumableSupply.__table__])
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


def get_recent_organizations(limit=12):
    with session_scope() as session:
        rows = (
            session.execute(
                select(distinct(ConsumableSupply.organization))
                .order_by(ConsumableSupply.organization)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    return [row for row in rows if row]


def get_pending_supplies(limit=30):
    with session_scope() as session:
        supplies = (
            session.execute(
                select(ConsumableSupply)
                .where(ConsumableSupply.status == "pending")
                .order_by(desc(ConsumableSupply.id))
                .limit(limit)
            )
            .scalars()
            .all()
        )

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
