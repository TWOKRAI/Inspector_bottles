# MIGRATION.md — Миграция на data_schema_module v2.0

**Дата:** 2026-03-13 | **Версия:** 2.0 | **Статус:** Backward compatible ✅

---

## 📋 Обзор изменений

data_schema_module пережил крупный рефакторинг (v1.x → v2.0) с целью улучшить модульность, независимость и документированность. **Все старые импорты продолжают работать** благодаря систематическим алиасам в `_compat.py`.

| Аспект | v1.x | v2.0 | Совместимость |
|--------|------|------|---------------|
| Структура | 10+ подпапок, неясная иерархия | 5 слоёв (core, registry, serialization, container, extensions) | ✅ 100% backward compat |
| Классы | `RegisterBase`, `RegisterMixin` | `SchemaBase`, `SchemaMixin` + алиасы | ✅ Старые имена работают |
| Интерфейсы | в `core/interfaces.py` | в корне `interfaces.py` | ✅ Оба пути работают |
| Зависимости | Перемешаны (core + extensions) | Отделены (extensions/ явный импорт) | ✅ Auto-migrate если нужно |
| API | 80+ экспортов | 50 экспортов (минимальный) | ✅ Все ключевые там |

---

## ✅ Начните с этого

### ✅ 1. Если ваш код уже работает — ничего не делайте

```python
# Это всё ещё работает идеально
from data_schema_module import RegisterBase, RegisterMixin, register_schema

class MyConfig(RegisterBase):
    value: float = 1.0
```

**Зачем менять?** Не обязательно. Но новые имена и структура более интуитивны и лучше следуют Python соглашениям.

---

## 🔄 Миграция по этапам

### Этап 1: Базовые классы (5 минут)

**Что изменилось:**
- `RegisterBase` → `SchemaBase` (старое имя всё ещё работает)
- `RegisterMixin` → `SchemaMixin` (старое имя всё ещё работает)

**Миграция:**

```python
# ❌ Старый стиль (работает, но устаревший)
from data_schema_module import RegisterBase, RegisterMixin

class MyConfig(RegisterBase):
    value: float = 1.0

# ✅ Новый стиль (рекомендуется)
from data_schema_module import SchemaBase, SchemaMixin

class MyConfig(SchemaBase):
    value: float = 1.0
```

**Действие:** Если хотите модернизировать, просто переименуйте. Но старое имя работает вечно.

---

### Этап 2: Интерфейсы (если используете)

**Что изменилось:**
- `IRegisterStorage` → `ISchemaStorage`
- `IAsyncRegisterStorage` → `IAsyncSchemaStorage`
- `ISchemaManager` → `ISchemaRegistry`

**Миграция:**

```python
# ❌ Старый стиль
from data_schema_module.core.interfaces import IRegisterStorage

class MyStorage:
    def __implements__(self) -> IRegisterStorage:
        ...

# ✅ Новый стиль
from data_schema_module import ISchemaStorage

class MyStorage:
    def __implements__(self) -> ISchemaStorage:
        ...
```

**Действие:** Переименуйте интерфейсы. Старые имена работают как алиасы.

---

### Этап 3: Расширения (Extensions) — важно!

**ЧТО ИЗМЕНИЛОСЬ:**

В v1.x расширения были смешаны в основном `__init__.py`. В v2.0 они требуют явного импорта:

```python
# ❌ Старый стиль (больше не работает для StorageManager)
from data_schema_module import StorageManager  # ❌ ImportError!

# ✅ Новый стиль (явный импорт)
from data_schema_module.extensions.storage_manager import StorageManager
```

**Полный список миграций Extensions:**

| Компонент | Старый импорт | Новый импорт |
|-----------|---------------|-------------|
| StorageManager | `from data_schema_module import StorageManager` | `from data_schema_module.extensions.storage_manager import StorageManager` |
| VersionManager | `from data_schema_module import VersionManager` | `from data_schema_module.extensions.versioning import VersionManager` |
| BaseComponentModel | `from data_schema_module.models import BaseComponentModel` | `from data_schema_module.extensions.models import BaseComponentModel` |
| ComponentDNA | `from data_schema_module.models.dna import ComponentDNA` | `from data_schema_module.extensions.models import ComponentDNA` |
| SchemaVisualizer | `from data_schema_module.tools import SchemaVisualizer` | `from data_schema_module.extensions.tools import SchemaVisualizer` |
| ModelFactory | `from data_schema_module.factory import ModelFactory` | `from data_schema_module.extensions.factory import ModelFactory` |

