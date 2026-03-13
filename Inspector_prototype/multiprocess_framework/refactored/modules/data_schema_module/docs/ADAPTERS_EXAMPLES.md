# Примеры адаптеров — Интеграция data_schema_module с другими модулями

**Версия:** 2.0 | **Дата:** 2026-03-13 | **Статус:** Примеры для Шага 11

---

## 📖 Концепция

**Адаптеры** позволяют модулям фреймворка преобразовывать схемы в формат, специфичный для их использования. Это следует принципу **Dependency Inversion** — каждый модуль зависит от абстракции (`ISchemaAdapter`), а не от конкретной реализации.

```
┌─────────────────────────────────────────────────────────┐
│ data_schema_module                                      │
│  ├── interfaces.py  → ISchemaAdapter (протокол)       │
│  └── (core, registry, serialization, container, ...)   │
└─────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │ implements         │ implements         │ implements
         │                    │                    │
    ┌────┴────────────┐  ┌───┴──────────────┐  ┌─┴─────────────┐
    │ router_module   │  │ config_module    │  │ process_mgr   │
    │ adapters/       │  │ adapters/        │  │ adapters/     │
    │ schema_adapter. │  │ schema_adapter.  │  │ schema_adapter│
    │ py              │  │ py               │  │ .py           │
    └────────────────┘  └──────────────────┘  └───────────────┘
```

---

## 1️⃣ RouterSchemaAdapter — преобразование схемы в маршруты

**Расположение:** `router_module/adapters/schema_adapter.py`

**Назначение:** Преобразовать схему в описание каналов маршрутизации.

**Реализация:**

```python
# router_module/adapters/schema_adapter.py
from typing import Type, Dict, Any
from data_schema_module import ISchemaAdapter, ISchema

class RouterSchemaAdapter:
    """
    Адаптер для преобразования Schema в описание маршрутов Router'а.
    
    Из FieldMeta каждого поля извлекаем информацию маршрутизации
    (channel, priority, access_level) и строим реестр маршрутов.
    """
    
    def adapt(self, schema_class: Type[ISchema], **options) -> Dict[str, Any]:
        """
        Преобразовать Schema в реестр маршрутов для Router.
        
        Результат:
        {
            "channel_1": {
                "fields": ["field_a", "field_b"],
                "priority": 1,
            },
            "channel_2": {
                "fields": ["field_c"],
                "priority": 0,
            },
        }
        """
        routes = {}
        
        for field_name, meta in schema_class.get_all_fields_meta().items():
            if not meta.routing:
                continue
            
            # Поддерживаем оба формата: dict и FieldRouting
            if isinstance(meta.routing, dict):
                channel = meta.routing.get("channel")
            else:
                # FieldRouting имеет атрибут channel
                channel = getattr(meta.routing, "channel", None)
            
            if not channel:
                continue
            
            # Создаём или обновляем запись канала
            if channel not in routes:
                routes[channel] = {
                    "fields": [],
                    "priority": getattr(meta.routing, "priority", 0) 
                                if not isinstance(meta.routing, dict) 
                                else meta.routing.get("priority", 0),
                }
            
            routes[channel]["fields"].append(field_name)
        
        return routes
    
    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """
        Адаптировать конкретный экземпляр (если нужны значения полей).
        """
        # Получить маршруты из класса
        routes = self.adapt(type(schema_instance))
        
        # Если нужны значения — добавить их
        if options.get("include_values"):
            data = schema_instance.model_dump()
            for channel_info in routes.values():
                for field_name in channel_info["fields"]:
                    channel_info.setdefault("values", {})[field_name] = data.get(field_name)
        
        return routes


# ============================================================================
# Использование в router_module
# ============================================================================

# router_module/__init__.py или config
from .adapters.schema_adapter import RouterSchemaAdapter

adapter = RouterSchemaAdapter()

# Во время инициализации Router'а:
routes = adapter.adapt(DrawRegisters)
print(routes)
# Output:
# {
#     "control_draw": {
#         "fields": ["dp", "min_dist"],
#         "priority": 1,
#     }
# }

# Использовать в RouterManager:
for channel, info in routes.items():
    self.register_channel(channel, priority=info["priority"])
    for field in info["fields"]:
        self.add_field_to_channel(field, channel)
```

---

## 2️⃣ ConfigSchemaAdapter — преобразование схемы в параметры конфига

**Расположение:** `config_module/adapters/schema_adapter.py`

**Назначение:** Преобразовать схему в дерево параметров для ConfigManager.

**Реализация:**

