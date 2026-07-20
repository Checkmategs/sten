from sten.elaborate import elaborate_item, relevant_excerpt


def test_relevant_excerpt_prefers_overlapping_lines():
    transcript = "\n".join(
        [
            "Погода сегодня хорошая.",
            "Решили перенести запуск виджета на сентябрь.",
            "Потом пили чай.",
            "Гоша сделает дизайн виджета к пятнице.",
        ]
    )
    out = relevant_excerpt(transcript, "виджет запуск сентябрь", max_chars=200)
    assert "виджета" in out
    assert "Погода" not in out


def test_elaborate_calls_llm(monkeypatch):
    from sten import elaborate as el

    def fake(prompt, **kwargs):
        assert "Дополни пункт" in prompt
        assert "виджет" in prompt
        return '  "Расширенный пункт про виджет."  '

    monkeypatch.setattr(el, "generate", fake)
    assert (
        el.elaborate_item("виджет", transcript_excerpt="про виджет говорили")
        == "Расширенный пункт про виджет."
    )
