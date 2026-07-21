import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from sten.audio import to_wav16k
from sten.config import DATA_DIR, OLLAMA_MODEL, WHISPER_MODEL
from sten.items import SummaryItem, category_label
from sten.summarize import summarize
from sten.transcribe import Segment, transcribe, transcript_text

_CATEGORY_ORDER = ("decision", "task", "topic", "question")


def render_markdown(items: list[SummaryItem]) -> str:
    if not items:
        return "# Саммари встречи\n\nНет пунктов.\n"
    lines = ["# Саммари встречи", ""]
    themes: list[str] = []
    for item in items:
        if item.theme not in themes:
            themes.append(item.theme)
    for theme in themes:
        lines.append(f"## {theme}")
        lines.append("")
        theme_items = [i for i in items if i.theme == theme]
        for category in _CATEGORY_ORDER:
            matching = [i for i in theme_items if i.category == category]
            if not matching:
                continue
            for i in matching:
                lines.append(f"- **{category_label(category)}:** {i.text}")
        lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: Path, segments: list[Segment], items: list[SummaryItem]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript_text(segments), encoding="utf-8")
    (out_dir / "transcript.json").write_text(
        json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps({"items": [asdict(i) for i in items]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "summary.md").write_text(render_markdown(items), encoding="utf-8")


def run(audio_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("1/4 Конвертация аудио...")
    wav = to_wav16k(audio_path, out_dir / "audio.wav")

    print(f"2/4 Транскрипция (whisper {WHISPER_MODEL})...")
    segments = transcribe(wav)
    print(f"    сегментов: {len(segments)}, прошло {time.time() - t0:.0f} c")

    print("3/4 Диаризация спикеров (pyannote)...")
    from sten.diarize import diarize_segments

    segments = diarize_segments(segments, wav)
    n_speakers = len({s.speaker for s in segments if s.speaker})
    print(f"    спикеров: {n_speakers}, прошло {time.time() - t0:.0f} c")

    print(f"4/4 Саммаризация ({OLLAMA_MODEL})...")
    items = summarize(segments)

    write_outputs(out_dir, segments, items)
    print(f"Готово за {time.time() - t0:.0f} c. Результаты: {out_dir}")
    print(f"  {out_dir / 'summary.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sten: аудио встречи → транскрипт и саммари")
    parser.add_argument("audio", type=Path, help="путь к аудиофайлу")
    parser.add_argument("--out", type=Path, default=None, help="папка результатов")
    args = parser.parse_args()
    out_dir = args.out or DATA_DIR / "meetings" / args.audio.stem
    run(args.audio, out_dir)


if __name__ == "__main__":
    main()
