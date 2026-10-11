from sten.report import (
    MeetingReport,
    build_report,
    parse_report,
    render_report_text,
    report_to_items,
)
from sten.transcribe import Segment
from sten import report as report_mod


def _sample() -> MeetingReport:
    return parse_report(
        """
        {
          "title": "Инструмент мониторинга",
          "summary": "Договорились начать с информирования.",
          "outcome": "Следующий шаг — макет.",
          "participants": [
            {"speaker": "Спикер 1", "role": "Руководитель проекта", "name": "Сергей"},
            {"speaker": "Спикер 2", "role": "не указан", "name": "—"}
          ],
          "topics": [{"title": "Виджет", "text": "Отдельный виджет в хром-баре."}],
          "decisions": [{"text": "Сначала показать расход", "initiator": "Сергей"}],
          "tasks": [
            {"text": "Проверить выгрузку в память", "assignee": "не указан", "due": ""}
          ]
        }
        """
    )


def test_parse_report_drops_unknown_placeholders():
    report = _sample()
    assert report.title == "Инструмент мониторинга"
    assert report.participants[1].role == ""
    assert report.participants[1].name == ""
    assert report.tasks[0].assignee == ""
    assert report.tasks[0].due == ""
    assert report.decisions[0].initiator == "Сергей"


def test_render_report_text_omits_empty_assignee_and_due():
    text = render_report_text(_sample())
    assert "Название встречи\nИнструмент мониторинга" in text
    assert "Спикер 1 — Руководитель проекта — Сергей" in text
    assert "Спикер 2" in text
    assert "не указан" not in text
    assert "инициатор: Сергей" in text
    assert "ответственный" not in text
    assert "срок" not in text
    assert "Итог встречи\nСледующий шаг — макет." in text


def test_report_to_items_keeps_categories():
    items = report_to_items(_sample())
    assert [(item.category, item.theme) for item in items] == [
        ("topic", "Виджет"),
        ("decision", "Решения"),
        ("task", "Задачи"),
    ]


def test_build_report_empty_skips_llm():
    assert build_report([]) == MeetingReport()


def test_build_report_single_chunk(monkeypatch):
    def fake_generate(prompt, *, schema=None, model=None, **kwargs):
        assert schema is not None
        assert "Спикер 1" in prompt
        assert kwargs["num_ctx"] == report_mod._REPORT_CTX
        assert kwargs["num_predict"] == report_mod._REPORT_PREDICT
        return (
            '{"title":"Тема","summary":"Кратко","outcome":"",'
            '"participants":[{"speaker":"Спикер 1","role":"","name":"Анна"}],'
            '"topics":[],"decisions":[],"tasks":[]}'
        )

    monkeypatch.setattr(report_mod, "generate", fake_generate)
    report = build_report([Segment(0.0, 1.0, "Анна на связи", speaker="Спикер 1")])
    assert report.title == "Тема"
    assert report.participants[0].name == "Анна"
    assert report.participants[0].role == ""
