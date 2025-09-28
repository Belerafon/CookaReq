"""Service layer abstractions for CookaReq."""

from .requirements import (
    RequirementsService,
    Document,
    DocumentLabels,
    DocumentNotFoundError,
    LabelDef,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    RequirementPage,
    ValidationError,
    iter_links,
    label_color,
    parse_rid,
    rid_for,
    stable_color,
)

__all__ = [
    "RequirementsService",
    "Document",
    "DocumentLabels",
    "DocumentNotFoundError",
    "LabelDef",
    "RequirementIDCollisionError",
    "RequirementNotFoundError",
    "RequirementPage",
    "ValidationError",
    "iter_links",
    "label_color",
    "parse_rid",
    "rid_for",
    "stable_color",
]