**Действие:** Если используете эти компоненты, обновите импорты.

**Быстрый поиск и замена:**

```bash
# Sed-команда для замены StorageManager
sed -i 's/from data_schema_module import StorageManager/from data_schema_module.extensions.storage_manager import StorageManager/g' *.py

# Аналогично для других компонентов
```

---

### Этап 4: Основные компоненты Core (проверка)

**Что НЕ изменилось (Core API):**

```python
# Все эти импорты остаются без изменений
from data_schema_module import (
    SchemaBase,           # (также RegisterBase)
    FieldMeta,            # не менялось
    FieldRouting,         # не менялось
    Percent, HsvHue, Pixels,  # type aliases не менялись
    RegistersContainer,   # не менялось
    register_schema,      # не менялось
    get_default_registry, # новое, но удобное
    DataConverter,        # не менялось
    FileStorage,          # не менялось
)
```

**Действие:** Ничего. Core API стабилен.

---

### Этап 5: process() и Dict at Boundary

**Что НЕ изменилось:**

```python
from data_schema_module import process

# Эта строка работает идеально
launcher.add_process(*process(ProcessConfig(), WorkerConfig()))
```

**Что изменилось (внутренне):** 
- `process()` теперь явно называется из `config_converters.py`
- Но импорт остаётся в основном `__init__.py`

**Действие:** Ничего. API идентичен.

---

## 🎯 Сценарии миграции по модулям

### Для `channel_routing_module`

```python
# ❌ Было (работает, но старый стиль)
from data_schema_module import RegisterBase, FieldMeta

# ✅ Теперь (рекомендуется)
from data_schema_module import SchemaBase, FieldMeta
```

**Действие:** Просто переименуйте `RegisterBase` → `SchemaBase`. Тесты не нужны.

---

### Для `config_module`

```python
# ❌ Было
from data_schema_module import StorageManager, DataConverter

# ✅ Теперь
from data_schema_module.extensions.storage_manager import StorageManager
from data_schema_module import DataConverter  # остаётся здесь
```

**Действие:** Обновить импорт StorageManager на явный путь.

---

### Для `process_manager_module`

```python
# ❌ Было
from data_schema_module import merge_with_defaults, process

# ✅ Теперь
from data_schema_module import merge_with_defaults, process  # оба остаются!
```

**Действие:** Ничего, API идентичен.

---

### Для `shared_resources_module`

```python
# ❌ Было
from data_schema_module import StorageManager

# ✅ Теперь
from data_schema_module.extensions.storage_manager import StorageManager
```

**Действие:** Обновить импорт на явный путь.

---

## 📦 Комплексная сценарий миграции для проекта

**Команда для обновления всех импортов в проекте:**

```bash
# 1. Замена StorageManager
find . -name "*.py" -exec sed -i 's/from data_schema_module import StorageManager/from data_schema_module.extensions.storage_manager import StorageManager/g' {} \;

# 2. Замена VersionManager
find . -name "*.py" -exec sed -i 's/from data_schema_module import VersionManager/from data_schema_module.extensions.versioning import VersionManager/g' {} \;

# 3. Замена BaseComponentModel
find . -name "*.py" -exec sed -i 's/from data_schema_module.models import BaseComponentModel/from data_schema_module.extensions.models import BaseComponentModel/g' {} \;

# 4. Замена ComponentDNA
find . -name "*.py" -exec sed -i 's/from data_schema_module.models import ComponentDNA/from data_schema_module.extensions.models import ComponentDNA/g' {} \;

# 5. Замена SchemaVisualizer
find . -name "*.py" -exec sed -i 's/from data_schema_module.tools import SchemaVisualizer/from data_schema_module.extensions.tools import SchemaVisualizer/g' {} \;

# 6. Замена RegisterBase на SchemaBase (опционально, для стиля)
find . -name "*.py" -exec sed -i 's/RegisterBase/SchemaBase/g' {} \;
```

**После выполнения:** Запустить тесты
```bash
pytest --tb=short -q
```

---

## 🔍 Проверка совместимости (Troubleshooting)

### Проблема 1: `ImportError: cannot import name 'StorageManager'`

```python
# ❌ Ошибка
from data_schema_module import StorageManager

# ✅ Решение
from data_schema_module.extensions.storage_manager import StorageManager
```

---

### Проблема 2: `AttributeError: 'RegisterBase' is not defined`

Это не должно случиться, но если всё же:

```python
# ✅ Решение 1: используйте новое имя
from data_schema_module import SchemaBase as RegisterBase

# ✅ Решение 2: используйте алиас напрямую
from data_schema_module import RegisterBase  # это должно работать
```

---

### Проблема 3: Старые тесты ломаются

Если тесты используют внутренние пути типа `core/interfaces.py`:

```python
# ❌ Было
from data_schema_module.core.interfaces import ISchema

# ✅ Теперь
from data_schema_module import ISchema
```

---

## 📊 Чеклист миграции для вашего проекта

Используйте этот чеклист для полной миграции:

- [ ] **Шаг 1:** Обновить импорты StorageManager → extensions
- [ ] **Шаг 2:** Обновить импорты VersionManager → extensions
- [ ] **Шаг 3:** Обновить импорты компонентов models → extensions
- [ ] **Шаг 4:** Обновить импорты tools → extensions
- [ ] **Шаг 5:** Переименовать RegisterBase → SchemaBase (опционально)
- [ ] **Шаг 6:** Переименовать RegisterMixin → SchemaMixin (опционально)
- [ ] **Шаг 7:** Запустить все тесты — должны пройти
- [ ] **Шаг 8:** Проверить документацию импортов в README
- [ ] **Шаг 9:** Обновить docstrings в коде (если есть)
- [ ] **Шаг 10:** Commit с сообщением: "refactor: migrate to data_schema_module v2.0"

---

## 🚀 Рекомендованный порядок миграции

### Если вы не спешите (safe way)

1. **Неделя 1:** Обновить импорты extensions (StorageManager, VersionManager, etc.)
2. **Неделя 2:** Переименовать базовые классы (RegisterBase → SchemaBase)
3. **Неделя 3:** Запустить полный регрессионный тест
4. **Неделя 4:** Commit и code review

### Если вы спешите (fast way)

1. **Шаг 1:** Применить все sed-команды из раздела выше
2. **Шаг 2:** Запустить `pytest --tb=short`
3. **Шаг 3:** Если проходят — commit
4. **Шаг 4:** Если не проходят — fix failures один за один

---

## 📚 Дополнительная помощь

### Где найти информацию

- **README.md** — Полная документация модуля, примеры
- **STATUS.md** — Статус рефакторинга, чеклист
- **interfaces.py** — Все протоколы и ABC (595 строк)
- **docs/QUICK_REFERENCE.md** — Краткая справка API
- **docs/examples/** — Примеры кода

### Команда для помощи

Если что-то не работает:

```bash
# 1. Проверить версию
python -c "import data_schema_module; print(data_schema_module.__version__)"

# 2. Запустить тесты модуля
pytest data_schema_module/tests/ -v

# 3. Проверить импорт (с деталями ошибки)
python -c "from data_schema_module.extensions.storage_manager import StorageManager"
```

---

## ✅ Итоговая таблица совместимости

| Компонент | v1.x Импорт | v2.0 Импорт | Статус |
|-----------|------------|-----------|--------|
| SchemaBase | RegisterBase | SchemaBase | ✅ Оба работают |
| SchemaMixin | RegisterMixin | SchemaMixin | ✅ Оба работают |
| FieldMeta | FieldMeta | FieldMeta | ✅ Без изменений |
| FieldRouting | FieldRouting | FieldRouting | ✅ Без изменений |
| RegistersContainer | RegistersContainer | RegistersContainer | ✅ Без изменений |
| StorageManager | from data_schema_module | from .extensions.storage_manager | ⚠️ Требует обновления |
| VersionManager | from data_schema_module | from .extensions.versioning | ⚠️ Требует обновления |
| BaseComponentModel | from data_schema_module.models | from .extensions.models | ⚠️ Требует обновления |
| ComponentDNA | from data_schema_module.models.dna | from .extensions.models | ⚠️ Требует обновления |
| SchemaVisualizer | from data_schema_module.tools | from .extensions.tools | ⚠️ Требует обновления |
| ISchemaStorage | IRegisterStorage | ISchemaStorage | ✅ Оба работают (алиас) |

---

## 🎯 Финальные советы

1. **Не спешите переписывать всё** — v2.0 полностью совместима с v1.x
2. **Обновляйте импорты extensions постепенно** — начните с одного модуля
3. **Переименуйте базовые классы для стиля** — но это опционально
4. **Запускайте тесты после каждого этапа** — чтобы уловить проблемы рано
5. **Обновляйте документацию вашего проекта** — укажите, что используется v2.0

---

**Вопросы?** Обратитесь к README.md или STATUS.md.

**Версия документа:** 1.0 | **Дата:** 2026-03-13
