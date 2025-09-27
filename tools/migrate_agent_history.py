#!/usr/bin/env python3
"""Utility to migrate agent chat history files to the current format."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.ui.chat_entry import (
    ChatConversation,
    ChatEntry,
    _recalculate_pair_token_info,
)
from app.llm.tokenizer import TokenCountResult


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Не удалось прочитать JSON из {path}: {exc}") from exc


def _normalise_entry_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    prepared = dict(payload)
    prompt = str(prepared.get("prompt", ""))
    response = str(prepared.get("response", ""))
    token_info_raw = prepared.get("token_info")
    token_info: TokenCountResult
    if isinstance(token_info_raw, Mapping):
        try:
            token_info = TokenCountResult.from_dict(token_info_raw)
        except Exception:
            token_info = _recalculate_pair_token_info(prompt, response)
    else:
        token_info = _recalculate_pair_token_info(prompt, response)
    prepared["token_info"] = token_info.to_dict()
    prepared["tokens"] = token_info.tokens or 0
    return prepared


def _conversation_from_payload(payload: Mapping[str, Any]) -> ChatConversation | None:
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, Sequence):
        return None
    prepared_entries: list[dict[str, Any]] = []
    for entry_raw in entries_raw:
        if not isinstance(entry_raw, Mapping):
            continue
        prepared_entry = _normalise_entry_payload(entry_raw)
        try:
            ChatEntry.from_dict(prepared_entry)
        except ValueError:
            continue
        prepared_entries.append(prepared_entry)
    if not prepared_entries:
        return None
    prepared_payload = dict(payload)
    prepared_payload["entries"] = prepared_entries
    conversation = ChatConversation.from_dict(prepared_payload)
    if not conversation.entries:
        return None
    return conversation


def _conversation_from_flat_sequence(payload: Sequence[Any]) -> ChatConversation | None:
    prepared_entries: list[dict[str, Any]] = []
    for entry_raw in payload:
        if not isinstance(entry_raw, Mapping):
            continue
        prepared_entry = _normalise_entry_payload(entry_raw)
        try:
            ChatEntry.from_dict(prepared_entry)
        except ValueError:
            continue
        prepared_entries.append(prepared_entry)
    if not prepared_entries:
        return None
    conversation = ChatConversation.new()
    conversation.entries = []
    for entry_payload in prepared_entries:
        entry = ChatEntry.from_dict(entry_payload)
        conversation.append_entry(entry)
    first = conversation.entries[0]
    if first.prompt_at:
        conversation.created_at = first.prompt_at
    last = conversation.entries[-1]
    if last.response_at or last.prompt_at:
        conversation.updated_at = last.response_at or last.prompt_at
    conversation.ensure_title()
    return conversation


def migrate_history(raw: Any) -> dict[str, Any]:
    conversations: list[ChatConversation] = []
    active_id: str | None = None

    if isinstance(raw, Mapping):
        version = raw.get("version")
        if version is not None and version not in {1, 2}:
            raise RuntimeError(f"Неизвестная версия истории: {version!r}")
        conversations_raw = raw.get("conversations")
        if not isinstance(conversations_raw, Sequence):
            raise RuntimeError("Отсутствует список бесед в истории")
        for conversation_raw in conversations_raw:
            if not isinstance(conversation_raw, Mapping):
                continue
            conversation = _conversation_from_payload(conversation_raw)
            if conversation is not None:
                conversations.append(conversation)
        active_raw = raw.get("active_id")
        if isinstance(active_raw, str) and any(
            conv.conversation_id == active_raw for conv in conversations
        ):
            active_id = active_raw
    elif isinstance(raw, Sequence):
        conversation = _conversation_from_flat_sequence(raw)
        if conversation is not None:
            conversations.append(conversation)
    else:
        raise RuntimeError("Поддерживаются только объекты JSON или массив записей")

    if not conversations:
        raise RuntimeError("Не удалось извлечь ни одной валидной беседы из истории")

    if active_id is None:
        active_id = conversations[-1].conversation_id

    return {
        "version": 2,
        "active_id": active_id,
        "conversations": [conv.to_dict() for conv in conversations],
    }


def _default_output_path(path: Path) -> Path:
    suffix = path.suffix or ""
    return path.with_name(path.stem + ".migrated" + suffix)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Конвертирует файлы истории агента в актуальный формат (версия 2) "
            "с обязательным блоком token_info."
        )
    )
    parser.add_argument("input", type=Path, help="Путь к исходному файлу истории")
    parser.add_argument(
        "--output",
        type=Path,
        help="Путь для сохранения результата (по умолчанию <input>.migrated.json)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Переписать исходный файл на месте. Перед записью создаётся резервная "
            "копия с суффиксом .bak, либо по пути из --backup"
        ),
    )
    parser.add_argument(
        "--backup",
        type=Path,
        help="Путь к резервной копии при использовании --in-place (по умолчанию <input>.bak)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующие файлы вывода или резервной копии",
    )
    args = parser.parse_args(argv)

    if args.in_place and args.output is not None:
        parser.error("нельзя одновременно использовать --output и --in-place")

    input_path = args.input
    raw = _load_json(input_path)
    payload = migrate_history(raw)

    if args.in_place:
        backup_path = args.backup or input_path.with_suffix(input_path.suffix + ".bak")
        if backup_path.exists() and not args.force:
            parser.error(f"файл резервной копии уже существует: {backup_path}")
        if backup_path != input_path:
            input_path.replace(backup_path)
        output_path = input_path
    else:
        output_path = args.output or _default_output_path(input_path)
        if output_path.exists() and not args.force:
            parser.error(f"файл назначения уже существует: {output_path}")

    _write_json(output_path, payload)

    if args.in_place:
        sys.stdout.write(
            f"История успешно мигрирована и записана в {output_path} (резервная копия: {backup_path})\n"
        )
    else:
        sys.stdout.write(f"История успешно мигрирована и записана в {output_path}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
