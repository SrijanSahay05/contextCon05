"""Column helpers shared by the ORM models."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def bigint_pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def fk(
    target: str, *, nullable: bool = False, ondelete: str = "CASCADE", primary_key: bool = False
) -> MappedColumn[Any]:
    return mapped_column(
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=not primary_key,
        primary_key=primary_key,
    )


def enum_col(enum: type[StrEnum], **kwargs: Any) -> MappedColumn[Any]:
    # stored as varchar + check constraint, so adding a value needs no type migration
    return mapped_column(
        Enum(
            enum,
            native_enum=False,
            length=32,
            values_callable=lambda members: [m.value for m in members],
        ),
        **kwargs,
    )
