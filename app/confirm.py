"""Confirmation callback registry for user interactions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

ConfirmCallback = Callable[[str], bool]
_callback: ConfirmCallback | None = None


class ConfirmDecision(Enum):
    """Tri-state confirmation result for requirement updates."""

    NO = "no"
    YES = "yes"
    ALWAYS = "always"


@dataclass(frozen=True)
class RequirementUpdatePrompt:
    """Information shown when confirming an MCP requirement update."""

    rid: str
    patch: Sequence[Any]
    directory: str | None = None
    revision: int | None = None


RequirementUpdateConfirmCallback = Callable[[RequirementUpdatePrompt], ConfirmDecision]
_requirement_update_callback: RequirementUpdateConfirmCallback | None = None
_requirement_update_always: bool = False


def set_confirm(callback: ConfirmCallback) -> None:
    """Register confirmation *callback* returning True to proceed."""
    global _callback
    _callback = callback


def set_requirement_update_confirm(
    callback: RequirementUpdateConfirmCallback,
) -> None:
    """Register specialised confirmation for MCP requirement updates."""

    global _requirement_update_callback, _requirement_update_always
    _requirement_update_callback = callback
    # Reset stored preference when the UI provides a new handler.
    _requirement_update_always = False


def reset_requirement_update_preference() -> None:
    """Clear session-wide "always" confirmation for requirement updates."""

    global _requirement_update_always
    _requirement_update_always = False


def confirm(message: str) -> bool:
    """Invoke registered confirmation callback with *message*.
    Raises ``RuntimeError`` if no callback configured.
    """
    if _callback is None:
        raise RuntimeError("Confirmation callback not configured")
    return _callback(message)


def confirm_requirement_update(prompt: RequirementUpdatePrompt) -> ConfirmDecision:
    """Return confirmation decision for an MCP requirement update."""

    global _requirement_update_always

    if _requirement_update_always:
        return ConfirmDecision.ALWAYS

    if _requirement_update_callback is None:
        decision = _fallback_requirement_update_confirm(prompt)
    else:
        decision = _requirement_update_callback(prompt)

    if decision is ConfirmDecision.ALWAYS:
        _requirement_update_always = True
    return decision


def _fallback_requirement_update_confirm(
    prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Default requirement update confirmation using the generic callback."""

    message = format_requirement_update_prompt(prompt)
    if _callback is None:
        return ConfirmDecision.YES
    confirmed = _callback(message)
    return ConfirmDecision.YES if confirmed else ConfirmDecision.NO


def format_requirement_update_prompt(
    prompt: RequirementUpdatePrompt, *, include_changes: bool = True
) -> str:
    """Return a human-readable confirmation message for *prompt*."""

    from .i18n import _

    rid = prompt.rid or _("(unknown requirement)")
    header = _("Update requirement \"{rid}\"?").format(rid=rid)

    details: list[str] = [header]
    if prompt.directory:
        details.append(
            _("Directory: {directory}").format(directory=str(prompt.directory))
        )
    if prompt.revision is not None:
        details.append(
            _("Expected revision: {revision}").format(revision=prompt.revision)
        )

    if include_changes:
        changes = list(summarise_requirement_patch(prompt.patch))
        if changes:
            details.append("")
            details.append(_("Planned changes:"))
            details.extend(f"  {line}" for line in changes)

    return "\n".join(details)


def summarise_requirement_patch(
    patch: Sequence[Any] | Iterable[Any]
) -> Iterable[str]:
    """Yield textual descriptions for JSON Patch operations in *patch*."""

    from .i18n import _

    for index, operation in enumerate(patch, start=1):
        if not isinstance(operation, Mapping):
            yield _("{index}. Invalid patch operation").format(index=index)
            continue

        op = str(operation.get("op", "")) or _("(missing op)")
        path = str(operation.get("path", "")) or "/"
        value_known = "value" in operation
        from_path = str(operation.get("from", "")) if operation.get("from") else None

        if op in {"add", "replace", "test"} and value_known:
            value_text = _format_patch_value(operation.get("value"))
            yield _("{index}. {op} {path} → {value}").format(
                index=index, op=op, path=path, value=value_text
            )
        elif op == "remove":
            yield _("{index}. {op} {path}").format(index=index, op=op, path=path)
        elif op in {"move", "copy"} and from_path:
            yield _("{index}. {op} {source} → {path}").format(
                index=index, op=op, source=from_path, path=path
            )
        else:
            remaining = {
                key: value
                for key, value in operation.items()
                if key not in {"op"}
            }
            yield _("{index}. {op} ({details})").format(
                index=index,
                op=op,
                details=_format_patch_value(remaining),
            )


