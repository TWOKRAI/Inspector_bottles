# Handoff: lifecycle-stop-ownership после Task 1.6 — Ф1 закрыта (2026-09-26)

**План:** [`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md) · **main:** `ae0eebde` (merge Task 1.6)

## Сделано

- **Task 1.6 — DONE, слита в main.** Итог отпуска очередей каждого ребёнка (`released` / `buffered_dropped`) едет в PM
  через слот `RawArray('q',3)` на воплощение. PM пишет одну запись `stop summary:` в `observability.db`, данные лежат в
  `extra.context.stop_summary`, severity WARNING при потере или `reported=false`. Чтобы запись успела до снятия
  store-tap, в `ProcessModule.stop()` добавлен хук `_before_observability_teardown()`: PM останавливает в нём детей. ADR-PMM-033.
- По дороге были две ложные посылки брифа ведущего (запись в `extra`; «логгер в `shutdown()` пишет в стор»).
  Обе поймал developer, записаны в память: `.claude/memory/feedback_shutdown_logs_miss_the_store.md`.
- Ревью: it.1 REQUEST_CHANGES (исключение в хуке срывало слив и повтор `stop_all`), it.2 APPROVE_WITH_NOTES.
- **CTO: merge gate ACCEPT_WITH_DEBT, Ф1 ACCEPT WITH CONDITIONS**, см. [`docs/reviews/2026-09-26_lifecycle-phase-1-cto.md`](../reviews/2026-09-26_lifecycle-phase-1-cto.md).
- Попутно на main: инвентарь `emergency_log` +2 за сторож 1.5 (`ae328398`, красный main поймал сосед gui-service).

## Следующий шаг

Ф1 закрыта. **Ф2 ждёт L-6** (Фаза 4 `transport-single-policy`) и четырёх условий CTO (чекбоксы в плане перед разделом Ф2):
1. D1 — Linux/Orin проверка 1.5 (отложено владельцем, `docs/claude/OPEN_QUESTIONS.md`).
2. Юнит-тест правила severity `_publish_stop_summary`: около 15 строк, дёшево, можно сделать в любой момент.
3. Прогон `--backend-live` перед Ф2 (или живые тесты в CI).
4. Флейк `children_exit_hook_in_system_stop_mode` (1/9).

Долги до старта Task 3.1: указатель ADR-PM-045 → ADR-PMM-033 в `process_module/DECISIONS.md`; формулировка ADR-PMM-033
п.4 (в сводку попадают все имена `os_processes`).

## Открыто

- На пути сбоя `stop_all` сводка публикуется уже после снятия store-tap и в стор не попадает. Принято, записано в ADR.
- Если `_process_monitor.stop()` бросает, детей никто не останавливает. Дефект старый, на main так же.
- `GenericProcessManagerApp.shutdown` теперь идёт после `stop_all`. Дефектом не воспроизведено, сосед 2c предупреждён.
- Порядок записи `reported` последним тестом не закреплён.
- Не проверены: Qt `GuiProcess`, Windows/spawn.
- `plans/lifecycle-stop-ownership.md` весит 44 КБ, `process_manager_module/DECISIONS.md` — 215 КБ, бюджет doc-size-guard 32 КБ: оба пора делить.

## Хвосты

Worktree ждут решения владельца: `lso-1.6-dev` (`fix/lifecycle-1.6`, слита), `lso-1.6-tester` (`test/lifecycle-1.6`,
тесты перенесены в ветку через cherry-pick), а также прежние `lso-1.5-dev`, `lso-1.5-tester`, `lso-1.4-dev`, `lso-1.4-tester`,
`lso-hotfix`. Порты 9800–9899 свободны. Скрипт инъекций и предсказания лежат в scratchpad сессии и не сохраняются;
матрица записана в плане (блок «Итог» Task 1.6).
