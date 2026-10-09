# Copy meeting transcript to clipboard

## Goal

On the consensus page tab «Текст записи», let the user copy the full meeting transcript into the system clipboard with one click.

## Placement

- Button sits **above** the transcript body.
- Visible only when the transcript tab is active **and** transcript text is loaded and non-empty.
- Hidden while loading, on error, or when transcript is unavailable/empty.

## Behavior

- Copies the **raw** transcript string from the API (`transcript` state), including timestamp lines like `[00:01]`.
- Uses `navigator.clipboard.writeText`.
- On success: button label becomes «Скопировано» for ~2 seconds, then returns to «Копировать».
- On failure: show a short error near the button (reuse consensus error styling or inline text).

## UI

- Text button, no icon.
- Reuse `consensus-btn-secondary` styling.
- Optional thin toolbar row above `.consensus-transcript-text` for alignment.

## Out of scope

- Copying protocol items / summaries.
- Stripping timestamps.
- Header or tab-bar placement.

## Files

- `sten/web/src/pages/ConsensusPage.tsx`
- `sten/web/src/index.css` (minimal layout if needed)
