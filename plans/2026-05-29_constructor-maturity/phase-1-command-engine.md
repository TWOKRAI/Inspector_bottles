# Phase 1 — Примирение движка команд/undo (один движок + pluggable middleware)

- **Slug:** constructor-maturity / phase-1
- **Дата:** 2026-05-29
- **Статус:** DETAILED (ожидает approval + старт P0-gate). P1.1 = read-only investigation (обязателен ПЕРВЫМ).
- **Ветка:** `refactor/constructor-maturity`
- **Master:** [`plan.md`](plan.md)

## Назначение

После cross-tab рядом живут **две системы команд/undo**:
- **domain-dispatch** (`adapters/dispatch/command_dispatcher.py` + `ProjectHistory`) — snapshot-undo, typed commands → `Project.apply()` → typed events. Забрал топологию (AddProcess/RemoveProcess/ConnectWire/SetPluginConfig).
- **framework ActionBus** (`actions_module/bus.py`) — patch-undo (forward/backward dict), завязан на `rm`, несёт зрелую инфраструктуру: **PreAuthGuard (RBAC), AuditMiddleware, SQL action_log (`IActionLogWriter`), coalescing, `undo_to(id)`**. Жив для `ROLE_UPDATE` (roles_panel), `NODE_MOVE`, `RECIPE_APPLY`.

**Проблема:** дублирование машинерии (orchestrator сам себя называет «Зеркало framework ActionBus») + зрелые фичи (auth/audit) **не перенесены** на domain-путь → топология, возможно, мутируется без RBAC-hook и без audit-лога.

**Цель P1:** один движок команд для editor-домена (**domain-dispatch**) с **pluggable middleware**, в которые инжектируются auth/audit, поднятые из ActionBus. Убрать дублирование и мёртвый код. Это фундамент: в framework (P6) поедет ОДИН примирённый движок, не два.

> **Дизайн-направление (path A из обсуждения):** domain-dispatch = единственный движок editor-домена; ActionBus-фичи (RBAC pre-hook, audit post-hook) становятся **переиспользуемыми middleware** поверх dispatch. ActionBus либо удаляется (если ROLE_UPDATE/NODE_MOVE/RECIPE мигрируют), либо остаётся узким инфра-слоем — **решает P1.1 по фактам**.

## Источники истины

| Документ | Что |
|---|---|
| `adapters/dispatch/command_dispatcher.py` | domain-dispatch: `dispatch/undo/redo/_restore/_emit_config_diff`, change-callbacks |
| `multiprocess_framework/modules/actions_module/bus.py` | ActionBus: execute/record/undo/redo, pre_execute_hook, post_execute, log_writer |
| `multiprocess_prototype/frontend/actions/` | bus_factory, middleware (PreAuthGuard, AuditMiddleware), handlers |
| `Services/sql/action_log/` | потребитель action-log (audit persistence) — проверить связь |
| [`plan.md`](plan.md) §P1, принципы | scope, no-big-bang, engine-vs-model |

> **Правило:** перед каждой задачей P1.x — `grep` актуальных call-sites (память устаревает).

---

## Декомпозиция

```
P1.1 investigation (read-only) ──> P1.2 middleware-контракт ──> P1.3 auth+audit на dispatch ──> P1.4 миграция/изоляция ActionBus ──> P1.5 dead-code + verify
```

| Под-фаза | Описание | Scope | Зависит | Статус |
|---|---|---|---|---|
| **P1.1** | Investigation: реально ли топология потеряла RBAC/audit; кто ещё на ActionBus; что пишет action_log | read-only | — | **DONE** ([audit](../../docs/refactors/2026-05_command_engine_audit.md), вердикт A) |
| **P1.2** | Middleware-контракт поверх domain-dispatch: `pre_dispatch`/`post_dispatch` хуки (Protocol), без логики | S (domain+adapters) | P1.1 | манифест |
| **P1.3** | Поднять PreAuthGuard + AuditMiddleware как middleware dispatch'а; топология снова RBAC+audit | M | P1.2 | манифест |
| **P1.4** | Решить судьбу ActionBus: мигрировать ROLE_UPDATE/NODE_MOVE/RECIPE на dispatch ИЛИ зафиксировать ActionBus как узкий инфра-слой | L | P1.3 | манифест |
| **P1.5** | Удалить мёртвый `frontend/actions/` (что не нужно), cumulative verify, ADR | S-M | P1.4 | манифест |

> Детализируются P1.2–P1.5 только после deliverable P1.1 (факты решают форму middleware и судьбу ActionBus).

---

## Task P1.1 — Investigation: audit/RBAC-разрыв и потребители ActionBus (read-only)

**Level:** Senior (investigator, Opus) — read-only, диагностика, без правок кода.
**Assignee:** investigator
**Goal:** Закрыть фактами открытый вопрос из обсуждения: **реально ли** мутации топологии (теперь через domain-dispatch) потеряли RBAC-гейтинг и audit-лог, и кто ещё фактически зависит от framework ActionBus. От этого зависит форма P1.2–P1.4.

