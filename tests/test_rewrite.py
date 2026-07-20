from sten import rewrite as rewrite_mod
from sten.rewrite import rewrite_item


def test_rewrite_calls_llm_and_strips(monkeypatch):
    def fake(prompt, **kwargs):
        assert "Возражение" in prompt
        assert "бюджет" in prompt
        return '  "Новая формулировка"  '

    monkeypatch.setattr(rewrite_mod, "generate", fake)
    assert rewrite_item("Старое", "бюджет не согласован") == "Новая формулировка"
