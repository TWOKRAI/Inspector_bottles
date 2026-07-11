# DECISIONS.md — `data_schema_module`

Локальные архитектурные решения модуля. Глобальные правила фреймворка — в [`../../DECISIONS.md`](../../DECISIONS.md).

---

## ADR-DS-001 (was ADR-120): Удаление `_compat.py`
- Дата: 2026-04-09
- Статус: принято
- Контекст: Файл реэкспортировал символы для «старого» API; grep по текущий каталог не показал внешних импортов из `_compat`. Все потребители используют `from data_schema_module import …`.
- Решение: Удалить `_compat.py`; публичный контракт остаётся в `__init__.py` и канонических пакетах.
- Причина: Меньше мёртвого кода и дублирования путей импорта.
- Отклонённые альтернативы: Оставить файл «на всякий случай» — отклонено.

---

## ADR-DS-002 (was ADR-121): Удаление shim-директорий и re-export файлов
- Дата: 2026-04-09
- Статус: принято
- Контекст: После рефакторинга v2.0 остались переходные обёртки: `fields/`, `utils/`, `registry/register_discovery.py`, `registry/registers_scanner.py`, `storage/file_storage.py`, тонкие re-export в `extensions/storage_manager.py` и `extensions/process_data_container.py`. Дублировали канонические пути (`core/`, `serialization/`, `container/`, `registry/discovery.py`, `storage/`).
- Решение: Удалить shims; внутренние импорты и тесты перевести на канонические модули. Функция `_class_name_to_snake` перенесена в `registry/discovery.py` (раньше только в `registers_scanner.py`). `FileStorage` в `storage/__init__.py` импортируется из `serialization/file_storage.py`.
- Причина: Однозначные пути, меньше файлов и расхождений с `core/`.
- Отклонённые альтернативы: Оставить shims бессрочно — отклонено.

---

## ADR-DS-003 (was ADR-122): Удаление `tests_backup/`
- Дата: 2026-04-09
- Статус: принято
- Контекст: Устаревшие тесты со старыми путями (`fields/register_base` и т.д.).
- Решение: Удалить каталог целиком; регрессии покрыты актуальными тестами в `tests/`.
- Причина: Шум и ложное ощущение покрытия.
- Отклонённые альтернативы: Починить backup-тесты — отклонено (дублирование).

---

## ADR-DS-004 (was ADR-123): `extensions/` — только явный импорт
- Дата: 2026-04-09
- Статус: принято
- Контекст: Расширения (versioning, factory, tools, metrics-shim к `core.metrics`, api-обёртки) не входят в top-level `data_schema_module.__init__`.
- Решение: Сохранить `extensions/` для опциональных компонентов; `StorageManager` и `ProcessDataContainer` импортировать из `data_schema_module.storage` (реализация в `storage/`), не через удалённые shim-файлы в `extensions/`.
- Причина: Зависимости от `process_module` и др. остаются изолированными; ядро без лишних side effects при `import data_schema_module`.
- Отклонённые альтернативы: Реэкспорт StorageManager снова в корень пакета — отклонено (нарушает слойность).

---