```python
# config_module/adapters/schema_adapter.py
from typing import Type, Dict, Any
from data_schema_module import ISchemaAdapter, ISchema

class ConfigSchemaAdapter:
    """
    Адаптер для преобразования Schema в параметры конфигурации.
    
    Каждое поле схемы становится параметром в ConfigManager с его
    ограничениями (min/max), значением по умолчанию и метаданными.
    """
    
    def adapt(self, schema_class: Type[ISchema], **options) -> Dict[str, Any]:
        """
        Преобразовать Schema в реестр параметров конфигурации.
        
        Результат:
        {
            "dp": {
                "type": "float",
                "default": 1.4,
                "description": "Разрешение",
                "constraints": {"min": 0.1, "max": 20.0},
                "unit": "px",
                "access_level": 0,
            },
            "enabled": {
                "type": "bool",
                "default": True,
                "description": "Включено",
            },
        }
        """
        result = {}
        
        for field_name, meta in schema_class.get_all_fields_meta().items():
            field_info = schema_class.model_fields[field_name]
            
            param_info = {
                "type": self._get_type_name(field_info.annotation),
                "default": field_info.default,
                "description": meta.description or field_name,
            }
            
            # Добавить метаданные FieldMeta если есть
            if meta.info:
                param_info["info"] = meta.info
            
            if meta.unit:
                param_info["unit"] = meta.unit
            
            if meta.min is not None or meta.max is not None:
                param_info["constraints"] = {}
                if meta.min is not None:
                    param_info["constraints"]["min"] = meta.min
                if meta.max is not None:
                    param_info["constraints"]["max"] = meta.max
            
            if meta.access_level > 0:
                param_info["access_level"] = meta.access_level
            
            if meta.readonly:
                param_info["readonly"] = True
            
            if meta.examples:
                param_info["examples"] = meta.examples
            
            # Интернационализация (если нужна)
            if meta.description_i18n:
                param_info["description_i18n"] = meta.description_i18n
            
            result[field_name] = param_info
        
        return result
    
    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """
        Адаптировать экземпляр (получить текущие значения параметров).
        """
        config_schema = self.adapt(type(schema_instance))
        values = schema_instance.model_dump()
        
        # Добавить текущие значения
        for param_name, param_info in config_schema.items():
            param_info["value"] = values.get(param_name)
        
        return config_schema
    
    def _get_type_name(self, annotation: Any) -> str:
        """Преобразовать type annotation в строку."""
        if hasattr(annotation, "__name__"):
            return annotation.__name__
        return str(annotation)


# ============================================================================
# Использование в config_module
# ============================================================================

# config_module/__init__.py или config manager
from .adapters.schema_adapter import ConfigSchemaAdapter

adapter = ConfigSchemaAdapter()

# Во время инициализации ConfigManager'а:
config_params = adapter.adapt(ProcessConfig)
print(config_params)
# Output:
# {
#     "timeout": {
#         "type": "float",
#         "default": 5.0,
#         "description": "Таймаут, сек",
#         "constraints": {"min": 0.1, "max": 60.0},
#     },
#     "workers": {
#         "type": "int",
#         "default": 4,
#         "description": "Кол-во воркеров",
#         "constraints": {"min": 1, "max": 32},
#     },
# }

# Использовать для валидации и UI
config_manager.register_parameters(config_params)

# Для снятия текущих значений:
current_values = adapter.adapt_instance(config_instance)
```

---

## 3️⃣ ProcessSchemaAdapter — преобразование схемы в конфиг процесса

**Расположение:** `process_manager_module/adapters/schema_adapter.py`

**Назначение:** Преобразовать схему в конфиг для запуска процесса.

**Реализация:**

```python
# process_manager_module/adapters/schema_adapter.py
from typing import Type, Dict, Any, Tuple
from data_schema_module import ISchemaAdapter, ISchema, HasBuild

class ProcessSchemaAdapter:
    """
    Адаптер для преобразования Schema в конфиг процесса.
    
    Следует принципу Dict at Boundary: Schema → dict, который будет
    передан через очередь в дочерний процесс.
    """
    
    def adapt(self, schema_class: Type[ISchema], **options) -> Tuple[str, Dict[str, Any]]:
        """
        Преобразовать Schema в (name, config_dict) для процесса.
        
        Возвращает:
            (name: str, config_dict: Dict[str, Any])
            
        Пример:
            ("ProcessConfig", {"timeout": 5.0, "workers": 4, ...})
        """
        # Получить имя схемы
        name = self._get_schema_name(schema_class)
        
        # Создать экземпляр со значениями по умолчанию
        instance = schema_class()
        
        # Преобразовать в dict (для передачи через процесс-границу)
        config_dict = instance.model_dump()
        
        return (name, config_dict)
    
    def adapt_instance(self, schema_instance: Any, **options) -> Tuple[str, Dict[str, Any]]:
        """
        Адаптировать конкретный экземпляр.
        """
        name = self._get_schema_name(type(schema_instance))
        config_dict = schema_instance.model_dump()
        return (name, config_dict)
    
    def _get_schema_name(self, schema_class: Type) -> str:
        """
        Получить имя схемы (используется как ключ в конфиге).
        
        Порядок:
        1. Если класс имеет HasBuild.build() → использовать результат build()
        2. Иначе использовать __name__ класса
        """
        if hasattr(schema_class, "build"):
            try:
                name, _ = schema_class.build(schema_class())
                return name
            except Exception:
                pass
        
        return schema_class.__name__


# ============================================================================
# Использование в process_manager_module
# ============================================================================

# process_manager_module/launcher/system_launcher.py
from .adapters.schema_adapter import ProcessSchemaAdapter

adapter = ProcessSchemaAdapter()

# Во время добавления процесса:
process_config = MyProcessConfig()
worker_config = MyWorkerConfig()

# Адаптировать конфиги (преобразовать в dict)
process_name, process_dict = adapter.adapt_instance(process_config)
worker_name, worker_dict = adapter.adapt_instance(worker_config)

# Добавить в очередь запуска
launcher.add_process(
    process_name=process_name,
    config=process_dict,    # Dict at Boundary!
    worker_name=worker_name,
    worker_config=worker_dict,
)

# ============================================================================
# Специальный случай: процессы с HasBuild
# ============================================================================

from data_schema_module import HasBuild, process

# Если схема наследует HasBuild, можно использовать helper:
launcher.add_process(*process(ProcessConfig(), WorkerConfig()))

# Внутри process():
def process(
    process_config: HasBuild,
    worker_config: HasBuild,
) -> Tuple[Tuple[str, Dict], Tuple[str, Dict]]:
    """
    Вспомогательная функция для преобразования конфигов через HasBuild.
    """
    adapter = ProcessSchemaAdapter()
    return (
        adapter.adapt_instance(process_config),
        adapter.adapt_instance(worker_config),
    )
```

