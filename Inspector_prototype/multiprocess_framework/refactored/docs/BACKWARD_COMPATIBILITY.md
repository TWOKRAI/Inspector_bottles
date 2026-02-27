# Обратная совместимость

## ✅ Гарантии обратной совместимости

Все изменения **полностью обратно совместимы**. Старый код продолжает работать без изменений.

### 1. ObservableMixin - simple_mode

**По умолчанию**: `simple_mode=False`

```python
# Старый код (продолжает работать как раньше)
ObservableMixin.__init__(self, managers={...}, auto_proxy=True)
# Работает как раньше - создает прокси-методы, плагины и т.д.

# Новый код (опционально)
ObservableMixin.__init__(self, managers={...}, simple_mode=True)
# Упрощенный режим - только приватные методы
```

**Изменения**:
- Добавлен новый параметр `simple_mode=False` (по умолчанию отключен)
- Старый код работает без изменений
- Новый режим опционален

### 2. BaseManager - get_adapter()

**Изменения**:
- Улучшена документация `get_adapter()` - теперь явно указано что это рекомендуемый способ
- Улучшена документация `__getattr__()` - добавлено предупреждение
- Добавлены новые методы диагностики (`get_debug_info()`, `print_debug_info()`)

**Старый код продолжает работать**:
```python
# Magic-доступ (работает как раньше)
adapter = manager.command_adapter

# Явный доступ (рекомендуется, но не обязателен)
adapter = manager.get_adapter("command")
```

### 3. Новые методы диагностики

**Добавлены новые методы** (не влияют на существующий код):
- `get_available_methods()` - только в ObservableMixin
- `print_available_methods()` - только в ObservableMixin
- `get_debug_info()` - только в BaseManager
- `print_debug_info()` - только в BaseManager

### 4. LoggingFacade

**Новый модуль** - не влияет на существующий код:
- Создан новый модуль `core/logging_facade.py`
- Старый код продолжает использовать LoggerManager напрямую
- Новый код может использовать LoggingFacade для удобства

## 🔍 Проверка обратной совместимости

### Тест 1: Старый код ObservableMixin

```python
# Старый код должен работать
class OldManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            auto_proxy=True  # Старый способ
        )
    
    def do_work(self):
        self.log_info("Работа")  # Должно работать
```

**Результат**: ✅ Работает как раньше

### Тест 2: Старый код BaseManager

```python
# Старый код должен работать
manager = BaseManager("Test")
adapter = SomeAdapter()
manager.attach_adapter(adapter, name="test")

# Magic-доступ (старый способ)
adapter = manager.test_adapter  # Должно работать
```

**Результат**: ✅ Работает как раньше

### Тест 3: Новый код с simple_mode

```python
# Новый код (опционально)
class NewManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            simple_mode=True  # Новый режим
        )
    
    def do_work(self):
        self._log_info("Работа")  # Приватный метод
```

**Результат**: ✅ Работает, но использует упрощенный режим

## 📋 Миграция (опционально)

Миграция на новые возможности **не обязательна**. Старый код продолжает работать.

### Если хотите использовать simple_mode:

1. Добавьте параметр `simple_mode=True` в `ObservableMixin.__init__()`
2. Используйте приватные методы (`_log_info` вместо `log_info`)
3. Используйте явный доступ к адаптерам (`get_adapter()` вместо magic-доступа)

### Если хотите использовать диагностику:

1. Используйте `manager.print_debug_info()` для отладки
2. Используйте `manager.get_available_methods()` для понимания доступных методов

## ⚠️ Важно

- **Все изменения опциональны** - старый код работает без изменений
- **simple_mode=False по умолчанию** - старый код работает как раньше
- **Новые методы не влияют на существующий код** - они только добавляют функциональность

