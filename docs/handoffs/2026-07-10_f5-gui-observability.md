# Handoff — Ф5 GUI state-plane + observability persistence (2026-07-10)

**Читать первым для продолжения Ф5 (задачи 5.19 + 5.20b).**

## Что влито в main (merge fd963396, `--no-ff`)

Ветка `feat/gui-state-plane` (11 коммитов) в main. Gate: framework/modules **3926 passed**, prototype **2953 passed**. Live-провалидировано через `backend_ctl` (region_pipeline).

### Ф5.9 GUI state-plane ✅
- `state_delta_message` (`multiprocess_prototype/frontend/state/delta_message.py`) — единый envelope Delta→bridge (value/**deleted**/old_value/**transaction_id**/source). Раньше delete терялся (sentinel MISSING протекал в setter).
- `bindings.py`: delete-обработка (`BindingHandle.reset`, флаг `deleted`); **fan-out на delete получает sentinel `DELETED`** (экспорт из `frontend.state`), не None — потребитель динамических строк отличает удаление.
- `StateProxy.ensure_subscription`/`release_subscription` — refcount по паттерну; `GuiStateBindings.bind/unbind` авто-подписывают (закрыт класс «панель мертва, забыли wildcard»). Обратная карта `_sub_id_pattern` → O(1) unsubscribe.
- frontend `glob_match` → делегат в framework `match_pattern` (один матчер).

### Ф5.20a persistent-стор ✅
- `ObservabilityStore` (`channel_routing_module/observability/observability_store.py`) — SQLite/WAL/`synchronous=NORMAL`, путь `<INSPECTOR_LOG_DIR>/observability.db`. API: `append_records` / `list_records(kind, module, severity_in, offset, limit, newest_first)` / `count` / `clear` / `.dropped`.
- **Наполнение (решение владельца):** log/stats — пачкой из drain-петли ProcessModule (heartbeat); **error — через `StoreTapChannel` на logger_manager И error_manager** (min ERROR). **Live-урок:** приложение логирует ошибки через `ctx.log_error`/`logger.error` (logger_manager), а НЕ error_manager (напр. `Plugins/sources/capture/plugin.py:222`) — tap только на error_manager давал error=0. См. память `project_observability_store_error_routing`.

## Code-review (8 finder-агентов, high) — 8/10 findings закрыто

Закрыто: refcount-leak при reap, fan-out delete (DELETED), блокировка heartbeat (synchronous=NORMAL + `.dropped`), warn при отсутствии tap, `severity_in` (membership+lowercase), Delta.is_delete, StoreTapChannel→IChannel, O(1) unsubscribe.

**НЕ закрыто (осознанно) — учесть в 5.19/5.20b:**
- **#4** `app.py:_forward_state_delta_to_topology` на delete делает early-return — узел НЕ удаляется из RegistersManager (призрак). Нужен topology-level remove (отдельная фича).
- **#5** double-write: tap на двух менеджерах без idempotency-ключа. Если код и логирует, и track'ает одну ошибку → 2 строки. При проявлении — dedup по `transaction_id` (в записях его сейчас нет).

## СЛЕДУЮЩЕЕ: 5.20b + 5.19 (делать вместе)

### 5.20b hub→GUI live-tail (плумбинг, ОТЛОЖЕН сюда)
Живой хвост записей в GUI — **отдельным каналом, НЕ state-дельтой**. Паттерн — как `log_tail` (`process_module/commands/builtin_commands.py:723` `_cmd_log_tail_subscribe`): router-push `targets=[gui]`, `queue_type=system`. Дизайн:
- Процесс-side: форвардер push'ит дренированные записи (и/или tap) на GUI-subscriber с `data_type="observability_record"`.
- GUI-side: `DataReceiverBridge.dispatch` уже классифицирует по data_type (`bridge_impl.py:73`) — добавить ветку "observability_record" (kind "state"-подобный, но отдельный listener API, НЕ state_updated). Подписка панели.
- Подписка/активация: mirror `log_tail` subscribe-команды (иначе форвардер «мёртв» без подписчика).
- e2e-приёмка: эмиссия в модуле → вкладка показывает запись — **нужен живой backend (backend_ctl) + виджет 5.19**, поэтому и делать вместе.

### 5.19 виджет 3 вкладок Логи/Ошибки/Статистика (M)
- Обобщить `AuditLogPanel` (`frontend/widgets/tabs/settings/administration/audit_log_panel.py`, база `BaseAdminPanel`, несёт ~90%) → переиспользуемая `RecordHistoryPanel` (+ presenter/Protocol, фильтр по уровню, источник/канал, кнопка **Копировать**, live-append). Инстанс на 3 вкладки, каждая на свой kind.
- **Целая история** — пагинацией из `ObservabilityStore.list_records` (стор уже готов, 5.20a). **Живой хвост** — из hub→GUI-канала (5.20b).
- **Убрать 4 поддельные state-дельты** (`app.py:851-871`: chain_fps/chain_latency_ms/trace_segments/trace_branches) — питают панель «Все процессы» (`_panels.py:491-509`), GUI-вычисляемы → нужен замещающий GUI-локальный маршрут, иначе регресс.
- `history/` MVP (settings/history/) — НЕ трогать (домен undo/redo).
- Зависимости: 5.9 (state-plane, ✅) + 5.20 (источник данных).

## Инфра для live-проверки
- Boot headless: `BackendHarness(port=8765, recipe=None→region_pipeline)`, `BACKEND_CTL=1`. Только файлом с `if __name__=="__main__": multiprocessing.freeze_support()` (spawn на macOS). Свой `INSPECTOR_LOG_DIR` → там `observability.db`.
- MCP `backend-ctl` подключается к 127.0.0.1:8765 как второй клиент (один бэкенд — ловушки «два бэкенда» нет).
- Камеры физической нет (только веб-камера) → ошибка «не удалось открыть камеру 0» ожидаема, полезна как live error-кейс.

## Прочее по Ф5
- Свободны: **5.8** RuntimeDeps (M), **5.18** depth-reduction (вернуть depth≥0.60, M), **5.6a** diff-отчёт форм→GATE G2.
- Крупная **5.3** recipe-orchestrator (M+M, отдельная сессия) → за ней блокированы **5.11–5.13** app_module skeleton (+3 вопроса скоупа).
- main НЕ запушен в origin (206 коммитов впереди; push owner-gated).
- Грязное рабочее дерево (`.claude/agent-memory/*`, `uv.lock`, `health/.claude/`) — не относится к Ф5, было грязным с начала.
