"""Tests for agent chat panel spacing issues."""

import wx
import wx.lib.scrolledpanel as scrolled
from typing import Any

from app.ui.agent_chat_panel.components.segments import MessageSegmentPanel, TurnCard
from app.ui.agent_chat_panel.types import (
    AgentResponse,
    AgentSegment,
    PromptSegment,
    TimestampInfo,
    TranscriptSegment,
)
from tests.gui.helpers import (
    BaseWxTestCase,
    assert_eventually,
    assert_not_raised,
    wait_for,
)

class TestAgentChatSpacing(BaseWxTestCase):
    """Test cases for agent chat panel spacing issues."""

    def test_message_spacing_after_navigation(self):
        """Verify that message spacing remains consistent after navigation."""
        # Create a test frame with a scrolled panel to simulate the chat view
        frame = wx.Frame(None)
        panel = scrolled.ScrolledPanel(frame)
        panel.SetSizer(wx.BoxSizer(wx.VERTICAL))
        panel.SetupScrolling()
        
        # Create a test message
        entry_id = "test-message"
        segments = [
            TranscriptSegment(
                kind="agent",
                payload=AgentSegment(
                    entry_id=entry_id,
                    entry_index=0,
                    response=AgentResponse(
                        text="Test message",
                        display_text="Test message",
                        is_final=True,
                        raw_data={"test": "data"},
                    ),
                ),
            )
        ]
        
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

    def test_raw_data_section_spacing(self):
        """Verify spacing around raw data section is consistent."""
        frame = wx.Frame(None)
        panel = scrolled.ScrolledPanel(frame)
        panel.SetSizer(wx.BoxSizer(wx.VERTICAL))
        panel.SetupScrolling()
        
        # Create a test message with raw data
        entry_id = "test-raw-data"
        segments = [
            TranscriptSegment(
                kind="agent",
                payload=AgentSegment(
                    entry_id=entry_id,
                    entry_index=0,
                    response=AgentResponse(
                        text="Test message with raw data",
                        display_text="Test message with raw data",
                        is_final=True,
                        raw_data={"test": "data"},
                    ),
                ),
            )
        ]
        
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
