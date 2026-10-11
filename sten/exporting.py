"""Transcript and meeting-brief downloads: TXT, SRT, DOCX."""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

from sten.report import MeetingReport, render_report_text
from sten.transcribe import Segment


def format_srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(float(seconds) * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(segments: list[Segment]) -> str:
    blocks: list[str] = []
    index = 1
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.speaker:
            text = f"{segment.speaker}: {text}"
        start = format_srt_timestamp(segment.start)
        end = format_srt_timestamp(max(segment.end, segment.start))
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
        index += 1
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _paragraph(text: str, *, bold: bool = False) -> str:
    safe = escape(text)
    run = f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{safe}</w:t></w:r>'
    if not bold:
        run = f'<w:r><w:t xml:space="preserve">{safe}</w:t></w:r>'
    return f"<w:p>{run}</w:p>"


def _docx_paragraphs(report: MeetingReport) -> list[str]:
    paragraphs: list[str] = []

    def heading(title: str) -> None:
        paragraphs.append(_paragraph(title, bold=True))

    def body(text: str) -> None:
        if text:
            paragraphs.append(_paragraph(text))

    if report.title:
        heading("Название встречи")
        body(report.title)
    if report.participants:
        heading("Участники")
        for person in report.participants:
            parts = [person.speaker, person.role, person.name]
            body(" — ".join(part for part in parts if part))
    if report.summary:
        heading("Краткое резюме")
        body(report.summary)
    if report.topics:
        heading("Ключевые темы")
        for topic in report.topics:
            if topic.title and topic.text:
                body(f"{topic.title} — {topic.text}")
            else:
                body(topic.title or topic.text)
    if report.decisions:
        heading("Принятые решения")
        for decision in report.decisions:
            line = decision.text
            if decision.initiator:
                line += f" — инициатор: {decision.initiator}"
            body(line)
    if report.tasks:
        heading("Задачи и договорённости")
        for task in report.tasks:
            line = task.text
            if task.assignee:
                line += f" — ответственный: {task.assignee}"
            if task.due:
                line += f" — срок: {task.due}"
            body(line)
    if report.outcome:
        heading("Итог встречи")
        body(report.outcome)
    if not paragraphs:
        body(render_report_text(report).strip() or "Нет обзора.")
    return paragraphs


def render_docx(report: MeetingReport) -> bytes:
    body = "".join(_docx_paragraphs(report))
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>
    </w:sectPr>
  </w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document.encode("utf-8"))
    return buffer.getvalue()
