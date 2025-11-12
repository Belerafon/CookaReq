"""Tests for agent chat panel spacing issues."""

import wx
import wx.lib.scrolledpanel as scrolled
from typing import Any

from app.ui.agent_chat_panel.components.segments import TurnCard
from app.ui.agent_chat_panel.view_model import (
    AgentResponse,
    AgentSegment,
    AgentTurn,
    TimestampInfo,
    TranscriptSegment,
)
def test_message_spacing_after_navigation():
    """Verify that message spacing remains consistent after navigation."""
    # Create a test frame with a scrolled panel to simulate the chat view
    frame = wx.Frame(None)
    panel = scrolled.ScrolledPanel(frame)
    panel.SetSizer(wx.BoxSizer(wx.VERTICAL))
    panel.SetupScrolling()

    # Create a test message
    entry_id = "test-message"
    segments = _build_agent_segments(entry_id)

    # Create the turn card
    turn_card = TurnCard(
        panel,
        entry_id=entry_id,
        entry_index=0,
        on_layout_hint=None,
    )

    # Update with initial segments
    turn_card.update(
        segments=segments,
        on_regenerate=None,
        regenerate_enabled=True,
    )

    # Add to panel
    panel.GetSizer().Add(turn_card, 0, wx.EXPAND | wx.ALL, 5)
    panel.GetSizer().Layout()
    panel.Refresh()

    # Get initial height
    initial_height = turn_card.GetSize().height

    # Simulate navigating away and back by hiding and showing
    turn_card.Hide()
    wx.Yield()
    turn_card.Show()
    panel.Layout()
    panel.Refresh()

    # Force a repaint
    panel.Update()
    wx.Yield()

    # Get height after navigation
    final_height = turn_card.GetSize().height

    # Verify heights match
    assert initial_height == final_height, \
        f"Height changed from {initial_height} to {final_height} after navigation"

    frame.Destroy()


def test_raw_data_section_spacing():
    """Verify spacing around raw data section is consistent."""
    frame = wx.Frame(None)
    panel = scrolled.ScrolledPanel(frame)
    panel.SetSizer(wx.BoxSizer(wx.VERTICAL))
    panel.SetupScrolling()

    # Create a test message with raw data
    entry_id = "test-raw-data"
    segments = _build_agent_segments(
        entry_id,
        response_text="Test message with raw data",
        raw_payload={"test": "data"},
    )

    # Create and update the turn card
    turn_card = TurnCard(
        panel,
        entry_id=entry_id,
        entry_index=0,
        on_layout_hint=None,
    )
    turn_card.update(
        segments=segments,
        on_regenerate=None,
        regenerate_enabled=True,
    )

    # Add to panel and layout
    panel.GetSizer().Add(turn_card, 0, wx.EXPAND | wx.ALL, 5)
    panel.GetSizer().Layout()

    # Find the raw data section
    raw_section = None
    for child in turn_card.GetChildren():
        if isinstance(child, wx.CollapsiblePane) and "Raw" in child.GetLabel():
            raw_section = child
            break

    # Verify raw section exists and is properly positioned
    assert raw_section is not None, "Raw data section not found"

    # Get position relative to parent
    raw_pos = raw_section.GetPosition()
    parent_pos = turn_card.GetPosition()
    relative_y = raw_pos.y - parent_pos.y

    # Verify there's not excessive space above the raw section
    # The exact value may need adjustment based on your UI design
    assert relative_y < 100, f"Excessive space ({relative_y}px) above raw data section"

    frame.Destroy()


def _build_agent_segments(
    entry_id: str,
    *,
    response_text: str = "Test message",
    raw_payload: Any | None = None,
) -> list[TranscriptSegment]:
    """Construct transcript segments compatible with the current view model."""

    timestamp = TimestampInfo(
        raw=None,
        occurred_at=None,
        formatted="",
        missing=True,
        source=None,
    )
    response = AgentResponse(
        text=response_text,
        display_text=response_text,
        timestamp=timestamp,
        step_index=None,
        is_final=True,
        regenerated=False,
    )
    turn = AgentTurn(
        entry_id=entry_id,
        entry_index=0,
        occurred_at=None,
        timestamp=timestamp,
        streamed_responses=(response,),
        final_response=response,
        reasoning=(),
        llm_request=None,
        tool_calls=(),
        raw_payload=raw_payload,
        events=(),
    )
    agent_segment = AgentSegment(
        turn=turn,
        layout_hints={},
        can_regenerate=True,
    )
    return [
        TranscriptSegment(
            segment_id=f"{entry_id}:agent",
            entry_id=entry_id,
            entry_index=0,
            kind="agent",
            payload=agent_segment,
        )
    ]
