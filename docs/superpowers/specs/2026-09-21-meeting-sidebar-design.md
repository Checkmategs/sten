---
title: Meeting list in sidebar
date: 2026-09-21
status: approved
---

# Список встреч в сайдбаре

## Goal

Показать в левой навигации Sten все осмысленные встречи, чтобы можно было переходить между ними без знания id.

Суперседит non-goal из `2026-09-03-chatgpt-shell-design.md` («история встреч в сайдбаре — позже»).

## Non-goals

- Поиск по встречам
- Группировка по дням
- Редактирование / удаление из списка
- Страница-архив
- Поле `error` в ответе списка (деталь встречи по-прежнему в `GET /api/meetings/{id}`)

## API

`GET /api/meetings`

Query:

- `include_id` (optional int) — id текущей открытой встречи. Если такая есть в БД, она попадает в ответ даже когда её иначе отфильтровали.

Ответ: JSON-массив, новые сверху (`ORDER BY id DESC`):

```json
[
  {"id": 42, "title": "Встреча 2026-09-18 17:06", "status": "ready", "created_at": "2026-09-18T14:14:50.933258+00:00"}
]
```

Фильтр на сервере: скрыть `status=recording`, у которых нет исходного аудио (`find_source_audio` бросает `FileNotFoundError` или файл нулевого размера — уже так). Остальные статусы (`processing`, `ready`, `consensus`, `error`) всегда видны.

`POST /api/meetings` не меняется. Конфликт маршрутов нет: коллекция `GET/POST /meetings` рядом с `GET /meetings/{id}`.

Реализация: `db.list_meetings()` уже есть; рядом — тонкая функция «есть ли исходное аудио», чтобы не ловить исключение в цикле списка как основной API.

## Клиент

- `api.listMeetings(includeId?: number)` в `api.ts`.
- Список живёт в `AppShell`, между «Новая встреча» и футером.
- Загрузка: при монтировании и при смене `location.pathname`. Из pathname берём `include_id` (`/m/:id/...`).
- Ошибка загрузки: строка «Не удалось загрузить встречи» в сайдбаре; основная страница не ломается.
- Пустой список: ничего не рисуем, только кнопка «Новая встреча».

## Навигация по клику

| status | маршрут |
| --- | --- |
| `recording`, `processing`, `error` | `/m/:id/process` |
| `ready`, `consensus` | `/m/:id/consensus` |

Активная строка: id из текущего URL. Стили — как hover «Новая встреча» (лёгкий фон).

`ProcessPage` по-прежнему редиректит `ready`/`consensus` на consensus; клик на готовую встречу сразу туда.

## UI

Сайдбар ~260px, существующие токены оболочки.

Строка:

- название, одна строка, ellipsis
- дата под ним, muted: `created_at` в `ru`, формат вроде «18 сент., 17:06» (`day`, короткие месяц и время)
- справа точка статуса: зелёная `ready`/`consensus`, серая `processing`/`recording`, красная `error`

Список `overflow-y: auto`, футер остаётся внизу (`flex` как сейчас: top растёт, foot прижат).

Узкий экран (`max-width: 800px`): сайдбар уже горизонтальный топбар. Список — вторая полоса под ним; каждая встреча — компактный чип (название + дата + точка), горизонтальный скролл, без переноса. Футер по-прежнему скрыт.

## Тесты

В `tests/test_api_meetings.py` / `tests/test_db.py`:

- список отдаёт ready/error и recording **с** аудио
- recording **без** аудио отсутствует
- `include_id` возвращает брошенный recording
- порядок: больший id первым

Фронтовых автотестов в репо нет — не добавляем.

## Files

- `sten/api/meetings.py` — `GET /meetings`
- `sten/db.py` — `has_source_audio` (или эквивалент)
- `tests/test_api_meetings.py`, `tests/test_db.py`
- `sten/web/src/api.ts`
- `sten/web/src/components/AppShell.tsx`
- `sten/web/src/index.css`
