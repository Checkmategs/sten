# Copy Transcript Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a «Копировать» button above the full meeting transcript that copies raw text to the clipboard.

**Architecture:** Local UI state on `ConsensusPage` for copy feedback; call `navigator.clipboard.writeText(transcript)` when text is available.

**Tech Stack:** React + existing Sten consensus CSS classes.

## Global Constraints

- Russian UI labels: «Копировать» / «Скопировано».
- Copy raw API transcript including `[mm:ss]` timestamp lines.
- Button only when transcript tab has non-empty loaded text.
- Reuse `consensus-btn-secondary`; no new iconography.

---

### Task 1: Copy button on ConsensusPage

**Files:**
- Modify: `sten/web/src/pages/ConsensusPage.tsx`
- Modify: `sten/web/src/index.css` (toolbar spacing only if needed)

- [x] Add `copied` / `copyError` state and `handleCopyTranscript` using `navigator.clipboard.writeText`.
- [x] Render toolbar with secondary button above `TimedTranscript` when `transcript` is truthy.
- [x] Reset «Скопировано» after ~2s via `setTimeout` (clear on unmount).
- [x] Add minimal CSS for `.consensus-transcript-toolbar` if flex spacing is needed.
- [ ] Manually verify: open meeting → «Текст записи» → copy → paste elsewhere.
