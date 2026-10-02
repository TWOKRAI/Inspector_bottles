# Хендофф: 4.7b закрыта и влита в main, дальше 4.7d пилотом команды — 2026-10-02 (9)

**main:** `6e0fbec0b`, **не запушен** (40+ коммитов впереди `origin/main`). Интеграционная ветка 4.7b — `feat/t47b-integrate`.
**Предыдущий:** [`2026-10-01_transport-f4-handoff-8.md`](2026-10-01_transport-f4-handoff-8.md).
**План:** [`task-4.7.md`](../../plans/transport-single-policy/task-4.7.md), статус и раздел 4.7b обновлены.

## Что сделано

| Шаг | Итог |
|---|---|
| 4.7b1 (имя сегмента, реестр) | `4b773d416` + `9dd99c852`. Один режим `{base}_{owner}_{pid}_{inc}` через `_bounded_name`; схлопнутое имя держит полный `base`, пока `len(base) + 9 ≤ 26`; `base` > 17 символов — известный потолок. Флаги `FW_SHM_OWNER_INCARNATION` / `HANDLE_CACHE` / `ZERO_COPY` удалены, `LOAN_PROTOCOL` FROZEN. Ревью Opus: REQUEST_CHANGES → исправлено |
| 4.7b2 (кэш reader'а, read-only view) | `6604d96f1` + `b16e11dbc` + `f169cab0f` + `e1e4af8cc`. Ключ `(owner, slot, idx)`, кэпа 8 нет, handle с живым view → `_retired` / `deferred_closes`; пайплайн получает read-only view, `on_receive` копирует; `frame_saver` копирует удерживаемое (регрессия найдена ревью). Ревью Opus: REQUEST_CHANGES → APPROVE_WITH_NITS → нитки закрыты |
| Интеграция | `c1ed6f578` (последний `xfail` снят), `9f6e989a3` (C7: сообщение в полёте дропается целиком при realloc любого ключа — решение 4.4c теперь единое) |
| Инъекции лида | b1 — 7/7 свойств убиты; b2 — 7 свойств, 6 сразу, дыру `view_valid` по имени закрыл `b16e11dbc` |
| Радиус | framework/modules + blob_detector + prototype/frontend + backend_ctl: main 17 failed / интеграция 17 failed (2 новых исправлены в `9f6e989a3`); router + shared_resources + frame_saver: 1083 passed, 3 failed (известные `test_socket_channel_hol_*`) |
| Документы (tech-writer) | статус плана, устаревшие описания удалённых флагов и старого формата имени (DECISIONS/STATUS/README модулей, `apps/line_sim/README.md`), четыре вопроса в `OPEN_QUESTIONS.md` |

## Следующий шаг

1. **4.7d** идёт пилотом команды в другом чате: ветка `feat/t47d`, worktree `../Inspector_bottles--team-t47d`. Часть 4.7d-3 — после rebase на `6e0fbec0b` (правит `frame_shm_middleware.py`, как и 4.7b).
2. **Живой A/B** — `dualcam_synth`, ≥ 3 прогона на сторону, замок стенда. Числа для CTO: `ipc_queue_depth` и `transit_over_budget` (ADR-173).
3. **4.7e, кэп моста** — `_HANDLE_CAP=32` по имени даёт 0 попаданий при 5×8 и 3×12 (замер ревью); нужен кэп = сумма глубин подписанных отправителей.

## Открыто

- Push main — ждёт владельца (40+ коммитов впереди `origin/main`).
- Решение 4.8c (бенч из GUI через `QProcess`) владелец не подтвердил.
- Четыре новых вопроса в [`OPEN_QUESTIONS.md`](../claude/OPEN_QUESTIONS.md): осиротевшие SHM после `kill -9` на POSIX (решение владельца, Orin О-6); хук `protect-branch.sh` смотрит ветку cwd, а не worktree (инфра); копия каждого кадра в `frame_saver` stream (follow-up); кэп моста (в 4.7e).
- Pre-existing: segfault в `test_sampler_ceiling_policy` (не наш), `test_socket_channel_hol_*` ×3.
- `deferred_closes` — только свойство reader'а, в телеметрию не экспортируется.
- Worktree'ы можно удалять: `t47b1-impl`, `t47b2-impl`, `t47b-int`, `t47b-tester`, `t47d-spec`, `order-rebuild`, `t47c-impl`.
