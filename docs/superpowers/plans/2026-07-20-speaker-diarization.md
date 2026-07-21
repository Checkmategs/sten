# Speaker diarization implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** pyannote diarization + speaker-labeled transcript UI  
**Spec:** `docs/superpowers/specs/2026-07-20-speaker-diarization-design.md`

**Files:**
- Create `sten/diarize.py` — assign/merge + pyannote wrapper
- Modify `sten/transcribe.py` — `Segment.speaker`, `transcript_text`
- Modify `sten/pipeline.py` — diarize after whisper
- Modify `sten/api/processing.py` — `start_diarize`
- Modify `sten/api/meetings.py` — transcript turns + POST diarize
- Modify `sten/config.py` — `HF_TOKEN`
- Modify frontend ConsensusPage + api.ts + CSS
- Modify `requirements.txt`
- Tests: `tests/test_diarize.py`, API tests

## Task 1: Pure assign/merge + Segment.speaker (TDD)

- [ ] Tests for assign_speakers, merge_turns, transcript_text with speakers
- [ ] Implement without calling pyannote

## Task 2: pyannote wrapper + pipeline hook

- [ ] `diarize_wav(wav) -> list[(start,end,label)]` using HF_TOKEN
- [ ] Call from `pipeline.run` after whisper; clear error if no token/model

## Task 3: API + re-diarize for existing meetings

- [ ] Extend GET transcript with turns/diarized
- [ ] POST `/diarize` + processing worker
- [ ] Tests with mocked diarize_wav

## Task 4: UI

- [ ] Render turns on transcript tab
- [ ] «Разметить спикеров» when not diarized
- [ ] Deploy; run diarize on meeting 8

## Task 5: Deploy notes

- Install torch/pyannote on server
- Set HF_TOKEN
- User must accept https://huggingface.co/pyannote/speaker-diarization-3.1 and https://huggingface.co/pyannote/segmentation-3.0
