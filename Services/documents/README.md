# documents — плоскость документов (аудит + вердикты)

## Назначение

Долговечное хранилище **документов** — записей, отвечающих на вопрос «что было решено»,
а не «что происходило». Два рода: аудит смен наблюдаемости (кто, когда, чем менял
настройку) и вердикты о качестве изделия («деталь N признана браком, уверенность 0.91»).

Отделено от диагностики намеренно и в обе стороны: чистка логов не имеет права унести
документ, а вечное хранение документов не должно распространяться на диагностику. Срок
хранения задаётся **по времени** и per-kind.

## Публичный API

Ре-экспорт из `__init__.py` (совпадает с `__all__`):

- `IDocumentSink` — приёмник документов, единственное, что видит фреймворк ([interfaces.py](interfaces.py))
- `IDocumentStore` — приёмник + чтение + ретеншен ([interfaces.py](interfaces.py))
- `DocumentStore` — реализация поверх `Services/sql` ([store.py](store.py))
- `KIND_AUDIT`, `KIND_VERDICT` — роды документов
- `make_document_sink(config)` — фабрика стока для сшивки из конфига ([wiring.py](wiring.py))

## Сшивка с фреймворком (Ф8.5, вариант B)

Фреймворк не имеет права импортировать `Services`, а живой сток ему нужен: аудит смен
наблюдаемости рождается внутри его процесса. Поэтому он знает **строку из конфига**:

```yaml
# multiprocess_prototype/backend/config/system.yaml
observability:
  documents:
    factory: "Services.documents.wiring:make_document_sink"
    config:
      db_path: data/documents.db
      retention_sec: {audit: 31536000, verdict: 315360000}
      purge_interval_sec: 3600
```

Фреймворк резолвит `factory` importlib'ом, зовёт с `config` и вешает результат на аудит
процесса; уборку исполняет такт heartbeat. Пустая `factory` → плоскости нет, поведение
прежнее. Отказ фабрики → процесс стартует без плоскости и **пишет WARNING с адресом
ключа**: молчаливый `sink is None` неотличим от «не настроено».

Экземпляр стока публикуется на процессе как `svc.document_sink` — второй клиент
(вердикты приложения) обязан писать в него же, а не заводить свой: один писатель на
процесс, одна БД на систему в режиме WAL.

## Использование

Создание (композиционный корень):

```python
from Services.documents import DocumentStore, KIND_AUDIT, KIND_VERDICT
from Services.sql.adapters.sqlite import SQLiteSyncAdapter
from Services.sql.configs import SQLManagerConfig

adapter = SQLiteSyncAdapter(SQLManagerConfig(url="sqlite:///documents.db", dialect="sqlite"))
adapter.setup()
store = DocumentStore(adapter, retention_sec={KIND_AUDIT: 90 * 24 * 3600})  # вердиктам срок не задан
```

Запись вердикта с линии:

```python
store.append({
    "kind": KIND_VERDICT, "ts": time.time(), "source": "line_a",
    "summary": "N-1743: брак", "part_id": "N-1743", "confidence": 0.91,
})
```

Чтение за период и уборка протухшего:

```python
store.query(kind=KIND_VERDICT, since=day_start, limit=50)   # свежие первыми
store.purge_expired()                                        # → число удалённых
```

## Границы

**Что этот модуль НЕ делает:**

- не заводит своего движка, пула и DDL — таблицу собирает `DDLBuilder` из `SQLMeta`,
  вставку делает `GenericRepository`;
- не дедуплицирует: документ — событие, а не состояние, два одинаковых вызова дают две
  строки;
- не удаляет документы рода, для которого срок не задан. Молчание конфига не является
  разрешением потерять документ о качестве;
- не переносит историю `action_log` — это отдельное решение;
- не отвечает за диагностику. Логи и `ObservabilityStore` — соседняя плоскость.

**Зависит от:** `Services/sql` (репозиторий, адаптеры, DDL),
`multiprocess_framework.modules.data_schema_module` (`SchemaBase`).

**Кто импортирует:** композиционный корень (`multiprocess_prototype`). Фреймворк
импортировать этот пакет **не имеет права** (правило слоёв 9) и не импортирует — он знает
только `IDocumentSink`, то есть один вызов с `dict`.

## Почему сток, а не фильтр по уровню

Допуск в долговечное хранилище фреймворка гейтится severity (tap с `min_level="ERROR"`),
а документ — не severity: запись аудита пишется на INFO/WARNING и потому не доезжает туда
вообще (ADR-CRM-013, воспроизведено запуском). Здесь правило допуска выражено
**структурно** — у документа свой приёмник, и попадание в него не зависит от уровня.
Фильтра, который надо не забыть настроить, нет вовсе.

## Стабильность

`contract` — README + `interfaces.py` с Pre/Post + контрактные тесты
([tests/test_contract.py](tests/test_contract.py), 17 тестов).
