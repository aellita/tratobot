from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _msk_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)


class CategoryType(StrEnum):
    FOOD = "food"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    SUBSCRIPTIONS = "subscriptions"
    OTHER = "other"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_msk_now)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    month: Mapped[str] = mapped_column(String(7))

    total_income: Mapped[float] = mapped_column(Float, default=0)
    mandatory_payments: Mapped[float] = mapped_column(Float, default=0)
    black_day_fund: Mapped[float] = mapped_column(Float, default=0)
    wishlist_name: Mapped[str] = mapped_column(String(255), default="Хотелка")
    wishlist_target: Mapped[float] = mapped_column(Float, default=0)
    period_start_day: Mapped[int] = mapped_column(Integer, default=1)
    free_money: Mapped[float] = mapped_column(Float, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_msk_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_msk_now, onupdate=_msk_now)

    @property
    def _clamped_start(self) -> int:
        import calendar

        today = _msk_now()
        raw = self.period_start_day or 1
        return min(raw, calendar.monthrange(today.year, today.month)[1])

    @property
    def days_remaining(self) -> int:
        import calendar

        today = _msk_now()
        start = self._clamped_start
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        if start == 1:
            return max(days_in_month - today.day + 1, 0)
        if today.day >= start:
            remaining = days_in_month - today.day
            next_days = start - 1
            return remaining + next_days + 1
        else:
            return start - today.day

    @property
    def _period_total_days(self) -> int:
        import calendar

        today = _msk_now()
        start = self._clamped_start
        if start == 1:
            return calendar.monthrange(today.year, today.month)[1]
        return 30

    @property
    def daily_limit(self) -> float:
        if self.free_money > 0:
            available = self.free_money
            total = max(self.days_remaining, 1)
        else:
            available = self.total_income - self.mandatory_payments - self.black_day_fund
            total = max(self._period_total_days, 1)
        return max(available / total, 0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[CategoryType | None] = mapped_column(
        SQLEnum(CategoryType), nullable=True, default=None
    )
    keywords: Mapped[str] = mapped_column(Text, default="[]")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=_msk_now)
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    is_from_wishlist: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Wishlist(Base):
    __tablename__ = "wishlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    name: Mapped[str] = mapped_column(String(255))
    target_amount: Mapped[float] = mapped_column(Float)
    current_amount: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_msk_now)


class BlackDayFund(Base):
    __tablename__ = "black_day_funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[float] = mapped_column(Float, default=0)
    used_amount: Mapped[float] = mapped_column(Float, default=0)


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), unique=True)
    morning_report_time: Mapped[str] = mapped_column(String(5), default="08:00")
    evening_report_time: Mapped[str] = mapped_column(String(5), default="22:00")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rounding_mode: Mapped[int] = mapped_column(Integer, default=0)


class DailyReportsLog(Base):
    __tablename__ = "daily_reports_log"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    sent_date: Mapped[date] = mapped_column(Date, primary_key=True)
