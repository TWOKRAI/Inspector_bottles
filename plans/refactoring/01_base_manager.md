# Refactoring plan: `base_manager` (модуль #1)

> **Статус:** Шаг 4 (все 7 шагов) — ✅ ЗАВЕРШЁН.
> **Автор плана:** Opus, Фаза 1 мета-плана v4.1.
> **Ссылки:** [мета-план §4.3 и §5](../floating-leaping-ritchie.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md) · [00_overview.md](./00_overview.md)

---

## 1. Vision (от автора, Шаг 0)

1. **Идея модуля своими словами.** База всех менеджеров + удобный способ коннектиться к `logger_manager`/`statistic_manager`/`error_manager` (возможно и другим). Текущая реализация — `ObservableMixin`, автор не уверен, правильный ли это подход, но хотел упростить взаимодействие. «Все менеджеры коннектятся к этим модулям».
2. **Связи.** Автор доверяет моему суждению (Opus). Рекомендация: **наследование** (`class LoggerManager(BaseManager, ObservableMixin)`) как основной путь, `interfaces.py` (`IBaseManager`, `IBaseAdapter`, `IObservableMixin`) — для моков/DI/тестов. Чистый DI через Protocol без наследования — избыточно для целей фреймворка.
3. **Что НЕ нужно.** Автор на моё суждение. Анализ выявил 4 пласта дубляжа (приватные методы / `PluginRegistry` / `ObservableDecorators` / `mixins/methods/*_methods.py`) — к удалению. `MethodCache` — к удалению (см. §6.1). `__getattr__` magic на адаптерах — к удалению (см. §6.2). `on_event`/`emit_event` — к удалению (дублирует dispatch/router).
4. **Особенности.** Избегать костылей, всегда помнить про pickle-safe и multiprocess. Важнейшее ADR-наследие: методы `_log_*` должны остаться методами класса (а не замыканиями через `types.MethodType`) — это именно то, что починило pickle на Windows spawn (см. раздел «Архитектурные решения» в текущем README.md).

---

## 2. Текущее состояние (baseline)

- **Файлов:** 29 `.py` (без tests/__pycache__)
- **LOC:** 2425 (без tests)
- **Тестов:** 4 test-файла
- **Публичный API (`__init__.py`):** `BaseManager`, `BaseAdapter`, `ObservableMixin`, `BaseManagerConfig` + `interfaces.py` (IBaseManager, IBaseAdapter, IObservableMixin)
- **Внешние потребители (из grep `from base_manager`):**
  `sql_module`, `config_module`, `logger_module` (README-пример), `error_module` (README-пример), `frontend_module`, внутренние тесты фреймворка. Также используется в `command_module`, `router_module`, `worker_module`, `process_module`, `console_module`, `dispatch_module`, `shared_resources_module` через наследование (см. README §«Кто использует модуль»).
- **Покрытие:** pytest --cov недоступен в этой среде; 69/69 тестов проходят.
- **Baseline тесты:** 69 passed (test_base_manager: 23, test_observable_mixin: 26, test_mixin_integration: 10, test_plugin_system: 10).

### 2.1. LOC по файлам

| Файл | LOC | Назначение |
|---|---|---|
| `mixins/observable_mixin.py` | **501** | Ядро ObservableMixin (раздутое) |
| `core/base_manager.py` | **324** | BaseManager (lifecycle + adapters + events + __getattr__) |
| `interfaces.py` | 256 | Protocol/ABC контракты |
| `adapters/base_adapter.py` | 202 | BaseAdapter |
| `mixins/plugins/builtin_plugins.py` | 156 | LoggerPlugin/StatsPlugin/ErrorPlugin (**к удалению**) |
| `mixins/core/manager_registry.py` | 157 | ManagerRegistry (оставить) |
| `mixins/decorators/observable_decorators.py` | 146 | logged/timed/monitored (**к удалению**) |
| `mixins/plugins/plugin_base.py` | 99 | ObservablePlugin ABC (**к удалению**) |
| `mixins/core/method_cache.py` | 98 | MethodCache (**к удалению**) |
| `mixins/plugins/plugin_registry.py` | 85 | PluginRegistry (**к удалению**) |
| `mixins/proxies/proxy_creator.py` | 80 | ProxyCreator (оставить) |
| `utils/name_utils.py` | 58 | `get_adapter_name_from_class` (оставить, но без magic __getattr__ стаёт почти не нужен — см. §5) |
| `mixins/methods/logging_methods.py` | 26 | **NO-OP заглушка** (подтверждено чтением) |
| `mixins/methods/error_methods.py` | 25 | **NO-OP заглушка** (предположительно) |
| `mixins/methods/stats_methods.py` | 25 | **NO-OP заглушка** (предположительно) |
| `configs/base_manager_config.py` | 15 | BaseManagerConfig (проверить содержимое в Шаге 4.0) |
| `types/` (пустой) | 6 | **к удалению** |
| мелкие `__init__.py` | ~100 | служебные |

