from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.enum import MusicTaskStatus, TransactionStatus, TransactionType, UserRole

from .base import Base


class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credits: Mapped[int] = mapped_column(default=2)
    role: Mapped[str] = mapped_column(String(50), default=UserRole.USER.value)

    referrer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    balance: Mapped[int] = mapped_column(default=0, nullable=False)

    registration_datetime: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
    )
    last_active: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    transactions: Mapped[list["TransactionModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    usage_events: Mapped[list["UsageEventModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    music_tasks: Mapped[list["MusicTaskModel"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class TransactionModel(Base):
    __tablename__ = "transactions"

    user_idpk: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    manager_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(
        String(50),
        default=TransactionType.TOPUP.value,
    )
    method: Mapped[str] = mapped_column(String(50))
    plan: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(String(10))
    credits: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(
        String(50),
        default=TransactionStatus.SUCCESS.value,
    )
    payload: Mapped[str] = mapped_column(String(200))
    telegram_charge_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_charge_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
    )

    user: Mapped[UserModel] = relationship(back_populates="transactions")


class UsageEventModel(Base):
    __tablename__ = "usage_events"

    user_idpk: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
    )

    user: Mapped[UserModel] = relationship(back_populates="usage_events")


class MusicTaskModel(Base):
    __tablename__ = "music_tasks"

    user_idpk: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    filename_base: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(50), default=MusicTaskStatus.PENDING.value
    )
    errors: Mapped[int] = mapped_column(default=0)
    credits_cost: Mapped[int] = mapped_column(default=2)
    poll_timeout: Mapped[int] = mapped_column(default=600)
    last_polled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    audio_file_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    instrumental: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    user: Mapped[UserModel] = relationship(back_populates="music_tasks")
