import pytest

from sten.items import ITEMS_SCHEMA, parse_items
from sten.llm import generate


def test_generate_disables_thinking_and_caps_tokens(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "ок"}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("sten.llm.httpx.post", fake_post)
    assert generate("привет", num_predict=128) == "ок"
    assert captured["json"]["think"] is False
    assert captured["json"]["options"]["num_predict"] == 128
    assert captured["json"]["options"]["num_ctx"] == 8192


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
