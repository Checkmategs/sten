"""Expand a protocol item with more detail from the meeting transcript."""

from sten.llm import generate

_ELABORATE_PROMPT = """Ты — секретарь совещания. Дополни пункт протокола деталями из транскрипта.
Сохрани исходный смысл, но сделай формулировку конкретнее: кто, что, к какому сроку, какие условия и нюансы звучали.
2–4 предложения на русском. Без кавычек, без преамбулы («Вот уточнённый пункт» и т.п.).
Не выдумывай фактов, которых нет в транскрипте. Если деталей мало — чуть расширь ясность, не фантазируй.

Тема блока (если есть): {theme}

Текущий пункт:
{text}

Релевантный фрагмент транскрипта:
{transcript_excerpt}"""


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1]
    return text


def relevant_excerpt(transcript: str, item_text: str, *, max_chars: int = 4500) -> str:
    """Pick transcript windows that share words with the item (simple overlap score)."""
    transcript = transcript.strip()
    if not transcript:
        return ""
    if len(transcript) <= max_chars:
        return transcript

    words = {w.lower() for w in item_text.split() if len(w) > 3}
    if not words:
        return transcript[:max_chars]

    # Sliding windows by paragraphs / lines
    parts = [p.strip() for p in transcript.split("\n") if p.strip()]
    if not parts:
        return transcript[:max_chars]

    scored: list[tuple[int, str]] = []
    for part in parts:
        lower = part.lower()
        score = sum(1 for w in words if w in lower)
        if score:
            scored.append((score, part))
    scored.sort(key=lambda x: -x[0])

    chosen: list[str] = []
    total = 0
    for _score, part in scored:
        if total + len(part) + 1 > max_chars:
            continue
        chosen.append(part)
        total += len(part) + 1
        if total >= max_chars * 0.8:
            break
    if not chosen:
        return transcript[:max_chars]
    return "\n".join(chosen)


def elaborate_item(
    text: str, *, transcript_excerpt: str, theme: str = ""
) -> str:
    prompt = _ELABORATE_PROMPT.format(
        text=text,
        theme=theme or "—",
        transcript_excerpt=transcript_excerpt or "(фрагмент пуст — уточни только ясность формулировки)",
    )
    response = generate(prompt)
    return _strip_quotes(response.strip())