---

## 📝 Шаблон для собственного адаптера

Если вы создаёте новый модуль, который работает со схемами, используйте этот шаблон:

```python
# my_module/adapters/schema_adapter.py
from typing import Type, Dict, Any
from data_schema_module import ISchemaAdapter, ISchema

class MyModuleSchemaAdapter:
    """
    Адаптер для моего модуля.
    
    Преобразует Schema в формат, специфичный для моего use case.
    """
    
    def adapt(self, schema_class: Type[ISchema], **options) -> Dict[str, Any]:
        """
        Основной метод адаптации (для класса).
        
        Args:
            schema_class: Класс схемы (наследник SchemaBase)
            **options: Дополнительные параметры
        
        Returns:
            Dict с адаптированными данными
        """
        result = {}
        
        for field_name, meta in schema_class.get_all_fields_meta().items():
            # Ваша логика преобразования
            result[field_name] = {
                "description": meta.description,
                "type": schema_class.model_fields[field_name].annotation,
            }
        
        return result
    
    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """
        Адаптация конкретного экземпляра (для получения значений).
        
        Args:
            schema_instance: Экземпляр SchemaBase
            **options: Дополнительные параметры
        
        Returns:
            Dict с адаптированными данными + значениями
        """
        adapted = self.adapt(type(schema_instance))
        values = schema_instance.model_dump()
        
        # Добавить значения
        for field_name in adapted:
            adapted[field_name]["value"] = values.get(field_name)
        
        return adapted
```

---

## 🧪 Тестирование адаптеров

```python
# router_module/tests/test_schema_adapter.py
import unittest
from typing import Annotated
from data_schema_module import FieldMeta, SchemaBase, FieldRouting
from ..adapters.schema_adapter import RouterSchemaAdapter

class TestRouterSchemaAdapter(unittest.TestCase):
    
    def setUp(self):
        self.adapter = RouterSchemaAdapter()
        
        # Создать тестовую схему
        DRAW = FieldRouting(channel="control_draw", priority=1)
        
        class TestSchema(SchemaBase):
            dp: Annotated[float, FieldMeta("Разрешение", routing=DRAW)] = 1.4
            min_dist: Annotated[float, FieldMeta("Мин. расстояние", routing=DRAW)] = 50.0
        
        self.schema_class = TestSchema
    
    def test_adapt_extracts_routes(self):
        """Адаптер должен извлечь маршруты из FieldMeta."""
        routes = self.adapter.adapt(self.schema_class)
        
        self.assertIn("control_draw", routes)
        self.assertEqual(set(routes["control_draw"]["fields"]), {"dp", "min_dist"})
        self.assertEqual(routes["control_draw"]["priority"], 1)
    
    def test_adapt_instance_includes_values(self):
        """Адаптер экземпляра должен включить значения полей."""
        instance = self.schema_class()
        routes = self.adapter.adapt_instance(instance, include_values=True)
        
        self.assertIn("control_draw", routes)
        self.assertIn("values", routes["control_draw"])
        self.assertEqual(routes["control_draw"]["values"]["dp"], 1.4)

if __name__ == "__main__":
    unittest.main()
```

---

## 📚 Дополнительные материалы

- **README.md** — Основная документация
- **interfaces.py** — Определение `ISchemaAdapter` протокола
- **docs/examples/** — Примеры использования компонентов
- **MIGRATION.md** — Миграция на новый API

---

## 🎯 Следующие шаги

1. **Шаг 1:** Скопировать примеры адаптеров в соответствующие модули
2. **Шаг 2:** Интегрировать адаптеры в инициализацию модулей
3. **Шаг 3:** Написать тесты для каждого адаптера
4. **Шаг 4:** Обновить документацию модулей (README)
5. **Шаг 5:** Запустить интеграционные тесты

---

**Версия документа:** 1.0 | **Дата:** 2026-03-13 | **Статус:** Примеры готовы для внедрения
