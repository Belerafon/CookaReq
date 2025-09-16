"""Convert legacy flat requirements into document-based hierarchy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

from app.core.model import (
    Requirement,
    requirement_fingerprint,
    requirement_from_dict,
    requirement_to_dict,
)

RULE_RE = re.compile(r"^label:([^=]+)=([^->]+)->([A-Z][A-Z0-9_]*)$")
LEGACY_ID_RE = re.compile(
    r"^(?:(?P<prefix>(?=.*[A-Za-z_])[A-Za-z0-9_]+?)[-_]?)?(?P<num>[0-9]+)$"
)


@dataclass
class Rule:
    """Mapping from a label to target document prefix."""

    label: str
    target: str


def parse_rules(expr: str | None) -> list[Rule]:
    """Parse rule expression ``label:key=value->PREFIX;...``."""

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
        rules.append(Rule(label=f"{key}={value}", target=target))
    return rules


def select_prefix(labels: Iterable[str], rules: list[Rule], default: str) -> str:
    """Return document prefix based on ``labels`` and ``rules``."""

    for rule in rules:
        if rule.label in labels:
            return rule.target
    return default


def _normalize_source(value: Any) -> str:
    """Return a string representation of ``value`` preserving structure."""

    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _serialize_requirement(req: Requirement) -> dict[str, Any]:
    """Convert ``req`` into JSON-serializable dictionary with all schema fields."""

<<<<< codex/fix-merge-issues-in-remove-redundant-names-in-files
    data = requirement_to_dict(req)
    if "links" not in data:
=====
    data = asdict(req)
    data.pop("doc_prefix", None)
    data.pop("rid", None)
    for key, value in list(data.items()):
        if isinstance(value, Enum):
            data[key] = value.value
    if req.links:
        serialized_links: list[Any] = []
        for link in req.links:
            payload = link.to_dict()
            if len(payload) == 1:
                serialized_links.append(payload["rid"])
            else:
                serialized_links.append(payload)
        data["links"] = serialized_links
    else:
>>>>> main
        data["links"] = []
    return data


def migrate_to_docs(directory: str | Path, *, rules: str | None = None, default: str) -> None:
    """Migrate legacy requirement files in ``directory`` to document structure."""

    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(str(directory))

    rule_objs = parse_rules(rules)
    digits_map: dict[str, int] = {default: 0}
    parsed: List[dict] = []
    max_width = 0

    # First pass: read legacy files and collect metadata
    for fp in root.glob("*.json"):
        with fp.open(encoding="utf-8") as fh:
            data = json.load(fh)
        raw_id = data.get("id")
        if raw_id is None:
            raise ValueError(f"missing id in {fp}")

        aliases: list[str] = []

        def add_alias(value: str) -> None:
            if value not in aliases:
                aliases.append(value)

        if isinstance(raw_id, int):
            digits_id = str(raw_id)
            normalized_id = f"{default}{digits_id}"
            add_alias(normalized_id)
            add_alias(digits_id)
            display_id = digits_id
        elif isinstance(raw_id, str):
            normalized_id = raw_id
            add_alias(normalized_id)
            display_id = raw_id
        else:
            raise ValueError(f"invalid id format: {raw_id}")

        match = LEGACY_ID_RE.match(normalized_id)
        if not match:
            raise ValueError(f"invalid id format: {display_id}")

        num_str = match.group("num")
        num = int(num_str)
        width = len(num_str)
        if width > max_width:
            max_width = width
        labels = list(data.get("labels", []))
        prefix = select_prefix(labels, rule_objs, default)
        digits_map[prefix] = max(digits_map.get(prefix, 0), width)
        parsed.append(
            {
                "fp": fp,
                "data": data,
                "aliases": aliases,
                "num": num,
                "prefix": prefix,
                "labels": labels,
                "links": list(data.get("links", [])),
            }
        )

    if digits_map[default] == 0:
        digits_map[default] = max_width or 3

    # Determine new identifiers and build mapping
    id_map: dict[str, str] = {}
    for info in parsed:
        digits = digits_map[info["prefix"]]
        rid = f"{info['prefix']}{info['num']:0{digits}d}"
        info["rid"] = rid
        for alias in info["aliases"]:
            id_map[alias] = rid

    # Second pass: rewrite items and links
    items: list[tuple[str, int, dict]] = []
    fingerprints: dict[str, str] = {}
    for info in parsed:
        statement = info["data"].get("statement")
        if statement is None:
            raise ValueError(f"missing statement in {info['fp']}")
        legacy = dict(info["data"])
        legacy["id"] = info["num"]
        legacy["statement"] = statement
        legacy["title"] = legacy.get("title", "") or ""
        legacy.pop("text", None)
        legacy.pop("tags", None)
        legacy["labels"] = [
            lbl for lbl in info["labels"] if not lbl.startswith("doc=")
        ]
        if "source" in legacy:
            legacy["source"] = _normalize_source(legacy["source"])
        if info["links"]:
            remapped_links = []
            for link in info["links"]:
                new_link = id_map.get(link)
                if new_link is None and not isinstance(link, str):
                    new_link = id_map.get(str(link))
                remapped_links.append(new_link if new_link is not None else link)
            legacy["links"] = remapped_links
        else:
            legacy.pop("links", None)
        req = requirement_from_dict(
            legacy,
            doc_prefix=info["prefix"],
            rid=info["rid"],
        )
        item = _serialize_requirement(req)
        fingerprints[info["rid"]] = requirement_fingerprint(item)
        items.append((info["prefix"], info["num"], item, info["fp"]))

    # Populate link fingerprints and suspicion flags
    for _prefix, _num, item, _fp in items:
        links = item.get("links")
        if not links:
            continue
        enriched: list[dict[str, Any]] = []
        for raw in links:
            entry = dict(raw)
            rid = entry.get("rid")
            fingerprint = None if rid is None else fingerprints.get(rid)
            entry["fingerprint"] = fingerprint
            entry["suspect"] = fingerprint is None
            enriched.append(entry)
        if enriched:
            item["links"] = enriched
        else:
            item["links"] = []

    # Write new items and remove legacy files
    for prefix, num, item, fp in items:
        items_dir = root / prefix / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        digits = digits_map[prefix]
        filename = f"{num:0{digits}d}.json"
        with (items_dir / filename).open("w", encoding="utf-8") as fh:
            json.dump(item, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fp.unlink()

    # Create document descriptors
    for prefix, digits in digits_map.items():
        doc_dir = root / prefix
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "items").mkdir(exist_ok=True)
        doc = {
            "title": prefix,
            "digits": digits,
            "parent": None,
            "labels": {"allowFreeform": True, "defs": []},
            "attributes": {},
        }
        with (doc_dir / "document.json").open("w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert legacy flat requirements into document-based hierarchy.",
    )
    parser.add_argument("directory", help="Directory with legacy requirement files")
    parser.add_argument(
        "--rules",
        help="Assignment rules in the form 'label:key=value->PREFIX;...'",
    )
    parser.add_argument("--default", required=True, help="Default document prefix")
    cli_args = parser.parse_args()
    migrate_to_docs(cli_args.directory, rules=cli_args.rules, default=cli_args.default)
