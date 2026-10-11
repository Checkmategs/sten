import argparse
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from sten.audio import to_wav16k
from sten.config import DATA_DIR, WHISPER_MODEL
from sten.items import SummaryItem, category_label
from sten.report import MeetingReport, build_report, render_report_text, report_to_items
from sten.speakers import seed_speakers
from sten.transcribe import Segment, gpu_memory_free_mib, transcribe, transcript_text

_CATEGORY_ORDER = ("decision", "task", "topic", "question")
# Shares follow typical time: transcription and diarization are the long middle,
# and the brief keeps a wide tail so the bar can keep moving while the model writes.
_STAGE_RANGE = {
    1: (0, 5),
    2: (5, 38),
    3: (38, 70),
    4: (70, 99),
}
_STAGE_TOTAL = 4
DIARIZE_LABEL = "Идёт разметка спикеров…"


def overall_percent(step: int, fraction: float = 0.0) -> int:
    """Map pipeline step + in-step fraction to 0–99 (ready is 100 via status)."""
    lo, hi = _STAGE_RANGE.get(step, (0, 0))
    fraction = max(0.0, min(1.0, fraction))
    return int(round(lo + (hi - lo) * fraction))


def pipeline_devices(
    gpus: list[tuple[int, int]],
) -> tuple[list[tuple[int, int]] | None, int | None]:
    """Give Whisper the freest GPU and diarization the next one.

    With one GPU or none, diarization waits until Whisper has released memory.
    ``gpus`` is the list from ``gpu_memory_free_mib`` (most free memory first).
    """
    if len(gpus) < 2:
        return None, None
    return [gpus[0]], gpus[1][0]


def diarize_creep(elapsed: float, estimate: float) -> float:
    """Grow through the diarization stage without reaching the end early.

    At ``elapsed == estimate`` the fraction is about 0.63, then it slows and
    caps at 0.92 until pyannote actually finishes.
    """
    estimate = max(float(estimate), 1.0)
    elapsed = max(0.0, float(elapsed))
    return min(0.92, 1.0 - math.exp(-elapsed / estimate))


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


def _start_diarize(wav: Path, device_index: int | None, box: dict) -> threading.Thread:
    def job() -> None:
        try:
            from sten.diarize import diarize_wav

            if device_index is None:
                print("3/4 Разметка спикеров...", flush=True)
            else:
                print(f"3/4 Разметка спикеров на cuda:{device_index}...", flush=True)
            box["turns"] = diarize_wav(wav, device_index=device_index)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    return thread


def write_outputs(
    out_dir: Path,
    segments: list[Segment],
    items: list[SummaryItem],
    report: MeetingReport | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript_text(segments), encoding="utf-8")
    (out_dir / "transcript.json").write_text(
        json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary: dict = {"items": [asdict(i) for i in items]}
    if report is not None:
        summary["report"] = report.to_dict()
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown = render_report_text(report) if report is not None else render_markdown(items)
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")


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
        if pct < last_pct:
            return
        if pct == last_pct and fraction not in (0.0, 1.0):
            return
        last_pct = pct
        if on_stage is not None:
            on_stage(step, _STAGE_TOTAL, label, pct)

    print("1/4 Конвертация аудио...")
    report(1, "Конвертация аудио…", 0.0)
    wav = to_wav16k(audio_path, out_dir / "audio.wav")
    report(1, "Конвертация аудио…", 1.0)

    whisper_gpus, diarize_index = pipeline_devices(gpu_memory_free_mib())
    diarize_box: dict = {"turns": None, "error": None}
    diarize_thread: threading.Thread | None = None
    diarize_started = time.time()
    if diarize_index is not None:
        diarize_thread = _start_diarize(wav, diarize_index, diarize_box)

    print(f"2/4 Транскрипция (whisper {WHISPER_MODEL})...")
    report(2, "Транскрипция…", 0.0)
    t_asr = time.time()
    transcribe_kwargs = {}
    if whisper_gpus is not None:
        transcribe_kwargs["gpus"] = whisper_gpus
    try:
        segments = transcribe(
            wav,
            on_progress=lambda frac: report(2, "Транскрипция…", frac),
            **transcribe_kwargs,
        )
    except Exception:
        if diarize_thread is not None:
            diarize_thread.join()
        raise
    asr_seconds = time.time() - t_asr
    print(f"    сегментов: {len(segments)}, прошло {time.time() - t0:.0f} c")
    report(2, "Транскрипция…", 1.0)

    if segments:
        report(3, DIARIZE_LABEL, 0.0)
        if diarize_thread is None:
            diarize_started = time.time()
            diarize_thread = _start_diarize(wav, None, diarize_box)
        # Pyannote does not report its own progress. Creep the bar for about as
        # long as transcription took, and hold short of the end until it returns.
        estimate = max(20.0, asr_seconds)
        stop_creep = threading.Event()

        def creep() -> None:
            while not stop_creep.wait(0.4):
                report(
                    3,
                    DIARIZE_LABEL,
                    diarize_creep(time.time() - diarize_started, estimate),
                )

        creeper = threading.Thread(target=creep, daemon=True)
        creeper.start()
        err_path = out_dir / "diarize_error.txt"
        try:
            diarize_thread.join()
            if diarize_box["error"] is not None:
                raise diarize_box["error"]
            from sten.diarize import apply_diarization

            segments = apply_diarization(segments, diarize_box["turns"] or [])
        except Exception as exc:
            print(f"    разметка спикеров не удалась: {exc}")
            err_path.write_text(str(exc)[:500], encoding="utf-8")
        else:
            if err_path.exists():
                err_path.unlink()
        finally:
            stop_creep.set()
            creeper.join(timeout=2)
        report(3, DIARIZE_LABEL, 1.0)
    elif diarize_thread is not None:
        diarize_thread.join()

    print("4/4 Обзор совещания...")
    report(4, "Обзор совещания…", 0.0)
    # The model call is one blocking request. Creep the brief's share of the
    # bar until it returns, and never run backwards if a chunk finishes first.
    report_estimate = max(20.0, asr_seconds)
    report_started = time.time()
    stop_report = threading.Event()

    def creep_report() -> None:
        while not stop_report.wait(0.4):
            report(
                4,
                "Обзор совещания…",
                diarize_creep(time.time() - report_started, report_estimate),
            )

    report_creeper = threading.Thread(target=creep_report, daemon=True)
    report_creeper.start()
    try:
        meeting_report = build_report(
            segments,
            on_progress=lambda frac: report(4, "Обзор совещания…", frac),
        )
    finally:
        stop_report.set()
        report_creeper.join(timeout=2)
    write_outputs(out_dir, segments, report_to_items(meeting_report), meeting_report)
    seed_speakers(out_dir, segments)
    report(4, "Обзор совещания…", 1.0)
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
