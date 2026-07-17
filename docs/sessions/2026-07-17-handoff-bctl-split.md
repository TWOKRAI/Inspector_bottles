# Handoff: backend_ctl driver.py split (для нового чата)

- **Дата:** 2026-07-17
- **main:** `5aedbbca` (локальный, +25 от origin/main — НЕ запушен)
- **Для:** нового чата — задача **сплит `backend_ctl/driver.py`** с директивой «сделать красиво»
- **Ветка задачи:** создать `refactor/backend-ctl-driver-split` от main

---

## TL;DR

Прошлая сессия закрыла две волны в main: **телеметрия** (dashboard+фикс+ADR-PM-018+ниты) и **backend_ctl Phase 2** (observability_tail + watch_like_gui + introspect.memory), затем **Fable-ревью → фиксы F1-F7 + hardening**. Всё в main, ~300+ тестов зелены. Остался **структурный долг: `driver.py` разросся до ~1567 строк** (god-file). Задача нового чата — **разбить его на пакет** на текущей раскладке (без codemod) + **вычистить процессные комментарии** (следы AI-разработки).

---

## Задача: сплит `backend_ctl/driver.py`

### Почему сейчас и без codemod
План `plans/backend-ctl-framework-module.md` (раздел «РАЗВЯЗКА СПЛИТА ⟂ ПЕРЕЕЗДА», 2026-07-17) склеивал два дела в Phase 1: **(a) сплит** god-file и **(b) переезд** в `multiprocess_framework/tooling/backend_ctl/`. На codemod layer-grouping гейтится **только (b)**. Сплит (a) делается на ТЕКУЩЕЙ раскладке отдельным заходом; последующий `git mv` уже разбитых файлов в `tooling/` остаётся чистым. Секвенция: **F1-F7 (done) → сплит (эта задача) → post-codemod переезд**.

### Что разбить (целевая структура — пакет `backend_ctl/driver/`)
`driver.py` (1567 строк, класс `BackendDriver`) смешивает: транспорт (сокет/reconnect) + протокол (request_id-матчинг/unwrap) + event-bus (subscribe/events/dispatch) + датаклассы результатов + ~30 обёрток доменов (introspect/telemetry/log-tail/observability/watch/state). Разбить по образцу карты Phase 1 из плана:
- `transport.py` — сокет-клиент, connect/close/reconnect, `dispatch_raw`, read-loop
- `protocol.py` — request/request_id-матчинг, `unwrap`/`_leaf_result`, карантин таймаутов
- `events.py` — событийный канал (`subscribe`/`events`/`_emit_event`)
- `subscriptions.py` — durable-реестр (`_register_subscription`/`export`/`import`/`replay`)
- `results.py` (или `protocol_types.py`) — типизированные датаклассы (`MemoryStats`, introspect-результаты)
- `domains/` — обёртки по доменам: `introspect.py`, `telemetry.py`, `observability.py` (tail+records), `watch.py` (watch_like_gui+resub+applier), `logs.py`, `state.py`, `ui.py`
- `driver.py` — тонкий `BackendDriver`, композирующий вышеперечисленное (mixins или делегация)
Поведение **бит-в-бит**, характеризация — существующие unit-тесты на новых импортах. `backend_ctl/driver.py` → re-export-шим (`from .driver import BackendDriver, GUI_DEFAULT_PATTERNS, OBSERVABILITY_RECORD_COMMAND, MemoryStats, …`) чтобы `from backend_ctl.driver import BackendDriver` продолжал работать (потребители: `mcp_tools.py`, `mcp_server.py`, `harness.py`, тесты, probe-скрипты).