### 2.2. Проблемы

1. **4 способа подключить observability:**
   - ✅ Приватные методы `_log_*`/`_record_*`/`_track_*` прямо на `ObservableMixin` (pickle-safe, рекомендованный).
   - ❌ `ObservableDecorators.logged/timed/monitored` как инстанс-атрибуты (`instance.logged = ...`). Параллельный API, не pickle-safe.
   - ❌ `PluginRegistry` + `ObservablePlugin` + `builtin_plugins.py` (LoggerPlugin/StatsPlugin/ErrorPlugin). Делает ровно то же, что приватные методы, но через плагинный механизм.
   - ❌ `mixins/methods/{logging,error,stats}_methods.py` — бывший подход через `types.MethodType`, сейчас оставлены как no-op заглушки «для обратной совместимости и как точка расширения».
2. **`simple_mode` флаг** теряет смысл после удаления плагинов/декораторов — убрать.
3. **`MethodCache`** (98 LOC) — микро-оптимизация `getattr` по `(manager_name, method_name)`. На ~5–10 пар ключей кеш экономит ~100ns/вызов. Для реальных сценариев (даже 50 fps инспекция) незаметно. Пользователь подтвердил: **удалить сразу**.
4. **`BaseManager.__getattr__` magic** для адаптеров + «noop-заглушка для proxy-методов после unpickle» — перегружено. Пользователь спросил рекомендацию, я рекомендую **удалить** (см. §6.2 ниже).
5. **`BaseManager.on_event`/`emit_event`** — мини-система событий внутри менеджера. Дублирует функциональность `dispatch_module`/`router_module`. Пользователь подтвердил: **удалить**.
6. **`_managers` backward-compat property** на ObservableMixin (для `BaseAdapter`). Мигрировать `BaseAdapter` на явный `_registry.managers` или `get_manager(...)` и удалить property.
7. **`types/` пустой** — удалить.
8. **Документация:** в `base_manager/docs/` сейчас `INTERFACES_USAGE.md`, `PLUGIN_SYSTEM.md` (и возможно другие). Новое правило автора (feedback_module_docs): README = краткий обзор + ссылки, `docs/` остаётся для подробной актуальной документации. `PLUGIN_SYSTEM.md` становится неактуальным (плагины удалены) → удалить. `INTERFACES_USAGE.md` обновить / оставить в `docs/`.

---

## 3. Целевое состояние

### 3.1. Публичный API (не меняется)

```python
from base_manager import BaseManager, ObservableMixin, BaseAdapter, BaseManagerConfig
from base_manager.interfaces import IBaseManager, IBaseAdapter, IObservableMixin
```

### 3.2. Структура файлов (целевая)

```
base_manager/
├── __init__.py                     # публичный API (без изменений)
├── interfaces.py                   # Protocol/ABC контракты (почищенные от PluginRegistry)
├── README.md                       # краткий обзор + ссылки на docs/
├── STATUS.md                       # УДАЛЁН (статус в секции README)
├── core/
│   ├── __init__.py
│   └── base_manager.py             # ~230 LOC (убрано __getattr__, events, debug-магия)
├── adapters/
│   ├── __init__.py
│   └── base_adapter.py             # ~180 LOC (мигрирован с _managers → get_manager)
├── mixins/
│   ├── __init__.py
│   ├── interfaces.py               # IObservableMixin (без плагинных методов)
│   ├── observable_mixin.py         # ~280 LOC (убрано: plugins, decorators, simple_mode, cache)
│   ├── core/
│   │   ├── __init__.py
│   │   └── manager_registry.py     # 157 LOC (без изменений)
│   └── proxies/
│       ├── __init__.py
│       └── proxy_creator.py        # 80 LOC (без изменений)
├── configs/
│   ├── __init__.py
│   └── base_manager_config.py      # 15 LOC (проверить актуальность Pydantic-схемы)
├── utils/
│   ├── __init__.py
│   └── name_utils.py               # ~20 LOC (если remain использование) ИЛИ удалить вместе с __getattr__
├── docs/
│   ├── INTERFACES_USAGE.md         # обновлён, ссылается на актуальный interfaces.py
│   └── OBSERVABLE_ARCHITECTURE.md  # новый: почему 2 режима, pickle-гарантии, почему не плагины
└── tests/
    ├── test_base_manager.py
    ├── test_observable_mixin.py
    ├── test_mixin_integration.py
    └── (test_plugin_system.py УДАЛЁН)
```

