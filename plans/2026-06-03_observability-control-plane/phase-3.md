# Phase 3: Единая секция конфига + hot-reload в проде

**Цель фазы:** ввести единую секцию `observability` (одна точка для Logger/Error/Stats),
реально прокинуть её из прототипа в `managers`-конфиг процессов (сейчас всё на defaults,
ErrorManager при пустом конфиге не создаётся) и подключить `ConfigFileWatcher` +
`Config.subscribe` → `reconfigure` так, чтобы правка `system.yaml` перестраивала каналы/уровни
без рестарта.

---

### Task 3.1 — Pydantic-схема `ObservabilityConfig` + expand → managers_config

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Единая схема `ObservabilityConfig` (логирование + ошибки + статистика в одной секции) с функцией `expand_observability(dict) -> {"logger": {...}, "error": {...}, "stats": {...}}`, дающей словари, совместимые с существующими `LoggerManagerConfig` / `ErrorManagerConfig` / `StatsManagerConfig`.

**Context:** Reuse-first: НЕ создаём новые менеджеры и НЕ дублируем поля — `ObservabilityConfig`
это **фасад** над тремя существующими конфигами. `expand_observability` раскладывает единую
секцию в три dict, которые `process_managers.py` (146-265) уже умеет принимать как
`managers_config["logger"|"error"|"stats"]`. Схема — `SchemaBase` (Pydantic v2), на границе
процесса всё равно dict (Dict at Boundary). Это закрывает пробел «3 разных Pydantic-конфига
без единой точки».

**Files:**
- `multiprocess_framework/modules/process_module/configs/observability_config.py` — создать: `class ObservabilityConfig(SchemaBase)` с под-секциями (`log_level`, `log_directory`, `enable_batching`, `console: bool`, `file: bool`, `errors: {...}`, `stats: {...}`) — минимальный набор, покрывающий file/console-sink Итерации 1; функция `expand_observability(data: dict) -> dict` → `{"logger": ..., "error": ..., "stats": ...}`. Сверься с полями `LoggerManagerConfig` (logger_manager_config.py), `ErrorManagerConfig`, `StatsManagerConfig`, чтобы expand давал валидные dict.
- `multiprocess_framework/modules/process_module/configs/__init__.py` — экспорт.
- `multiprocess_framework/modules/process_module/tests/test_observability_config.py` — unit: `expand_observability` даёт dict, которые `LoggerManagerConfig.model_validate` / `ErrorManagerConfig.model_validate` / `StatsManagerConfig` принимают без ошибок.

