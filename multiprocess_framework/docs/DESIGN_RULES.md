# Design Rules — Императивные правила

**Назначение:** список **обязательных** правил для разработчиков и агентов, работающих с фреймворком. Каждое правило — императивно (что обязано / что запрещено), с обоснованием и проверкой соблюдения.

> **Принцип:** правило сформулировано так, чтобы его можно было проверить (тестом, grep'ом или ревью). Если правило нельзя проверить — это не правило.

---

## R-1. Импорты — каноничные

**Обязано:** внутри фреймворка использовать только

```python
from multiprocess_framework.modules.<X> import Y
from multiprocess_framework import Y          # с корневого фасада
```

**Запрещено:** `from <X> import Y` (без префикса), `sys.path.insert`, `pythonpath = .` в `pytest.ini`, `__path__`-хаки.

**Почему:** один способ импорта — одна точка отказа. Корневой фасад (`__init__.py`) гарантирует 49 публичных символов.

**Проверка:**
```bash
grep -rE "^(from|import) (base_manager|data_schema_module|message_module|router_module|logger_module|process_module|process_manager_module|worker_module|config_module|shared_resources_module|console_module|dispatch_module|command_module|channel_routing_module|registers_module|sql_module|statistics_module|frontend_module|error_module)" multiprocess_framework --include="*.py"
```
**Ожидание:** пусто.

---

## R-2. Менеджер = `BaseManager + ObservableMixin`

**Обязано:** любой менеджер фреймворка наследует **обоих** родителей:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, manager_name: str, logger=None):
        BaseManager.__init__(self, manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger} if logger else {})
```

**Запрещено:** прямое использование `print()`, `logging.getLogger()`, `traceback.print_exc()`. Только `self._log_*`, `self._record_*`, `self._track_*`.

**Почему:** единая точка наблюдаемости. Подмена логгера на сокет/БД делается одной строкой.

**Проверка:** `grep -rn "print(" modules/` — должно быть только в `__main__` блоках или явных stdout-каналах.

---

## R-3. Dict at Boundary

**Обязано:** между процессами передаётся только `dict` через `model_dump()` / `to_dict()`. На приёмной стороне — `Message.from_dict()` / `model_validate()`.

**Запрещено:** передавать в `Queue` / `Pipe` / `SharedResourcesManager`:
- Pydantic-объекты напрямую (`BaseModel`, `SchemaBase`)
- Закрытые методы / lambdas / closures
- Незарегистрированные классы

**Почему:** Pydantic-объекты не всегда сериализуются под Windows spawn. Plain `dict` — единственный гарантированно pickle-safe формат.

**Проверка:**
```python
import pickle
pickle.dumps(payload)   # должно работать без ошибок
```

---

## R-4. Регистр = `SchemaBase` с `FieldMeta` + `FieldRouting`

**Обязано:** каждое поле регистра описано с `FieldMeta`. Если поле должно доставляться в другие процессы — добавляется `FieldRouting(channel=..., process_targets=...)`.

```python
class CameraRegister(SchemaBase):
    fps: Annotated[int, FieldMeta(
        description="...",
        min_value=1, max_value=60,
        routing=FieldRouting(channel="camera_settings", process_targets=["camera"]),
    )] = 30
```

**Запрещено:** дублировать декларацию поля в frontend-конфиге, валидаторе, mapper'е. Декларация — **одна**.

**Почему:** один источник истины. UI, валидация, дефолты, маршруты выводятся из декларации.

---

## R-5. `interfaces.py` — единственный публичный контракт

**Обязано:** потребители модуля X импортируют только из `multiprocess_framework.modules.X.interfaces` или с фасада. Реализации (`core/`, `adapters/`, `channels/`) — приватны.

**Запрещено:** импортировать `from multiprocess_framework.modules.X.core.<file>` из других модулей. Допустимо только внутри X.

**Почему:** изоляция. Замена реализации не должна ломать потребителей.

**Проверка:** ревью `from ...modules.<X>.core` в чужих модулях.

---

## R-6. Канал ≠ имя процесса

**Обязано:** разделять две сущности:
- **`targets`** в `send_message`/`Message.targets` — **имена процессов**.
- **`FieldRouting.channel`** / `Message.channel` — **канал Router'а** (логический поток сообщений).

**Запрещено:** использовать имя процесса как имя канала и наоборот.

**Почему:** двухуровневая маршрутизация: «куда» (процесс) + «по какому каналу» (тип потока).

**Подробнее:** [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md).

---

## R-7. Один `RouterManager` на процесс

**Обязано:** в `ProcessModule` использовать `self.router` — единственный `RouterManager` процесса.

**Запрещено:** создавать второй `RouterManager` в worker'е. Маршрутизация — централизованная.

**Почему:** thread-safe `_stats`, единая `AsyncSender`-очередь, одна точка контроля.

---

## R-8. Worker — `while not stop_event.is_set()`

**Обязано:** воркер периодически проверяет `stop_event`:

```python
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            stop_event.wait(timeout=0.05)
            continue
        do_work()
