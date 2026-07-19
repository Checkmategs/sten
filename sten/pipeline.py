import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from sten.audio import to_wav16k
from sten.config import DATA_DIR
from sten.items import SummaryItem
from sten.summarize import summarize
from sten.transcribe import Segment, transcribe, transcript_text

_CATEGORY_TITLES = [
    ("decision", "Решения"),
    ("task", "Задачи"),
    ("topic", "Темы"),
    ("question", "Открытые вопросы"),
]


def render_markdown(items: list[SummaryItem]) -> str:
    if not items:
        return "# Саммари встречи\n\nНет пунктов.\n"
    lines = ["# Саммари встречи", ""]
    for category, title in _CATEGORY_TITLES:
        matching = [i for i in items if i.category == category]
        if not matching:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {i.text}" for i in matching)
        lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: Path, segments: list[Segment], items: list[SummaryItem]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript_text(segments))
    (out_dir / "transcript.json").write_text(
        json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2)
    )
    (out_dir / "summary.json").write_text(
        json.dumps({"items": [asdict(i) for i in items]}, ensure_ascii=False, indent=2)
    )
    (out_dir / "summary.md").write_text(render_markdown(items))


def run(audio_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("1/3 Конвертация аудио...")
    wav = to_wav16k(audio_path, out_dir / "audio.wav")

    print("2/3 Транскрипция (whisper medium)...")
    segments = transcribe(wav)
    print(f"    сегментов: {len(segments)}, прошло {time.time() - t0:.0f} c")

    print("3/3 Саммаризация (qwen2.5:7b)...")
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
