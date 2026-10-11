"""Structured meeting brief: title, people, topics, decisions, tasks, outcome."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from sten.chunking import chunk_segments
from sten.items import SummaryItem
from sten.llm import generate
from sten.transcribe import Segment

_BLANK_MARKERS = {
    "",
    "не указан",
    "не указано",
    "не указана",
    "неизвестно",
    "нет данных",
    "—",
    "-",
    "–",
    "n/a",
    "none",
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "outcome": {"type": "string"},
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "role": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["speaker", "role", "name"],
            },
        },
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["title", "text"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "initiator": {"type": "string"},
                },
                "required": ["text", "initiator"],
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "assignee": {"type": "string"},
                    "due": {"type": "string"},
                },
                "required": ["text", "assignee", "due"],
            },
        },
    },
    "required": [
        "title",
        "summary",
        "outcome",
        "participants",
        "topics",
        "decisions",
        "tasks",
    ],
}

_INSTRUCTION = """Ты составляешь краткий обзор совещания по расшифровке, не стенограмму.
Верни только факты, которые есть в тексте. Не выдумывай имена, роли, сроки и ответственных.
Если имя, роль, инициатор, ответственный или срок не названы — оставь пустую строку.
Не пиши «не указан», «неизвестно» и прочерки.

- title — короткое название темы встречи, не имя файла.
- summary — два-три предложения: о чём договорились.
- outcome — одно предложение: итог и следующий шаг.
- participants — по одному на каждую метку спикера из текста. speaker — точная метка
  (например «Спикер 1»). role и name — только если они прозвучали.
- topics — не больше пяти. Короткий title и одно предложение text.
- decisions — только явно принятые. initiator — имя или метка спикера, либо пустая строка.
- tasks — только конкретные поручения. assignee и due — только если прозвучали, иначе пустые строки.
Пиши по-русски, коротко."""

_MAP_PROMPT = """Ниже фрагмент транскрипта. Выпиши только факты для короткого обзора:
название темы, участники (метка, роль и имя — только если названы),
резюме в одном предложении, до трёх тем, решения, задачи.
Не пересказывай фрагмент. Не больше десяти коротких пунктов. Чего не было — не дописывай.

Фрагмент:
{chunk}"""

_REDUCE_PROMPT = (
    _INSTRUCTION
    + """

Ниже частичные выжимки одной встречи. Собери один обзор: убери повторы,
не добавляй фактов, которых нет в выжимках.

{partials}"""
)

_SINGLE_PROMPT = _INSTRUCTION + """

