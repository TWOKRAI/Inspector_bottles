# Полоса Р2 · Task SPI хаба — передача посреди задачи (2026-10-26, перед compact)

Лид: сессия inspector-bottles-69 (до перезапуска — inspector-bottles-00). Координатор: inspector-bottles-47.
Ветка `feat/robot-v2-spi`, worktree `.claude/worktrees/robot-v2-spi`. Бриф `plans/robot-protocol-v2/tasks/SPI.md` (+ acceptance,
framework, seams, debts, deviations, injections, injections-predictions, injections-result, stand/).

## Стадия

- Сделано: стадия 0 (Sonnet ×2 APPROVED) → слепой tester (А1–А27) → реализация a, b1, b2, c1, c1b, d0 (C-47), d1, d2, d3, c2,
  c2b, f1, f2a, f2b, g, docs → ревью задачи Sonnet ×2 APPROVED → матрица 38 инъекций (22 да / 11 частично / 5 нет; 4 выживших
  закрыты тестами 9402aab38; 32 — эквивалентный мутант) → ревью ветки Opus р.1 CHANGES REQUESTED (два источника каталога) →
  SPI.h (beab63c97, 4fd918c39: таблица видов `Services/device_hub/kinds.py`, команды из `OP_SPECS`) → Opus р.2 APPROVED (b6e2012fa).
- Идёт: **SPI.h2** (teamlead a11e0626915c174f9, не закоммичено на момент записи): убрать `_bound` (позднее связывание — костыль
  по Opus р.2), `DeviceHubPlugin.__init_subclass__` (вид в подклассе = один шаг), `driver_options` по (kind, protocol),
  охрана `stop_aware` не-bool → TypeError, ADR «args у 38», разметка «Открыто» — цель 0 костылей (принцип владельца,
  повторён 2026-10-26: «костылей не должно быть»).

## Дальше

1. Принять SPI.h2 (прогоны light поимённо; AST-дифф assert слепых C-29/SPI при смене рига пуст) → короткая проверка у
   reviewer Opus a4428012eeb5b786d (тот же, р.3 как подтверждение правки после APPROVED).
2. «ready» координатору на ч.2 окна heavy (~40 мин): Services/device_hub/tests, Plugins/hub/device_hub/tests,
   process_module/tests, process_manager_module/tests целиком; регенерация CAPABILITIES (`python -m backend_ctl.dump_capabilities`,
   гейт `backend_ctl/tests/test_capabilities.py::test_dump_matches_committed` сейчас красный — условие слияния); стенд v2 по
   `plans/robot-protocol-v2/tasks/SPI.stand/README.md` (S0–S3 + device_io; не хуже C-29 0,75–1,23 с). Машина: ~0,5 ГБ RAM, окон нет.
3. Перед merge: rebase на main, validate.py, backend/tests (timed), framework suite (heavy); красные — по plans/queue/defects.md;
   «сливаю» координатору → ждать «ок»; handoff `docs/handoffs/<дата>_R2-SPI-merged.md`; отчёт `docs/reports/<дата>_robot-protocol-v2_SPI.md`;
   plan.md строка SPI → DONE.

## Открыто

- CAPABILITIES не перегенерированы (условие слияния).
- После SPI.h/h2 полные каталоги и стенд не гонялись; инъекции на SPI.h — только teamlead (Edit с откатом), матрица не повторялась.
- `git checkout --` отклоняет классификатор auto mode — откаты правкой Edit; worktree `robot-v2-spi-inj` (ветка tests/robot-v2-spi-inj)
  содержит постороннюю правку `docs/reviews/2026-10-26_SPI-task-sonnet-review.md` — удалить worktree и ветку после слияния.
- Пилот стадии 0: дефект дизайна «два источника каталога» найден Opus-ревью ветки, частично от стадии 0 (записано координатором).
- Решения владельца 2026-10-26: принцип «без костылей, архитектура на рост»; В1 «SPI.d сейчас»; set_servo v1 — immediate.

## Агенты

| agentId | роль | модель | статус | ~расход |
|---|---|---|---|---|
| a28130b6fa3d79055 | manager (бриф) | Opus | готово | 340k |
| a96736394a76e699d | tech-writer (разделение plan/DECISIONS) | Sonnet | готово | 148k |
| ad0bcd5eb29ad5467 | reviewer стадии 0 | Sonnet | APPROVED | 413k |
| a83bcc9cf7d929ae7 | tester слепой | Sonnet | готово | 281k |
| a041542897fd85a64 | teamlead a…d2 | Opus | готово | 419k |
| a0e3ed0ccef256059 | developer c2…g, docs, правки ревью задачи | Sonnet | готово | 348k |
| a3111d7744f1699a8 | reviewer задачи | Sonnet | APPROVED ×2 | 327k |
| ac025b3f21f0bddf8 | developer матрица + тесты выживших | Sonnet | готово | 252k |
| a98d8ddbff4707ef3 | developer подготовка стенда | Sonnet | готово (не запускался) | 253k |
| a4428012eeb5b786d | reviewer ветки | Opus | APPROVED р.2 | 263k |
| a11e0626915c174f9 | teamlead SPI.h, SPI.h2 | Opus | **идёт SPI.h2** | 211k+ |
