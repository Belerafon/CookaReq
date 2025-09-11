"""Domain models for requirements."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class RequirementType(str, Enum):
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    INTERFACE = "interface"


class Status(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    BASELINED = "baselined"
    RETIRED = "retired"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verification(str, Enum):
    INSPECTION = "inspection"
    ANALYSIS = "analysis"
    DEMONSTRATION = "demonstration"
    TEST = "test"


@dataclass
class Units:
    quantity: str
    nominal: float
    tolerance: Optional[float] = None


@dataclass
class Attachment:
    path: str
    note: str = ""


@dataclass
class Requirement:
    id: int
    title: str
    statement: str
    type: RequirementType
    status: Status
    owner: str
    priority: Priority
    source: str
    verification: Verification
    acceptance: Optional[str] = None
    conditions: str = ""
    trace_up: str = ""
    trace_down: str = ""
    version: str = ""
    modified_at: str = ""
    units: Optional[Units] = None
    labels: List[str] = field(default_factory=list)
    attachments: List[Attachment] = field(default_factory=list)
    revision: int = 1
    approved_at: Optional[str] = None
    notes: str = ""
