from sten.chunking import chunk_segments
from sten.items import ITEMS_SCHEMA, SummaryItem, parse_items
from sten.llm import generate
from sten.transcribe import Segment

_ITEMS_INSTRUCTION = """Ты — аналитик совещания, не стенографист и не хроникёр.
Составь ИТОГОВЫЙ протокол: сжатые выводы, а не пересказ «что говорили по ходу встречи».

Правила:
- Синтезируй: однородные реплики и уточнения → один сильный пункт.
- Не пиши «обсудили…», «говорили о…», «рассматривали…». Пиши итог: «Решили…», «Сделать…», «Открыто: …».
- На длинную встречу ориентир 12–30 пунктов всего, не десятки дублей.
- category:
  - decision — принятое решение / договорённость;
  - task — конкретное действие (кто / что / срок, если звучало);
  - question — нерешённый вопрос или разногласие;
  - topic — только важный контекст, без которого непонятны решения (используй редко).
- theme — короткая тема-кластер на русском (2–5 слов). Одинаковая формулировка theme для связанных пунктов.
  Примеры: «Виджеты активности», «Профиль пользователя», «Задачи и чек-листы», «Админка организаций».
Не выдумывай ничего, чего нет в тексте."""

_MAP_PROMPT = """Ниже фрагмент транскрипта. Выпиши только существенные итоги фрагмента (решения, задачи, открытые вопросы).
Без хронологического пересказа. Компактно, по-русски, маркированным списком.

Фрагмент:
{chunk}"""

_REDUCE_PROMPT = _ITEMS_INSTRUCTION + """

Ниже — частичные выжимки одной встречи. Собери единый протокол:
объедини дубли, сформулируй итоговые выводы, разложи по theme и category.

{partials}"""

_COMBINE_PROMPT = """Ниже — частичные выжимки одной встречи. Объедини в более короткую выжимку:
оставь решения, задачи и открытые вопросы; убери повторы и болтовню. По-русски.

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
