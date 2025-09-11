"""Russian localization dictionaries for enum fields."""

TYPE = {
    "requirement": "Требование",
    "constraint": "Ограничение",
    "interface": "Интерфейс",
}

STATUS = {
    "draft": "Черновик",
    "in_review": "На рецензии",
    "approved": "Согласовано",
    "baselined": "Зафиксировано",
    "retired": "Снято с применения",
}

PRIORITY = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
}

VERIFICATION = {
    "inspection": "Инспекция",
    "analysis": "Анализ",
    "demonstration": "Демонстрация",
    "test": "Испытание",
}

TRANSLATIONS = {
    "type": TYPE,
    "status": STATUS,
    "priority": PRIORITY,
    "verification": VERIFICATION,
}


def code_to_ru(category: str, code: str) -> str:
    """Return Russian label for given code.

    If the code or category is unknown, the original code is returned.
    """
    return TRANSLATIONS.get(category, {}).get(code, code)


def ru_to_code(category: str, label: str) -> str:
    """Return internal code for given Russian label.

    If the label or category is unknown, the original label is returned.
    """
    mapping = TRANSLATIONS.get(category, {})
    for code, ru in mapping.items():
        if ru == label:
            return code
    return label
