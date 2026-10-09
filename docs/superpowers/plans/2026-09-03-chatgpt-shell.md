# ChatGPT Shell UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Sten a ChatGPT-light app shell and Cosmoq-style animated grain background without changing meeting workflow or APIs.

**Architecture:** Wrap routes in `AppShell` (sidebar + atmosphere layers). Restyle existing page/component CSS classes via design tokens in `index.css`. No API or hook changes.

**Tech Stack:** React + Vite + plain CSS (no new UI library)

## Global Constraints

- Light theme only; no chat metaphor
- Matte white surfaces (no glass on cards/sidebar)
- Preserve TV-scale type on consensus
- Honor `prefers-reduced-motion`
- Do not commit unless user asks

---

## File map

| File | Responsibility |
| --- | --- |
| `sten/web/src/components/AppShell.tsx` | Sidebar + atmosphere markup |
| `sten/web/src/App.tsx` | Wrap `Routes` in shell |
| `sten/web/src/index.css` | Tokens, atmosphere, shell, restyle pages |
| `sten/web/index.html` | `lang=ru`, title Sten |
| `docs/superpowers/specs/2026-09-03-chatgpt-shell-design.md` | Approved design |

---

### Task 1: AppShell + route wrap

- [ ] Create `AppShell.tsx` with atmosphere (`blobs` + `grain`), aside (logo + «Новая встреча»), main slot
- [ ] Wrap routes in `App.tsx`
- [ ] Update `index.html` lang/title
- [ ] Manual: app boots, sidebar link goes to `/`

### Task 2: Tokens + Cosmoq atmosphere CSS

- [ ] Add `:root` tokens and atmosphere animations in `index.css`
- [ ] Sidebar + main layout (desktop + mobile collapse)
- [ ] `prefers-reduced-motion` static blobs

### Task 3: Restyle pages & ItemCard

- [ ] Restyle record / process / consensus / item-card to ChatGPT-light controls
- [ ] Keep class names and a11y attributes
- [ ] Verify visually in browser (record + consensus empty/error if no server)

---

**Spec:** `docs/superpowers/specs/2026-09-03-chatgpt-shell-design.md`
