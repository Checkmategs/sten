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

_COMBINE_PROMPT = """Ниже — частичные саммари последовательных фрагментов одной встречи. Объедини их в одно связное саммари,
сохранив все решения, задачи (кто/что/когда), темы и открытые вопросы. Не выдумывай ничего нового. Пиши по-русски.

{partials}"""

# Безопасный размер промпта для num_ctx=16384: кириллица ~2+ символа на токен,
# плюс запас на инструкции и ответ модели.
_REDUCE_BUDGET_CHARS = 20000

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
    while len("\n\n---\n\n".join(partials)) > _REDUCE_BUDGET_CHARS:
        partials = [
            generate(_COMBINE_PROMPT.format(partials=batch), num_ctx=16384)
            for batch in _batch_partials(partials)
        ]
    joined = "\n\n---\n\n".join(partials)
    raw = generate(_REDUCE_PROMPT.format(partials=joined), schema=ITEMS_SCHEMA, num_ctx=16384)
    return parse_items(raw)


def _batch_partials(partials: list[str]) -> list[str]:
    """Жадно группирует последовательные частичные саммари в батчи,
    чтобы объединённый текст каждого батча не превышал _REDUCE_BUDGET_CHARS.
    Отдельное саммари больше бюджета образует собственный батч."""
    sep = "\n\n---\n\n"
    batches: list[str] = []
    current: list[str] = []
    for p in partials:
        if current and len(sep.join([*current, p])) > _REDUCE_BUDGET_CHARS:
            batches.append(sep.join(current))
            current = []
        current.append(p)
    if current:
        batches.append(sep.join(current))
    return batches