def _format_patch_value(value: Any) -> str:
    """Return short preview of JSON Patch *value* suitable for prompts."""

    if isinstance(value, str):
        formatted = json.dumps(value, ensure_ascii=False)
    else:
        try:
            formatted = json.dumps(value, ensure_ascii=False)
        except TypeError:
            formatted = repr(value)
    if len(formatted) > 200:
        return formatted[:197] + "…"
    return formatted


def wx_confirm(message: str) -> bool:
    """GUI confirmation dialog using wxWidgets."""

    import wx  # type: ignore

    from .i18n import _

    try:
        parent = wx.GetActiveWindow()
    except AttributeError:  # pragma: no cover - stubs may omit helper
        parent = None
    if not parent:
        try:
            windows = wx.GetTopLevelWindows()
        except AttributeError:  # pragma: no cover - stubs may omit helper
            windows = []
        parent = windows[0] if windows else None

    style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
    dialog = wx.MessageDialog(parent, message, _("Confirm"), style=style)
    try:
        result = dialog.ShowModal()
    finally:
        dialog.Destroy()

    return result in {wx.ID_YES, wx.YES, wx.ID_OK, wx.OK}


def wx_confirm_requirement_update(
    prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Show a rich confirmation dialog for MCP requirement updates."""

    import wx  # type: ignore

    from .i18n import _

    if _requirement_update_always:
        return ConfirmDecision.ALWAYS

    try:
        parent = wx.GetActiveWindow()
    except AttributeError:  # pragma: no cover - stubs may omit helper
        parent = None
    if not parent:
        try:
            windows = wx.GetTopLevelWindows()
        except AttributeError:  # pragma: no cover - stubs may omit helper
            windows = []
        parent = windows[0] if windows else None

    dialog = wx.Dialog(parent, title=_("Confirm requirement update"))
    sizer = wx.BoxSizer(wx.VERTICAL)

    intro = format_requirement_update_prompt(prompt, include_changes=False)
    intro_ctrl = wx.StaticText(dialog, label=intro)
    intro_ctrl.Wrap(600)
    sizer.Add(intro_ctrl, 0, wx.ALL | wx.EXPAND, 12)

    changes = list(summarise_requirement_patch(prompt.patch))
    if changes:
        planned = wx.StaticText(dialog, label=_("Planned changes:"))
        sizer.Add(planned, 0, wx.LEFT | wx.RIGHT, 12)
        change_text = "\n".join(changes)
        summary = wx.TextCtrl(
            dialog,
            value=change_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        summary.SetMinSize((520, 200))
        sizer.Add(summary, 1, wx.ALL | wx.EXPAND, 12)

    button_sizer = wx.StdDialogButtonSizer()
    yes_btn = wx.Button(dialog, wx.ID_YES, label=_("Yes"))
    no_btn = wx.Button(dialog, wx.ID_NO, label=_("No"))
    always_btn = wx.Button(
        dialog, wx.ID_APPLY, label=_("Always for this session (all requirements)")
    )
    no_btn.SetDefault()
    no_btn.SetFocus()
    button_sizer.AddButton(always_btn)
    button_sizer.AddButton(no_btn)
    button_sizer.AddButton(yes_btn)
    button_sizer.SetAffirmativeButton(yes_btn)
    button_sizer.SetNegativeButton(no_btn)

    def _on_button(event: wx.CommandEvent) -> None:  # type: ignore[name-defined]
        dialog.EndModal(event.GetId())

    for btn in (always_btn, no_btn, yes_btn):
        btn.Bind(wx.EVT_BUTTON, _on_button)

    button_sizer.Realize()
    sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

    dialog.SetSizerAndFit(sizer)
    dialog.SetMinSize(dialog.GetSize())
    dialog.CentreOnParent()

    def _on_close(_event: wx.Event) -> None:  # type: ignore[name-defined]
        dialog.EndModal(wx.ID_NO)

    dialog.Bind(wx.EVT_CLOSE, _on_close)

    result: int
    try:
        result = dialog.ShowModal()
    finally:
        dialog.Destroy()

    if result in {wx.ID_YES, wx.YES}:
        return ConfirmDecision.YES
    if result == wx.ID_APPLY:
        return ConfirmDecision.ALWAYS
    return ConfirmDecision.NO


def auto_confirm(_message: str) -> bool:
    """Confirmation callback that always returns True."""
    return True


def auto_confirm_requirement_update(
    _prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Requirement update confirmation that always approves changes."""

    return ConfirmDecision.ALWAYS
