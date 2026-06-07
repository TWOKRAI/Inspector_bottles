# Phase 1: Контракт reconfigure + инвалидация кэша

**Цель фазы:** дать всем CRM-менеджерам единый метод `reconfigure(config: dict)`,
который пересобирает каналы/маршруты из dict, и закрыть критический баг — `should_log()`
кэширует решения без инвалидации. Это фундамент, к которому позже подключаются watcher
(Phase 3) и IPC-команды (Phase 4).

---

### Task 1.1 — `reconfigure(config)` на CRM + invalidate-cache в Logger **[VERTICAL SLICE]**

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Базовый `reconfigure(config: dict)` на `ChannelRoutingManager` (full-rebuild каналов из dict) + override в `LoggerManager`, инвалидирующий `_decision_cache`; доказано smoke-тестом E2E.

**Context:** Это единая точка, в которую позже войдут hot-reload и IPC-команды. Reuse-first:
вся механика реестра каналов, Dispatcher и `_close_all_channels()` уже есть в CRM
(channel_routing_module/core/channel_routing_manager.py:361). LoggerManager уже умеет
строить каналы из конфига в `_setup_channels()` (logger_manager.py:186). Дописываем тонкую
обёртку «закрыть старое → применить новый dict → построить заново», а в Logger — сброс кэша.
Баг: `should_log()` кладёт решение в `self._decision_cache` (logger_manager.py:301-309) и
**никогда** не инвалидирует — после смены `default_level`/scope старые решения залипают.

**Files:**
- `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py` — добавить базовый `reconfigure(config: dict) -> bool` и хук `_rebuild_from_config(config: dict)` (по умолчанию no-op, наследники переопределяют). Базовый `reconfigure` оркеструет: `flush()` → `_close_all_channels()` → `self._config = normalize_config(config)` → `_rebuild_from_config(config)` → лог.
- `multiprocess_framework/modules/channel_routing_module/interfaces.py` — добавить в `IChannelRoutingManager` абстрактный/дефолтный контракт `reconfigure(self, config: Dict[str, Any]) -> bool`.
- `multiprocess_framework/modules/logger_module/core/logger_manager.py` — добавить `invalidate_decision_cache()` (очищает `self._decision_cache`); переопределить `_rebuild_from_config()`: заново применить `LoggerManagerConfig` через `_resolve_log_config()`, вызвать `_setup_channels()` + `_setup_batcher()`, затем `invalidate_decision_cache()`.
- `multiprocess_framework/modules/channel_routing_module/tests/test_channel_routing_manager.py` — unit на базовый `reconfigure` (каналы пересозданы).
- `multiprocess_framework/modules/logger_module/tests/test_logger_manager.py` (создать если нет — сверься с существующими тестами модуля через Glob) — smoke E2E.

**Steps:**
1. В CRM добавить `_rebuild_from_config(self, config: dict) -> None` (no-op база) и публичный `reconfigure(self, config: dict) -> bool` с try/except и логом через `self._log_info`. Внутри: `self.flush()`, закрыть текущие каналы (`_close_all_channels()` уже чистит реестр и закрывает), пересоздать Dispatcher-маршруты при необходимости (для Logger каналы регистрируются прямо в `_channel_registry`, без route — учесть это).
2. ВНИМАНИЕ к различию: LoggerManager регистрирует каналы через `self._channel_registry.register(channel)` напрямую (logger_manager.py:229), а CRM `register_channel()` дополнительно вешает handler в Dispatcher. `_rebuild_from_config` в Logger должен повторить именно логику `_setup_channels()`, плюс очистить `self._module_channels`.
3. В Logger override `_rebuild_from_config`: `self.config = self._resolve_log_config(config)`; очистить `self._module_channels` (закрыть каналы); вызвать `_setup_channels()`; `_setup_batcher()`; `invalidate_decision_cache()`.
4. Добавить `invalidate_decision_cache(self) -> None: self._decision_cache.clear()`.
5. Smoke-тест E2E: создать `LoggerManager(config={...file-канал, default_level INFO...})`, `initialize()`, залогировать DEBUG (должен быть skipped и закэширован как False), затем `reconfigure({...default_level DEBUG...})`, снова DEBUG — теперь должен пройти (кэш инвалидирован). Проверить, что новый канал присутствует в `get_all_channels()`.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/channel_routing_module/tests/test_channel_routing_manager.py -q` — green.
- [ ] `python -m pytest multiprocess_framework/modules/logger_module/tests/ -q` — green.
- [ ] Smoke-тест: после `reconfigure` со сменой `default_level` старое закэшированное решение `should_log` инвалидировано (assert на изменившийся результат).
- [ ] После `reconfigure` со сменой набора каналов `get_all_channels()` отражает новый набор (старые закрыты).
- [ ] `python scripts/validate.py` — без новых ошибок.

**Out of scope:** diff-апдейт каналов (только full-rebuild); StatsManager/ErrorManager override (Task 1.2/1.3); подключение watcher (Phase 3).
**Edge cases:** reconfigure до `initialize()` (буфер не стартован) — не падать; пустой/невалидный dict → лог-warning + вернуть False, не ронять процесс; повторный reconfigure подряд (идемпотентность).
**Dependencies:** нет.
**Module contract:** public-api-change (новый публичный метод на `IChannelRoutingManager`).

---

### Task 1.2 — `reconfigure` override в StatsManager

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `StatsManager._rebuild_from_config(config)` пересоздаёт каналы агрегации (LogStatsChannel/FileStatsChannel) из dict, сохраняя живые метрики.

**Context:** Reuse-first: `StatsManager._setup_channels()` (stats_manager.py:117) уже строит
каналы из `self._config_dict`. Базовый `reconfigure` из Task 1.1 закроет старые каналы;
override должен обновить `self._config_dict` через `normalize_config` и вызвать `_setup_channels()`.
Буфер агрегации (`AggregationWindow`) и live-`self._metrics` НЕ сбрасываются (метрики переживают reconfigure).

**Files:**
- `multiprocess_framework/modules/statistics_module/core/stats_manager.py` — override `_rebuild_from_config(config)`: обновить `self._config_dict = normalize_config(config, default={})`, обновить `self._default_tags`, вызвать `_setup_channels()`. Не трогать `self._metrics` и буфер.
- `multiprocess_framework/modules/statistics_module/tests/test_stats_manager.py` (сверься через Glob) — unit на reconfigure (каналы сменились, метрики живы).

**Steps:**
1. Override `_rebuild_from_config(self, config: dict) -> None`.
2. Обновить `self._config_dict`, `self._default_tags` из нового dict.
3. Вызвать `self._setup_channels()` (он сам добавит LogStats/FileStats по новому конфигу).
4. НЕ вызывать reset метрик.
5. Тест: записать метрику → reconfigure со сменой `channels` → метрика читается через `get_metric()`, набор каналов сменился.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/statistics_module/tests/ -q` — green.
- [ ] После reconfigure `get_all_metrics()` сохраняет ранее записанные метрики.
- [ ] Набор каналов соответствует новому конфигу.

