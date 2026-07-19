import json
from pathlib import Path

from sten.items import SummaryItem
from sten.pipeline import render_markdown, write_outputs
from sten.transcribe import Segment


def test_render_markdown_groups_by_category():
    items = [
        SummaryItem("Запуск в сентябре", "decision"),
        SummaryItem("Иван готовит план к пятнице", "task"),
        SummaryItem("Бюджет не согласован", "question"),
    ]
    md = render_markdown(items)
    assert md.index("## Решения") < md.index("## Задачи") < md.index("## Открытые вопросы")
    assert "## Темы" not in md  # пустая категория опущена
    assert "- Запуск в сентябре" in md


def test_render_markdown_empty():
    assert "нет пунктов" in render_markdown([]).lower()


def test_write_outputs_creates_all_files(tmp_path: Path):
    segments = [Segment(0.0, 1.5, "Привет всем.")]
    items = [SummaryItem("Поздоровались", "topic")]
    write_outputs(tmp_path, segments, items)

    assert (tmp_path / "transcript.txt").read_text() == "Привет всем."
    tj = json.loads((tmp_path / "transcript.json").read_text())
    assert tj == [{"start": 0.0, "end": 1.5, "text": "Привет всем."}]
    sj = json.loads((tmp_path / "summary.json").read_text())
    assert sj == {"items": [{"text": "Поздоровались", "category": "topic"}]}
    assert "Поздоровались" in (tmp_path / "summary.md").read_text()
