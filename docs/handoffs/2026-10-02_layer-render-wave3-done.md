---
date: 2026-10-02
topic: layer-render — волна 3 (2.2 эффекты, 6.1 вырез, 1.4 фильтр «перца») влита в feat/layer-render, режим «Компания v3»
machine: Windows
branch: feat/layer-render
---

## Session goal

Волна 3 плана `layer-render` в режиме «Компания v3»: ревью спеки до тестеров → тестер RED (последовательно, worktree до
кода) → разработчик (один на задачу до конца волны) → инъекции лида → ревьюер (итерация 2 — тот же, дозовом) → слияние.

## Done

- Спеки: 1.4 (`phase-1.md`), 2.2 (`phase-2-core.md`), 6.1 (новый `phase-6-train.md`) — `f171975c`; ревью спеки (3 MAJOR в 2.2)
  → правки `b294a6af` (база тестеров).
- **2.2** `effects.py` (`EFFECTS`, `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`), `apply_photometric` одной строкой — влито `8665d7b7`.
- **6.1** `crop.py` (`side_from_radius`, `square_crop`, `resize_square`), `center_crop` и `holdout_eval` делегируют — влито `f9ef5c45`.
- **1.4** `min_area` + `--gap-min-area 8` — влито `3ea586c0`; плитка стенда пересобрана (данные вне git, см. план).
- `main` 9602157cb влит — `99905c91`. Радиус 1920 passed / 5 skipped, sentrux ✓, validate без ошибок.
- Ф9 (редактор разметки YOLO на том же механизме) — идея владельца в плане и OPEN_QUESTIONS (`b3b93db3`).
- Карты зон: `docs/maps/layer_render.md`, `docs/maps/crop.md`, `docs/maps/line_sim_tools.md`. Замер — `docs/claude/pilot-company-v3.md`.

## agentId (дозов — SendMessage по id; имя после обрыва/на следующий день не резолвится)

| Роль | Задачи | agentId | Контекст на конце |
|---|---|---|---|
| dev-effects (developer Sonnet) | 2.2, 1.4 + правки, хендофф `2026-10-02_wave3-dev-effects.md` | `a24daa7deed1d4c29` | 247k — свежего на следующую волну |
| dev-crop (developer Sonnet) | 6.1 + правки, хендофф `2026-10-02_task-6.1-developer.md` | `a5775e2c272fc9863` | 161k |
| rev-spec-w3 (reviewer Opus) | ревью спеки | `aaed95d23a61f17dc` | 178k |
| rev-22 / rev-61 / rev-14 (reviewer Opus) | 2.2 / 6.1 / 1.4 | `a697ad29b625d1d51` / `a9ca88238a287a14e` / `a759332e582064cad` | 169k / 140k / 132k |
| tester-22 / -61 / -14 (Sonnet) | RED-наборы | `a1b576bd1b5102f7d` / `a2f0ac7d5f7d06205` / `a171ebdd05f07bb6d` | 135–147k |

## Next step

1. Вопрос владельцу — волна 4: по плану после 2.2 открыта **2.3** (`LayerSpec`/`compose_layers` в `layer_render`, Senior — teamlead),
   после 6.1 — **6.4** (`holdout_eval` на формуле конвейера, О-1). 2.3 и 6.4 не пересекаются по файлам.
2. ff `main` → `feat/layer-render` — SHA соседу (`inspector-bottles-6e`, трек transport) заранее.

## Open

- `OPEN_QUESTIONS.md`: хук `protect-branch` блокирует коммиты субагентов в соседних worktree (коммитит лид); отложенное из
  волны 3 (pickle `EffectSpec`, мост требует поле `AugmentConfig`, живой снимок стенда 1.4).
- Worktree волны (`../Inspector_bottles--lr{22,61,14}-{tester,impl}`) влиты — можно удалить.

## Unreliable

- 1.4 A7 — на точной свёртке, не на живом стенде. Числа покрытия 69.9 % / 0.09 % — прокси 1.2 (не разметка).
- Мои предсказания инъекций: промахи 4/18 (2.2), 2/16 (6.1), 1/10 (1.4) — свойства пойманы, карта «тест → свойство» неточна там,
  где тесты тестера шире, чем я ждал.
- `subagent_tokens` в замере — размер контекста, не оплаченные токены.
