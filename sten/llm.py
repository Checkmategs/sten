import httpx

from sten.config import OLLAMA_MODEL, OLLAMA_URL


def generate(
    prompt: str, *, schema: dict | None = None, model: str = OLLAMA_MODEL, num_ctx: int = 8192
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
    }
    if schema is not None:
        payload["format"] = schema
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=600.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Ollama недоступна ({OLLAMA_URL}): {e}") from e
    return resp.json()["response"]