### ДИРЕКТИВА ВЛАДЕЛЬЦА — «сделать красиво» (production-grade)
При разбиении **вычистить рабочие/процессные комментарии** AI-разработки, оставить чистые смысловые (полный текст — в плане, раздел развязки):
- **убрать:** хеши коммитов (`фикс 67bdad49`, `(ea7009d1)`), пометки ревью (`баг ревью`, `Fable`, `фикс A`, `нит #N`, `F1/F3`, `finding-1 ревью 1.2`), inline-номера задач в теле/докстроках (`Task 2.2`, `Ф5.20b`, `п.5 ТЗ`, `(Ф1 Task 1.2)`)
- **оставить и переформулировать без «я/агент/ревьюер»:** комментарии про ПОЧЕМУ (инвариант/грабли — напр. «resub из reader-потока = дедлок → applier-поток»; «atomic-rebind: heartbeat итерирует .values() в другом потоке»)
- докстроки — по делу (Args/Returns/поведение/инвариант), без процессных хвостов
- итог: код читается как чистый production-модуль, не журнал AI-работы. Правило — эталон и для будущих модулей.

### Acceptance
- `pytest backend_ctl/tests/ -q` (кроме `*_live.py`/`harness_smoke`) зелёный на новых импортах; поведение бит-в-бит
- `from backend_ctl.driver import BackendDriver` (и прочие символы) работает через шим
- ruff + pyright чисто; НЕ гонять `test_mcp_server_live_against_backend` (красный pre-existing на этой машине — SHM/spawn WinError, не регресс)
- НИ ОДНОГО процессного комментария (хеш/ревью-пометка/Task-номер) в новых файлах — grep-самопроверка

---

## Состояние backend_ctl (что уже в main)

- **Phase 0** hardening ✅ (`cfc3e531`, второй чат)
- **Phase 2** на текущей раскладке ✅: 2.1 `observability_tail`, 2.2 `watch_like_gui`+авто-resub, 2.4 `introspect.memory`
- **Fable-ревью F1-F7** ✅ (`7410f566`…`de1d0557`) + hardening `6b1c3441` (atomic-rebind hot-path)
  - F1: per-subscriber observability-форвардер (watch не угоняет obs-хвост у GUI); **смена wire-контракта** `observability.tail.unsubscribe` (несёт `subscriber`)
  - F2 реконнект-durable + re-watch манифест (mcp_server), F3 гонка unwatch↔resub (само-исцеление), F4 listener до подписок, F5 severity-фильтр `tail_level`, F6 pool из публичного `router.get_stats()`, F7 контракт-тест
- **Отложено:** 2.3 telemetry read-model (блокер coherence Task 3.5); Phase 1 переезд + Phase 3 MCP-SDK + Phase 4 — post-codemod
- **Верификация:** live — `introspect_memory`/`watch`/state/авто-resub/`log_tail` работают; F1 dual-consumer доказан **unit'ом** (два подписчика+fan-out), live-content недостижим (observability-плоскость тиха в dualcam_synth: store rowCount=0, stats→state по ADR-136) — деталь в [[project_backend_ctl_framework_module]]

## Память (обновлена, dual-write)
`project_backend_ctl_framework_module` — Phase 0+2, Fable F1-F7, уроки (авто-resub дедлок→applier, atomic-rebind hot-path fan-out, «тихие плоскости → unit-пруф не live»). Плюс `project_telemetry_dashboard`, `project_telemetry_publish_control`.

## Грабли / заметки для нового чата
- **main НЕ запушен** (+25 от origin) — если нужно, `git push` по решению владельца.
- **worktree-хвосты:** `.claude/worktrees/agent-*` (5 шт, merged) — можно `git worktree remove --force` + `git worktree prune` (в прошлой сессии команда была denied — запускать точечно/с подтверждением). `Inspector_bottles_bctl` — второй чат, НЕ трогать.
- **session-log конфликты** при merge веток: `docs/sessions/2026-07-17.md` — авто-append pre-commit хука, резолв union (`sed '/^<<<<<<< /d; /^=======$/d; /^>>>>>>> /d'`).
- **Коммиты:** trailers `Why:`/`Layer:` + `Refs: plans/backend-ctl-framework-module.md`; pre-commit ruff-format → re-stage.
- **Тесты:** проектный `.venv/Scripts/python.exe` ([[feedback_always_project_venv]]).
