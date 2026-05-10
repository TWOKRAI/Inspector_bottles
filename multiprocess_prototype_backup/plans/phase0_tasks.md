# Фаза 0: Очистка кодовой базы — детальные ТЗ

**Дата:** 2026-04-30
**Статус:** DRAFT
**Родительский план:** `multiprocess_prototype/plans/general_refactoring.md`

---

## Обзор

Фаза 0 — безопасная подготовка к рефакторингу. **Никаких архитектурных изменений, никакого переноса во фреймворк.** Цель: убрать мёртвый код, устранить дублирование заглушек, починить импорты — чтобы Фаза 2 (перенос во фреймворк) работала с чистой базой.

Ожидаемый результат: ~2,500 строк удалено, нет нарушений канонических импортов, тесты коллектируются без ошибок.

**Порядок выполнения (от наименее рискованного к наиболее):**
0.1 → 0.2 → 0.3 → 0.6 → 0.4 → 0.5

После каждой подзадачи: smoke-проверка (см. раздел "Верификация").

---

## Факты, проверенные при анализе кода

### Расхождения с исходным планом

1. **`camera_policy.py` в корне vs `registers/camera/policy.py`:**
   - Корневой файл (39 строк): содержит 3 типа камер (`"simulator"`, `"webcam"`, `"hikvision"`), функции `is_valid_camera_type()`, `supports_enum()`, `supports_hardware_handoff()`, `Tuple` из `typing`.
   - `registers/camera/policy.py` (24 строки): содержит **4 типа** (`"file"` добавлен), нет функций (только константы), использует `tuple[...]` вместо `Tuple[...]`, имеет `__all__`.
   - **Вывод:** корневой файл — устаревший дубликат. `registers/camera/__init__.py` уже реэкспортирует `policy.py`. Нужно удалить корневой файл и проверить все его импортёры.

2. **`registers/schemas/` — уже pure re-export заглушки:**
   Все файлы (6 py-файлов + 2 `__init__.py`) уже содержат только `# DEPRECATED: use ... directly` + re-export. Реальный код давно в `registers/camera/`, `registers/pipeline/`, `registers/payloads/`. Удаление безопасно при условии обновления импортёров.

3. **`registers/producer.py` и `registers/aggregator.py`:**
   - Ссылаются на `from .names import PRODUCER_REGISTER / AGGREGATOR_REGISTER`.
   - Файл `registers/names.py` **не существует** — это сломанный импорт.
   - `registers/__init__.py` их **не импортирует** и не включает в `create_registers()`.
   - **Вывод:** оба файла — артефакты демо-примера фреймворка (producer/aggregator процессы), никогда не подключались к прототипу. Удалить.

4. **`AppConfig.processor` property:**
   Уже помечен `@deprecated` с `warnings.warn()`. Находится в `config/app.py` строки 89-100. Удалить property, оставить метод.

5. **`config/logging.py` (23 строки):**
   Содержит только `LoggingConfig(SchemaBase)` — маленький класс. Уже импортируется в `config/app.py` как `from .logging import LoggingConfig`. Встроить означает перенести класс прямо в `config/app.py`.

6. **`backend/processes/*/__main__.py` (6 файлов):**
   Все 6 файлов (`camera`, `processor`, `renderer`, `database`, `robot`, `gui`) — отладочные standalone-запускалки для разработки (запуск единственного процесса без оркестратора). **НЕ используются в production-запуске** (`run.py` → `SystemLauncher`). Это отладочная утилита, её удаление не влияет на основной запуск. Рекомендация: **оставить** — они полезны при разработке/отладке отдельных процессов. В план не включать.

7. **Тест-директории `registers/system_topology/tests/` и `frontend/models/sections/tests/`:**
   Обе директории содержат только пустой `__init__.py`. Тест-файлов нет. Перемещать нечего — нужно просто удалить эти пустые директории.