**Out of scope:** remote-stats / router-интеграция; смена flush_interval на лету (буфер уже создан — задел Phase 4).
**Edge cases:** reconfigure с `enable_logging=False` и без logger-менеджера → fallback-канал создаётся (логика уже в `_setup_channels`); пустой `channels`.
**Dependencies:** Task 1.1.
**Module contract:** public-api-change.

---

### Task 1.3 — `reconfigure` override в ErrorManager

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `ErrorManager._rebuild_from_config(config)` пересоздаёт каналы (наследует Logger) и перестраивает `_level_to_channel` через `_setup_level_routes()`.

**Context:** ErrorManager наследует LoggerManager (error_manager.py:112), поэтому базовая
пересборка каналов придёт из Task 1.1. Специфика — severity-routing `_level_to_channel`
(error_manager.py:167) строится в `_setup_level_routes()` по наличию каналов
`critical_file/errors_file/warnings_file`. После пересборки каналов надо его перестроить.
Также конфиг ErrorManager проходит через `_normalize_error_config` / `expand_error_manager_config` —
reconfigure должен принять и плоский error-dict, и развёрнутый.

**Files:**
- `multiprocess_framework/modules/error_module/core/error_manager.py` — override `_rebuild_from_config(config)`: нормализовать через `_normalize_error_config(config)`, применить `LoggerManagerConfig`, вызвать parent-логику пересборки каналов, затем `_setup_level_routes()`; обновить `self._include_stacktrace`.
- `multiprocess_framework/modules/error_module/tests/test_error_manager.py` (сверься через Glob) — unit на reconfigure (level-routes перестроены).

**Steps:**
1. Override `_rebuild_from_config(self, config: dict) -> None`.
2. `name, log_config, include_stacktrace = _normalize_error_config(config)`; `self._include_stacktrace = include_stacktrace`; `self.config = log_config`.
3. Переиспользовать пересборку каналов из родителя (вынести общую часть Logger в helper, если удобно, либо вызвать те же `_setup_channels()`/`_setup_batcher()` + `invalidate_decision_cache()`).
4. Вызвать `self._setup_level_routes()`.
5. Тест: reconfigure со сменой набора severity-каналов → `get_stats()["level_routes"]` отражает новый маппинг.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/error_module/tests/ -q` — green.
- [ ] После reconfigure `_level_to_channel` соответствует наличию каналов (assert через `get_stats()["level_routes"]`).
- [ ] `include_stacktrace` обновляется из нового конфига.

**Out of scope:** изменение публичного `log()`-поведения; новые типы severity.
**Edge cases:** конфиг без warnings_file → WARNING падает на errors_file (логика уже в `_setup_level_routes`); пустой dict → defaults (`_DEFAULT_CONFIG`).
**Dependencies:** Task 1.1.
**Module contract:** public-api-change.
