from __future__ import annotations

from .doc_store import LabelDef, stable_color


def _preset(keys: list[str]) -> list[LabelDef]:
    def title_from_key(k: str) -> str:
        return k.replace("-", " ").replace("_", " ").title()

    return [LabelDef(key=k, title=title_from_key(k), color=stable_color(k)) for k in keys]


PRESET_SETS: dict[str, list[LabelDef]] = {
    "basic": _preset(
        [
            "functional",
            "non-functional",
            "ui",
            "performance",
            "reliability",
            "safety",
            "security",
            "usability",
            "constraint",
            "regulatory",
        ]
    ),
    "role": _preset(
        [
            "system",
            "software",
            "hardware",
            "integration",
            "test",
        ]
    ),
    "status": _preset(
        [
            "draft",
            "approved",
            "in-progress",
            "implemented",
            "verified",
            "obsolete",
        ]
    ),
    "priority": _preset(
        [
            "high",
            "medium",
            "low",
        ]
    ),
    "additional": _preset(
        [
            "critical",
            "derived",
            "untested",
            "suspect-link",
            "attachments",
        ]
    ),
}

PRESET_SET_TITLES: dict[str, str] = {
    "basic": "Basic",
    "role": "By role",
    "status": "By status",
    "priority": "By priority",
    "additional": "Additional",
}