**Удаляется полностью:**
- `mixins/methods/` (весь подпакет — no-op заглушки)
- `mixins/plugins/` (весь подпакет — PluginRegistry/ObservablePlugin/builtin_plugins)
- `mixins/decorators/` (весь подпакет — ObservableDecorators)
- `mixins/core/method_cache.py`
- `types/` (пустой)
- `docs/PLUGIN_SYSTEM.md`
- `base_manager/STATUS.md`, `base_manager/MIGRATION.md` (если есть)

**Целевые метрики:** ~17 файлов (−12), ~1 650 LOC (−32%), публичный API без изменений, тесты зелёные.

**Фактические метрики (после Шага 4):** 17 файлов (−12 ✓), 1474 LOC (−39%, цель −32% перевыполнена ✓), 52 passed + 2 skipped (было 69: −10 удалённых plugin-тестов, −5 events/__getattr__ тестов, +2 новых). validate.py зелёный ✓.

### 3.3. `ObservableMixin.__init__` — целевая сигнатура

```python
def __init__(
    self,
    managers: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    auto_proxy: bool = False,
) -> None:
    """
    Args:
        managers:   {'logger': logger_mgr, 'stats': stats_mgr, 'error': err_mgr, ...}
        config:     {'logger': True, 'stats': False} — какие активны.
        auto_proxy: создать публичные прокси (log_info, record_metric, track_error, ...).
    """
```

Удалены: `simple_mode`, `plugins`, `enable_decorators` (в config).

### 3.4. `BaseManager` — целевой API

| Публичный метод | Остаётся? |
|---|---|
| `initialize()` / `shutdown()` (abstract) | ✅ |
| `attach_adapter` / `get_adapter` / `has_adapter` / `list_adapters` / `detach_adapter` | ✅ |
| `get_stats` / `get_debug_info` / `print_debug_info` | ✅ |
| `on_event` / `emit_event` | ❌ удалить |
| `__getattr__` magic для адаптеров | ❌ удалить |
| `__str__` / `__repr__` | ✅ |

После удаления events и `__getattr__` `core/base_manager.py` сокращается с 324 до ~230 LOC.

---

## 4. Атомарные шаги (для Sonnet)

Каждый шаг — **отдельный коммит**, тесты модуля зелёные после каждого. После каждого шага: `pytest multiprocess_framework/modules/base_manager/tests -v`.

### Шаг 4.0 — Baseline и аудит ✅

- [x] Тесты: 69/69 passed (4 файла: test_base_manager, test_observable_mixin, test_mixin_integration, test_plugin_system).
- [x] `on_event`/`emit_event` — **реальные потребители BaseManager вне `base_manager/`:**
  - `sql_module/core/sql_manager.py:101,106,111,120,125,130` — `self.emit_event(...)` (SqlManager наследует BaseManager).
  - `sql_module/metrics/sql_metrics.py:30-31` — `hasattr(self._manager, "emit_event")` + `self._manager.emit_event(...)`.
  - `frontend_module/application/frontend_manager.py:146` — `self.emit_event(...)`.
  - `test_base_manager_integration.py:224,227,419-420,501,504` — тестовые, удалить вместе с тестами.
  - `shared_resources_module`, `router_module`, `frontend/diagnostics.py` — **другие** `emit_event` (не BaseManager), не трогать.
- [x] `PluginRegistry`/`ObservablePlugin`/builtin — **только** внутри `base_manager/` и его тестах. Внешних потребителей нет (кроме комментария в `statistics_module/interfaces.py:18`, не код).
  - `proxy_creator.py` использует плагины — нужна переработка в Шаге 4.2.
- [x] `logged`/`@timed`/`@monitored`/`ObservableDecorators`/`enable_decorators`:
  - `test_base_manager_integration.py:445` — `@manager.logged(...)` — удалить вместе с тестом.
  - `test_observable_mixin.py:86,99,100,328,333,342` — тесты, адаптировать в Шаге 4.3.
  - `observable_mixin.py:42,107-113` — код, удалить в Шаге 4.3.
