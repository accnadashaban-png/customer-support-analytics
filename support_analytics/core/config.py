"""Workspace configuration: business hours, SLA, topics, closing phrases and plan prices.

Every team works differently, so these live in one JSON file (see `workspace.example.json`)
instead of in code. Defaults suit a team that works Sunday to Thursday, 9:00-18:00 Cairo time.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Hours(BaseModel):
    start: str = "09:00"
    end: str = "18:00"

    @field_validator("start", "end")
    @classmethod
    def hh_mm(cls, v: str) -> str:
        h, m = v.split(":")
        if not (0 <= int(h) <= 24 and 0 <= int(m) < 60):
            raise ValueError("use HH:MM")
        return v

    def minutes(self) -> tuple[int, int]:
        to_min = lambda s: int(s.split(":")[0]) * 60 + int(s.split(":")[1])  # noqa: E731
        return to_min(self.start), to_min(self.end)


class BusinessHours(BaseModel):
    timezone: str = "Africa/Cairo"
    days: dict[str, Hours] = Field(default_factory=lambda: {d: Hours() for d in ("sun", "mon", "tue", "wed", "thu")})
    holidays: list[date] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as exc:  # ZoneInfoNotFoundError is a KeyError, not a ValueError
            raise ValueError(f"unknown time zone: {v}") from exc
        return v

    @field_validator("days")
    @classmethod
    def known_days(cls, v: dict[str, Hours]) -> dict[str, Hours]:
        unknown = set(v) - set(WEEKDAYS)
        if unknown:
            raise ValueError(f"unknown weekday keys: {sorted(unknown)}")
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


# Checked in order, so more specific topics come first ("cancel my subscription" is a cancellation).
DEFAULT_TOPICS = {
    "access": ["log in", "login", "password", "can't access", "verification", "account", "دخول", "باسورد", "كلمة السر",
               "مش قادر ادخل", "الحساب"],
    "billing": ["paid", "payment", "invoice", "refund", "charge", "card", "دفعت", "الدفع", "فاتورة", "استرجاع", "فلوس"],
    "cancellation": ["cancel", "unsubscribe", "stop my", "الغاء", "إلغاء", "الغي", "ألغي"],
    "plans": ["upgrade", "plan", "pro", "elite", "basic", "discount", "price", "ارقي", "أرقي", "ترقية", "الباقة", "اشتراك",
              "خصم", "سعر"],
    "events": ["live", "session", "webinar", "schedule", "اللايف", "لايف", "مواعيد", "الجلسة"],
    "technical": ["video", "not working", "error", "bug", "app", "crash", "الفيديو", "مش بيشتغل", "مشكلة", "التطبيق"],
}


class WorkspaceConfig(BaseModel):
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    sla_first_response_minutes: int = Field(60, ge=1, description="target first response, in business minutes")
    contact_gap_hours: float = Field(12, gt=0, description="silence that starts a new contact in the same thread")
    upgrade_window_days: int = Field(14, ge=1)
    alert_after_minutes: int = Field(120, ge=1, description="flag unanswered contacts older than this (business minutes)")
    topics: dict[str, list[str]] = Field(default_factory=lambda: dict(DEFAULT_TOPICS))
    closing_phrases: list[str] = Field(default_factory=lambda: [
        "thanks", "thank you", "thx", "ok", "okay", "great", "perfect", "شكرا", "شكرًا", "متشكر", "تمام", "تسلم", "مشكور"])
    tier_order: list[str] = Field(default_factory=lambda: ["Free", "Basic", "Pro", "Elite"])
    monthly_price: dict[str, float] = Field(default_factory=lambda: {"Free": 0.0, "Basic": 9.0, "Pro": 29.0, "Elite": 79.0})
    currency: str = "USD"


def load_config(path: Path | None) -> WorkspaceConfig:
    if path is None or not Path(path).exists():
        return WorkspaceConfig()
    return WorkspaceConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
