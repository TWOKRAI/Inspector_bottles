# Phase 4: Design-for-extension (заделы, без реализации)

**Цель фазы:** зафиксировать точки расширения так, чтобы будущие итерации (SQLChannel,
SocketChannel-push, IPC-команды `logger.sink.enable` / `config.reload` / `stats.subscribe`,
cross-process remote-stats, GUI-вкладка) подключались к уже построенному контуру
`reconfigure` + реестр sink-фабрик **без переделки**. Реализация — НЕ в этой итерации.

---

### Task 4.1 — Документ-контракт точек расширения

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Короткий ADR/DECISIONS-документ, фиксирующий, КАК будущие фичи подключаются к `reconfigure()` и реестру sink-фабрик, с явными сигнатурами-якорями (без кода фич).

**Context:** Reuse-first доведён до предела: документ не вводит новых механизмов, а показывает,
что всё необходимое уже есть — `IChannel.write` (контракт sink), `register_sink_factory`
(Phase 2), `reconfigure(config: dict)` (Phase 1), `BackendDriver` + `RouterManager.request/reply`
+ `introspect.*` (живой control plane). Цель — чтобы следующий разработчик не изобретал, а
дописывал по якорям.

**Files:**
- `multiprocess_framework/modules/channel_routing_module/DECISIONS.md` (или новый ADR через `/adr`, индекс — `multiprocess_framework/DECISIONS.md`) — раздел «Observability Control Plane: точки расширения».
- `multiprocess_framework/modules/logger_module/README.md` / `STATUS.md` — добавить ссылку на контракт sink-фабрик и `reconfigure`.
- После правок `DECISIONS.md` — запустить `python -m scripts.sync` (правило проекта №8) для пересборки сводных разделов.

**Steps (содержание документа):**
1. **SQLChannel** — новый класс `class SqlChannel(LogChannel)` (или `IChannel`), регистрируется `register_sink_factory("sql", SqlChannel)`; конфиг-секция `channels: {audit_sql: {type: sql, dsn: ...}}`. Никаких правок менеджеров. (Ссылка: comm-system plan §12 P2.)
2. **SocketChannel-push** — `class SocketChannel(IChannel)`: `write()` шлёт через `RouterManager` (Dict at Boundary, без прямого SHM — memory-правило `feedback_no_shm_hacks`). Регистрируется так же. Это путь к cross-process remote-stats.
3. **IPC-команды** → дёргают `reconfigure`: `config.reload` → `manager.reconfigure(new_dict)`; `logger.sink.enable` → toggle через `ObservableMixin.enable`/`unregister_channel`+`register_channel`; `stats.subscribe` → регистрация SocketChannel как sink. Точка входа — `BackendDriver` + `introspect.handlers` (memory `project_backend_control_mcp`). Зафиксировать имена команд и какой метод reconfigure они вызывают.
4. **GUI-вкладка** — читает `get_stats()` / `get_registered_sink_types()`, пишет через те же IPC-команды (никакого прямого доступа к менеджерам из GUI — Dict at Boundary).
5. **cross-process remote-stats** — StatsManager получает router-ссылку и SocketChannel-sink; явно отметить, что в Итерации 1 router не держится намеренно (ADR comm-system §9.7).

**Acceptance criteria:**
- [ ] Документ содержит для каждой из 4 точек: (а) какой готовый контракт используется, (б) точную сигнатуру-якорь, (в) что именно дописывается, (г) что НЕ требует правок.
- [ ] Указаны Refs на comm-system plan §12 (P2 SQLChannel, P3 audit-log) и backend-control-mcp plan.
- [ ] `python -m scripts.sync` выполнен, `python scripts/validate.py` — без дрифта документации.

**Out of scope:** любой код фич; benchmark; выбор конкретного SQL-драйвера.
**Edge cases:** n/a (документ).
**Dependencies:** Task 1.1–1.3, 2.1 (документ ссылается на их API).
**Module contract:** n/a (документация/ADR).