Транскрипт:
{chunk}"""

# Выжимки короткие, поэтому сборка держится в 8192, а не в 16384.
_REDUCE_BUDGET_CHARS = 10000
_MAP_CTX = 4096
_REPORT_CTX = 8192
# Короткий список фактов и компактный JSON. Длинный лимит заставлял модель писать лишнее.
_MAP_PREDICT = 512
# 1024 токена qwen3.5:9b не хватало, чтобы закрыть JSON (обрыв около 1000 токенов).
_REPORT_PREDICT = 2048


@dataclass
class Participant:
    speaker: str = ""
    role: str = ""
    name: str = ""


@dataclass
class Topic:
    title: str = ""
    text: str = ""


@dataclass
class Decision:
    text: str = ""
    initiator: str = ""


@dataclass
class Task:
    text: str = ""
    assignee: str = ""
    due: str = ""


@dataclass
class MeetingReport:
    title: str = ""
    summary: str = ""
    outcome: str = ""
    participants: list[Participant] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def blank_field(value: object) -> str:
    """Return stripped text, or '' when the model used a placeholder for unknown."""
    text = str(value or "").strip()
    if text.casefold() in _BLANK_MARKERS:
        return ""
    return text


def report_is_blank(report: MeetingReport) -> bool:
    return not any(
        (
            report.title,
            report.summary,
            report.outcome,
            report.participants,
            report.topics,
            report.decisions,
            report.tasks,
        )
    )


def parse_report(raw: str) -> MeetingReport:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM вернула невалидный JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM вернула не объект")

    participants: list[Participant] = []
    for entry in data.get("participants") or []:
        if not isinstance(entry, dict):
            continue
        person = Participant(
            speaker=blank_field(entry.get("speaker")),
            role=blank_field(entry.get("role")),
            name=blank_field(entry.get("name")),
        )
        if person.speaker or person.role or person.name:
            participants.append(person)

    topics: list[Topic] = []
    for entry in data.get("topics") or []:
        if not isinstance(entry, dict):
            continue
        topic = Topic(
            title=blank_field(entry.get("title")),
            text=blank_field(entry.get("text")),
        )
        if topic.title or topic.text:
            topics.append(topic)

    decisions: list[Decision] = []
    for entry in data.get("decisions") or []:
        if not isinstance(entry, dict):
            continue
        text = blank_field(entry.get("text"))
        if not text:
            continue
        decisions.append(Decision(text=text, initiator=blank_field(entry.get("initiator"))))

    tasks: list[Task] = []
    for entry in data.get("tasks") or []:
        if not isinstance(entry, dict):
            continue
        text = blank_field(entry.get("text"))
        if not text:
            continue
        tasks.append(
            Task(
                text=text,
                assignee=blank_field(entry.get("assignee")),
                due=blank_field(entry.get("due")),
            )
        )

    return MeetingReport(
        title=blank_field(data.get("title")),
        summary=blank_field(data.get("summary")),
        outcome=blank_field(data.get("outcome")),
        participants=participants,
        topics=topics,
        decisions=decisions,
        tasks=tasks,
    )


def report_from_dict(data: dict) -> MeetingReport:
    return parse_report(json.dumps(data, ensure_ascii=False))


def report_to_items(report: MeetingReport) -> list[SummaryItem]:
    """Flat protocol rows kept for the existing items table."""
    items: list[SummaryItem] = []
    for topic in report.topics:
        body = topic.text or topic.title
        if not body:
            continue
        if topic.title and topic.text:
            body = f"{topic.title}. {topic.text}"
        items.append(SummaryItem(body, "topic", topic.title or "Общее"))
    for decision in report.decisions:
        items.append(SummaryItem(decision.text, "decision", "Решения"))
    for task in report.tasks:
        items.append(SummaryItem(task.text, "task", "Задачи"))
    return items


def _participant_line(person: Participant) -> str:
    parts = [person.speaker, person.role, person.name]
    return " — ".join(part for part in parts if part)


def _decision_line(decision: Decision) -> str:
    if decision.initiator:
        return f"{decision.text} — инициатор: {decision.initiator}"
    return decision.text


def _task_line(task: Task) -> str:
    line = task.text
    if task.assignee:
        line += f" — ответственный: {task.assignee}"
    if task.due:
        line += f" — срок: {task.due}"
    return line


def render_report_text(report: MeetingReport) -> str:
    """Plain text of the brief for copy and summary.md."""
    blocks: list[str] = []

    def add(heading: str, lines: list[str]) -> None:
        if not lines:
            return
        blocks.append(heading)
        blocks.extend(lines)

    add("Название встречи", [report.title] if report.title else [])
    add("Участники", [_participant_line(p) for p in report.participants])
    add("Краткое резюме", [report.summary] if report.summary else [])
    add(
        "Ключевые темы",
        [
            f"– {topic.title} — {topic.text}" if topic.title and topic.text
            else f"– {topic.title or topic.text}"
            for topic in report.topics
        ],
    )
    add("Принятые решения", [f"– {_decision_line(d)}" for d in report.decisions])
    add("Задачи и договорённости", [f"– {_task_line(t)}" for t in report.tasks])
    add("Итог встречи", [report.outcome] if report.outcome else [])
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def speaker_labels(segments: list[Segment]) -> list[str]:
    labels: list[str] = []
    for segment in segments:
        name = (segment.speaker or "").strip()
        if name and name not in labels:
            labels.append(name)
    return labels


def _labeled_segments(segments: list[Segment]) -> list[Segment]:
    labeled: list[Segment] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.speaker:
            text = f"{segment.speaker}: {text}"
        labeled.append(Segment(segment.start, segment.end, text, segment.speaker))
    return labeled


_RETRY_NOTE = (
    "\n\nПредыдущий ответ оборвался и не был законченным JSON. "
    "Верни один короткий объект: не больше трёх тем, пяти решений и пяти задач. "
    "Каждую строку закрой."
)


def _generate_report(prompt: str) -> MeetingReport:
    raw = generate(
        prompt,
        schema=REPORT_SCHEMA,
        num_ctx=_REPORT_CTX,
        num_predict=_REPORT_PREDICT,
    )
    try:
        return parse_report(raw)
    except ValueError:
        raw = generate(
            prompt + _RETRY_NOTE,
            schema=REPORT_SCHEMA,
            num_ctx=_REPORT_CTX,
            num_predict=_REPORT_PREDICT,
        )
        return parse_report(raw)


def build_report(
    segments: list[Segment],
    on_progress: Callable[[float], None] | None = None,
) -> MeetingReport:
    chunks = chunk_segments(_labeled_segments(segments))
    if not chunks:
        return MeetingReport()

    def tick(fraction: float) -> None:
        if on_progress is not None:
            on_progress(fraction)

    labels = speaker_labels(segments)
    hint = ""
    if labels:
        hint = "Метки спикеров: " + ", ".join(labels) + ".\n"

    if len(chunks) == 1:
        tick(0.0)
        report = _generate_report(hint + _SINGLE_PROMPT.format(chunk=chunks[0]))
        tick(1.0)
        return report

    n_map = len(chunks)
    partials: list[str] = []
    for index, chunk in enumerate(chunks):
        tick(index / (n_map + 1))
        partials.append(
            generate(
                _MAP_PROMPT.format(chunk=chunk),
                num_ctx=_MAP_CTX,
                num_predict=_MAP_PREDICT,
            )
        )
    while len("\n\n---\n\n".join(partials)) > _REDUCE_BUDGET_CHARS:
        next_partials: list[str] = []
        batches = _batch_partials(partials)
        for index, batch in enumerate(batches):
            tick(min(0.98, (n_map + index + 1) / (n_map + len(batches) + 1)))
            next_partials.append(
                generate(
                    "Сожми выжимки в более короткий список фактов, без новых деталей.\n\n"
                    + batch,
                    num_ctx=_REPORT_CTX,
                    num_predict=_MAP_PREDICT,
                )
            )
        partials = next_partials
    tick(n_map / (n_map + 1))
    report = _generate_report(
        hint + _REDUCE_PROMPT.format(partials="\n\n---\n\n".join(partials))
    )
    tick(1.0)
    return report


def _batch_partials(partials: list[str]) -> list[str]:
    sep = "\n\n---\n\n"
    batches: list[str] = []
    current: list[str] = []
    for partial in partials:
        if current and len(sep.join([*current, partial])) > _REDUCE_BUDGET_CHARS:
            batches.append(sep.join(current))
            current = []
        current.append(partial)
    if current:
        batches.append(sep.join(current))
    return batches
