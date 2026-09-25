# Handoff: lifecycle-stop-ownership после Task 1.4 (2026-09-25)

**План:** [`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md) · **main:** `c9ae9b06` на момент записи

## Сделано

- **Ф1: Task 1.1, 1.3, 1.2, 1.4 — DONE, слиты в main.** Task 1.4 (сирот нет) — `8d21bf5b`: guard бьёт группу PM
  и после его сбора; спавнер ждёт PM `graceful + 1.0 + 1.0 + 1.5` (8.5 с > 7.0 с); harness досъёмывает поддерево
  и делает `killpg` группы PM. ADR-PMM-031. Живьём `inspection_full` с SIGSTOP-ребёнком: сирот 2 → 0; времена
  штатного стопа не изменились (32 стопа). Итог и остаток — в плане, раздел Task 1.4.
- **Хотфиксы main по находке соседней сессии:** `10cb1254` — инвентарь `emergency_log` +2 за `process_runner.py`
  (долг L-2 Task 1.2); `1546bfa3` — 6 фикстур реестра плагинов на `snapshot → clear → yield → clear → restore`
  (падал `test_harness_log_dir` в общем прогоне). Общая страховка в корневом conftest отвергнута: +29 падений против main.
- Память: `feedback_safety_net_masks_primary_fix`, `feedback_global_rollback_breaks_import_time_state`.

## Следующий шаг

**Task 1.5** — ребёнок физически не переживает родителя: Linux `prctl(PR_SET_PDEATHSIG)` через `ctypes` в начале
`run_process_function` + проверка «родитель уже умер»; macOS — контрольная труба, поток-сторож видит EOF.
Acceptance в плане: `kill -9` PM на живом `inspection_full` → детей 0 за ≤ 2 с; Linux-путь проверить на Linux
(Orin или CI-контейнер). Порядок стадий — tester в worktree до кода → teamlead → инъекции ведущего → стенд → reviewer.
**Перед началом предупредить соседа** (gui-service, сейчас `inspector-bottles-05`): 1.5 трогает `process_runner` /
`run_process_function`. Он подтвердил, что их не трогает.

## Открыто (подробности — `docs/claude/OPEN_QUESTIONS.md`)

- Необъяснённый однократный сбой перед слиянием 1.4: живая сирота на пути SIGINT в тесте A6 (после перезагрузки
  машины); 14 прогонов после — чисто. Подозрение на сам тест (пауза 2.0 с → SIGKILL лаунчера), пауза заменена опросом.
- Живой тест хука выхода Task 1.1 нестабилен на обоих деревьях — гонка признака `(system-wide)` (`process_runner.py:39`).
- Segfault в `logger_module/tests/test_sampler_ceiling_policy.py` при полном прогоне фреймворка одним процессом
  (есть и на main; в изоляции зелёный) — при замерах `--ignore` этого файла.
- Follow-up ревью 1.4 (в «Принятом риске» ADR-PMM-031): устаревший pid PM без сверки личности; при
  `stop_timeout` 30 с спавнер дольше watchdog'а harness'а; второй SIGINT не ускоряет выход.
- Вне моей линии: 47 падений в `Plugins` (io/otel_export, `test_no_silent_swallows`), `config_module/test_watcher`
  «чужой файл» — одинаковы на main, не разбирались.

## Соседи и порты

- gui-service (`inspector-bottles-05`) на момент записи гонял 5 живых тестов на c9ae9b06 в портах 8860–8910 —
  результат `system_shutdown_live` не пришёл; если там `BackendUnavailable` — стык их 1.3a (SocketChannel) и моей 1.1.
  Мои живые прогоны — 8900–9799; у соседа 7900–7999.
- Worktree: `.claude/worktrees/lso-1.4-dev`, `lso-1.4-tester` (незакоммиченный handoff тестера), `lso-hotfix` —
  не удалены, ждут решения владельца.
