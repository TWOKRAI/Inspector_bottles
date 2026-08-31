---
name: project-observability-closure-progress
description: "observability-closure — Ф0, Ф1.1 и Ф1.2 закрыты (последняя 2026-08-31); Р-1 решена владельцем как (а), Task 1.3 разблокирована; Р-8 — до Ф5; ветка feat/observability-closure, merge в main — по закрытии Ф2"
metadata:
  node_type: memory
  type: project
  originSessionId: 6ba40fcc-81c2-440a-b226-24fcdf6b63d8
  modified: 2026-08-29T19:31:27.988Z
---

Ветка `feat/observability-closure` (порт `feat/observation-port` уже в ней; `main` — на 64+ коммита
позади, merge по плану — после Ф2). План: `plans/observability-closure/plan.md` + `phase-N-*.md`.

## Закрыто

- **Ф0** (0.1–0.5): гейт держался порядком сбора (C1), `process_restart_verified` лгал (M4), ложные
  WARNING каталога (M1), `full` у 44 MCP-инструментов (M2/M3/m6). Ревью Ф0 — `review-phase-0.md`.
- **Ф1.1 (C3)** — 2026-08-29, коммиты `4724f220` (17 красных тестов тестера) → `28cf8fd3` (механизм)
  → `3513dfef` (8 сторожей по ревью) → `3096cd06` (боевая проводка diag.*, ADR). Механизм:
  `logger_module/core/process_hooks.py` (`install_process_hooks(services)`, singleton на
  интерпретатор), счётчики `thread_exceptions/warnings_captured/hook_delivery_failures` в
  `ErrorManager.stats` → `introspect.observability.counters.error`; `HealthState.report_error(**fields)`;
  `ProcessModule.report_error`; команды `diag.thread_raise`/`diag.warn`; аномалия `thread_exceptions`
  в `system_overview`. Матрица: 23 + 8 инъекций (17/23 и 8/8 совпали с предсказанием). Живой стенд:
  `pult` 0→1/1/0, контроль `lines` 0, `errors.log` 0→10 строк, одна `kind=error` в сторе.
  Ревью: итерация 1 — 6 сторожей отсутствовали (0 красных при снятом свойстве); итерация 2 — APPROVED.

## Что стенд Ф1.1 показал для соседних задач (числа)

- **M14 / Task 1.2:** `ProcessManager.counters.logger.unresolved_channel_records = 12` на чистом старте.
- **M8 / Task 1.3:** один инцидент хука = ДВЕ строки в сторе (`[health] …` как `kind=log` + `kind=error`).
- Троттл health 5 с на пару (тип, `thread:<имя>`): второй инцидент того же потока за 5 с считается,
  но записи не даёт (воспроизведено ревьюером: 2 → 1 запись) — задокументировано, не дефект.
- Одиночка хуков — на интерпретатор: два `ProcessModule` в одном интерпретаторе едут в чужую плоскость
  (`docs/claude/OPEN_QUESTIONS.md`); в тестах и на стенде сценария нет.
- MCP-сервер backend-ctl держит `backend_ctl`, загруженный при старте сессии: новые аномалии
  `system_overview` видны только драйвером из свежего процесса (то же, что в Ф0.5).

- **Ф1.2 (M14/m3)** — 2026-08-31, коммиты `d4deba58` (5 красных тестера) → `3badcf83` (реализация)
  → `e1867a60` (мой сторож «один разъём на точку») → `0a075682` (10 находок ревью) → `8cecc306`
  (остатки Р1/Р5). **Причина оказалась НЕ той, что записал план:** не «запись раньше регистрации
  канала», а ДВЕ дороги к одному конфигу — рождение собирало голым `expand_observability`, а он
  эмитит ЧАСТИЧНЫЙ набор каналов; Pydantic заменяет набор целиком, `scopes` остаются дефолтом схемы
  и ведут в `system_file`/`messages_file`, которых в реестре нет. Ровно 6 записей × 2 приёмника = 12.
  Лечится швом `compose_managers_payload` (одна сборка на рождение и на пересборку), не буфером.
  Стенд: 12 → **0**, аномалий 0 при 8 процессах, `launcher/system.log` 10 строк (6 из них — чужие:
  spawner, PluginRegistry, Hikvision SDK, devices_sync — до задачи уходили в stdlib без хендлеров).
  Гейт 9058. Ревью: итерация 1 — 10 находок, итерация 2 — APPROVED.

## Открыто для владельца

- **Р-1 РЕШЕНА** 2026-08-30 как **(а)** — отдельная плоскость ошибок. Task 1.3 разблокирована.
- **Р-8** (паритет инструментов ↔ документов) — до Ф5; рекомендация — повесить на `backend_ctl/README.md`.
- Долги Task 1.2, не блокеры: Р2 (маршрут после закрытия не охраняется у `_log_warning`/`_log_error`),
  Р3 (отказ `clear()` в `stop()` без сторожа), Р4 (`is_posix()` — белый список, глушит уборку на
  FreeBSD/AIX). POSIX-половина уборки на Windows не гоняется — доказательством был бы прогон на Linux.
- Счётчик `unresolved_channel_records` НЕ различает «канала ещё нет» / «канала уже нет» / «оператор
  снял» — три факта приходят одним числом (`OPEN_QUESTIONS.md`, F9). Значит критерий «нет
  `observability_loss`» — утверждение о моменте, а не о свойстве: на остановке он перестаёт
  выполняться у каждого процесса.

Связано: [[project_observation_port_progress]], [[feedback_pytest_owns_threading_excepthook_for_the_session]],
[[feedback_a_list_walking_guard_cannot_see_a_removed_item]], [[feedback_a_peer_session_shares_the_tree]],
[[feedback_the_plans_stated_cause_is_a_hypothesis]].
