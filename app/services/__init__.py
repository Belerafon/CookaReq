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
from .user_documents import UserDocumentsService

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
    "UserDocumentsService",
]
