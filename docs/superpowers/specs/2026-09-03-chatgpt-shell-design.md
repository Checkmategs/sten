---
title: ChatGPT-like shell + Cosmoq atmosphere
date: 2026-09-03
status: approved
---

# Sten UI: оболочка ChatGPT + атмосфера Cosmoq

## Goal

Перекрасить веб-Sten в светлый визуальный язык ChatGPT (сайдбар, центрированный контент, мягкие карточки, чёрные primary-кнопки) и добавить signature-фон в духе [cosmoq.framer.website](https://cosmoq.framer.website/): медленные цветовые пятна + film grain. Сценарий продукта не меняется: запись → обработка → согласование.

## Non-goals

- Чат-лента, composer снизу, пузыри сообщений
- Тёмная тема
- История встреч в сайдбаре (API `GET /meetings` нет; `db.list_meetings` есть — позже)
- Смена API, пайплайна, контрактов хуков

## Layout

```
+--------+----------------------------------+
| Sten   |  [centered column 48–56rem]      |
| Новая  |  page content                    |
| встреча|                                  |
|        |                                  |
+--------+----------------------------------+
  sidebar     main + atmosphere behind all
```

- `AppShell` оборачивает все маршруты.
- Сайдбар ~260px: логотип, кнопка «Новая встреча» → `/`.
- На узких экранах сайдбар складывается в компактный верхний бар.
- На consensus крупная типографика для ТВ сохраняется.

## Visual tokens

| Token | Value |
| --- | --- |
| Page wash | `#f7f7f8` (просвечивает через атмосферу) |
| Surface | `#ffffff` |
| Border | `#e5e5e5` |
| Text | `#0d0d0d` |
| Muted | `#6b6b6b` |
| Primary button | `#0d0d0d` / text `#fff` |
| Accept / success | `#0f7b3c` |
| Stop / danger | `#c43c3c` |
| Error surface | `#fdeaea` |
| Radius control | `12px` (кнопки ближе к pill где уместно) |
| Font | system UI stack (`-apple-system`, Segoe UI, …) |

**Atmosphere (signature):** фиксированный слой за UI — 2–3 радиальных blob (тёплый peach, лаванда, мятный) с медленным `transform` 20–40s; поверх SVG/CSS grain, `mix-blend-mode: overlay`, opacity ~0.25–0.4. `pointer-events: none`. Сайдбар и карточки **матовые белые**, без glass/blur.

`prefers-reduced-motion: reduce`: blob-анимация выключается, остаётся статичный градиент + зерно.

## Screens

- **Record:** название, таймер, level meter, «Начать запись» / «Загрузить файл», «Стоп», те же a11y-состояния (http, тишина, 5s stop).
- **Process:** статус, процент, очередь/retry.
- **Consensus:** табы, карточки пунктов, баннер согласования, транскрипт.

Поведение и copy не ломаем; меняем оболочку и CSS.

## Components / files

- `sten/web/src/App.tsx` — shell + routes
- `sten/web/src/components/AppShell.tsx` — sidebar + atmosphere
- `sten/web/src/index.css` — tokens + restyle существующих классов
- `sten/web/index.html` — `lang="ru"`, title Sten

## A11y

- Контраст текста на атмосфере: контент на белых поверхностях.
- Focus-visible кольцо.
- Grain/blobs `aria-hidden`.
- Существующие `role`/`aria-*` на записи и прогрессе сохраняем.
