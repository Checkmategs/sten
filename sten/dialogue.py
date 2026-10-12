"""IBIS dialogue map: questions, ideas, and the arguments for and against them."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sten.chunking import chunk_segments
from sten.llm import generate
from sten.report import blank_field, speaker_labels
from sten.transcribe import Segment

IDEA_STATUSES = ("adopted", "open", "rejected")
_MAX_QUESTIONS = 5
_MAX_IDEAS = 4
_MAX_ARGUMENTS = 3

DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "ideas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": list(IDEA_STATUSES),
                                },
                                "author": {"type": "string"},
                                "pros": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "text": {"type": "string"},
                                            "author": {"type": "string"},
                                        },
                                        "required": ["text", "author"],
                                    },
                                },
                                "cons": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "text": {"type": "string"},
                                            "author": {"type": "string"},
                                        },
                                        "required": ["text", "author"],
                                    },
                                },
                            },
                            "required": ["text", "status", "author", "pros", "cons"],
                        },
                    },
                },
                "required": ["text", "ideas"],
            },
        }
    },
    "required": ["questions"],
}

_INSTRUCTION = """Ты собираешь карту диалога совещания (IBIS): вопросы, идеи и доводы.
Верни только то, что прозвучало. Не выдумывай вопросы, идеи, доводы, авторов и исходы.
Если автор не назван — пустая строка. Не пиши «не указан» и прочерки.

- questions — не больше пяти. text — вопрос, который группа реально разбирала.
  Не превращай в вопрос тему без развилки и без доводов.
- ideas — ответы на этот вопрос, не больше четырёх. text — формулировка идеи.
- status: adopted — вариант приняли; rejected — явно отвергли; open — не закрыли.
- author — имя или метка спикера, иначе пустая строка.
- pros — доводы за идею, cons — доводы против. Не больше трёх каждого.
  Не приписывай довод, которого не было.
Пиши по-русски, коротко."""

_MAP_PROMPT = """Ниже фрагмент транскрипта. Выпиши только вопросы, по которым были разные
идеи или явные доводы за и против. Для каждого: вопрос, идеи, статус
(adopted, rejected или open), автор если назван, доводы за и против.
Не пересказывай фрагмент. Чего не было — не дописывай.

Фрагмент:
{chunk}"""

_REDUCE_PROMPT = (
    _INSTRUCTION
    + """

Ниже частичные карты одной встречи. Собери одну: убери повторы,
не добавляй вопросов и доводов, которых нет в картах.

{partials}"""
)

_SINGLE_PROMPT = _INSTRUCTION + """