**Steps:**
1. Изучить поля трёх целевых конфигов (Logger/Error/Stats) — собрать минимальный единый фасад только для file/console + базовые уровни/батчинг.
2. Описать `ObservabilityConfig(SchemaBase)` с дефолтами, дающими рабочую триаду (важно: чтобы ErrorManager создавался — error-секция непустая по умолчанию).
3. Реализовать `expand_observability(data)`: собрать `logger`-dict (channels file+console по флагам), `error`-dict (warnings/errors/critical файлы), `stats`-dict.
4. Тест валидности всех трёх результатов.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/process_module/tests/test_observability_config.py -q` — green.
- [ ] `LoggerManagerConfig.model_validate(expand(...)["logger"])` не падает.
- [ ] `ErrorManagerConfig.model_validate(expand(...)["error"])` не падает.
- [ ] `StatsManagerConfig`-валидация `expand(...)["stats"]` не падает.
- [ ] Дефолтная (пустая) секция даёт непустой `error`-dict (чтобы ErrorManager создавался).

**Out of scope:** SQL/Socket-секции (задел Phase 4); per-module channels editor; миграция старых managers-конфигов.
**Edge cases:** частичная секция (только `log_level`) → остальное defaults; неизвестные ключи игнорируются/валидируются по политике SchemaBase.
**Dependencies:** нет (можно параллельно Phase 1).
**Module contract:** new-lite (новый single-file публичный модуль конфигурации).

---

### Task 3.2 — Прокидка секции `observability` из прототипа в managers-конфиг процессов

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** В прототипе секция `observability` из `system.yaml` (sys_config) реально доходит до `managers_config` каждого процесса; ErrorManager перестаёт зависеть от случайного пустого конфига.

**Context:** Reuse-first: конвейер уже есть — `system.yaml → load_system_config →
_merge_defaults(blueprint, sys_config) → SystemBlueprint → build_configs() →
ProcessConfiguration.managers → config_handler.get_managers_config()` (launch.py:234,247;
process_config_handler.py:106). Дописываем: (1) добавить секцию `observability` в схему
sys_config и в `system.yaml`; (2) в `_merge_defaults` (или build_configs) разложить
`observability` через `expand_observability` в `managers` каждого процесса. Это закрывает
пробел «прототип НЕ передаёт managers_config — всё на defaults».

**Files:**
- `multiprocess_prototype/backend/config/schemas.py` — добавить секцию `observability` в системную схему (sys_config). Сверься с фактической структурой (где `system`, `discovery`, `backend_ctl`).
- `multiprocess_prototype/backend/config/system.yaml` (или фактический путь — `multiprocess_prototype/backend/config/`, см. CONFIG_PATH в main.py:34) — добавить секцию `observability` с дефолтами (file+console, INFO).
- `multiprocess_prototype/backend/launch.py` — в `_merge_defaults` / `build()` (около 234-251): прокинуть `expand_observability(sys_config.observability.model_dump())` в `managers` каждого process-config (или в blueprint defaults так, чтобы дошло до `ProcessConfiguration.managers`). Сверься, как сейчас формируются `configs` и есть ли у них `.managers`.
- `multiprocess_prototype/backend/config/tests/` — тест: после build у process-config непустой `managers` с logger/error/stats.

**Steps:**
1. Найти точку, где формируется `managers` для процессов (через `_merge_defaults` в blueprint dict или после `build_configs`).
2. Прокинуть expand-результат как defaults для `managers` (не затирая явные per-process переопределения, если есть).
3. Убедиться, что ErrorManager теперь создаётся (его секция непустая) — проверить через `_create_error_manager` (process_managers.py:168).
4. Тест на наличие managers-секций.

**Acceptance criteria:**
- [ ] После сборки прототипа `config_handler.get_managers_config()` процесса содержит `logger`, `error`, `stats` (не пусто).
- [ ] ErrorManager реально создаётся (в `ManagersBundle.error is not None`).
- [ ] Smoke прототипа (`/run-proto` или существующий launch-тест) стартует без регрессий.
- [ ] `python -m pytest multiprocess_prototype/backend/config/tests/ -q` — green.

**Out of scope:** per-process разные секции observability (Итерация 1 — общая для всех; cross-process — позже); GUI-редактор секции.
**Edge cases:** отсутствие секции `observability` в yaml → defaults из схемы; явные per-process managers в blueprint имеют приоритет над общим observability.
**Dependencies:** Task 3.1.
**Module contract:** n/a (конфиг + прокидка, не контракт модуля).

---

### Task 3.3 — Подключение `ConfigFileWatcher` + `Config.subscribe` → `reconfigure`

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Правка `system.yaml` (секция `observability`) на лету перестраивает каналы/уровни менеджеров без рестарта: `ConfigFileWatcher` → `Config.update` → `Config.subscribe(key="observability")` → `manager.reconfigure(expand(...)[role])`.

**Context:** Reuse-first — НИ строчки нового watcher-кода: `ConfigFileWatcher`
(config_module/tools/watcher.py) уже на watchdog, дебаунсит, грузит файл через `DataConverter`
и зовёт `Config.update` + `on_reload`. `Config.subscribe(cb, key)` (config.py:106) даёт
реактивную подписку. `Config.update` шлёт `_notify("*")` (config.py:69-74) — подписка по
ключу `"observability"` сработает, т.к. `_notify` для `"*"` обходит всех; уточни: подписку
вешать на `"*"` или на `"observability"` (см. `_notify` логику — при `update` ключ всегда
`"*"`, значит подписываться надо на `"*"` ИЛИ доработать так, чтобы reconfigure вызывался по
`"*"` и сам читал секцию `observability` из конфига). Менеджеры reconfigure уже готовы
(Phase 1). Узкое место — где в backend-процессе живёт `Config` и сами менеджеры: их собирает
`ProcessManagers`/orchestrator. Developer/teamlead сверяется с фактическим lifecycle.

**Files:**
- `multiprocess_framework/modules/process_module/managers/process_managers.py` ИЛИ соответствующий orchestrator/launch-слой прототипа (`multiprocess_prototype/orchestrator.py` / `backend/launch.py`) — подключить watcher: создать/получить `Config` (через `config_manager.create_config("observability", initial_data=expand(...))`), повесить подписку, callback вызывает `logger.reconfigure(...)`, `error.reconfigure(...)`, `stats.reconfigure(...)`; стартовать `ConfigFileWatcher(path=system.yaml, config=cfg, on_reload=...)`. Точное место — определить по фактическому коду (где доступны и менеджеры, и путь к файлу).
- `multiprocess_framework/modules/config_module/tools/__init__.py` — проверить экспорт `ConfigFileWatcher` (уже должен быть).
- Тест: `multiprocess_framework/modules/.../tests/test_observability_hot_reload.py` — smoke с **реальным временным файлом**: записать yaml → создать Config+watcher+менеджер → изменить файл → подождать дебаунс → assert reconfigure отработал (уровень/канал сменился). Использовать `tmp_path`, watchdog реально стартует.

**Steps:**
1. Определить место в lifecycle процесса, где доступны и триада менеджеров, и путь к `system.yaml`.
2. Создать `Config` с начальной observability-секцией (через ConfigManager — см. open question в plan.md).
3. Подписать callback `_on_observability_change(key, old, new)`: прочитать актуальную секцию из Config, `expand_observability`, вызвать `reconfigure` у трёх менеджеров. Учесть, что `update` шлёт ключ `"*"` — подписаться так, чтобы callback гарантированно сработал (на `"*"` или продумать вызов вручную в `on_reload` watcher'а вместо subscribe).
4. Стартовать `ConfigFileWatcher`; корректно `stop()` при shutdown процесса.
5. Smoke-тест с временным файлом (учесть дебаунс 1с — дать `time.sleep`/poll с таймаутом).

**Acceptance criteria:**
- [ ] Smoke-тест: изменение файла → в течение N секунд `logger`/`error`/`stats` перестроены (assert на новый уровень и/или новый канал).
- [ ] `_decision_cache` логгера инвалидирован после reload (повторная проверка `should_log` даёт новое решение).
- [ ] Watcher корректно останавливается при shutdown (нет висящих потоков — проверить `is_running == False`).
- [ ] `python scripts/validate.py` и smoke прототипа — без регрессий.
- [ ] (При наличии Qt-GUI прототипа) — после правки конфига на работающем прототипе уровень логирования меняется без рестарта (ручная проверка/qt-smoke по memory-правилу, опционально).

**Out of scope:** IPC-команда `config.reload` (Phase 4 — задел); diff-апдейт; per-process отдельные файлы.
**Edge cases:** частично записанный файл (watcher уже глотает исключение — config.py watcher:78); быстрые повторные правки (дебаунс); файл удалён/переименован (не ронять процесс); reconfigure до initialize.
**Dependencies:** Task 1.1, 1.2, 1.3, 3.1, 3.2.
**Module contract:** impl-only (подключение существующих компонентов, без нового публичного API).
