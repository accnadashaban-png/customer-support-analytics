"""How accurate is the topic classification? Measured on hand-labeled messages, never on the classifier's own output.

The labeled set (`topics_labeled.csv`, 176 contacts in English, Egyptian, Gulf, Levantine, Maghrebi, MSA, Franco
and mixed, some with several messages) is split in two: even ids are the development half, used to improve the
keywords; odd ids are the test half, measured only after the keywords were frozen. The test half is the number
to trust.

"uncertain" is not a wrong answer and not a right one: it is reported as coverage (how often the classifier
decided) and counted as a miss in recall, never in precision.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from support_analytics.analytics.topics import classify
from support_analytics.core.config import WorkspaceConfig

LABELED = Path(__file__).with_name("topics_labeled.csv")


def load(path: Path = LABELED) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{**r, "messages": [m.strip() for m in r["messages"].split("||")]} for r in csv.DictReader(f)]


def evaluate(rows: list[dict[str, Any]], cfg: WorkspaceConfig | None = None) -> dict[str, Any]:
    cfg = cfg or WorkspaceConfig()
    labels = sorted({r["label"] for r in rows})
    confusion: Counter[tuple[str, str]] = Counter()
    errors = []
    for r in rows:
        got = classify(r["messages"], cfg.topics, cfg.topic_min_ratio).topic
        confusion[(r["label"], got)] += 1
        if got != r["label"]:
            errors.append({"id": r["id"], "label": r["label"], "got": got, "text": " || ".join(r["messages"])})
    n = len(rows)
    decided = sum(v for (_, g), v in confusion.items() if g != "uncertain")
    correct = sum(v for (t, g), v in confusion.items() if t == g)
    per_topic = {}
    for lab in labels:
        tp = confusion[(lab, lab)]
        predicted = sum(v for (_, g), v in confusion.items() if g == lab)
        actual = sum(v for (t, _), v in confusion.items() if t == lab)
        per_topic[lab] = {"precision": round(tp / predicted, 3) if predicted else None,
                          "recall": round(tp / actual, 3) if actual else None, "support": actual}
    return {"cases": n, "accuracy": round(correct / n, 3) if n else None,
            "accuracy_when_decided": round(correct / decided, 3) if decided else None,
            "coverage": round(decided / n, 3) if n else None, "per_topic": per_topic,
            "confusion": {f"{t} -> {g}": v for (t, g), v in sorted(confusion.items()) if t != g}, "errors": errors}


def split(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dev = [r for r in rows if int(r["id"][1:]) % 2 == 0]
    test = [r for r in rows if int(r["id"][1:]) % 2 == 1]
    return dev, test


def markdown(dev: dict[str, Any], test: dict[str, Any]) -> list[str]:
    lines = ["## Topic classification (hand-labeled)", "",
             "| | Development half | Test half (the number to trust) |", "|---|---|---|",
             f"| Contacts | {dev['cases']} | {test['cases']} |",
             f"| Accuracy (uncertain counts as wrong) | {dev['accuracy']:.1%} | {test['accuracy']:.1%} |",
             f"| Accuracy when it decides | {dev['accuracy_when_decided']:.1%} | {test['accuracy_when_decided']:.1%} |",
             f"| Coverage (decided, not uncertain) | {dev['coverage']:.1%} | {test['coverage']:.1%} |", "",
             "| Topic | Precision (test) | Recall (test) | Contacts (test) |", "|---|---|---|---|"]
    for topic, m in test["per_topic"].items():
        p = f"{m['precision']:.0%}" if m["precision"] is not None else "-"
        r = f"{m['recall']:.0%}" if m["recall"] is not None else "-"
        lines.append(f"| {topic} | {p} | {r} | {m['support']} |")
    if test["errors"]:
        lines += ["", "Test-half mistakes (label -> classifier):", ""]
        lines += [f"- `{e['id']}` {e['label']} -> **{e['got']}**: {e['text']}" for e in test["errors"]]
    return lines
