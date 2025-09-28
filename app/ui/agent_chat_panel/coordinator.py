"""Controller orchestrating the chat session and backend interactions."""

from __future__ import annotations

from typing import Mapping, Sequence

from .controller import AgentRunController
from .execution import AgentCommandExecutor, _AgentRunHandle
from .session import AgentChatSession


class AgentChatCoordinator:
    """Glue layer between the UI events and the agent runtime."""

    def __init__(
        self,
        *,
        session: AgentChatSession,
        run_controller: AgentRunController,
        command_executor: AgentCommandExecutor,
    ) -> None:
        self._session = session
        self._run_controller = run_controller
        self._command_executor = command_executor

    # ------------------------------------------------------------------
    @property
    def session(self) -> AgentChatSession:
        return self._session

    # ------------------------------------------------------------------
    def submit_prompt(self, prompt: str, *, prompt_at: str | None = None) -> None:
        """Send a prompt to the agent pipeline."""

        self._run_controller.submit_prompt(prompt, prompt_at=prompt_at)

    # ------------------------------------------------------------------
    def submit_prompt_with_context(
        self,
        prompt: str,
        *,
        conversation_id: str,
        context_messages: Sequence[Mapping[str, object]] | Mapping[str, object] | None,
        prompt_at: str | None,
    ) -> None:
        """Send a prompt that carries additional context information."""

        self._run_controller.submit_prompt_with_context(
            prompt,
            conversation_id=conversation_id,
            context_messages=context_messages,
            prompt_at=prompt_at,
        )

    # ------------------------------------------------------------------
    def cancel_active_run(self) -> _AgentRunHandle | None:
        """Abort the current agent run when possible."""

        return self._run_controller.stop()

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Stop the underlying controller and cancel the executor."""

        self._run_controller.stop()


__all__ = ["AgentChatCoordinator"]
