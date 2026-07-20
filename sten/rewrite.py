from sten.llm import generate

_REWRITE_PROMPT = """Ты — секретарь совещания. Переформулируй пункт протокола с учётом возражения участника.
Сохрани смысл договорённости, убери двусмысленность. Один абзац на русском, без кавычек и преамбулы.
Если возражение требует исключить пункт — верни пустую строку.

Текущий пункт:
{text}

Возражение:
{objection}

Фрагмент транскрипта (может быть пустым):
{transcript_excerpt}"""


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1]
    return text


def rewrite_item(text: str, objection: str, *, transcript_excerpt: str = "") -> str:
    prompt = _REWRITE_PROMPT.format(
        text=text,
        objection=objection,
        transcript_excerpt=transcript_excerpt,
    )
    response = generate(prompt)
    return _strip_quotes(response.strip())
