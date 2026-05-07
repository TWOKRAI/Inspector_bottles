# T2.3 — IChainLogger Protocol для chain_module

> **Родительский план:** [`framework_assessment_2026_05_07.md`](./framework_assessment_2026_05_07.md) §2 Tier-2 T2.3
> **Дата:** 2026-05-07
> **Тип задачи:** developer (с лёгким architectural change в base_manager)
> **Оценка:** 0.5 дня
> **Pipeline:** plan (этот документ) → implement → test → review → ship

---

## 1. Цель

Зафиксировать **публичный** протокол логгера, который принимает `chain_module`, и убрать вызовы псевдо-приватных методов (`log._log_warning`) у переданного снаружи объекта.

## 2. Контекст и фактическое состояние

### 2.1. Что есть сейчас

| Файл | Что использует |
|------|----------------|
| `chain_module/core/context.py:22` | `logger: Any = None  # ObservableMixin-совместимый объект с методами _log_*` |
| `chain_module/core/error_policy.py:46,57,68` | `log._log_warning(msg)` / `log._log_error(msg)` — **единственное место** в chain_module, где логгер передан **извне** и зовутся `_log_*` |
| `chain_module/worker_pool/dispatcher.py`, `metrics/latency.py`, `thread_pool/pool.py` | `self._log_*` — вызовы **на самом себе** через `ObservableMixin`. Это нормально, не предмет задачи. |
| `multiprocess_prototype/plugins/services/processor_worker/plugin.py:206` | `ChainContext(...)` создаётся **без** `logger` |
| `multiprocess_prototype/tests/unit/test_*` | `ChainContext()` создаётся без logger |

**Ключевой факт:** `ChainContext.logger` сейчас **никогда** не передаётся в реальном коде. Все три вызова `log._log_*` в `error_policy.py` уходят в ветку `if log is not None: …` — никогда не срабатывают на текущей кодовой базе. То есть никакая регрессия в production невозможна, scope действительно изолирован.

### 2.2. Контракт `IObservableMixin`

Существует в `modules/base_manager/interfaces.py:184-198`:
```python
@abstractmethod
def _log_debug(self, message: str, **kwargs) -> None: ...
def _log_info(self, message: str, **kwargs) -> None: ...
def _log_warning(self, message: str, **kwargs) -> None: ...
def _log_error(self, message: str, **kwargs) -> None: ...
```

Имена с `_` — не настоящий private (Python это convention), но семантически: «эти методы для использования наследниками `BaseManager`». Передавать менеджер во внешний модуль и звать там `_log_*` — нарушение этой конвенции.

## 3. Решение

### 3.1. Добавить публичные методы в `ObservableMixin`

В `IObservableMixin` (ABC) и в реализации `ObservableMixin`:
```python
def log_debug(self, message: str, **kwargs) -> None:
    self._log_debug(message, **kwargs)
def log_info(self, message: str, **kwargs) -> None:
    self._log_info(message, **kwargs)
def log_warning(self, message: str, **kwargs) -> None:
    self._log_warning(message, **kwargs)
def log_error(self, message: str, **kwargs) -> None:
    self._log_error(message, **kwargs)
```

**Почему алиасы, а не переименование:**
- В chain_module/state_store_module/everywhere `self._log_*` вызывается из десятков мест. Переименовать = большой PR без архитектурной пользы.
- Внутри менеджеров `_log_*` остаются «семейными» (каноничный путь). Публичные `log_*` — для использования **внешним** кодом, который принял менеджер как зависимость.

### 3.2. `IChainLogger` Protocol в `chain_module/interfaces.py`

```python
@runtime_checkable
class IChainLogger(Protocol):
    """Узкий контракт логгера для исполнителей chain_module.

    Любой объект с этими тремя публичными методами годится. ObservableMixin
    удовлетворяет (после добавления log_* алиасов в base_manager).
    """
    def log_info(self, message: str, **kwargs: Any) -> None: ...
    def log_warning(self, message: str, **kwargs: Any) -> None: ...
    def log_error(self, message: str, **kwargs: Any) -> None: ...
```

`log_debug` **не включаем** — не используется в `error_policy.py` и других внешних потребителях chain_module.

### 3.3. `ChainContext.logger`

```python
from chain_module.interfaces import IChainLogger
@dataclass
class ChainContext:
    ...
    logger: IChainLogger | None = None
```

Импорт `IChainLogger` в `core/context.py` — без циклов: `interfaces.py` импортирует только из `typing`, `context.py` импортирует из `interfaces.py` через `from ..interfaces import IChainLogger`.

### 3.4. `error_policy.py`

Заменить:
```python
if log is not None:
    log._log_warning(msg)   # было
    log.log_warning(msg)    # стало
```

Аналогично `_log_error` → `log_error`.

## 4. Acceptance criteria

- [ ] `IObservableMixin` в `modules/base_manager/interfaces.py` содержит публичные `log_debug`/`log_info`/`log_warning`/`log_error` (как `@abstractmethod` с дефолтной реализацией через `_log_*` НЕ выйдет — ABC так не работает; либо делаем неабстрактные методы в реализации, либо добавляем concrete `def` в ABC).
   - **Реализация:** в ABC методы декларируются как абстрактные с docstring; в `ObservableMixin` — конкретные тонкие алиасы `log_X(self, ...) -> None: self._log_X(...)`. Если ABC не позволяет смешивать абстрактное и конкретное — оставить только в реализации, а в ABC ограничиться docstring-ом наверху класса.
