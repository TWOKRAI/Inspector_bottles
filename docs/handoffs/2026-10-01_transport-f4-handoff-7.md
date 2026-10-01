# Хендофф: 4.7a слита, 4.7c на переделку по вердикту CTO, пауза — 2026-10-01 (7)

**Ветка:** `feat/qr-code-reader`, worktree `.claude/worktrees/qr-sync`. **Предыдущий:**
[`2026-09-30_transport-f4-handoff-6.md`](2026-09-30_transport-f4-handoff-6.md).
**План:** [`task-4.7.md`](../../plans/transport-single-policy/task-4.7.md). Свежий статус и вердикт CTO —
в его конце. Разбиение на 4.7a–e — там же.

## Указания владельца (этот чат)

- Главное — система универсальная, эффективная и производительная по всем узлам.
- Камер может быть больше одной. Они не должны конфликтовать и должны быть максимально эффективны
  (это 4.7e в плане).
- Код пишет Sonnet (`developer`/`tester`), ревью — Opus, архитектурные развилки — CTO (Fable).
- После вердикта CTO — слияние в main и пауза.

## Где что лежит

| Что | Где |
|---|---|
| 4.7a | слита. Отчёты: `docs/reviews/2026-10-01_task-4.7a-{tester,developer}.md` |
| 4.7c | `feat/t47c-impl` (`a8ffdf54` + ревью `2d7b8fdf` + вердикт `f3f96670`), worktree `t47c-impl`. Код в main не идёт |
| RED-тесты 4.7b/4.7c | в ветке, как `xfail(strict=True)`. С реализации каждый XPASS требует снять пометку |
| Ревью и вердикт | `docs/reviews/2026-10-01_task-4.7ac-review.md`, `docs/reviews/2026-10-01_task-4.7-cto-verdict.md` |
| Инъекции | scratchpad сессии `b1a7e359…/scratchpad/inj/` (`inject.py`, `spec_a*.py`, `spec_c*.py`). Скрипты временные |

## Следующий шаг

1. **4.7c переделка, developer.** Делается по C1–C4 и проводу из вердикта.
   - Тесты тестера про «очередь 4» устарели. Сначала их переписывает tester по новому acceptance,
     но только в части IPC-очереди.
   - Тесты `inflight_budget` и глубины 8 остаются в силе.
   - В 4.7c-ветке те же тесты лежат без xfail. При слиянии брать версию с пометками и снимать их по
     XPASS.
2. **4.7b.** Реализация по RED-тестам `efd8d3df`. Нужно решение лида: тестер отметил, что для длинных
   имён «владелец и pid в имени» буквально невыполним (`_bounded_name` хеширует). В плане 4.7e это
   принято: уникальность держится на хеше.
3. **4.7d.** Спека по вердикту CTO.
4. **Живой A/B.** Протокол замка стенда, ≥ 3 прогонов на сторону, `dualcam_synth`.

## Открыто

- Не наши, красные на базе `9ae6621e`:
  - `test_socket_channel_hol_*` ×3;
  - `test_remote_frame_source` (1);
  - `test_hot_rebuild_framework_layer_key_count_is_pinned` (38 != 37).

  Не разбирались.
- Стоп-хук `pre_report_gate` у агентов зовёт системный python без pytest и ругается
  (`ModuleNotFoundError: pytest`). Это сообщил developer 4.7a.
- Решение 4.8c (бенч из GUI через `QProcess`) владелец ещё не подтвердил. Вопрос перенесён из
  хендоффа 6.
- Вопрос CTO владельцу: маркер по разрыву `frame_id` — второго сорта, без `trace_id`/`capture_ts`. Его
  нужно занести в `OPEN_QUESTIONS.md`, ещё не занесён.
- Worktree'ы `t47a-tester`, `t47b-tester`, `t47c-tester`, `t47a-impl` можно удалить после слияния.
  `t47c-impl` и `t47b-tester` нужны дальше.

## Сосед

`inspector-bottles-cf` закрылся. Линию line-sim/layer-render ведёт новый чат по
`docs/handoffs/2026-10-01_layer-render-wave1-next.md`. Договорённости прежние: замок стенда, «ок» на
движение main с SHA, зоны не пересекаются. Его зоны: Services/{line_sim, ml_*, dataset_gen,
layer_render}, Plugins/sim, word_layout, center_crop.
