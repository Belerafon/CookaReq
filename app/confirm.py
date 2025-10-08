"""Confirmation callback registry for user interactions."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ParamSpec, TypeVar
from collections.abc import Callable, Iterable, Sequence

ConfirmCallback = Callable[[str], bool]
_callback: ConfirmCallback | None = None


class ConfirmDecision(Enum):
    """Tri-state confirmation result for requirement updates."""

    NO = "no"
    YES = "yes"
    ALWAYS = "always"


@dataclass(frozen=True)
class RequirementChange:
    """Description of a single requirement update for confirmation prompts."""

    kind: str
    field: str | None = None
    value: Any | None = None


@dataclass(frozen=True)
class RequirementUpdatePrompt:
    """Information shown when confirming an MCP requirement update."""

    rid: str
    changes: Sequence[RequirementChange] = field(default_factory=tuple)
    directory: str | None = None
    tool: str | None = None


RequirementUpdateConfirmCallback = Callable[[RequirementUpdatePrompt], ConfirmDecision]
_requirement_update_callback: RequirementUpdateConfirmCallback | None = None
_requirement_update_always: bool = False

_T = TypeVar("_T")
_P = ParamSpec("_P")


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


def _call_in_wx_main_thread(
    func: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Execute *func* on the wx main thread and return its result."""
    import wx  # type: ignore

    is_main_thread = True
    if hasattr(wx, "IsMainThread"):
        try:
            is_main_thread = bool(wx.IsMainThread())
        except Exception:  # pragma: no cover - defensive guard
            is_main_thread = True
    if is_main_thread:
        return func(*args, **kwargs)

    get_app = getattr(wx, "GetApp", None)
    try:
        app = get_app() if callable(get_app) else None
    except Exception:  # pragma: no cover - defensive guard
        app = None
    if app is None:
        return func(*args, **kwargs)

    done = threading.Event()
    result: dict[str, Any] = {}

    def _invoke() -> None:
        try:
            result["value"] = func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - propagate later
            result["error"] = exc
        finally:
            done.set()

    try:
        wx.CallAfter(_invoke)
    except Exception:  # pragma: no cover - fallback when CallAfter fails
        return func(*args, **kwargs)

    done.wait()

    if "error" in result:
        raise result["error"]

    if "value" not in result:  # pragma: no cover - defensive
        raise RuntimeError("wx main-thread callback did not provide a result")

    return result["value"]


def _fallback_requirement_update_confirm(
    prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Return fallback requirement update confirmation via the generic callback."""
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
    if prompt.tool:
        details.append(_("Tool: {tool}").format(tool=prompt.tool))

    if include_changes:
        changes = list(summarise_requirement_changes(prompt.changes))
        if changes:
            details.append("")
            details.append(_("Planned changes:"))
            details.extend(f"  {line}" for line in changes)

    return "\n".join(details)


def summarise_requirement_changes(
    changes: Sequence[RequirementChange] | Iterable[RequirementChange],
) -> Iterable[str]:
    """Yield textual descriptions for requirement updates in *changes*."""
    from .i18n import _

    for index, change in enumerate(changes, start=1):
        if not isinstance(change, RequirementChange):
            yield _("{index}. Invalid change payload").format(index=index)
            continue

        kind = change.kind or ""
        value = change.value

        if kind == "field":
            field_name = change.field or _("(missing field)")
            value_text = _format_change_value(value)
            yield _("{index}. set {field} → {value}").format(
                index=index,
                field=field_name,
                value=value_text,
            )
        elif kind == "labels":
            labels_value = [] if value is None else value
            value_text = _format_change_value(labels_value)
            yield _("{index}. replace labels → {value}").format(
                index=index,
                value=value_text,
            )
        elif kind == "attachments":
            attachments_value = [] if value is None else value
            value_text = _format_change_value(attachments_value)
            yield _("{index}. replace attachments → {value}").format(
                index=index,
                value=value_text,
            )
        elif kind == "links":
            links_value = [] if value is None else value
            value_text = _format_change_value(links_value)
            yield _("{index}. replace links → {value}").format(
                index=index,
                value=value_text,
            )
        else:
            value_text = _format_change_value(value)
            yield _("{index}. {kind} → {value}").format(
                index=index,
                kind=kind or _("update"),
                value=value_text,
            )


def _format_change_value(value: Any) -> str:
    """Return short preview of change *value* suitable for prompts."""
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
    from .i18n import _

    def _show_dialog() -> bool:
        import wx  # type: ignore

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

    return _call_in_wx_main_thread(_show_dialog)


def wx_confirm_requirement_update(
    prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Show a rich confirmation dialog for MCP requirement updates."""
    if _requirement_update_always:
        return ConfirmDecision.ALWAYS

    from .i18n import _

    def _show_dialog() -> ConfirmDecision:
        import wx  # type: ignore

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

        changes = list(summarise_requirement_changes(prompt.changes))
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
            dialog,
            wx.ID_APPLY,
            label=_("Always until restart (all requirements)"),
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

        try:
            result = dialog.ShowModal()
        finally:
            dialog.Destroy()

        if result in {wx.ID_YES, wx.YES}:
            return ConfirmDecision.YES
        if result == wx.ID_APPLY:
            return ConfirmDecision.ALWAYS
        return ConfirmDecision.NO

    return _call_in_wx_main_thread(_show_dialog)


def auto_confirm(_message: str) -> bool:
    """Return ``True`` for every confirmation request."""
    return True


def auto_confirm_requirement_update(
    _prompt: RequirementUpdatePrompt,
) -> ConfirmDecision:
    """Approve requirement update prompts unconditionally."""
    return ConfirmDecision.ALWAYS
