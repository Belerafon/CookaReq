"""Convert legacy flat requirements into document-based hierarchy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RULE_RE = re.compile(r"^tag:([^=]+)=([^->]+)->([A-Z][A-Z0-9_]*)$")


@dataclass
class Rule:
    """Mapping from a tag to target document prefix."""

    tag: str
    target: str


def parse_rules(expr: str | None) -> list[Rule]:
    """Parse rule expression ``tag:key=value->PREFIX;...``."""

    rules: list[Rule] = []
    if not expr:
        return rules
    for part in expr.split(";"):
        part = part.strip()
        if not part:
            continue
        m = RULE_RE.match(part)
        if not m:
            raise ValueError(f"invalid rule: {part}")
        key, value, target = m.groups()
        rules.append(Rule(tag=f"{key}={value}", target=target))
    return rules


def select_prefix(labels: Iterable[str], rules: list[Rule], default: str) -> str:
    """Return document prefix based on ``labels`` and ``rules``."""

    for rule in rules:
        if rule.tag in labels:
            return rule.target
    return default


def migrate_to_docs(directory: str | Path, *, rules: str | None = None, default: str) -> None:
    """Migrate legacy requirement files in ``directory`` to document structure."""

    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(str(directory))
    rule_objs = parse_rules(rules)
    digits_map: dict[str, int] = {}
    items: list[tuple[str, str, dict]] = []

    for fp in list(root.glob("*.json")):
        with fp.open(encoding="utf-8") as fh:
            data = json.load(fh)
        old_id = data.get("id")
        if not isinstance(old_id, str):
            raise ValueError(f"missing id in {fp}")
        m = re.match(r"([A-Za-z0-9_]+)[-_]?([0-9]+)", old_id)
        if not m:
            raise ValueError(f"invalid id format: {old_id}")
        num = int(m.group(2))
        width = len(m.group(2))
        labels = list(data.get("labels", []))
        prefix = select_prefix(labels, rule_objs, default)
        digits_map.setdefault(prefix, width)
        rid = f"{prefix}{num:0{digits_map[prefix]}d}"
        item = {
            "id": num,
            "title": data.get("title", ""),
            "text": data.get("statement", ""),
            "tags": [lbl for lbl in labels if not lbl.startswith("doc=")],
        }
        if "revision" in data:
            item["revision"] = data["revision"]
        items.append((prefix, rid, item))
        fp.unlink()

    for prefix, rid, item in items:
        items_dir = root / prefix / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        with (items_dir / f"{rid}.json").open("w", encoding="utf-8") as fh:
            json.dump(item, fh, ensure_ascii=False, indent=2, sort_keys=True)

    for prefix, digits in digits_map.items():
        doc_dir = root / prefix
        doc = {
            "prefix": prefix,
            "title": prefix,
            "digits": digits,
            "parent": None,
            "labels": {"allowFreeform": True, "defs": []},
        }
        with (doc_dir / "document.json").open("w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