- [x] `_managers\b` — `BaseAdapter.base_adapter.py:129` — единственный внешний потребитель backward-compat property. Мигрировать в Шаге 4.5.
- [x] `LoggingMethods`/`StatsMethods`/`ErrorMethods` — **только** внутри `mixins/methods/`. Никем снаружи не импортируются. Безопасно удалять в Шаге 4.1.
- [x] `__getattr__` / `get_adapter_name_from_class` — только внутри `base_manager/core/base_manager.py` (строки 114, 313). После удаления `__getattr__` `name_utils.py` нужна только для `attach_adapter:114` (автоматическое имя при `attach_adapter(adapter)`). Решение: удалить после Шага 4.5, если вызов останется только внутренним.
- [x] Коммит: `refactor(base_manager): baseline audit before refactoring`.

### Шаг 4.1 — Удалить no-op `mixins/methods/`

- [x] Проверить по grep из 4.0, что эти классы никем не импортируются вне `mixins/methods/__init__.py`.
- [x] Удалить `mixins/methods/` целиком (4 файла, 96 LOC).
- [x] Тесты зелёные.
- [x] Коммит: `refactor(base_manager): remove no-op mixins/methods/ stubs`.

### Шаг 4.2 — Удалить плагинную систему

- [x] Удалить параметр `plugins` из `ObservableMixin.__init__`.
- [x] Удалить поля `_plugin_registry`, методы `register_plugin`/`unregister_plugin`/`has_plugin`/`get_plugin`/`_apply_plugin_methods`/`_apply_plugin_decorators`.
- [x] Убрать упоминание плагинов из `get_state()`.
- [x] Удалить `IObservableMixin` методы, связанные с плагинами (в `mixins/interfaces.py`).
- [x] Удалить `mixins/plugins/` целиком (4 файла, ~340 LOC).
- [x] Удалить `tests/test_plugin_system.py`.
- [x] Удалить `docs/PLUGIN_SYSTEM.md`.
- [x] Тесты зелёные (может понадобиться правка импортов в `test_observable_mixin.py`).
- [x] Коммит: `refactor(base_manager): remove PluginRegistry and ObservablePlugin`.

### Шаг 4.3 — Удалить декораторы

- [x] Удалить `mixins/decorators/` целиком (2 файла, 162 LOC).
- [x] Удалить блок в `ObservableMixin.__init__`, создающий декораторы.
- [x] Удалить `enable_decorators` из ожидаемых ключей `config`.
- [x] Тесты зелёные.
- [x] Коммит: `refactor(base_manager): remove ObservableDecorators (logged/timed/monitored)`.

### Шаг 4.4 — Удалить `simple_mode` и `MethodCache`

- [x] Удалить параметр `simple_mode` и все его проверки.
- [x] Удалить поле `_cache` и импорт `MethodCache`; `_call_manager` работает прямым `getattr`.
- [x] Удалить `_cache` из `__getstate__`/`__setstate__`.
- [x] Удалить `mixins/core/method_cache.py` (98 LOC).
- [x] Тесты зелёные.
- [x] Коммит: `refactor(base_manager): drop simple_mode and MethodCache`.

### Шаг 4.5 — Удалить `BaseManager.__getattr__` magic и events

- [x] По списку из 4.0 заменить `manager.<adapter_name>` на `manager.get_adapter("<adapter_name>")` во всех потребителях. Каждая замена — в том же коммите (атомарность).
- [x] Удалить `BaseManager.__getattr__`, `on_event`, `emit_event`, поле `_event_handlers`.
- [x] Удалить `_managers` backward-compat property из `ObservableMixin`; мигрировать `BaseAdapter` на `manager._registry.managers` (или приватный getter, если логично).
- [x] Переупростить `__getstate__`/`__setstate__` в `ObservableMixin` — больше нет noop-заглушек для proxy после unpickle.
- [x] Тесты зелёные (включая pickle-тесты).
- [x] Коммит: `refactor(base_manager): remove __getattr__ magic and in-process events`.

### Шаг 4.6 — Финальная уборка

- [x] Удалить `types/` (пустой).
- [x] Проверить `utils/name_utils.py` — если `get_adapter_name_from_class` не используется (она была нужна только для `__getattr__`), удалить и его.
- [x] Удалить `base_manager/STATUS.md`, `MIGRATION.md`, `PROBLEMS.md` если есть.
- [x] Прогнать `python scripts/validate.py` — должно быть зелёно.
- [x] Собрать метрики «после»: LOC, файлы, тесты, покрытие.
- [x] Коммит: `refactor(base_manager): final cleanup and metrics`.

