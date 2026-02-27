# Объединение ObservableMixin и ManagerExtensionMixin

## Проблема

В старом коде было два миксина с дублированием функциональности:
- **ObservableMixin** - приватные методы (`_log_info`, `_record_metric`)
- **ManagerExtensionMixin** - автоматические прокси-методы (`log_info`, `record_metric`)

Оба миксина имели:
- Почти идентичную логику кэширования методов
- Одинаковые декораторы (`logged`, `timed`, `monitored`)
- Одинаковую логику управления состоянием
- Разницу только в именах методов и автоматическом создании прокси

## Решение

Создан **один универсальный ObservableMixin**, который объединяет лучшее из обоих:

### Ключевые особенности

1. **Гибкость использования:**
   - Приватные методы (`_log_info`) - всегда доступны
   - Публичные прокси-методы (`log_info`) - создаются автоматически при `auto_proxy=True`

2. **Производительность:**
   - Кэширование методов для оптимизации вызовов
   - Минимум накладных расходов

3. **Обратная совместимость:**
   - Поддерживает оба стиля использования
   - Старый код продолжит работать

## Использование

### Вариант 1: С приватными методами (как старый ObservableMixin)

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            config={'logger': True},
            auto_proxy=False  # Без автоматических прокси
        )
    
    def process(self):
        self._log_info("Обработка данных")  # Приватный метод
        self._record_metric("operations.count")
```

### Вариант 2: С автоматическими прокси-методами (как старый ManagerExtensionMixin)

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger,
                'stats': stats
            },
            config={'logger': True, 'stats': True},
            auto_proxy=True  # Автоматически создаст log_info(), record_metric() и т.д.
        )
    
    def process(self):
        self.log_info("Обработка данных")  # Публичный метод (автоматически создан)
        self.record_metric("operations.count")  # Публичный метод (автоматически создан)
        
        # Приватные методы тоже работают
        self._log_info("Тоже работает")
        self._record_metric("operations.count")
```

## Преимущества

1. **Нет дублирования** - один миксин вместо двух
2. **Гибкость** - можно использовать оба стиля
3. **Производительность** - кэширование методов
4. **Удобство** - автоматические прокси-методы при необходимости
5. **Обратная совместимость** - старый код продолжит работать

## Миграция

### Из ObservableMixin

```python
# Старый код
ObservableMixin.__init__(self, managers={...}, config={...})

# Новый код (работает без изменений)
ObservableMixin.__init__(self, managers={...}, config={...}, auto_proxy=False)
```

### Из ManagerExtensionMixin

```python
# Старый код
ManagerExtensionMixin.__init__(self, extensions={...}, config={...})

# Новый код
ObservableMixin.__init__(self, managers={...}, config={...}, auto_proxy=True)
# Заменить 'extensions' на 'managers'
```

## Автоматически создаваемые прокси-методы

При `auto_proxy=True` создаются следующие методы:

**Логирование** (если зарегистрирован `logger`):
- `log_debug(msg, **kwargs)`
- `log_info(msg, **kwargs)`
- `log_warning(msg, **kwargs)`
- `log_error(msg, **kwargs)`
- `log_critical(msg, **kwargs)`

**Статистика** (если зарегистрирован `stats` или `statistics`):
- `record_metric(name, value=1, tags=None)`
- `increment(name, tags=None)`
- `record_timing(name, duration, tags=None)`
- `gauge(name, value, tags=None)`

**Ошибки** (если зарегистрирован `error` или `errors`):
- `track_error(error, context=None)`
- `record_error(error, context=None)`

## Всегда доступные приватные методы

Независимо от `auto_proxy`, всегда доступны:
- `_log_debug(message, **kwargs)`
- `_log_info(message, **kwargs)`
- `_log_warning(message, **kwargs)`
- `_log_error(message, **kwargs)`
- `_log_critical(message, **kwargs)`
- `_track_error(error, context=None)`
- `_record_metric(metric_name, value=1, tags=None)`
- `_record_timing(metric_name, duration, tags=None)`

