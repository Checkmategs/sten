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

    def fake_generate(prompt, *, schema=None, model=None, **kwargs):
        calls.append(schema)
        return '{"items": [{"text": "Решили X", "category": "decision"}]}'

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    items = summarize([seg("Обсудили и решили X.")])
    assert items == [SummaryItem("Решили X", "decision")]
    assert len(calls) == 1
    assert calls[0] is not None  # schema передана


def test_multi_chunk_map_reduce(monkeypatch):
    calls = []

    def fake_generate(prompt, *, schema=None, model=None, **kwargs):
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


def test_oversized_partials_compacted_before_reduce(monkeypatch):
    calls = []  # (prompt, schema, num_ctx)

    def fake_generate(prompt, *, schema=None, model=None, num_ctx=8192):
        calls.append((prompt, schema, num_ctx))
        if schema is not None:
            return '{"items": [{"text": "Итог", "category": "topic"}]}'
        if "Фрагмент:" in prompt:  # map-вызов
            return "с" * 15000
        return "объединённое частичное саммари"  # combine-вызов

    monkeypatch.setattr(summarize_mod, "generate", fake_generate)
    segs = [seg("а" * 4000), seg("б" * 4000), seg("в" * 4000)]  # три чанка
    items = summarize(segs)
    assert items == [SummaryItem("Итог", "topic")]

    map_calls = [c for c in calls if c[1] is None and "Фрагмент:" in c[0]]
    combine_calls = [c for c in calls if c[1] is None and "Фрагмент:" not in c[0]]
    schema_calls = [c for c in calls if c[1] is not None]
    assert len(map_calls) == 3
    assert len(combine_calls) >= 1  # промежуточное объединение произошло
    assert combine_calls[0][2] == 16384
    assert len(schema_calls) == 1  # финальный reduce со схемой
    final_prompt, _, final_num_ctx = schema_calls[0]
    assert final_num_ctx == 16384
    assert len(final_prompt) <= summarize_mod._REDUCE_BUDGET_CHARS + len(
        summarize_mod._REDUCE_PROMPT
    )


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