---

## 5. Миграции в потребителях

Потенциально затронутые модули (из README §«Кто использует модуль» + grep):

- `logger_module`, `config_module`, `router_module`, `command_module`, `worker_module`, `process_module`, `console_module`, `dispatch_module`, `shared_resources_module`, `sql_module`, `frontend_module`, `error_module`.

**Проверить в каждом (Шаг 4.0, 4.5):**
1. Нет ли `manager.<adapter_name>` magic-доступа (`manager.command` вместо `manager.get_adapter("command")`).
2. Нет ли использования `PluginRegistry` / `ObservablePlugin` / декораторов `@logged`/`@timed`/`@monitored`.
3. Нет ли использования `manager.on_event(...)` / `emit_event(...)`.
4. Нет ли импорта из `base_manager.mixins.methods` / `base_manager.mixins.plugins` / `base_manager.mixins.decorators`.
5. `BaseAdapter._log()` — проверить, что fallback-логика не опирается на `_managers` (см. README строки 271–278).

---

## 6. Ключевые решения (обоснование)

### 6.1. `MethodCache` — удалить

`_call_manager` кеширует `(manager_name, method_name) → bound_method`. На типичном менеджере это ≤10 уникальных пар (logger.debug/info/warning/error/critical, stats.record_metric/record_timing, error.track_error). Стоимость `getattr` на реальном объекте — CPython MRO lookup ~100 ns. Даже при 10 000 вызовов/сек это 1 мс CPU, не заметно. Цена кеша — сложность (100 LOC, специальная обработка в `__getstate__`), риск утечки stale `bound_method` при подмене менеджера. **Решение:** удалить. Если через полгода обнаружится hot-path, где это реально важно — вернём локальной оптимизацией конкретного места, а не в базе.

### 6.2. `BaseManager.__getattr__` magic — удалить

См. рекомендацию в основном чате. Коротко: явный `get_adapter("name")` даёт типизацию и предсказуемые stack traces; magic переплетён с noop-proxy-заглушкой после unpickle → путает. README сам помечает `get_adapter` как рекомендованный. Миграция дешёвая (grep + sed).

### 6.3. Плагинная система — удалить

Мета-план §2.2 п.1 уже называет это кандидатом. README §«Плагины» показывает, что они дублируют private-методы: `LoggerPlugin` делает ровно то же, что `_log_*`. Единственное преимущество плагинов — добавить методы для **нового** менеджера (не logger/stats/error). Но: (а) в коде репозитория это не используется, (б) любой, кому нужно, может сделать наследник `ObservableMixin` с дополнительными приватными методами — это проще и яснее плагинов.

### 6.4. `simple_mode` — удалить

Флаг имел смысл только чтобы «отключить плагины и декораторы для отладки». После их удаления теряет смысл.

### 6.5. `on_event`/`emit_event` — удалить

In-process события внутри менеджера дублируют функциональность `dispatch_module` (ключ → handler) и `router_module` (между процессами). Сохранять оба API — размывает ответственность BaseManager. Потребители, которые реально регистрируют callbacks на события, должны либо использовать dispatch, либо вызывать методы напрямую.

### 6.6. `docs/` — оставить и обновить

Новое правило автора (feedback_module_docs): README кратко описывает «что есть и как пользоваться», `docs/` — подробности. Для `base_manager`:

- `docs/INTERFACES_USAGE.md` — обновить (убрать упоминания IObservableMixin-плагинов).
- `docs/PLUGIN_SYSTEM.md` — **удалить** (неактуален).
- `docs/OBSERVABLE_ARCHITECTURE.md` — **новый**: почему 2 режима (приватные + auto_proxy), почему методы класса, а не `types.MethodType`, pickle-гарантии для Windows spawn.

---

## 7. Тесты

### 7.1. Должны пройти без изменений

- `tests/test_base_manager.py` (lifecycle, adapters API — кроме magic `__getattr__`), после миграции на `get_adapter()`.
- `tests/test_observable_mixin.py` (приватные методы, auto_proxy, pickle) — **частично**: секции про плагины удалить.
- `tests/test_mixin_integration.py` — частично: убрать интеграцию с плагинами.

### 7.2. Удаляются

- `tests/test_plugin_system.py` — вместе с плагинами.

### 7.3. Добавляются 

