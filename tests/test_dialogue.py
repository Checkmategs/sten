import json
from pathlib import Path

from sten.dialogue import (
    DialogueMap,
    build_dialogue,
    dialogue_from_dict,
    parse_dialogue,
    render_dialogue_text,
    retarget_dialogue,
)
from sten.transcribe import Segment
from sten import dialogue as dialogue_mod


def _sample() -> DialogueMap:
    return parse_dialogue(
        """
        {
          "questions": [
            {
              "text": "Где показывать расход?",
              "ideas": [
                {
                  "text": "Отдельный виджет",
                  "status": "adopted",
                  "author": "Сергей",
                  "pros": [{"text": "Видно сразу", "author": "Спикер 2"}],
                  "cons": [{"text": "Занимает место", "author": "не указан"}]
                },
                {
                  "text": "Строка в отчёте",
                  "status": "rejected",
                  "author": "",
                  "pros": [],
                  "cons": [{"text": "Легко пропустить", "author": ""}]
                }
              ]
            }
          ]
        }
        """
    )


def test_parse_dialogue_drops_placeholders_and_unknown_status():
    dialogue = dialogue_from_dict(
        {
            "questions": [
                {
                    "text": "Как назвать?",
                    "ideas": [
                        {
                            "text": "Коротко",
                            "status": "maybe",
                            "author": "—",
                            "pros": [{"text": "—", "author": ""}],
                            "cons": [],
                        }
                    ],
                },
                {"text": "", "ideas": []},
            ]
        }
    )
    assert len(dialogue.questions) == 1
    idea = dialogue.questions[0].ideas[0]
    assert idea.status == "open"
    assert idea.author == ""
    assert idea.pros == []


def test_render_dialogue_text_marks_question_idea_and_arguments():
    text = render_dialogue_text(_sample())
    assert "? Где показывать расход?" in text
    assert "→ Отдельный виджет (принята, Сергей)" in text
    assert "+ Видно сразу — Спикер 2" in text
    assert "− Занимает место" in text
    assert "не указан" not in text
    assert "→ Строка в отчёте (отклонена)" in text


def test_retarget_dialogue_renames_authors():
    data = {"dialogue": _sample().to_dict()}
    assert retarget_dialogue(data, "Спикер 2", "Анна") is True
    pro = data["dialogue"]["questions"][0]["ideas"][0]["pros"][0]
    assert pro["author"] == "Анна"
    assert retarget_dialogue({}, "А", "Б") is False


def test_build_stored_dialogue_keeps_the_map(tmp_path: Path, monkeypatch):
    from sten import db
    from sten.api.processing import build_stored_dialogue
    from sten.dialogue import Idea, Question

    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    out = tmp_path / "meetings" / "7"
    out.mkdir(parents=True)
    (out / "transcript.json").write_text(
        '[{"start":0,"end":1,"text":"Да","speaker":"Спикер 1"}]',
        encoding="utf-8",
    )

    def fake(segments, on_progress=None):
        return DialogueMap(
            questions=[Question(text="Идём?", ideas=[Idea(text="Да", status="adopted")])]
        )

    monkeypatch.setattr("sten.dialogue.build_dialogue", fake)
    build_stored_dialogue(7)
    stored = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert stored["dialogue"]["questions"][0]["ideas"][0]["status"] == "adopted"
    assert "dialogue_error" not in stored


def test_build_stored_dialogue_records_model_errors(tmp_path: Path, monkeypatch):
    from sten import db
    from sten.api.processing import build_stored_dialogue

    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    out = tmp_path / "meetings" / "7"
    out.mkdir(parents=True)
    (out / "transcript.json").write_text("[]", encoding="utf-8")

    def fake(segments, on_progress=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("sten.dialogue.build_dialogue", fake)
    build_stored_dialogue(7)
    stored = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert "ollama down" in stored["dialogue_error"]


def test_build_dialogue_empty_skips_llm():
    assert build_dialogue([]) == DialogueMap()


def test_build_dialogue_single_chunk(monkeypatch):
    def fake_generate(prompt, *, schema=None, model=None, **kwargs):
        assert schema is not None
        assert "Спикер 1" in prompt
        assert kwargs["num_ctx"] == dialogue_mod._DIALOGUE_CTX
        assert kwargs["num_predict"] == dialogue_mod._DIALOGUE_PREDICT
        return (
            '{"questions":[{"text":"Идём дальше?",'
            '"ideas":[{"text":"Да","status":"adopted","author":"Спикер 1",'
            '"pros":[],"cons":[]}]}]}'
        )

    monkeypatch.setattr(dialogue_mod, "generate", fake_generate)
    dialogue = build_dialogue(
        [Segment(0.0, 1.0, "Да, идём", speaker="Спикер 1")]
    )
    assert dialogue.questions[0].text == "Идём дальше?"
    assert dialogue.questions[0].ideas[0].author == "Спикер 1"


def test_build_dialogue_retries_when_json_is_cut(monkeypatch):
    calls: list[str] = []

    def fake_generate(prompt, *, schema=None, model=None, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"questions": ['
        return '{"questions":[]}'

    monkeypatch.setattr(dialogue_mod, "generate", fake_generate)
    dialogue = build_dialogue([Segment(0.0, 1.0, "Короткий разговор")])
    assert dialogue.questions == []
    assert len(calls) == 2
    assert "оборвался" in calls[1]
