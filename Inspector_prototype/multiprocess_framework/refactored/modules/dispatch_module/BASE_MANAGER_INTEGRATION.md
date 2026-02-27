# Интеграция Dispatcher с BaseManager

## Изменения

Dispatcher теперь наследуется от `BaseManager` и `ObservableMixin` для единообразия со всеми менеджерами системы.

## Новая архитектура

```python
class Dispatcher(BaseManager, ObservableMixin):
    """
    Менеджер диспетчеризации сообщений.
    
    Наследуется от BaseManager для:
    - Единообразия со всеми менеджерами системы
    - Стандартного жизненного цикла (initialize/shutdown)
    - Поддержки адаптеров и событий
    
    Использует ObservableMixin для:
    - Автоматического логирования
    - Сбора статистики
    - Обработки ошибок
    """
```

## Изменения в API

### Инициализация

**Было:**
```python
dispatcher = Dispatcher("my_dispatcher")
```

**Стало:**
```python
dispatcher = Dispatcher("my_dispatcher", process=process)  # process опционально
dispatcher.initialize()  # Явная инициализация менеджера
```

### Завершение работы

**Было:**
```python
# Нет явного завершения
```

**Стало:**
```python
dispatcher.shutdown()  # Явное завершение работы менеджера
```

## Обратная совместимость

- ✅ Старый API продолжает работать
- ✅ `name` параметр переименован в `manager_name` (но `name` все еще работает через атрибут)
- ✅ Все методы диспетчеризации работают как раньше
- ✅ `process` параметр опциональный

## Преимущества

1. **Единообразие** - все менеджеры наследуются от BaseManager
2. **Жизненный цикл** - стандартные методы initialize/shutdown
3. **Адаптеры** - поддержка адаптеров через BaseManager
4. **События** - поддержка событий через BaseManager
5. **Статистика** - автоматический сбор статистики через BaseManager.get_stats()

## Пример использования

```python
from multiprocess_framework.refactored.modules.dispatch_module import Dispatcher

# Создание менеджера диспетчеризации
dispatcher = Dispatcher(
    manager_name="my_dispatcher",
    process=current_process,  # Опционально
    managers={'logger': logger_manager}
)

# Инициализация
dispatcher.initialize()

# Использование
dispatcher.register_handler("process", handler)
result = dispatcher.dispatch({"command": "process", "data": {}})

# Получение статистики
stats = dispatcher.get_stats()

# Завершение работы
dispatcher.shutdown()
```

## Миграция

Для существующего кода:

1. Добавьте вызов `initialize()` после создания Dispatcher
2. Добавьте вызов `shutdown()` перед завершением работы
3. Опционально: используйте `manager_name` вместо `name` при создании

```python
# Старый код
dispatcher = Dispatcher("my_dispatcher")
dispatcher.register_handler("process", handler)

# Новый код (минимальные изменения)
dispatcher = Dispatcher("my_dispatcher")
dispatcher.initialize()  # Добавить
dispatcher.register_handler("process", handler)
# ... работа ...
dispatcher.shutdown()  # Добавить
```

## Внутренняя архитектура

Dispatcher использует `BaseDispatcher` как внутренний компонент для базовой логики диспетчеризации:

```python
class Dispatcher(BaseManager, ObservableMixin):
    def __init__(self, manager_name, ...):
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, managers=managers, config=config)
        
        # Внутренний компонент для базовой логики
        self._base_dispatcher = BaseDispatcher(manager_name, default_strategy)
```

Это позволяет:
- Использовать BaseDispatcher отдельно для простых случаев
- Dispatcher получает все преимущества BaseManager
- Сохраняется обратная совместимость