Транскрипт:
{chunk}"""

_REDUCE_BUDGET_CHARS = 10000
_MAP_CTX = 4096
_DIALOGUE_CTX = 8192
_MAP_PREDICT = 768
_DIALOGUE_PREDICT = 2048

_STATUS_LABELS = {
    "adopted": "принята",
    "open": "открыта",
    "rejected": "отклонена",
}


@dataclass
class Argument:
    text: str = ""
    author: str = ""


@dataclass
class Idea:
    text: str = ""
    status: str = "open"
    author: str = ""
    pros: list[Argument] = field(default_factory=list)
    cons: list[Argument] = field(default_factory=list)


@dataclass
class Question:
    text: str = ""
    ideas: list[Idea] = field(default_factory=list)


@dataclass
class DialogueMap:
    questions: list[Question] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def dialogue_is_blank(dialogue: DialogueMap) -> bool:
    return not dialogue.questions


def _arguments(raw: object) -> list[Argument]:
    if not isinstance(raw, list):
        return []
    arguments: list[Argument] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = blank_field(entry.get("text"))
        if not text:
            continue
        arguments.append(Argument(text=text, author=blank_field(entry.get("author"))))
        if len(arguments) >= _MAX_ARGUMENTS:
            break
    return arguments


def parse_dialogue(raw: str) -> DialogueMap:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM вернула невалидный JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM вернула не объект")
    return dialogue_from_dict(data)


def dialogue_from_dict(data: dict) -> DialogueMap:
    questions: list[Question] = []
    for entry in data.get("questions") or []:
        if not isinstance(entry, dict):
            continue
        text = blank_field(entry.get("text"))
        if not text:
            continue
        ideas: list[Idea] = []
        for idea_raw in entry.get("ideas") or []:
            if not isinstance(idea_raw, dict):
                continue
            idea_text = blank_field(idea_raw.get("text"))
            if not idea_text:
                continue
            status = str(idea_raw.get("status") or "").strip()
            if status not in IDEA_STATUSES:
                status = "open"
            ideas.append(
                Idea(
                    text=idea_text,
                    status=status,
                    author=blank_field(idea_raw.get("author")),
                    pros=_arguments(idea_raw.get("pros")),
                    cons=_arguments(idea_raw.get("cons")),
                )
            )
            if len(ideas) >= _MAX_IDEAS:
                break
        questions.append(Question(text=text, ideas=ideas))
        if len(questions) >= _MAX_QUESTIONS:
            break
    return DialogueMap(questions=questions)


def render_dialogue_text(dialogue: DialogueMap) -> str:
    """Plain text of the map for the clipboard."""
    blocks: list[str] = []
    for question in dialogue.questions:
        lines = [f"? {question.text}"]
        for idea in question.ideas:
            author = f", {idea.author}" if idea.author else ""
            lines.append(f"  → {idea.text} ({_STATUS_LABELS[idea.status]}{author})")
            for pro in idea.pros:
                who = f" — {pro.author}" if pro.author else ""
                lines.append(f"    + {pro.text}{who}")
            for con in idea.cons:
                who = f" — {con.author}" if con.author else ""
                lines.append(f"    − {con.text}{who}")
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks).strip()
    return text + ("\n" if text else "")


def retarget_dialogue(data: dict, old: str, new: str) -> bool:
    """Rename a speaker inside a stored map. Returns whether a map was present."""
    dialogue = data.get("dialogue")
    if not isinstance(dialogue, dict):
        return False

    def swap(node: dict, key: str) -> None:
        if node.get(key) == old:
            node[key] = new

    for question in dialogue.get("questions") or []:
        if not isinstance(question, dict):
            continue
        for idea in question.get("ideas") or []:
            if not isinstance(idea, dict):
                continue
            swap(idea, "author")
            for key in ("pros", "cons"):
                for argument in idea.get(key) or []:
                    if isinstance(argument, dict):
                        swap(argument, "author")
    return True


def save_dialogue(out_dir: Path, dialogue: DialogueMap) -> None:
    path = out_dir / "summary.json"
    data: dict = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    data["dialogue"] = dialogue.to_dict()
    data.pop("dialogue_error", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_dialogue_error(out_dir: Path, message: str) -> None:
    path = out_dir / "summary.json"
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data["dialogue_error"] = message[:500]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    "Верни один короткий объект: не больше трёх вопросов и трёх идей на вопрос. "
    "Каждую строку закрой."
)


def _generate_dialogue(prompt: str) -> DialogueMap:
    raw = generate(
        prompt,
        schema=DIALOGUE_SCHEMA,
        num_ctx=_DIALOGUE_CTX,
        num_predict=_DIALOGUE_PREDICT,
    )
    try:
        return parse_dialogue(raw)
    except ValueError:
        raw = generate(
            prompt + _RETRY_NOTE,
            schema=DIALOGUE_SCHEMA,
            num_ctx=_DIALOGUE_CTX,
            num_predict=_DIALOGUE_PREDICT,
        )
        return parse_dialogue(raw)


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


def build_dialogue(
    segments: list[Segment],
    on_progress: Callable[[float], None] | None = None,
) -> DialogueMap:
    chunks = chunk_segments(_labeled_segments(segments))
    if not chunks:
        return DialogueMap()

    def tick(fraction: float) -> None:
        if on_progress is not None:
            on_progress(fraction)

    labels = speaker_labels(segments)
    hint = ""
    if labels:
        hint = "Метки спикеров: " + ", ".join(labels) + ".\n"

    if len(chunks) == 1:
        tick(0.0)
        dialogue = _generate_dialogue(hint + _SINGLE_PROMPT.format(chunk=chunks[0]))
        tick(1.0)
        return dialogue

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
                    "Сожми карты в более короткий список вопросов и доводов, "
                    "без новых деталей.\n\n" + batch,
                    num_ctx=_DIALOGUE_CTX,
                    num_predict=_MAP_PREDICT,
                )
            )
        partials = next_partials
    tick(n_map / (n_map + 1))
    dialogue = _generate_dialogue(
        hint + _REDUCE_PROMPT.format(partials="\n\n---\n\n".join(partials))
    )
    tick(1.0)
    return dialogue
