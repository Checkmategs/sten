import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from sten.audio import to_wav16k
from sten.config import DATA_DIR, WHISPER_MODEL
from sten.items import SummaryItem, category_label
from sten.transcribe import Segment, transcribe, transcript_text

_CATEGORY_ORDER = ("decision", "task", "topic", "question")
_STAGE_RANGE = {
    1: (0, 8),
    2: (8, 60),
    3: (60, 82),
    4: (82, 99),
}
_STAGE_TOTAL = 4


def overall_percent(step: int, fraction: float = 0.0) -> int:
    """Map pipeline step + in-step fraction to 0–99 (ready is 100 via status)."""
    lo, hi = _STAGE_RANGE.get(step, (0, 0))
    fraction = max(0.0, min(1.0, fraction))
    return int(round(lo + (hi - lo) * fraction))


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


def run(
    audio_path: Path,
    out_dir: Path,
    on_stage: Callable[[int, int, str, int], None] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    last_pct = -1

    def report(step: int, label: str, fraction: float = 0.0) -> None:
        nonlocal last_pct
        pct = overall_percent(step, fraction)
        if pct == last_pct and fraction not in (0.0, 1.0):
            return
        last_pct = pct
        if on_stage is not None:
            on_stage(step, _STAGE_TOTAL, label, pct)

    print("1/4 Конвертация аудио...")
    report(1, "Конвертация аудио…", 0.0)
    wav = to_wav16k(audio_path, out_dir / "audio.wav")
    report(1, "Конвертация аудио…", 1.0)

    print(f"2/4 Транскрипция (whisper {WHISPER_MODEL})...")
    report(2, "Транскрипция…", 0.0)
    segments = transcribe(
        wav, on_progress=lambda frac: report(2, "Транскрипция…", frac)
    )
    print(f"    сегментов: {len(segments)}, прошло {time.time() - t0:.0f} c")
    report(2, "Транскрипция…", 1.0)

    if segments:
        print("3/4 Разметка спикеров...")
        report(3, "Разметка спикеров…", 0.0)
        err_path = out_dir / "diarize_error.txt"
        try:
            from sten.diarize import diarize_segments

            segments = diarize_segments(segments, wav)
        except Exception as exc:
            print(f"    разметка спикеров не удалась: {exc}")
            err_path.write_text(str(exc)[:500], encoding="utf-8")
        else:
            if err_path.exists():
                err_path.unlink()
        report(3, "Разметка спикеров…", 1.0)

    # Protocol/summary is disabled for now: keep the speaker transcript only.
    write_outputs(out_dir, segments, [])
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
