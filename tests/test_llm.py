import pytest

from sten.items import ITEMS_SCHEMA, parse_items
from sten.llm import generate


@pytest.mark.integration
def test_generate_plain_text():
    out = generate("Ответь одним словом: столица Франции?")
    assert "париж" in out.lower()


@pytest.mark.integration
def test_generate_with_schema_returns_parseable_items():
    out = generate(
        "Составь список из одного пункта саммари: команда решила перенести релиз на май. "
        "Категории: decision, task, topic, question.",
        schema=ITEMS_SCHEMA,
    )
    items = parse_items(out)
    assert len(items) >= 1
