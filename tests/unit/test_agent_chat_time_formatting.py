from app.ui.agent_chat_panel.time_formatting import format_entry_timestamp


def test_format_entry_timestamp_converts_z_suffix():
    timestamp = "2025-10-01T10:39:36Z"
    formatted = format_entry_timestamp(timestamp)
    assert "10:39:36" in formatted
    assert "T" not in formatted


def test_format_entry_timestamp_handles_offsets():
    timestamp = "2025-10-01T10:39:36+00:00"
    formatted = format_entry_timestamp(timestamp)
    assert formatted.startswith("01 ")
    assert formatted.endswith("10:39:36")
