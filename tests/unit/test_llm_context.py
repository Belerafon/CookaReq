from app.llm.context import (
    extract_selected_rids_from_messages,
    extract_selected_rids_from_text,
)


def test_extract_selected_rids_from_text_returns_unique_canonical_ids() -> None:
    content = (
        "[Workspace context]\n"
        "Selected requirement RIDs: SYS1, SYS2, SYS1, INVALID, SYS3"
    )
    assert extract_selected_rids_from_text(content) == ["SYS1", "SYS2", "SYS3"]


def test_extract_selected_rids_from_text_handles_empty_annotation() -> None:
    content = "[Workspace context]\nSelected requirement RIDs: (none)"
    assert extract_selected_rids_from_text(content) == []


def test_extract_selected_rids_from_messages_merges_multiple_snapshots() -> None:
    messages = [
        {"role": "system", "content": "Selected requirement RIDs: SYS4, SYS5"},
        {"role": "assistant", "content": "irrelevant"},
        {"role": "system", "content": "Selected requirement RIDs: SYS5, SYS6"},
    ]
    assert extract_selected_rids_from_messages(messages) == [
        "SYS4",
        "SYS5",
        "SYS6",
    ]
