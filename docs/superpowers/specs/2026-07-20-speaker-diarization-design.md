# Speaker diarization (pyannote)

Date: 2026-07-20  
Status: approved

## Goal

Show the meeting transcript split by voice (speakers), using real audio diarization — not LLM guessing.

## Approach

1. Transcribe with Whisper as today → segments `(start, end, text)`.
2. Run **pyannote/speaker-diarization-3.1** on the same 16 kHz wav → intervals `(start, end, SPEAKER_XX)`.
3. Assign each Whisper segment the speaker with maximum time overlap.
4. Map `SPEAKER_00` → `Спикер 1` by first-appearance order.
5. Merge consecutive same-speaker segments into **turns** for display and `transcript.txt`.

## Data

- `Segment.speaker: str | None`
- `transcript.json` includes `speaker` per segment
- `transcript.txt` formatted as:

```
Спикер 1: …

Спикер 2: …
```

- `GET /api/meetings/{id}/transcript` returns:

```json
{
  "text": "...",
  "available": true,
  "turns": [{"speaker": "Спикер 1", "start": 0.0, "end": 12.3, "text": "..."}],
  "diarized": true
}
```

## Existing meetings

`POST /api/meetings/{id}/diarize` — diarize existing `audio.wav` + remap `transcript.json` without re-running Whisper or summarization. UI: button «Разметить спикеров» on the transcript tab when `diarized` is false.

## Ops

- Dependencies: `torch`, `torchaudio`, `pyannote.audio`
- Env: `HF_TOKEN` (Hugging Face), licenses accepted for pyannote models
- Missing token → clear error on diarize / processing step (no silent skip)

## Out of scope

- Manual speaker rename
- Feeding speakers into summarization prompts
- Diarization on Apple Silicon as a first-class target (GPU server is primary)

## Success

- New meetings get speakers in the pipeline automatically
- Meeting #8 can be diarized via the button; transcript tab shows labeled turns
