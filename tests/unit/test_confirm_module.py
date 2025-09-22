import pytest

from app import confirm as confirm_module
from app.confirm import (
    ConfirmDecision,
    RequirementChange,
    RequirementUpdatePrompt,
    format_requirement_update_prompt,
    reset_requirement_update_preference,
    set_requirement_update_confirm,
)


@pytest.fixture(autouse=True)
def restore_confirm_state():
    original_callback = confirm_module._requirement_update_callback
    original_always = confirm_module._requirement_update_always
    try:
        yield
    finally:
        confirm_module._requirement_update_callback = original_callback
        confirm_module._requirement_update_always = original_always


def test_format_requirement_update_prompt_includes_details():
    prompt = RequirementUpdatePrompt(
        rid="SYS-1",
        directory="/tmp/reqs",
        tool="update_requirement_field",
        changes=(
            RequirementChange(kind="field", field="title", value="New title"),
            RequirementChange(kind="labels", value=[]),
        ),
    )
    text = format_requirement_update_prompt(prompt)
    assert "Update requirement \"SYS-1\"?" in text
    assert "Directory: /tmp/reqs" in text
    assert "Tool: update_requirement_field" in text
    assert "set title" in text and "New title" in text
    assert "replace labels" in text


def test_confirm_requirement_update_always_caches_callback():
    calls: list[str] = []

    def decision(prompt: RequirementUpdatePrompt) -> ConfirmDecision:
        calls.append(prompt.rid)
        return ConfirmDecision.ALWAYS

    set_requirement_update_confirm(decision)

    first = confirm_module.confirm_requirement_update(
        RequirementUpdatePrompt(rid="SYS-1", changes=())
    )
    assert first is ConfirmDecision.ALWAYS

    second = confirm_module.confirm_requirement_update(
        RequirementUpdatePrompt(rid="SYS-2", changes=())
    )
    assert second is ConfirmDecision.ALWAYS
    assert calls == ["SYS-1"]

    reset_requirement_update_preference()
    third = confirm_module.confirm_requirement_update(
        RequirementUpdatePrompt(rid="SYS-3", changes=())
    )
    assert third is ConfirmDecision.ALWAYS
    assert calls == ["SYS-1", "SYS-3"]
