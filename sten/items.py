import json
from dataclasses import dataclass

CATEGORIES = ("decision", "task", "topic", "question")

_CATEGORY_LABELS = {
    "decision": "Решение",
    "task": "Задача",
    "topic": "Контекст",
    "question": "Открытый вопрос",
}

ITEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "theme": {"type": "string"},
                },
                "required": ["text", "category", "theme"],
            },
        }
    },
    "required": ["items"],
}


@dataclass
class SummaryItem:
    text: str
    category: str
    theme: str = "Общее"


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category)


def parse_items(raw: str) -> list[SummaryItem]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM вернула невалидный JSON: {e}") from e
    items = []
    for entry in data.get("items", []):
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        category = entry.get("category")
        if category not in CATEGORIES:
            category = "topic"
        theme = str(entry.get("theme", "")).strip() or "Общее"
        items.append(SummaryItem(text, category, theme))
    return items
