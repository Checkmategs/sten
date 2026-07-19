import json
from dataclasses import dataclass

CATEGORIES = ("decision", "task", "topic", "question")

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
                },
                "required": ["text", "category"],
            },
        }
    },
    "required": ["items"],
}


@dataclass
class SummaryItem:
    text: str
    category: str


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
        items.append(SummaryItem(text, category))
    return items
