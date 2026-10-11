from sten.config import read_hf_token


def test_read_hf_token_uses_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "from-env")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    assert read_hf_token() == "from-env"


def test_read_hf_token_prefers_project_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    project = tmp_path / ".hf_token"
    project.write_text("from-project\n", encoding="utf-8")
    monkeypatch.setattr("sten.config.project_hf_token_path", lambda: project)
    home = tmp_path / "home"
    cache = home / ".cache" / "huggingface"
    cache.mkdir(parents=True)
    (cache / "token").write_text("from-cache\n", encoding="utf-8")
    monkeypatch.setattr("sten.config.Path.home", lambda: home)
    assert read_hf_token() == "from-project"


def test_read_hf_token_skips_blank_env_and_reads_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "  ")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "sten.config.project_hf_token_path", lambda: tmp_path / "missing"
    )
    cached = tmp_path / ".cache" / "huggingface"
    cached.mkdir(parents=True)
    (cached / "token").write_text("from-cache\n", encoding="utf-8")
    monkeypatch.setattr("sten.config.Path.home", lambda: tmp_path)
    assert read_hf_token() == "from-cache"