**Вопросы расследования (отвечать `file:line` + вывод):**
1. **Audit-лог.** Кто вызывает `bus.set_log_writer(...)`? Какой `IActionLogWriter` подключён в проде (app.py)? Какие `action_type` реально доходят до `action_log` (SQL)? → Попадали ли туда топологические мутации ДО cross-tab, и попадают ли сейчас (после миграции на dispatch)?
2. **RBAC.** `PreAuthGuard` блокирует `WriteAction` до авторизации. Топологические мутации сейчас идут через `dispatch()` (без pre-hook). Чем гейтится создание/удаление процесса сейчас — permission_gate на виджетах/табах, или ничем? Есть ли реальная дыра «неавторизованный может мутировать топологию»?
3. **Живые потребители ActionBus.** Полный список `bus.execute/record/undo/redo` в проде: ROLE_UPDATE (roles_panel), NODE_MOVE, RECIPE_APPLY — подтвердить + найти прочие. Для каждого: завязан ли на `rm`, на patch-undo, на coalescing.
4. **Coalescing/undo_to.** Использует ли кто-то `undo_to(action_id)` или coalescing ActionBus в проде (фичи, которых нет у ProjectHistory)?
5. **action_log как продукт.** `Services/sql/action_log` — это требование (нужен журнал всех действий) или legacy? Кто читает action_log (UI History-вкладка? экспорт?)?
6. **Дубль change-callbacks.** Где `MainWindow`/History-вкладка подписаны — на ActionBus или на dispatch (`add_change_callback`)? Нет ли двойной подписки/двойного refresh.

**Deliverable:** `docs/refactors/2026-05_command_engine_audit.md` — факты по 6 вопросам + **рекомендация**: (A) dispatch-единственный + middleware; (B) dispatch для editor + ActionBus узкий инфра-слой для auth-домена; (C) гибрид. С обоснованием от фактов.

**Acceptance criteria:**
- [x] Все 6 вопросов отвечены с `file:line`-доказательствами
- [x] Явный вердикт: RBAC — частично потерян (field-edit дыра); audit — не было в проде вообще (с пруфом)
- [x] Полный inventory живых потребителей ActionBus (0 исполняющих в проде; таблица call-site → фичи)
- [x] Рекомендация A (один движок + middleware) с 2 поправками → вход для детализации P1.2
- [ ] Deliverable-документ ✅ создан + commit `docs(refactors): P1.1 command-engine audit` (ожидает commit)

> **Находки сверх плана:** (1) `ActionBus` в проде осиротел — 0 исполняющих потребителей, не «два движка», а один + мёртвый код; (2) audit/`action_log` в проде **никогда** не подключались → P1.3 audit = новая фича, не регрессия; (3) узкая RBAC-дыра: field-edit (`SetPluginConfig`) не гейтится `_can_edit()`; (4) framework-forms (`FormContext→ActionBus`) обходятся прототипом (`form_ctx=None`) → связка P1↔P2. Открытые вопросы владельцу: нужен ли `action_log` как продукт; ОК ли точечный фикс field-edit RBAC до системного middleware.

**Out of scope:** любые правки кода; детализация P1.2+ (после approval этого отчёта).
**Edge cases:** action_log может писаться асинхронно/через Services — проверить реальный путь, не только наличие writer.

---

## P1.2–P1.5 — манифест (детализируются после P1.1)

- **P1.2 Middleware-контракт.** Добавить в domain `CommandDispatcher` Protocol точки расширения `pre_dispatch(cmd) -> bool` / `post_dispatch(cmd, events) -> None` (имена уточнит P1.1). Чистый контракт, без auth/audit-логики — domain остаётся UI/framework-agnostic (middleware-реализации живут в adapters/frontend). Симметрия `add_change_callback`, который уже есть.
- **P1.3 Auth+audit на dispatch.** Перенести `PreAuthGuard` (как `pre_dispatch`) и `AuditMiddleware`+log-writer (как `post_dispatch`) на domain-dispatch. Топология снова RBAC-гейтится и пишется в action_log (если P1.1 подтвердит требование). ActionBus-версии — не трогать до P1.4.
- **P1.4 Судьба ActionBus.** По рекомендации P1.1: либо мигрировать ROLE_UPDATE/NODE_MOVE/RECIPE на dispatch (NODE_MOVE — возможно остаётся GUI-only вне домена), либо зафиксировать ActionBus как узкий инфра-слой auth-домена. Цель — **один движок editor-домена**, без конкуренции.
- **P1.5 Dead-code + verify.** Удалить неиспользуемое из `frontend/actions/` (V2ActionBuilder/handlers, ставшие мёртвыми). Cumulative: тесты зелёные, sentrux check_rules 9/9, ADR «один движок команд + middleware» (`adapters/DECISIONS.md` или domain). Live boot-smoke (qt-mcp) — undo/redo + RBAC + audit на живой системе.

---

## Риски P1

| Риск | Уровень | Митигация |
|---|---|---|
| P1.1 покажет, что audit-лог реально нужен и потерян → скрытая регрессия безопасности/комплаенса | **до выяснения HIGH** | P1.1 первой задачей, фактами; P1.3 восстанавливает |
| Миграция RECIPE_APPLY (IPC hot-swap) при изоляции ActionBus | HIGH | если P1.4 решит мигрировать — отдельный аккуратный заход + live-smoke (как G.6.5) |
| Middleware на dispatch ломает синхронный порядок save→events | MED | контракт P1.2: pre до apply, post после publish; тесты на реальном store+EventBus |
| Premature: чинить то, что и так работало (full-reload, permission_gate) | MED | P1.1 решает фактами, а не премисой; не трогать рабочее без пруфа дыры |

## Out of scope Phase 1

- Granular scene-updates / ликвидация `PipelineModel`-dict — **P3**.
- Единый манифест плагина / domain-Inspector — **P2**.
- Вынос движка в framework — **P6** (после app #2).
