import httpx

from sten.config import OLLAMA_MODEL, OLLAMA_URL


def generate(
    prompt: str,
    *,
    schema: dict | None = None,
    model: str = OLLAMA_MODEL,
    num_ctx: int = 8192,
    num_predict: int | None = None,
) -> str:
    options: dict = {"temperature": 0.2, "num_ctx": num_ctx}
    if num_predict is not None:
        options["num_predict"] = num_predict
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # qwen3 пишет длинный скрытый ход рассуждений; для обзора он только тормозит ответ.
        "think": False,
        "options": options,
    }
    if schema is not None:
        payload["format"] = schema
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=600.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Ollama недоступна ({OLLAMA_URL}): {e}") from e
    return resp.json()["response"]
