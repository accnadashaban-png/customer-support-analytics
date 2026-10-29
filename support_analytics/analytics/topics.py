"""What a contact is about: scored topics with a confidence, and "uncertain" instead of a guess.

How a topic is decided (the same rules for every team; the words come from the workspace config):

1. Text is normalized the way people really type: lower case, Arabic letter variants unified (أ إ آ -> ا,
   ة -> ه, ى -> ي), diacritics and stretched letters removed ("ازاييي" -> "ازاي").
2. Every member message of the contact counts, not only the first one ("Hi" followed by the real question is
   common). The first message that says something gets 1.5x weight; greetings and a closing "thanks" get none.
3. Each topic's keywords add points when they appear as words (Arabic keywords may carry the usual prefixes
   and suffixes: "وفاتورتي" matches "فاتورة"): a phrase of several words = 2 points, a word = 1,
   a weak word written with "~" (like "~plan") = 0.5, because it appears in many kinds of requests.
4. The topic with the most points wins only if it is clearly ahead: at least `min_ratio` (default 1.5) times
   the runner-up. Otherwise the contact is "uncertain" and is shown for a person to label; nothing matches: "other".
5. Confidence = winner's points / (winner's + runner-up's points), from 0.5 (a tie) to 1.0 (no competitor).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

ARABIC = re.compile(r"[؀-ۿ]")
DIACRITICS = re.compile(r"[ؗ-ًؚ-ْـ]")
GREETING_OR_CLOSING = re.compile(
    r"^(hi|hello|hey|good (morning|evening)|salam|thanks?|thank you|thx|ok|okay|great|perfect|السلام عليكم|سلام|"
    r"اهلا|مرحبا|صباح الخير|مساء الخير|شكرا|متشكر|تمام|تسلم|مشكور|اوك)( (all|so much|جدا|ليك|لك|كتير))?$")
PREFIX = r"(?:و|ف|ب|ل|ال|وال|بال|فال|لل|ع|عال)?"
SUFFIX = r"(?:ي|ك|ه|ها|نا|كم|هم|ات|ين|ون|تي|تك|ته|ني)?"


def normalize(text: str) -> str:
    t = DIACRITICS.sub("", text.lower())
    t = re.sub("[أإآ]", "ا", t).replace("ة", "ه").replace("ى", "ي")
    t = re.sub(r"(.)\1{2,}", r"\1", t)  # stretched letters: "ازاييي" -> "ازاي", "pleeease" -> "please"
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


@dataclass(frozen=True)
class Keyword:
    text: str
    weight: float
    pattern: re.Pattern[str]


@lru_cache(maxsize=4096)
def _keyword(raw: str) -> Keyword:
    weak = raw.startswith("~")
    text = normalize(raw.lstrip("~"))
    weight = 0.5 if weak else (2.0 if " " in text else 1.0)
    if ARABIC.search(text):
        stem = text[:-1] if text.endswith("ه") and len(text) > 3 else text  # "فاتوره" also matches "فاتورتي"
        body = re.escape(stem) + (r"[هت]?" if stem != text else "")
        pattern = re.compile(rf"(?<![\w]){PREFIX}{body}{SUFFIX}(?![\w])")
    else:
        pattern = re.compile(rf"(?<![\w]){re.escape(text)}(?![\w])")
    return Keyword(text, weight, pattern)


@dataclass
class TopicResult:
    topic: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)


def score(text: str, topics: dict[str, list[str]]) -> dict[str, float]:
    t = normalize(text)
    out: dict[str, float] = {}
    for topic, words in topics.items():
        s = sum(k.weight for k in (_keyword(w) for w in words) if k.text and k.pattern.search(t))
        if s:
            out[topic] = s
    return out


def classify(messages: list[str], topics: dict[str, list[str]], min_ratio: float = 1.5) -> TopicResult:
    totals: dict[str, float] = {}
    first = True
    for m in messages:
        if not normalize(m) or GREETING_OR_CLOSING.match(normalize(m)):
            continue
        weight = 1.5 if first else 1.0
        first = False
        for topic, s in score(m, topics).items():
            totals[topic] = totals.get(topic, 0.0) + s * weight
    if not totals:
        return TopicResult("other", 0.0, {})
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = round(top_score / (top_score + second), 2)
    if second and top_score < min_ratio * second:
        return TopicResult("uncertain", confidence, dict(ranked))
    return TopicResult(top, confidence, dict(ranked))
