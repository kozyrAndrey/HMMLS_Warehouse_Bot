import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from config import BASE_DIR
from modules.storage.postgres import Base, get_engine, session_scope


CATALOG_SEED_PATH = BASE_DIR / "resources" / "honest_sign_products.csv"
GTIN_LENGTHS = {8, 12, 13, 14}


class HonestSignProduct(Base):
    __tablename__ = "honest_sign_products"

    gtin: Mapped[str] = mapped_column(String(14), primary_key=True)
    honest_sign_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


def normalize_gtin(value):
    gtin = str(value or "").strip()
    if not gtin:
        raise ValueError("GTIN не указан.")
    if not gtin.isdigit():
        raise ValueError("GTIN должен содержать только цифры.")
    if len(gtin) not in GTIN_LENGTHS:
        raise ValueError("GTIN должен содержать 8, 12, 13 или 14 цифр.")
    return gtin.zfill(14)


def init_marking_storage():
    Base.metadata.create_all(get_engine(), tables=[HonestSignProduct.__table__])
    seed_honest_sign_products_if_empty()


def seed_honest_sign_products_if_empty(seed_path=CATALOG_SEED_PATH):
    seed_path = Path(seed_path)
    if not seed_path.exists():
        return 0

    with session_scope() as session:
        has_products = session.execute(select(HonestSignProduct.gtin).limit(1)).first()
    if has_products:
        return 0

    with seed_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return upsert_honest_sign_products(rows)


def upsert_honest_sign_products(rows):
    normalized_rows = []
    seen = set()
    for row in rows:
        gtin = normalize_gtin(row.get("gtin"))
        name = str(row.get("honest_sign_name") or "").strip()
        if not name:
            raise ValueError(f"Для GTIN {gtin} не указано название Честного ЗНАКа.")
        if gtin in seen:
            raise ValueError(f"GTIN {gtin} повторяется в импортируемом справочнике.")
        seen.add(gtin)
        normalized_rows.append((gtin, name))

    now = datetime.now()
    with session_scope() as session:
        existing = {
            product.gtin: product
            for product in session.execute(
                select(HonestSignProduct).where(
                    HonestSignProduct.gtin.in_([gtin for gtin, _ in normalized_rows])
                )
            ).scalars()
        }
        for gtin, name in normalized_rows:
            product = existing.get(gtin)
            if product:
                product.honest_sign_name = name
                product.updated_at = now
            else:
                session.add(
                    HonestSignProduct(
                        gtin=gtin,
                        honest_sign_name=name,
                        created_at=now,
                        updated_at=now,
                    )
                )
    return len(normalized_rows)


def upsert_honest_sign_product(gtin, honest_sign_name):
    normalized_gtin = normalize_gtin(gtin)
    name = str(honest_sign_name or "").strip()
    if not name:
        raise ValueError("Название Честного ЗНАКа не должно быть пустым.")

    now = datetime.now()
    with session_scope() as session:
        product = session.get(HonestSignProduct, normalized_gtin)
        created = product is None
        if product:
            product.honest_sign_name = name
            product.updated_at = now
        else:
            product = HonestSignProduct(
                gtin=normalized_gtin,
                honest_sign_name=name,
                created_at=now,
                updated_at=now,
            )
            session.add(product)
        session.flush()
        return honest_sign_product_to_dict(product), created


def get_honest_sign_product(gtin):
    normalized_gtin = normalize_gtin(gtin)
    with session_scope() as session:
        product = session.get(HonestSignProduct, normalized_gtin)
        return honest_sign_product_to_dict(product) if product else None


def get_honest_sign_names(gtins):
    normalized = []
    for gtin in gtins:
        try:
            normalized.append(normalize_gtin(gtin))
        except ValueError:
            continue
    if not normalized:
        return {}

    with session_scope() as session:
        products = session.execute(
            select(HonestSignProduct).where(HonestSignProduct.gtin.in_(set(normalized)))
        ).scalars().all()
    return {product.gtin: product.honest_sign_name for product in products}


def list_honest_sign_products():
    with session_scope() as session:
        products = session.execute(
            select(HonestSignProduct).order_by(HonestSignProduct.gtin)
        ).scalars().all()
        return [honest_sign_product_to_dict(product) for product in products]


def delete_honest_sign_product(gtin):
    normalized_gtin = normalize_gtin(gtin)
    with session_scope() as session:
        product = session.get(HonestSignProduct, normalized_gtin)
        if not product:
            return False
        session.delete(product)
    return True


def honest_sign_product_to_dict(product):
    return {
        "gtin": product.gtin,
        "honest_sign_name": product.honest_sign_name,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }
