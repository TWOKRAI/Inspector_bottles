# Полоса Р2 · Task SPI хаба — влита (2026-10-26)

Лид: inspector-bottles-69 (до перезапуска — inspector-bottles-00). Координатор: inspector-bottles-47.
Слияние `4d9cf4c4b` (ветка `feat/robot-v2-spi`, 42 коммита после rebase на ada1faa82). Отчёт —
`docs/reports/2026-10-26_robot-protocol-v2_SPI.md`; план — `plans/robot-protocol-v2/plan.md`, строка SPI → DONE.

## Что вошло

- Драйвер объявляет операции явным `Protocol` + `OpSpec` (`Services/device_hub/spi.py`); команды хаба строятся из таблицы
  видов `Services/device_hub/kinds.py`, исполнение — через `device_io` по имени (1.9m; C-47 — executors из топологии).
- Новый вид = строка таблицы или подкласс `DeviceHubPlugin` со своим `device_kinds` (`__init_subclass__`, copy-on-write).
- Сняты костыли: `_bound`, `getattr` по драйверу, опции «на весь вид» (теперь `kind | (kind, protocol)`); `stop_aware`
  сверяется по MRO (`inspect.getattr_static`). Хук `command_options` в process_module — ADR-PM-056; ADR-DH-009..012.

## Проверки

Opus ветки р.3 APPROVED; стенд v2: ветка S1–S3 1,18–1,25 с, база main ×3 1,20–1,36 с; device_hub 922/0/3, плагин 339/0,
process_module 3412/0, process_manager_module 1348/0, backend/tests 244/0, framework 12234/2 (C-4; новый флейк
`test_t45a_pacer_late_stays_zero_without_work` под нагрузкой, вне диффа — строку заводит координатор); validate 0/0.

## Открыто

- C-56 (GUI вкладки робота шлёт v1-имена драйверу v2) — проверить на стенде v2 через backend_ctl, вход/выход в строку C-56.
- C-57 (`introspect.*` «No handler» сразу после старта) и C-58 (циклический импорт ProcessHeartbeat) — на main, слой framework.
- Исполнитель 4/64 под нагрузкой не замерен; успешный `vfd_get_status` на стенде не наблюдался (ПЧ не подключён).
- Worktree `.claude/worktrees/robot-v2-spi` (ветка влита) — удалить после /clear этой сессии; worktree и ветка инъекций удалены.

## Агенты

| agentId | роль | модель | ~расход |
|---|---|---|---|
| a28130b6fa3d79055 | manager (бриф) | Opus | 340k |
| a96736394a76e699d | tech-writer | Sonnet | 148k |
| ad0bcd5eb29ad5467 | reviewer стадии 0 | Sonnet | 413k |
| a83bcc9cf7d929ae7 | tester слепой | Sonnet | 281k |
| a041542897fd85a64 | teamlead a…d2 | Opus | 419k |
| a0e3ed0ccef256059 | developer c2…g, docs | Sonnet | 348k |
| a3111d7744f1699a8 | reviewer задачи ×2 | Sonnet | 327k |
| ac025b3f21f0bddf8 | developer матрица | Sonnet | 252k |
| a98d8ddbff4707ef3 | developer стенд, окна | Sonnet | 380k |
| a4428012eeb5b786d | reviewer ветки ×3 | Opus | 297k |
| a11e0626915c174f9 | teamlead SPI.h–h3 | Opus | 320k |
| aac5f6d778cc9bb60 | junior финальные прогоны | Haiku | 71k |

Дальше по плану: C-33 (= T5.3e, кнопки «Остановить» / «Остановить принудительно») — порядок в `plans/queue/ORDER.md`.
