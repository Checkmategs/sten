import pytest

from sten.items import SummaryItem
from sten.transcribe import Segment
from sten import summarize as summarize_mod
from sten.summarize import summarize


def seg(text: str) -> Segment:
    return Segment(0.0, 1.0, text)


def test_empty_transcript_returns_empty():
    assert summarize([]) == []


def test_single_chunk_one_llm_call(monkeypatch):
    calls = []

    def fake_generate(prompt, *, schema=None, model=None):
        calls.append(schema)
        return '{"items": [{"text": "Решили X", "category": "decision"}]}'

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    items = summarize([seg("Обсудили и решили X.")])
    assert items == [SummaryItem("Решили X", "decision")]
    assert len(calls) == 1
    assert calls[0] is not None  # schema передана


def test_multi_chunk_map_reduce(monkeypatch):
    calls = []

    def fake_generate(prompt, *, schema=None, model=None):
        calls.append(schema)
        if schema is None:
            return "частичное саммари"
        return '{"items": [{"text": "Итог", "category": "topic"}]}'

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    segs = [seg("а" * 4000), seg("б" * 4000)]  # два чанка при max_chars=6000
    items = summarize(segs)
    assert items == [SummaryItem("Итог", "topic")]
    # 2 map-вызова без схемы + 1 reduce со схемой
    assert calls.count(None) == 2
    assert len(calls) == 3


@pytest.mark.integration
def test_summarize_real_llm():
    segs = [
        seg("Коллеги, предлагаю перенести запуск на сентябрь."),
        seg("Согласен. Тогда Иван готовит план миграции к пятнице."),
        seg("Договорились, переносим на сентябрь."),
    ]
    items = summarize(segs)
    assert len(items) >= 1
    joined = " ".join(i.text.lower() for i in items)
    assert "сентябр" in joined
