"""Tell automated messages apart from human replies.

Verification codes, welcome messages and renewal reminders are sent from the same
support account as real replies. If they counted, the team would look faster than
it is, so they're detected (whitespace- and case-insensitive) and excluded from
every team metric.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import Message

DEFAULT_PATTERNS = Path(__file__).with_name("bot_patterns.txt")


def load_patterns(path: Path = DEFAULT_PATTERNS) -> list[re.Pattern[str]]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [re.compile(ln, re.IGNORECASE) for ln in lines if ln and not ln.startswith("#")]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class AutomationClassifier:
    def __init__(self, patterns: list[re.Pattern[str]] | None = None):
        self.patterns = patterns if patterns is not None else load_patterns()

    def __call__(self, message: Message) -> bool:
        """True if an agent-side message was sent automatically. Member messages are never automated."""
        if message.sender != "agent":
            return False
        text = _squash(message.body)
        return any(p.search(text) for p in self.patterns)
