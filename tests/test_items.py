import pytest

from sten.items import SummaryItem, parse_items


def test_parses_valid_items():
    raw = '{"items": [{"text": "Запуск в сентябре", "category": "decision"}]}'
    assert parse_items(raw) == [SummaryItem("Запуск в сентябре", "decision")]


def test_unknown_category_becomes_topic():
    raw = '{"items": [{"text": "Что-то", "category": "жалоба"}]}'
    assert parse_items(raw)[0].category == "topic"


def test_blank_text_dropped():
    raw = '{"items": [{"text": "  ", "category": "task"}, {"text": "Дело", "category": "task"}]}'
    assert [i.text for i in parse_items(raw)] == ["Дело"]


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_items("не json")
