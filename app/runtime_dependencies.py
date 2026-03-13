"""Runtime dependency health checks executed during application startup."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Final

from app.log import logger


@dataclass(frozen=True, slots=True)
class StartupDependency:
    """Describes a runtime dependency and affected feature when absent."""

    module: str
    feature: str


STARTUP_DEPENDENCIES: Final[tuple[StartupDependency, ...]] = (
    StartupDependency("latex2mathml.converter", "DOCX formula conversion (LaTeX → MathML)"),
    StartupDependency("mathml2omml", "DOCX formula conversion (MathML → OMML for Word)"),
    StartupDependency("matplotlib", "PNG fallback rendering for formulas in preview and DOCX"),
)


def _is_module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def log_missing_startup_dependencies() -> tuple[str, ...]:
    """Log startup dependency diagnostics without interrupting startup."""
    missing: list[StartupDependency] = []
    statuses: list[str] = []
    for dependency in STARTUP_DEPENDENCIES:
        available = _is_module_available(dependency.module)
        statuses.append(f"{dependency.module}={'ok' if available else 'missing'}")
        if not available:
            missing.append(dependency)

    logger.info(
        "Startup optional dependency diagnostics: %s",
        ", ".join(statuses),
    )

    if not missing:
        return ()

    missing_modules = tuple(dep.module for dep in missing)
    details = "; ".join(f"{dep.module} → {dep.feature}" for dep in missing)
    logger.warning(
        "Optional runtime dependencies are missing: %s. Feature impact: %s",
        ", ".join(missing_modules),
        details,
    )
    return missing_modules