8. **Импорты `from state_store.X` (реальное количество):**
   `conftest.py` добавляет `multiprocess_prototype/` в `sys.path`, поэтому `from state_store.X` технически работает в тестах. Но это нарушение канонического импорта. `state_store/__init__.py` сам содержит такие импорты. Реальных вхождений ~133 (не 40 как в плане).

---

## Подзадача 0.1 — Удалить архивные виджеты

**Уровень:** Junior (Haiku)
**Исполнитель:** developer

**Цель:** Физически удалить директорию `frontend/widgets/_archive/` с 20 файлами мёртвого кода (~1,896 строк).

**Контекст:**
`_archive/` содержит три группы виджетов: `catalog_editor/`, `chain_editor/`, `_hikvision_widget_legacy/`. Они не импортируются ни из одного активного модуля (пустой `__init__.py` в корне `_archive/`). Все используемые Hikvision-функции уже перенесены в `frontend/widgets/sources/`.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/_archive/` — удалить всю директорию целиком

**Шаги:**
1. Убедиться что `frontend/widgets/_archive/__init__.py` пустой (проверено — 1 строка, пустой).
2. Выполнить grep по всему `multiprocess_prototype/` на `_archive`:
   ```
   grep -rn "_archive" multiprocess_prototype/ --include="*.py"
   ```
   Если результатов нет — безопасно удалять.
3. Удалить: `rm -rf multiprocess_prototype/frontend/widgets/_archive/`
4. Smoke-проверка.

**Acceptance criteria:**
- [ ] Директория `multiprocess_prototype/frontend/widgets/_archive/` не существует
- [ ] `grep -rn "_archive" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python scripts/validate.py` — без ошибок
- [ ] `pytest multiprocess_prototype/tests/ -x --co` — коллекция не падает

**Риски:** Минимальные. `_archive/__init__.py` пустой — никаких re-export нет.

**Edge cases:** Если grep найдёт импорт из `_archive` в каком-либо файле — не удалять, сначала разобраться.

**Зависимости:** Нет.

---

## Подзадача 0.2 — Удалить re-export заглушки `registers/schemas/`

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Цель:** Найти все импортёры `registers/schemas/`, перенаправить на прямые импорты, удалить директорию.

**Контекст:**
Все файлы в `registers/schemas/` — уже чистые re-export заглушки с пометкой DEPRECATED. Реальный код давно живёт в `registers/camera/`, `registers/pipeline/`, `registers/payloads/`, `registers/constants.py`. Директория создаёт иллюзию нужного модуля и мешает понять реальную структуру.

**Файлы в `registers/schemas/` (все удаляются):**
- `__init__.py` — compat layer
- `pipeline/__init__.py` — DEPRECATED
- `pipeline/widget_bridge.py` — re-export → `registers.pipeline.widget_bridge`
- `processing_tab/__init__.py` — re-export → `registers.constants`
- `processing_tab/post_processing_payload.py` — re-export → `registers.payloads.post_processing`
- `processing_tab/crop_regions_payload.py` — re-export → `registers.payloads.crop_regions`
- `processing_tab/names.py` — re-export → `registers.constants`
- `camera_tab.py` — re-export → `registers.camera`, `registers.constants`

**Шаги:**
1. Найти все импортёры каждой заглушки:
   ```
   grep -rn "from.*registers\.schemas" multiprocess_prototype/ --include="*.py"
   grep -rn "import.*registers\.schemas" multiprocess_prototype/ --include="*.py"
   ```
2. Для каждого найденного файла заменить импорт на прямой:
   - `from ...registers.schemas.pipeline.widget_bridge import X` → `from ...registers.pipeline.widget_bridge import X`
   - `from ...registers.schemas.processing_tab.post_processing_payload import X` → `from ...registers.payloads.post_processing import X`
   - `from ...registers.schemas.processing_tab.crop_regions_payload import X` → `from ...registers.payloads.crop_regions import X`
   - `from ...registers.schemas.processing_tab.names import X` → `from ...registers.constants import X`
   - `from ...registers.schemas.camera_tab import X` → `from ...registers.camera import X` (для `HikvisionParamRow`, `build_hikvision_param_rows`, `GuiCameraRegisters`) и `from ...registers.constants import X` (для `CAMERA_REGISTER`, `CAMERA_ROUTING`)
3. Повторный grep — убедиться что импортёров не осталось.
4. Удалить: `rm -rf multiprocess_prototype/registers/schemas/`
5. Smoke-проверка.

**Acceptance criteria:**
- [ ] Директория `multiprocess_prototype/registers/schemas/` не существует
- [ ] `grep -rn "registers\.schemas" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python scripts/validate.py` — без ошибок
- [ ] `pytest multiprocess_prototype/tests/ -x --co` — коллекция не падает
- [ ] Импорт без ошибок: `python -c "from multiprocess_prototype.registers import create_registers; create_registers()"`

**Риски:** Средние. Если какой-то внешний код импортирует через schemas — сломается. Поэтому сначала grep, потом удаление.

**Edge cases:** Если `registers/schemas/` импортируется через `__init__.py` registers — заменить там же.

**Зависимости:** Нет (не зависит от 0.1).

---

## Подзадача 0.3 — Убрать файлы-одиночки

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Цель:** Удалить устаревший корневой `camera_policy.py` и артефактные `registers/producer.py`, `registers/aggregator.py`.

### 0.3a — Удалить корневой `camera_policy.py`

**Контекст:**
Корневой `multiprocess_prototype/camera_policy.py` — устаревший дубликат `registers/camera/policy.py`. Расхождения: корневой знает только 3 типа камер (без `"file"`), содержит функции (`is_valid_camera_type`, `supports_enum`, `supports_hardware_handoff`), использует старый `typing.Tuple`. Канонический файл — `registers/camera/policy.py`, реэкспортируется через `registers/camera/__init__.py`.

**Файлы:**
- `multiprocess_prototype/camera_policy.py` — удалить
- Любые файлы-импортёры — обновить импорт

**Шаги:**
1. Найти все импортёры:
   ```
   grep -rn "from.*camera_policy import\|import camera_policy\|from multiprocess_prototype.camera_policy" multiprocess_prototype/ --include="*.py"
   grep -rn "from.*camera_policy import\|import camera_policy\|from multiprocess_prototype.camera_policy" multiprocess_framework/ --include="*.py"
   ```
2. Для каждого импортёра:
   - `from camera_policy import X` → `from multiprocess_prototype.registers.camera import X` (все нужные символы есть в `registers/camera/__init__.py`)
   - Функции `is_valid_camera_type`, `supports_enum`, `supports_hardware_handoff` — **не перенесены** в `registers/camera/policy.py`. Если они используются — добавить в `registers/camera/policy.py` перед удалением корневого файла (и не забыть добавить в `__all__` и реэкспортировать через `registers/camera/__init__.py`).
3. Удалить: `rm multiprocess_prototype/camera_policy.py`
4. Smoke-проверка.

**Acceptance criteria:**
- [ ] `multiprocess_prototype/camera_policy.py` не существует
- [ ] `grep -rn "camera_policy" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python -c "from multiprocess_prototype.registers.camera import CAMERA_TYPES"` — без ошибок

### 0.3b — Удалить артефактные `producer.py` и `aggregator.py`

**Контекст:**
`registers/producer.py` и `registers/aggregator.py` — регистры для демо-процессов фреймворка (producer/aggregator). К прototипу не относятся. Не импортируются из `registers/__init__.py`. Содержат сломанный импорт `from .names import PRODUCER_REGISTER/AGGREGATOR_REGISTER` (файл `registers/names.py` не существует).

**Файлы:**
- `multiprocess_prototype/registers/producer.py` — удалить
- `multiprocess_prototype/registers/aggregator.py` — удалить

**Шаги:**
1. Убедиться что они не импортируются:
   ```
   grep -rn "from.*registers.producer\|from.*registers.aggregator\|import producer\|import aggregator" multiprocess_prototype/ --include="*.py"
   ```
2. Если результатов нет — удалить оба файла.
3. Smoke-проверка.

**Acceptance criteria:**
- [ ] Файлы `registers/producer.py` и `registers/aggregator.py` не существуют
- [ ] `grep -rn "registers.producer\|registers.aggregator" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python -c "from multiprocess_prototype.registers import create_registers"` — без ошибок

**Риски (0.3b):** Минимальные — файлы сломаны (импортируют несуществующий `.names`) и не используются.

**Зависимости:** Нет.

---

## Подзадача 0.6 — Очистить пустые тест-директории

**Уровень:** Junior (Haiku)
**Исполнитель:** developer

**Цель:** Удалить пустые тест-директории, которые предназначались для переноса тестов, но тесты в них так и не появились.

**Контекст:**
По плану нужно было перенести тесты из `registers/system_topology/tests/` и `frontend/models/sections/tests/` в `tests/unit/`. После проверки: обе директории содержат только пустой `__init__.py` — реальных тест-файлов нет. Перемещать нечего.

**Файлы:**
- `multiprocess_prototype/registers/system_topology/tests/` — удалить директорию (только `__init__.py`)
- `multiprocess_prototype/frontend/models/sections/tests/` — удалить директорию (только `__init__.py`)
- При необходимости создать директории в `tests/unit/` для будущих тестов (если их нет): `tests/unit/registers/`, `tests/unit/frontend/`

**Шаги:**
1. Убедиться что в директориях только `__init__.py`:
   ```
   ls multiprocess_prototype/registers/system_topology/tests/
   ls multiprocess_prototype/frontend/models/sections/tests/
   ```
2. Удалить:
   ```
   rm -rf multiprocess_prototype/registers/system_topology/tests/
   rm -rf multiprocess_prototype/frontend/models/sections/tests/
   ```
3. Создать целевые директории с `__init__.py` если не существуют:
   ```
   multiprocess_prototype/tests/unit/registers/__init__.py  (если нет)
   multiprocess_prototype/tests/unit/frontend/__init__.py   (если нет)
   ```
4. Smoke-проверка.

**Acceptance criteria:**
- [ ] `registers/system_topology/tests/` не существует
- [ ] `frontend/models/sections/tests/` не существует
- [ ] Директории `tests/unit/registers/` и `tests/unit/frontend/` существуют (пустые `__init__.py`)
- [ ] `pytest multiprocess_prototype/tests/ -x --co` — коллекция не падает

**Риски:** Минимальные. Директории пустые — ни один тест не пострадает.

**Edge cases:** Проверить нет ли ссылок на эти тест-директории в `pytest.ini` / `pyproject.toml`.

**Зависимости:** Нет (выполнять после 0.1 для чистоты).

---

## Подзадача 0.4 — Deprecated AppConfig.processor + встроить LoggingConfig

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Цель:** Удалить устаревший `AppConfig.processor` property и встроить `LoggingConfig` из отдельного файла.

### 0.4a — Удалить `AppConfig.processor` property

**Контекст:**
Property `AppConfig.processor` (строки 89-100 в `config/app.py`) помечен как `@deprecated` с `warnings.warn(DeprecationWarning)`. Возвращает `processors[0]`. Удалить property, чтобы вызывающий код явно использовал `processors[0]`.

**Файлы:**
- `multiprocess_prototype/config/app.py` — удалить property (строки 89-100)
- Любые файлы-вызыватели `.processor` — заменить на `.processors[0]`

**Шаги:**
1. Найти все вызовы deprecated property:
   ```
   grep -rn "\.processor\b" multiprocess_prototype/ --include="*.py" | grep -v "processors\|processor_" | grep -v "config/app.py"
   grep -rn "app_config\.processor\b\|cfg\.processor\b\|config\.processor\b" multiprocess_prototype/ --include="*.py"
   ```
2. Для каждого вызывателя заменить `.processor` → `.processors[0]`.
3. Удалить property `processor` из `AppConfig` в `config/app.py` (строки 89-100).
4. Убедиться что `import warnings` в `config/app.py` больше не нужен — если так, удалить.
5. Smoke-проверка.

**Acceptance criteria:**
- [ ] В `config/app.py` нет метода `processor` (только `processors`)
- [ ] `grep -rn "\.processor\b" multiprocess_prototype/ --include="*.py"` не находит вызовов deprecated property
- [ ] `python -c "from multiprocess_prototype.config.app import AppConfig; c = AppConfig(); print(c.processors[0])"` — без ошибок

### 0.4b — Встроить `LoggingConfig` в `config/app.py`

**Контекст:**
`config/logging.py` содержит только `LoggingConfig` (23 строки). Уже импортируется в `config/app.py` как `from .logging import LoggingConfig`. Задача: перенести класс в `config/app.py`, удалить отдельный файл. Это уменьшает количество мелких файлов в `config/`.

**Файлы:**
- `multiprocess_prototype/config/logging.py` — скопировать содержимое класса в `app.py`, затем удалить
- `multiprocess_prototype/config/app.py` — добавить `LoggingConfig` перед `AppConfig`, убрать `from .logging import LoggingConfig`
- `multiprocess_prototype/config/__init__.py` — проверить и обновить реэкспорт если нужно

**Шаги:**
1. Найти все импортёры `config.logging` / `config/logging.py`:
   ```
   grep -rn "from.*config.logging import\|from.*config import.*LoggingConfig" multiprocess_prototype/ --include="*.py"
   grep -rn "from.*config.logging import\|from.*config import.*LoggingConfig" multiprocess_framework/ --include="*.py"
   ```
2. Скопировать тело `LoggingConfig` (включая импорты `os`, `Path`, `_PROTO_ROOT`) в `config/app.py` — перед классом `AppConfig`.
3. Убрать строку `from .logging import LoggingConfig` из `config/app.py`.
4. Обновить импортёров: если кто-то делает `from multiprocess_prototype.config.logging import LoggingConfig` — заменить на `from multiprocess_prototype.config.app import LoggingConfig` или `from multiprocess_prototype.config import LoggingConfig` (если реэкспортируется).
5. Обновить `config/__init__.py`: убедиться что `LoggingConfig` реэкспортируется.
6. Удалить `config/logging.py`.
7. Smoke-проверка.

**Acceptance criteria:**
- [ ] `multiprocess_prototype/config/logging.py` не существует
- [ ] `LoggingConfig` доступен из `multiprocess_prototype.config.app`
- [ ] `grep -rn "from.*config.logging import" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python -c "from multiprocess_prototype.config.app import AppConfig, LoggingConfig"` — без ошибок

**Риски (0.4b):** Средние. Если `config/logging.py` импортируется напрямую (не через `config/__init__.py`), такие импортёры сломаются. Поэтому сначала grep.

**Зависимости:** 0.4a и 0.4b независимы друг от друга, но оба после 0.1-0.3.

---

## Подзадача 0.5 — Канонические импорты `state_store`

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer

**Цель:** Заменить все `from state_store.X` → `from multiprocess_prototype.state_store.X` во всём `multiprocess_prototype/`, включая сам `state_store/__init__.py`.

**Контекст:**
`state_store/__init__.py` сам нарушает канонику — содержит 15+ строк вида `from state_store.core.delta import ...`. Это работает только благодаря `conftest.py`, который добавляет `multiprocess_prototype/` в `sys.path`. Такой подход нарушает правило "канонический импорт = полный путь от пакета". По плану: ~133 вхождения (не 40, как указано в `general_refactoring.md`).

**Важно:** Это самая сложная подзадача по охвату изменений. Необходимо учитывать что `conftest.py` добавляет `multiprocess_prototype/` в `sys.path` — после исправления импортов тесты могут требовать перезапуска с правильным `PYTHONPATH`.

**Файлы:**
- `multiprocess_prototype/state_store/__init__.py` — заменить все `from state_store.X` → `from multiprocess_prototype.state_store.X`
- Все файлы в `multiprocess_prototype/` с нарушением импорта

**Шаги:**
1. Собрать полный список нарушений:
   ```
   grep -rn "from state_store\." multiprocess_prototype/ --include="*.py"
   grep -rn "^import state_store" multiprocess_prototype/ --include="*.py"
   ```
   Сохранить список файлов — будет нужен для проверки.

2. Дополнительно проверить аналогичные нарушения для других подмодулей (зафиксировать, но НЕ исправлять в этой подзадаче):
   ```
   grep -rn "^from registers\." multiprocess_prototype/ --include="*.py"
   grep -rn "^from frontend\." multiprocess_prototype/ --include="*.py"
   grep -rn "^from backend\." multiprocess_prototype/ --include="*.py"
   grep -rn "^from services\." multiprocess_prototype/ --include="*.py"
   grep -rn "^from config\." multiprocess_prototype/ --include="*.py"
   ```
   Записать количество нарушений в комментарий в конце этого файла плана.

3. В первую очередь исправить `state_store/__init__.py` — заменить все относительные пути:
   ```python
   # ДО:
   from state_store.core.delta import MISSING, Delta, Transaction
   # ПОСЛЕ:
   from multiprocess_prototype.state_store.core.delta import MISSING, Delta, Transaction
   ```

4. Исправить все остальные файлы из списка шага 1. Использовать sed или ручную замену:
   ```
   # Паттерн для sed:
   sed -i '' 's/from state_store\./from multiprocess_prototype.state_store./g' <file>
   ```
   Применять к каждому файлу из списка.

5. Проверить что тесты в `multiprocess_prototype/tests/` по-прежнему работают. Тесты в `state_store/tests/` могут потребовать обновления `conftest.py` если импортируют `from state_store.X` напрямую.

6. Финальный grep — убедиться что нарушений нет:
   ```
   grep -rn "from state_store\." multiprocess_prototype/ --include="*.py"
   ```

**Acceptance criteria:**
- [ ] `grep -rn "^from state_store\." multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `grep -rn "^import state_store" multiprocess_prototype/ --include="*.py"` — 0 результатов
- [ ] `python -c "from multiprocess_prototype.state_store import TreeStore, StateStoreManager"` — без ошибок
- [ ] `pytest multiprocess_prototype/tests/ -x --co` — коллекция не падает
- [ ] `pytest multiprocess_prototype/state_store/tests/ -x --co` — коллекция не падает