- `test_base_manager.py::test_no_magic_getattr_for_adapters` — проверить, что `manager.nonexistent` выбрасывает `AttributeError` чисто, без подстановки proxy-заглушки.
- `test_observable_mixin.py::test_unpickle_without_managers_returns_none` — после unpickle без перерегистрации `_log_info("x")` возвращает None без исключений.
- `test_observable_mixin.py::test_two_modes_only` — проверить, что в `__init__` **нет** параметров `simple_mode`, `plugins`, `enable_decorators`.

---

## 8. Документация (для Haiku, Шаг 5)

### 8.1. `README.md` — переписать кратко по новому правилу

Разделы (по новому правилу feedback_module_docs + мета-план §6.2):

1. **Назначение** — 1–2 абзаца.
2. **Публичный API** — таблица (класс / метод → описание → пример импорта). Коротко.
3. **Быстрый старт** — один пример (RouterManager inheriting from BaseManager + ObservableMixin).
4. **Два режима observable** — приватные методы (по умолчанию) vs `auto_proxy=True`.
5. **Структура модуля** — дерево файлов (целевое).
6. **Зависимости** — никаких (foundation).
7. **Кто использует** — короткий список.
8. **Дефолтная схема конфига** — `BaseManagerConfig` (если есть содержимое; если нет — стёркнуть пункт).
9. **Подробная документация** — ссылки на `docs/INTERFACES_USAGE.md`, `docs/OBSERVABLE_ARCHITECTURE.md`.
10. **ADR** — ссылки на `DECISIONS.md`.
11. **Тесты** — команда запуска.
12. **Статус** — одна строка.

### 8.2. `ARCHITECTURE.md` — секция 6.1

После рефакторинга Haiku заполняет `§6.1 base_manager`: роль, локальный mermaid (`BaseManager ← ObservableMixin ← ProxyCreator / ManagerRegistry`), ссылка на `modules/base_manager/README.md`. ≤ 100 строк.

### 8.3. `modules/base_manager/DECISIONS.md` — локальные ADR

Создаётся новый файл `modules/base_manager/DECISIONS.md` для решений, касающихся только архитектуры модуля (согласно новому правилу, §3.1 в `plans/refactoring/00_overview.md`). Четыре новых ADR:

- **ADR-114:** Удаление PluginRegistry/ObservablePlugin из base_manager (мотивация: дублирование с приватными методами).
- **ADR-115:** Удаление ObservableDecorators (мотивация: 4-й способ делать то же самое, не pickle-safe).
- **ADR-116:** Удаление `BaseManager.__getattr__` magic-доступа к адаптерам (мотивация: явность, типизация, упрощение unpickle-сценария).
- **ADR-117:** Удаление `BaseManager.on_event`/`emit_event` (мотивация: дублирует dispatch_module/router_module).

Главный `multiprocess_framework/DECISIONS.md` содержит ссылку на локальный файл в разделе «Модульные решения» (индекс всех модульных DECISIONS.md по слоям).

---

## 9. Definition of Done (модуль #1)

- [x] Все тесты `base_manager` зелёные.
- [x] Все потребители (`sql_module`, `config_module`, `logger_module`, `error_module`, `router_module`, `command_module`, `worker_module`, `process_module`, `console_module`, `dispatch_module`, `shared_resources_module`, `frontend_module`) собираются и их тесты зелёные.
- [x] `python scripts/validate.py` зелёный.
- [x] LOC модуля сокращён ≥ 25% (цель ~32%).
- [x] Количество файлов сокращено ≥ 10 (с 29 до ~17).
- [x] Публичный API (`BaseManager`, `BaseAdapter`, `ObservableMixin`, `BaseManagerConfig` + interfaces) не изменился.
- [x] `README.md` переписан по новому правилу (краткий + ссылки на `docs/`).
- [x] `docs/INTERFACES_USAGE.md` обновлён, `docs/OBSERVABLE_ARCHITECTURE.md` создан, `docs/PLUGIN_SYSTEM.md` удалён.
- [x] `ARCHITECTURE.md` §6.1 заполнен (Haiku).
- [x] `modules/base_manager/DECISIONS.md` создан с ADR-114…117 (локальные решения модуля).
- [x] Главный `multiprocess_framework/DECISIONS.md` обновлён: раздел «Модульные решения» содержит ссылку на `modules/base_manager/DECISIONS.md`.
- [x] Baseline метрики «до» (§2) актуализированы с реальным покрытием; метрики «после» добавлены.
