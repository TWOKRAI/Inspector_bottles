---
name: project-observability-closure-progress
description: "observability-closure — Ф0 закрыта (2026-08-29 утро), Ф1.1 (C3, хуки процесса) закрыта 2026-08-29 вечером; Ф1.2/1.4 без развилок, Ф1.3 ждёт Р-1, Р-8 — до Ф5; ветка feat/observability-closure, merge в main — по закрытии Ф2"
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

## Открыто для владельца

- **Р-1** (плоскость ошибок, M8) — без него Task 1.3 не начать; рекомендация плана — (а).
- **Р-8** (паритет инструментов ↔ документов) — до Ф5; рекомендация — повесить на `backend_ctl/README.md`.
- Следующие без развилок: **Task 1.2** (лаунчер и ранние записи, M14/m3), **Task 1.4** (голоса окном).

Связано: [[project_observation_port_progress]], [[feedback_pytest_owns_threading_excepthook_for_the_session]],
[[feedback_a_list_walking_guard_cannot_see_a_removed_item]].
