"""Validated records that any data source must produce."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

TIERS = ["Free", "Basic", "Pro", "Elite"]  # ordered from lowest to highest
Tier = Literal["Free", "Basic", "Pro", "Elite"]


class Member(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    joined_at: AwareDatetime


class Message(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    conversation_id: str
    member_id: str
    sender: Literal["member", "agent"]
    agent_name: str | None = None
    body: str
    sent_at: AwareDatetime


class Subscription(BaseModel):
    """One row per tier change. `trial` counts as paid access at that tier; only ended statuses lose access."""
    member_id: str
    tier: Tier
    status: Literal["active", "trial", "canceled", "past_due", "expired"]
    started_at: AwareDatetime


def tier_rank(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else -1


def has_access(status: str) -> bool:
    return status in ("active", "trial")


