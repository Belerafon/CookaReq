"""Controller orchestrating the chat session and backend interactions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .controller import AgentRunController
from .execution import AgentCommandExecutor, _AgentRunHandle
from .session import AgentChatSession
from ..chat_entry import ChatEntry


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

    # ------------------------------------------------------------------
    @property
    def active_handle(self) -> _AgentRunHandle | None:
        """Expose the controller's active handle for inspection."""
        return self._run_controller.active_handle

    # ------------------------------------------------------------------
    def reset_active_handle(self, handle: _AgentRunHandle) -> None:
        """Clear the active handle if it matches *handle*."""
        self._run_controller.reset_active_handle(handle)

    # ------------------------------------------------------------------
    def regenerate_entry(self, conversation_id: str, entry: ChatEntry) -> None:
        """Trigger regeneration of the last entry in a conversation."""
        self._run_controller.regenerate_entry(conversation_id, entry)


__all__ = ["AgentChatCoordinator"]
