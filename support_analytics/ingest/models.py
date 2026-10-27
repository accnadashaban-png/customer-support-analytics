"""Validated records that any data source must produce.

Plan names are free text so any team can use its own (their order and prices come from
the workspace config). `trial` counts as paid access at that plan; only ended statuses lose access.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

TIERS = ["Free", "Basic", "Pro", "Elite"]  # default order, lowest to highest; override in the workspace config


class Member(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=200)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    joined_at: AwareDatetime


class Message(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    sender: Literal["member", "agent"]
    agent_name: str | None = Field(None, max_length=120)
    body: str = Field(max_length=20_000)
    sent_at: AwareDatetime


class Subscription(BaseModel):
    """One row per plan change."""
    member_id: str = Field(min_length=1, max_length=128)
    tier: str = Field(min_length=1, max_length=60)
    status: Literal["active", "trial", "canceled", "past_due", "expired"]
    started_at: AwareDatetime


def tier_rank(tier: str, order: list[str] | None = None) -> int:
    order = order or TIERS
    return order.index(tier) if tier in order else -1


def has_access(status: str) -> bool:
    return status in ("active", "trial")
