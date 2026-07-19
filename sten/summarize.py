from sten.chunking import chunk_segments
from sten.items import ITEMS_SCHEMA, SummaryItem, parse_items
from sten.llm import generate
from sten.transcribe import Segment

_ITEMS_INSTRUCTION = """Ты — секретарь совещания. Составь подробное саммари встречи в виде списка пунктов.
Каждый пункт — законченное утверждение на русском языке, понятное без чтения транскрипта.
Категории пунктов:
- decision — принятое решение;
- task — задача (по возможности укажи кто и к какому сроку);
- question — открытый вопрос или разногласие, оставшееся без решения;
- topic — обсуждённая тема, важный контекст.
Чем больше полезной информации сохранишь, тем лучше. Не выдумывай ничего, чего нет в тексте."""

_MAP_PROMPT = """Ниже фрагмент транскрипта совещания. Кратко, но без потери фактов перескажи его:
зафиксируй решения, задачи (кто/что/когда), обсуждённые темы и открытые вопросы. Пиши по-русски.

Фрагмент:
{chunk}"""

_REDUCE_PROMPT = _ITEMS_INSTRUCTION + """

Ниже — частичные саммари последовательных фрагментов одной встречи. Объедини их в единый список пунктов,
убери дубли и противоречия.

{partials}"""

_SINGLE_PROMPT = _ITEMS_INSTRUCTION + """

Транскрипт встречи:
{chunk}"""


def summarize(segments: list[Segment]) -> list[SummaryItem]:
    chunks = chunk_segments(segments)
    if not chunks:
        return []
    if len(chunks) == 1:
        raw = generate(_SINGLE_PROMPT.format(chunk=chunks[0]), schema=ITEMS_SCHEMA)
        return parse_items(raw)
    partials = [generate(_MAP_PROMPT.format(chunk=c)) for c in chunks]
    joined = "\n\n---\n\n".join(partials)
    raw = generate(_REDUCE_PROMPT.format(partials=joined), schema=ITEMS_SCHEMA)
    return parse_items(raw)