**Риски:** Высокие по охвату (~133 файла). Рекомендуется делать через `sed` скриптом, а не вручную, и проверять тесты после каждого пакета файлов. Особое внимание к `state_store/__init__.py` — он публичный API.

**Edge cases:**
- Строки вида `from state_store import X` (без точки после) — НЕ заменять автоматически, анализировать отдельно.
- Файлы в `state_store/tests/` могут иметь собственный conftest — проверить.
- После замены импортов проверить что `conftest.py` всё ещё нужен (скорее всего нужен для `multiprocess_framework/modules`).

**Зависимости:** Выполнять последней (после 0.1-0.4) — минимальный контекст нарушений.

---

## Финальная верификация Фазы 0

После выполнения всех подзадач (0.1 → 0.2 → 0.3 → 0.6 → 0.4 → 0.5):

```bash
# 1. Структурная валидация
python scripts/validate.py

# 2. Тесты фреймворка
python scripts/run_framework_tests.py

# 3. Коллекция тестов прототипа (не запуск, только сбор)
pytest multiprocess_prototype/tests/ -x --co -q

# 4. Проверка импортов ключевых модулей
python -c "from multiprocess_prototype.config.app import AppConfig, LoggingConfig; print('config OK')"
python -c "from multiprocess_prototype.registers import create_registers; print('registers OK')"
python -c "from multiprocess_prototype.state_store import TreeStore, StateStoreManager; print('state_store OK')"
python -c "from multiprocess_prototype.registers.camera import CAMERA_TYPES; print(CAMERA_TYPES)"

# 5. Отсутствие удалённых артефактов
test ! -d multiprocess_prototype/frontend/widgets/_archive && echo "archive OK"
test ! -d multiprocess_prototype/registers/schemas && echo "schemas OK"
test ! -f multiprocess_prototype/camera_policy.py && echo "camera_policy OK"
test ! -f multiprocess_prototype/registers/producer.py && echo "producer OK"
test ! -f multiprocess_prototype/registers/aggregator.py && echo "aggregator OK"
test ! -f multiprocess_prototype/config/logging.py && echo "logging OK"

# 6. Нет нарушений канонических импортов
grep -rn "^from state_store\." multiprocess_prototype/ --include="*.py" | wc -l
# Ожидается: 0
```