- [ ] `chain_module/interfaces.py` экспортирует `IChainLogger`.
- [ ] `ChainContext.logger: IChainLogger | None`.
- [ ] `core/error_policy.py` использует `log.log_warning` / `log.log_error`.
- [ ] `isinstance(some_observable_manager, IChainLogger)` возвращает `True` (runtime_checkable, проверка на дакфайл).
- [ ] Все 67 тестов `chain_module` проходят.
- [ ] Все тесты прототипа в `multiprocess_prototype/tests/unit/test_dag_runnable.py`, `test_chain_thread_pool.py`, `test_phase9_*` проходят.
- [ ] ADR-CHN-008 написан и подключён к `modules/chain_module/DECISIONS.md`.
- [ ] `framework_assessment_2026_05_07.md` § "История обновлений" обновлён.

## 5. Шаги реализации

1. **base_manager**:
   - В `modules/base_manager/core/observable_mixin.py` (или где живёт реализация — найти один раз) добавить четыре публичных метода-алиаса.
   - В `modules/base_manager/interfaces.py` `IObservableMixin` добавить четыре публичных метода как `@abstractmethod` (для документации контракта). **Без default implementation в ABC** — конкретику даёт `ObservableMixin`.
2. **chain_module**:
   - В `modules/chain_module/interfaces.py` добавить `IChainLogger` Protocol + в `__all__`.
   - В `modules/chain_module/core/context.py` импортировать `IChainLogger`, поменять тип `logger`.
   - В `modules/chain_module/core/error_policy.py` заменить `_log_warning` → `log_warning`, `_log_error` → `log_error`.
3. **ADR-CHN-008** в `modules/chain_module/DECISIONS.md`:
   - Заголовок: `## ADR-CHN-008: Публичный IChainLogger Protocol для исполнителей`
   - Контекст: ChainContext.logger был Any, error_policy звал приватные `_log_*` на чужом объекте.
   - Решение: узкий runtime_checkable Protocol с публичными `log_info/log_warning/log_error`; ObservableMixin получает публичные алиасы.
   - Последствия: внешний код может передавать в ChainContext **любой** объект с тремя методами (упрощает тесты — больше не нужен `Mock(spec=...)` с приватными атрибутами).
4. **Тесты** (см. §6).
5. Запустить `python scripts/validate.py` + `python scripts/run_framework_tests.py`.
6. Обновить `framework_assessment_2026_05_07.md` § 5.

## 6. Тесты

**Файл:** `multiprocess_framework/modules/chain_module/tests/test_error_policy.py` (новый, если не существует) или дополнить существующий.

| # | Сценарий | Ожидание |
|---|----------|----------|
| 1 | `apply_on_error_policy` с `logger=None` | работает без AttributeError, заполняет `context.warnings`/`errors` корректно |
| 2 | `apply_on_error_policy` с фейк-логгером (`SimpleNamespace` + три метода) | `log_warning`/`log_error` вызваны нужное число раз с ожидаемым префиксом |
| 3 | `on_error="skip"` | `result.skipped_nodes` содержит nid, `should_break=False`, вызван `log_warning` |
| 4 | `on_error="fail_region"` | `result.failed=True`, `result.fail_level="region"`, `should_break=True`, вызван `log_error` |
| 5 | `on_error="fail_camera"` (или любое другое значение) | `result.fail_level="camera"`, `should_break=True`, вызван `log_error` |
| 6 | `isinstance(LoggerManager_instance, IChainLogger)` | `True` (smoke-тест на runtime_checkable) — проверяет, что после добавления алиасов реальный менеджер фреймворка удовлетворяет Protocol |

Тест №6 — главный регрессионный: подтверждает что **существующие** менеджеры фреймворка автоматически становятся `IChainLogger`.

## 7. Риски

1. **`@abstractmethod` для `log_*` в `IObservableMixin`** заставит все наследники `BaseManager` реализовать новые методы. Если в репо есть тестовые fake-менеджеры, не наследующиеся через `ObservableMixin` напрямую — упадут. **Митигация:** перед добавлением `@abstractmethod` найти `class .*BaseManager` и `class .*ObservableMixin` через qex/grep, оценить blast radius. Если велик — оставить методы только в реализации, без ABC.
2. **Прототип `operations/base.py`** делает `re-export ChainContext`. После изменения тип `logger` стал `IChainLogger | None`. Если где-то в прототипе создаётся `ChainContext(logger=some_obj)` без публичных `log_*` — type-check упадёт. **Митигация:** grep подтвердил — в прототипе таких вызовов нет.
3. **Type-checker строгий?** Если у проекта подключён mypy в strict-mode, добавление abstractmethod в существующий ABC может включить новые ошибки. **Митигация:** запустить mypy после правок (если он настроен — проверить `pyproject.toml` / `mypy.ini`).

## 8. Out of scope

- ❌ Переименовать `_log_*` → `log_*` внутри менеджеров. Это сепаратный рефакторинг ~21 модуль, без архитектурной пользы.
- ❌ Добавить `track_error` / `record_metric` в `IChainLogger`. План явно ограничивает scope тремя методами.
- ❌ Включать `IChainLogger` в `state_store_module` или другие модули — они используют `self._log_*` внутри себя, проблема узкая для chain.

## 9. Definition of done

- [ ] PR содержит правки в `base_manager` + `chain_module` + ADR-CHN-008 + тесты.
- [ ] `python scripts/run_framework_tests.py` — green.
- [ ] `python scripts/validate.py` — green (после T1.3, который идёт в этом же дне).
- [ ] reviewer-агент апрувит без второй итерации.
- [ ] Запись в `framework_assessment_2026_05_07.md` § "История обновлений": T2.3 закрыт.