## ADR-DS-005: Декомпозиция `interfaces.py` по sub-package'ам
- Дата: 2026-05-11
- Статус: принято
- Контекст: До этой даты все 17 Protocol/ABC контрактов жили в одном корневом `interfaces.py` (594 LOC). Это удобно для импорта (`from data_schema_module import ISchemaRegistry`), но плохо для понимания границ: `IVersionManager` сидит рядом с `ISchema` и `IRegisterStorage`, у каждого слоя нет своего «лица». Также при добавлении нового интерфейса непонятно, куда его класть концептуально — все попадает в один monolith.
- Решение: Контракты разнесены по sub-package'ам по принципу «контракт живёт там же, где его реализация»:
  - `core/interfaces.py` — `ISchema`, `ISchemaAdapter`, `HasBuild`, `IDataValidator` (фундамент без внешних зависимостей).
  - `registry/interfaces.py` — `ISchemaRegistry`, `ISchemaManager` (реестр + legacy).
  - `serialization/interfaces.py` — `IDataConverter`, `ISchemaStorage`, `IAsyncSchemaStorage` + legacy aliases `IRegisterStorage` / `IAsyncRegisterStorage`.
  - `storage/interfaces.py` — `IStorageManager` (зависит от `process_module`).
  - `versioning/interfaces.py` — `IVersionManager` (зависит от `config_module`).
  - `tools/interfaces.py` — `IVisualizationFormatter`, `IDocumentationFormatter`, `ISchemaVisualizer`, `ISchemaDocumentationGenerator`.

  Корневой `interfaces.py` (86 LOC) превращён в **агрегатор-фасад**: реэкспортирует все 17 контрактов из sub-package'ов. Импорты `from data_schema_module.interfaces import ISchemaRegistry` продолжают работать без изменений в потребляющем коде. Внутренние импорты внутри модуля переписаны на локальные пути (`from .interfaces import ISchemaManager` в `registry/schema_registry.py`, `from ..core.interfaces import HasBuild` в `container/config_converters.py` и т.п.) — это разрешает проблему циклической инициализации при загрузке корневого `interfaces.py`.

  Backward compat: `core/interfaces.py` теперь содержит только 4 core-контракта (не 17 как раньше). Старые потребители `from data_schema_module.core.interfaces import ...` для не-core контрактов сломаются — но в кодовой базе таких импортов нет (проверено grep'ом перед изменением); единственным внутренним потребителем был `core/__init__.py`, обновлён.

- Причина: Каждый слой получил своё «лицо контракта»; добавление нового интерфейса теперь однозначно — кладётся туда, где его реализация. Корневой `interfaces.py` всё ещё работает как единая точка импорта (R-1 «единый канал»), но за ним стоит структурированная декомпозиция. Подготавливает почву для возможного будущего carve-out `tools/` в отдельный top-level модуль (его контракты уже изолированы).
- Отклонённые альтернативы:
  - **Оставить монолит** — терпимо, но затрудняет понимание границ и добавление нового интерфейса.
  - **Полностью удалить корневой `interfaces.py`** — сломает 43 файла-потребителя с импортами `from data_schema_module.interfaces import ...`. Стоимость миграции не окупается выигрышем.
  - **Использовать `__getattr__` (PEP 562) в корневом `__init__.py`** — lazy-loading через `__getattr__` сокращает import-time, но добавляет неявность; для interfaces (легковесные Protocol/ABC) overhead отсутствует.

---

## ADR-DS-006: Фасадный импорт — единственный канал для core-символов
- Дата: 2026-05-11
- Статус: принято
- Контекст: До этой даты потребители вне `data_schema_module/` импортировали core-символы (`SchemaBase`, `RegisterBase`, `FieldMeta`) и через корневой фасад, и через прямые пути в подпакеты: `from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta` и т.п. (11 файлов в `multiprocess_prototype/`, `Services/`, `multiprocess_framework/modules/process_module/tests/`). Это создавало лишние file-to-file edges в DSM и нарушало правило R-1 «единый канал импортов»: при reorg core/ потребители ломались напрямую, минуя фасад.
- Решение: Для core-символов, объявленных в корневом `__init__.py.__all__` (`SchemaBase`, `RegisterBase`, `FieldMeta`, `FieldRouting`, `register_schema`, `DataConverter`, …), фасадный импорт через корень модуля — **единственный разрешённый канал** из кода вне `data_schema_module/`. Прямые импорты `from data_schema_module.core.X import Y` для public API запрещены.

  Sed-миграция 11 файлов выполнена: `from data_schema_module.core.field_meta import FieldMeta` → `from data_schema_module import FieldMeta` (то же для `core.schema_base import SchemaBase/RegisterBase`).

  Исключения (где прямой подпакет-импорт обязателен — это **opt-in зависимости** по ADR-DS-004):
  - `from data_schema_module.storage.storage_manager import StorageManager` — зависит от `process_module`, не в корневом фасаде.
  - `from data_schema_module.extensions.versioning import VersionManager` — зависит от `config_module`.
  - `from data_schema_module.extensions.factory import ModelFactory` — динамическая фабрика, opt-in.
  - `from data_schema_module.extensions.models import ComponentDNA, BaseComponentModel` — модели компонентов.
  - `from data_schema_module.extensions.tools import SchemaVisualizer, SchemaDocumentationGenerator` — визуализация.

  Внутренние импорты внутри `data_schema_module/*` (относительные `from .core.field_meta import ...` или `from ..core.X import Y`) — нормальное явление, правило не касается них.

- Причина: Единый канал импортов даёт три полезных свойства:
  1. **Стабильный публичный контракт** — реорганизация подпакетов (move/rename внутри `core/`) не ломает потребителей.
  2. **Меньше file-to-file edges в DSM** — sentrux modularity улучшается.
  3. **Соответствие R-1 фреймворка** — то же правило применяется ко всему `multiprocess_framework`.

- Отклонённые альтернативы:
  - **Запретить вообще все прямые импорты подпакетов** (включая extensions/storage) — нарушает ADR-DS-004, делает зависимость от `process_module` неявной.
  - **Не вводить правило, оставить как есть** — те же файлы при следующем рефакторинге снова разбредутся по прямым путям; cleanup без правила = временная мера.
  - **Lint-rule на CI** — преждевременно; рекомендация в DECISIONS + grep в `validate.py` достаточны на этом этапе.

---

## ADR-DS-007: Канонический `deep_merge` — единственная реализация deep-merge словарей

- Дата: 2026-07-11
- Статус: принято
- Контекст (C5 / дубль D3 аудита дублирования): в проекте жили три независимые
  реализации глубокого слияния словарей:
  1. `data_schema_module.merge_with_defaults` — shallow-copy defaults, overlay по ссылке;
  2. `config_module.tools.deep_merge` — самопровозглашённый «канон» с deepcopy,
     `copy_base` и `list_strategy` (самый generic);
  3. `multiprocess_prototype…schemas._deep_merge` — `dict(base)` shallow, без опций.

  Наблюдаемый `==`-контракт у всех трёх совпадает (приоритет overlay, рекурсия
  вложенных dict, замена списков и скаляр↔dict, None перезаписывает). Отличались
  только семантикой копирования (shallow vs deepcopy → aliasing вложенных ссылок).

- Решение: единственный источник истины — **`deep_merge`** в
  `core/helpers.py` (сигнатура перенесена без изменений из config-версии:
  `deep_merge(base, overlay, *, copy_base=True, list_strategy="replace")`).
  Остальные — тонкие делегаты с сохранёнными сигнатурами и импорт-путями:
  `merge_with_defaults` (deep=True → `deep_merge(defaults, data)`; deep=False
  shallow-путь оставлен как есть), `config_module.tools.deep_merge`,
  `schemas._deep_merge`.

- Причина выбора data_schema (а не более generic config-версии): `config_module`
  уже импортирует из `data_schema_module` (`config.py` → `merge_with_defaults`).
  Канон в config заставил бы `data_schema` импортировать config → **цикл модулей**.
  Слой диктует: примитив живёт в нижнем модуле, верхние делегируют вниз.

- Поглощённые различия: shallow→deepcopy. Раньше `merge_with_defaults(proc_dict,
  DEFAULT_PROCESS_SCHEMA)` разделял вложенные ссылки с модульной константой
  `DEFAULT_PROCESS_SCHEMA` (латентный aliasing-риск). Канон делает deepcopy —
  результат полностью изолирован; `==`-контракт не изменён, все тесты зелёные
  без правок ожиданий (1100 passed). `list_strategy="append"` теперь доступен
  всем потребителям.

- Отклонённые альтернативы:
  - **Канон = `config_module.tools.deep_merge`** (по «самый generic») — создаёт
    цикл config↔data_schema, отклонено.
  - **Новый нейтральный модуль под merge** — избыточно для одной функции;
    задача требовала выбрать одну из трёх существующих.
  - **Удалить старые пути импорта** — нарушает обратную совместимость (20+
    call-sites), отклонено в пользу тонких делегатов.
  - **Оставить `state_store` `_deep_merge_inplace`** вне scope — сознательно: это
    path-based tree-merge с генерацией Delta (граница жизненного цикла, N2
    аудита), не общий примитив-словарь.
