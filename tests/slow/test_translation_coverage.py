"""Tests for translation coverage."""

import ast
from pathlib import Path

import polib
import pytest

pytestmark = pytest.mark.slow


def test_po_files_have_no_missing_translations():
    base = Path("app/locale")
    catalogs = {}
    all_ids = set()
    for lang_dir in base.iterdir():
        po_path = lang_dir / "LC_MESSAGES" / "CookaReq.po"
        if po_path.exists():
            catalog = polib.pofile(str(po_path))
            catalogs[lang_dir.name] = catalog
            all_ids.update(entry.msgid for entry in catalog if entry.msgid)
    for lang, catalog in catalogs.items():
        ids = {entry.msgid for entry in catalog if entry.msgid}
        missing = all_ids - ids
        assert not missing, f"{lang} missing translations: {sorted(missing)}"
        empty = [entry.msgid for entry in catalog if entry.msgid and not entry.msgstr]
        assert not empty, f"{lang} has empty translations: {empty}"


_TRANSLATION_ARGUMENT_SPECS = {
    "_": ((0, None),),
    "gettext": ((0, None),),
    "ngettext": ((0, "singular"), (1, "plural")),
    "pgettext": ((1, "message"),),
    "npgettext": ((1, "singular"), (2, "plural")),
}


def _extract_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extract_literal(node.left)
        right = _extract_literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _resolve_translation_names(tree: ast.AST) -> dict[str, str]:
    mapping = {name: name for name in _TRANSLATION_ARGUMENT_SPECS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                original = alias.name
                if original in _TRANSLATION_ARGUMENT_SPECS:
                    local_name = alias.asname or alias.name
                    mapping[local_name] = original
    return mapping


def _get_argument(call: ast.Call, position: int, keyword: str | None) -> ast.AST | None:
    if position < len(call.args):
        return call.args[position]
    if keyword is not None:
        for candidate in call.keywords:
            if candidate.arg == keyword:
                return candidate.value
    return None


def _collect_source_msgids(base: Path) -> set[str]:
    msgids: set[str] = set()
    for path in base.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        translation_names = _resolve_translation_names(tree)
        if not translation_names:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name: str | None = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                func_name = f"{func.value.id}.{func.attr}"
            if func_name is None:
                continue
            canonical = translation_names.get(func_name)
            if canonical is None:
                continue
            for position, keyword in _TRANSLATION_ARGUMENT_SPECS.get(canonical, ()): 
                arg_node = _get_argument(node, position, keyword)
                if arg_node is None:
                    continue
                literal = _extract_literal(arg_node)
                if literal:
                    msgids.add(literal)
    return msgids


def test_source_strings_are_in_catalogue():
    source_ids = _collect_source_msgids(Path("app"))
    catalog = polib.pofile("app/locale/en/LC_MESSAGES/CookaReq.po")
    catalog_ids = {entry.msgid for entry in catalog if entry.msgid}
    for entry in catalog:
        plural = getattr(entry, "msgid_plural", None)
        if plural:
            catalog_ids.add(plural)
    missing = sorted(msgid for msgid in source_ids if msgid not in catalog_ids)
    assert not missing, f"Source strings missing from catalogue: {missing}"