**Ожидаемый итог:** 
- Удалено ~2,500 строк мёртвого и дублирующего кода
- Нет нарушений `from state_store.X`  
- `registers/schemas/`, `frontend/widgets/_archive/`, `camera_policy.py`, `registers/producer.py`, `registers/aggregator.py`, `config/logging.py` — не существуют
- Все тесты коллектируются без ошибок

---

## Сводная таблица подзадач

| # | Подзадача | Уровень | Риск | Файлов удаляется | Зависит от |
|---|-----------|---------|------|-----------------|------------|
| 0.1 | Удалить `_archive/` | Junior | Низкий | ~20 | — |
| 0.2 | Удалить `registers/schemas/` | Middle | Средний | ~8 | — |
| 0.3a | Удалить корневой `camera_policy.py` | Middle | Средний | 1 | — |
| 0.3b | Удалить `producer.py`, `aggregator.py` | Junior | Низкий | 2 | — |
| 0.6 | Очистить пустые тест-директории | Junior | Низкий | ~2 | 0.1 |
| 0.4a | Удалить `AppConfig.processor` property | Middle | Средний | 0 (правка) | 0.1-0.3 |
| 0.4b | Встроить `LoggingConfig` в `app.py` | Middle | Средний | 1 | 0.1-0.3 |
| 0.5 | Канонические импорты `state_store` | Middle+ | Высокий | 0 (правка ~133 файлов) | 0.1-0.4 |

**Рекомендуемый порядок выполнения:** 0.1 и 0.3b параллельно → 0.2 и 0.3a → 0.6 → 0.4a и 0.4b → 0.5

---

## Постфактум: остаточные нарушения канонических импортов

Зафиксировано после выполнения подзадачи 0.5 (2026-04-30).
Нарушения для других подмодулей **не исправлялись** в Фазе 0 — будут отдельным проходом.

| Подмодуль | Файлов с нарушениями | Команда |
|-----------|---------------------|---------|
| `registers` | 22 | `grep -rln "^from registers\." multiprocess_prototype/ --include="*.py"` |
| `frontend` | 18 | `grep -rln "^from frontend\." multiprocess_prototype/ --include="*.py"` |
| `services` | 16 | `grep -rln "^from services\." multiprocess_prototype/ --include="*.py"` |
| `backend` | 2 | `grep -rln "^from backend\." multiprocess_prototype/ --include="*.py"` |
| `config` | 1 | `grep -rln "^from config\." multiprocess_prototype/ --include="*.py"` |
| `data` | 0 | — |
| `persistence` | 0 | — |
| **state_store** | **0** | исправлено в 0.5 (52 файла, 121 строка) |
