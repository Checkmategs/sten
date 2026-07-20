import json
from pathlib import Path

from sten.items import SummaryItem
from sten.pipeline import render_markdown, write_outputs
from sten.transcribe import Segment


def test_render_markdown_groups_by_theme():
    items = [
        SummaryItem("Запуск в сентябре", "decision", "Релиз"),
        SummaryItem("Иван готовит план к пятнице", "task", "Релиз"),
        SummaryItem("Бюджет не согласован", "question", "Бюджет"),
    ]
    md = render_markdown(items)
    assert md.index("## Релиз") < md.index("## Бюджет")
    assert "**Решение:** Запуск в сентябре" in md
    assert "**Задача:** Иван готовит план к пятнице" in md
    assert "**Открытый вопрос:** Бюджет не согласован" in md


def test_render_markdown_empty():
    assert "нет пунктов" in render_markdown([]).lower()


def test_write_outputs_creates_all_files(tmp_path: Path):
    segments = [Segment(0.0, 1.5, "Привет всем.")]
    items = [SummaryItem("Поздоровались", "topic", "Старт")]
    write_outputs(tmp_path, segments, items)

    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "Привет всем."
    tj = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert tj == [{"start": 0.0, "end": 1.5, "text": "Привет всем."}]
    sj = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert sj == {
        "items": [
            {"text": "Поздоровались", "category": "topic", "theme": "Старт"}
        ]
    }
    assert "Поздоровались" in (tmp_path / "summary.md").read_text(encoding="utf-8")
