"""Composition root building shared dependencies for CookaReq."""
from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from .config import ConfigManager
from .confirm import (
    ConfirmDecision,
    RequirementUpdatePrompt,
    set_confirm,
    set_requirement_update_confirm,
)
from .mcp.controller import MCPController
from .services.requirements import RequirementsService
from .settings import AppSettings
from .ui.requirement_model import RequirementModel

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from .agent import LocalAgent

ConfirmCallback = Callable[[str], bool]
RequirementUpdateConfirmCallback = Callable[[RequirementUpdatePrompt], ConfirmDecision]


class RequirementsServiceFactory(Protocol):
    """Factory protocol producing :class:`RequirementsService` instances."""

    def __call__(self, root: Path | str) -> RequirementsService:
        """Return a requirements service rooted at ``root``."""
        raise NotImplementedError


class LocalAgentFactory(Protocol):
    """Factory protocol creating configured :class:`LocalAgent` instances."""

    def __call__(
        self,
        settings: AppSettings,
        *,
        confirm_override: ConfirmCallback | None = None,
        confirm_requirement_update_override: RequirementUpdateConfirmCallback
        | None = None,
    ) -> LocalAgent:
        """Build an agent for ``settings`` optionally overriding confirmations."""
        raise NotImplementedError


class MCPControllerFactory(Protocol):
    """Factory protocol creating :class:`MCPController` instances."""

    def __call__(self) -> MCPController:
        """Return a new MCP controller."""
        raise NotImplementedError


class ApplicationContext:
    """Central dependency registry shared by GUI and CLI frontends."""

    def __init__(
        self,
        *,
        app_name: str = "CookaReq",
        confirm_callback: ConfirmCallback,
        requirement_update_confirm_callback: RequirementUpdateConfirmCallback,
        config_factory: Callable[[str], ConfigManager] | None = None,
        requirement_model_factory: Callable[[], RequirementModel] | None = None,
        requirements_service_cls: type[RequirementsService] = RequirementsService,
        local_agent_cls: type["LocalAgent"] | None = None,
        mcp_controller_cls: type[MCPController] = MCPController,
    ) -> None:
        self._app_name = app_name
        self._config_factory = config_factory or (lambda name: ConfigManager(name))
        self._requirement_model_factory = (
            requirement_model_factory or RequirementModel
        )
        self._requirements_service_cls = requirements_service_cls
        self._local_agent_cls = local_agent_cls
        self._mcp_controller_cls = mcp_controller_cls
        self._config: ConfigManager | None = None
        self._requirement_model: RequirementModel | None = None
        self._requirements_service_factory: RequirementsServiceFactory | None = None
        self._local_agent_factory: LocalAgentFactory | None = None
        self._mcp_controller_factory: MCPControllerFactory | None = None

        set_confirm(confirm_callback)
        set_requirement_update_confirm(requirement_update_confirm_callback)

    @property
    def config(self) -> ConfigManager:
        """Return lazily initialised :class:`ConfigManager`."""
        if self._config is None:
            self._config = self._config_factory(self._app_name)
        return self._config

    @property
    def requirement_model(self) -> RequirementModel:
        """Return shared :class:`RequirementModel` instance."""
        if self._requirement_model is None:
            self._requirement_model = self._requirement_model_factory()
        return self._requirement_model

    @property
    def requirements_service_factory(self) -> RequirementsServiceFactory:
        """Return factory constructing :class:`RequirementsService` objects."""
        if self._requirements_service_factory is None:
            service_cls = self._requirements_service_cls

            def _factory(root: Path | str) -> RequirementsService:
                return service_cls(Path(root))

            self._requirements_service_factory = _factory
        return self._requirements_service_factory

    @property
    def local_agent_factory(self) -> LocalAgentFactory:
        """Return factory creating :class:`LocalAgent` instances."""
        if self._local_agent_factory is None:
            agent_cls = self._local_agent_cls
            if agent_cls is None:
                from .agent import LocalAgent as _LocalAgent

                agent_cls = self._local_agent_cls = _LocalAgent

            def _factory(
                settings: AppSettings,
                *,
                confirm_override: ConfirmCallback | None = None,
                confirm_requirement_update_override: RequirementUpdateConfirmCallback
                | None = None,
            ) -> "LocalAgent":
                kwargs: dict[str, object] = {"settings": settings}
                if confirm_override is not None:
                    kwargs["confirm"] = confirm_override
                if confirm_requirement_update_override is not None:
                    kwargs["confirm_requirement_update"] = (
                        confirm_requirement_update_override
                    )
                return agent_cls(**kwargs)

            self._local_agent_factory = _factory
        return self._local_agent_factory

    @property
    def mcp_controller_factory(self) -> MCPControllerFactory:
        """Return factory creating :class:`MCPController` instances."""
        if self._mcp_controller_factory is None:
            controller_cls = self._mcp_controller_cls

            def _factory() -> MCPController:
                return controller_cls()

            self._mcp_controller_factory = _factory
        return self._mcp_controller_factory

    @classmethod
    def for_gui(cls, *, app_name: str = "CookaReq") -> "ApplicationContext":
        """Return context configured for the wx-based GUI."""
        from .confirm import wx_confirm, wx_confirm_requirement_update

        return cls(
            app_name=app_name,
            confirm_callback=wx_confirm,
            requirement_update_confirm_callback=wx_confirm_requirement_update,
        )

    @classmethod
    def for_cli(cls, *, app_name: str = "CookaReq") -> "ApplicationContext":
        """Return context configured for non-interactive CLI usage."""
        from .confirm import auto_confirm, auto_confirm_requirement_update

        return cls(
            app_name=app_name,
            confirm_callback=auto_confirm,
            requirement_update_confirm_callback=auto_confirm_requirement_update,
        )