```

**Запрещено:** бесконечный цикл без проверки `stop_event`, `time.sleep()` без `stop_event.wait()` (последний прерывается при остановке).

**Почему:** graceful shutdown. Без проверки — `terminate()`/`kill()` через 5 секунд.

---

## R-9. Signal handler — только `stop_event.set()`

**Обязано:** signal handler устанавливает `stop_event` и возвращает управление.

**Запрещено:** `sys.exit()`, `os._exit()`, `raise SystemExit()` в signal handler.

**Почему:** `sys.exit()` обрывает запись данных, оставляет ресурсы в неконсистентном состоянии.

**Проверка:** `grep -rn "sys.exit\|os._exit" modules/` — допустимо только в редких top-level main'ах.

---

## R-10. Логи — через env-переменную, не cwd

**Обязано:** путь логов читается из `MULTIPROCESS_LOG_DIR` или `INSPECTOR_LOG_DIR`. Дефолт — абсолютный путь, не `./logs`.

**Запрещено:** хардкод `Path("logs")` или `os.getcwd() / "logs"`.

**Почему:** дочерние процессы могут иметь другой cwd. Относительные пути приведут к разбросанным логам.

---

## R-11. Pickle-safe для всего, что попадает в `multiprocessing`

**Обязано:** всё, что передаётся в `Process(args=...)` / `Queue.put()`, должно быть `pickle.dumps()`-сериализуемо без ошибок.

**Запрещено:** lambdas, closures, методы инстансов, динамически созданные классы.

**Почему:** Windows `spawn` mode требует pickle. На Linux fork работает по-другому, но кросс-платформенность — обязательна.

**Проверка:** `pickle.dumps(payload)` в тесте.

---

## R-12. ADR — каждое архитектурное решение

**Обязано:** при изменении публичного контракта модуля или сквозного инварианта — добавить ADR:
- **Глобальное решение** → `multiprocess_framework/DECISIONS.md` с кодом `ADR-NNN`.
- **Локальное** → `modules/<X>/DECISIONS.md` с кодом `ADR-<КОД>-NNN` (`<КОД>` — см. [`ADR_REGISTRY.md`](ADR_REGISTRY.md)).
- Зарегистрировать в `docs/ADR_REGISTRY.md`.

**Запрещено:** «тихие» изменения публичного API без ADR.

**Почему:** воспроизводимость решений; видна история «почему так».

---

## R-13. Тесты — pytest, в `modules/<X>/tests/`

**Обязано:** новые модули добавляют:
- `modules/<X>/tests/test_*.py` — pytest-тесты.
- В `modules/pytest.ini` — путь к `<X>/tests` в `testpaths`.

**Запрещено:** тесты в произвольных местах. Использование `unittest.TestCase` без необходимости.

**Почему:** единая команда прогона: `python scripts/run_framework_tests.py`.

---

## R-14. Backward compatibility — без жалости

**Обязано:** удалять алиасы, deprecated-методы, shim-импорты в рамках текущего рефакторинга. Потребители (приложение) мигрируются синхронно.

**Запрещено:** держать `_compat.py`, `legacy.py`, `from .new import X as OldName`.

**Почему:** два пути для одного и того же удваивают сложность. Чистая кодовая база приоритет.

**Исключение:** в продакшен-релизе — обязательно через DEPRECATION-цикл (warnings.warn + срок). Сейчас фреймворк в активном рефакторинге, релизных гарантий нет.

---

## R-15. Pydantic v2 — `type(self).model_fields`

**Обязано:** доступ к `model_fields` через **класс**, не через инстанс:

```python
for name in type(self).model_fields:    # ✅
for name in self.__class__.model_fields: # ✅
```

**Запрещено:** `for name in self.model_fields` (deprecation warning в Pydantic v2.11, удаление в v3.0).

**Почему:** Pydantic v2.11+ запрещает доступ через инстанс.

**Проверка:** `grep -rn "self\.model_fields\|getattr(.*\"model_fields\"" modules/` — должно быть пусто.

---

## R-16. Регистры — в прикладном коде

**Обязано:** конкретные регистры (`CameraRegister`, `RecipeRegister` и т.д.) живут в **приложении** (`projects/<app>/registers/` или подобное). Фреймворк даёт только примитивы.

**Запрещено:** добавлять прикладные регистры в `multiprocess_framework/modules/`.

**Почему:** философия конструктора. Фреймворк — универсальный, регистры — доменные.

---

## R-17. Один модуль = одна папка

**Обязано:** каждый модуль — папка `modules/<name>/` с обязательными файлами:
- `__init__.py` — публичные экспорты
- `interfaces.py` — `Protocol`/`ABC`
- `README.md` — описание + API
- `STATUS.md` — этап и ограничения
- `DECISIONS.md` — локальные ADR (или индекс на глобальный)
- `tests/` — pytest

**Запрещено:** «голые» файлы в `modules/` (кроме `__init__.py`, `pytest.ini`, `conftest.py`).

---

## R-18. `model_dump()` — единственный сериализатор

**Обязано:** конвертация `SchemaBase → dict` — только через `instance.model_dump()` или `Message.to_dict()` (которая делегирует туда же).

**Запрещено:** `dataclasses.asdict()`, `json.dumps()` напрямую, кастомные `to_dict()` в наследниках `SchemaBase`.

**Почему:** `model_dump()` корректно обрабатывает Annotated, FieldMeta, computed_field. Кастомные сериализаторы рассинхронизируются.

---

## R-19. Конфиг на границе — `dict`, внутри — Pydantic

**Обязано:** конфиг процесса/менеджера принимается как `dict | None | SchemaBase`. Внутри менеджера — `normalize_config()` приводит к runtime-форме.

**Запрещено:** требовать обязательно Pydantic-объект (ломает Dict at Boundary). Требовать обязательно `dict` (теряем валидацию).

**Почему:** гибкость + валидация.

---

## R-20. `LogRecord` / `MetricRecord` / `Message` — value objects

**Обязано:** записи логов / метрик / сообщений — value objects (`@dataclass` или `SchemaBase`). Pickle-safe, immutable по конвенции.

**Запрещено:** мутабельные dict'ы с произвольными ключами.

**Почему:** контракт. Тесты, отладка, типизация.

---

## Сводная таблица

| Правило | Тип | Проверка |
|---------|-----|----------|
| R-1 | Импорты | `grep` top-level импортов |
| R-2 | Менеджер | `grep` `print/logging.getLogger` |
| R-3 | Dict at Boundary | `pickle.dumps(payload)` в тесте |
| R-4 | Регистр | ревью |
| R-5 | `interfaces.py` | `grep` `from ...modules.X.core` извне |
| R-6 | Канал ≠ имя процесса | ревью + `ipc-routing-checker` (если есть) |
| R-7 | Один Router | ревью |
| R-8 | Worker stop_event | `grep` `while True:` без `stop_event` |
| R-9 | Signal handler | `grep` `sys.exit\|os._exit` |
| R-10 | Логи через env | `grep` хардкода путей |
| R-11 | Pickle-safe | `pickle.dumps()` в тесте |
| R-12 | ADR | ревью PR |
| R-13 | Тесты | `pytest` собирает |
| R-14 | Backward compat | `grep` `_compat\|legacy\|deprecated` |
| R-15 | Pydantic v2 | `grep` `self.model_fields` |
| R-16 | Регистры в app | ревью |
| R-17 | Структура папок | `tools/validate_all_modules.py` |
| R-18 | `model_dump` | ревью |
| R-19 | Конфиг на границе | `normalize_config()` в каждом менеджере |
| R-20 | Value objects | ревью |

Автоматическая проверка структурных правил — `tools/validate_all_modules.py` (запускается через `python scripts/validate.py` из текущий каталог).
