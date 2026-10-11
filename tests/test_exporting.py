import zipfile
from io import BytesIO

from sten.exporting import render_docx, render_srt
from sten.report import parse_report
from sten.transcribe import Segment


def test_render_srt_uses_segment_times_and_speakers():
    text = render_srt(
        [
            Segment(0.0, 1.5, "Привет", "Спикер 1"),
            Segment(65.2, 66.0, "Дальше", None),
        ]
    )
    assert text.startswith("1\n00:00:00,000 --> 00:00:01,500\nСпикер 1: Привет\n")
    assert "2\n00:01:05,200 --> 00:01:06,000\nДальше\n" in text


def test_render_docx_contains_report_sections():
    report = parse_report(
        """
        {
          "title": "Мониторинг",
          "summary": "Кратко",
          "outcome": "Макет",
          "participants": [{"speaker": "Спикер 1", "role": "Роль", "name": ""}],
          "topics": [],
          "decisions": [{"text": "Показать расход", "initiator": ""}],
          "tasks": [{"text": "Проверить память", "assignee": "", "due": ""}]
        }
        """
    )
    blob = render_docx(report)
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "Мониторинг" in document
    assert "Краткое резюме" in document
    assert "Показать расход" in document
    assert "инициатор" not in document
    assert "ответственный" not in document
