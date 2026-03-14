# План интеграционных тестов для Base Manager Module

## Цель

Создать интеграционные тесты, которые проверяют взаимодействие компонентов модуля base_manager в реальных сценариях использования.

## Структура тестов

```
tests/
├── test_base_manager_integration.py      # Интеграция BaseManager + BaseAdapter
├── test_observable_mixin_integration.py  # Интеграция ObservableMixin с менеджерами
├── test_full_workflow.py                 # Полный workflow использования
└── test_error_scenarios.py               # Сценарии с ошибками
```

## Тестовые сценарии

### 1. BaseManager + BaseAdapter интеграция

**Файл:** `test_base_manager_integration.py`

**Сценарии:**
1. ✅ Создание менеджера → подключение адаптера → инициализация → использование
2. ✅ Подключение нескольких адаптеров → доступ к каждому
3. ✅ Magic-доступ к адаптерам через атрибуты
4. ✅ Отключение адаптера → проверка что доступ прекращен
5. ✅ События менеджера → обработка в адаптере
6. ✅ Статистика менеджера включает статистику адаптеров
7. ✅ Жизненный цикл: initialize → работа → shutdown

**Пример:**
```python
def test_manager_adapter_lifecycle():
    """Полный жизненный цикл менеджера с адаптером."""
    manager = TestManager("test_manager")
    adapter = TestAdapter(manager)
    
    # Подключение
    assert manager.attach_adapter(adapter, name="test") == True
    assert manager.has_adapter("test") == True
    
    # Инициализация
    assert manager.initialize() == True
    assert adapter.setup() == True
    
    # Использование
    assert manager.test_adapter is not None
    result = manager.test_adapter.do_something()
    assert result == "done"
    
    # Статистика
    stats = manager.get_stats()
    assert "test" in stats["adapters"]
    
    # Завершение
    assert manager.shutdown() == True
    assert adapter.is_initialized() == False
```

---

### 2. ObservableMixin интеграция с менеджерами

**Файл:** `test_observable_mixin_integration.py`

**Сценарии:**
1. ✅ Регистрация менеджера → использование приватных методов
2. ✅ Регистрация менеджера → auto_proxy=True → использование публичных методов
3. ✅ Регистрация нескольких менеджеров → использование всех
4. ✅ Включение/выключение менеджеров → проверка что методы работают/не работают
5. ✅ Контекстный менеджер → временное изменение состояния
6. ✅ Регистрация плагина → использование методов плагина
7. ✅ Динамическая регистрация менеджера → обновление прокси-методов
8. ✅ Кэширование методов → проверка производительности

**Пример:**
```python
def test_observable_mixin_full_workflow():
    """Полный workflow ObservableMixin с менеджерами."""
    logger = MockLogger()
    stats = MockStats()
    
    manager = TestManager("test", logger=logger, stats=stats, auto_proxy=True)
    
    # Приватные методы работают
    manager._log_info("Private log")
    assert len(logger.logs) == 1
    
    # Публичные методы работают
    manager.log_info("Public log")
    assert len(logger.logs) == 2
    
    # Статистика работает
    manager.record_metric("test.metric", value=5)
    assert len(stats.metrics) == 1
    
    # Включение/выключение
    manager.disable('logger')
    manager.log_info("Should not log")
    assert len(logger.logs) == 2  # Не увеличилось
    
    manager.enable('logger')
    manager.log_info("Should log")
    assert len(logger.logs) == 3  # Увеличилось
```

---

### 3. Полный workflow использования

**Файл:** `test_full_workflow.py`

**Сценарии:**
1. ✅ Создание менеджера с ObservableMixin → подключение адаптера → регистрация менеджеров → использование всех возможностей
2. ✅ Регистрация плагина → создание кастомных методов → использование
3. ✅ Декораторы → автоматическое логирование и мониторинг
4. ✅ События → генерация и обработка
5. ✅ Статистика → сбор статистики со всех компонентов
6. ✅ Конфигурация → обновление и применение

**Пример:**
```python
def test_complete_manager_workflow():
    """Полный workflow использования менеджера."""
    # Создание менеджера
    logger = MockLogger()
    stats = MockStats()
    manager = TestManager("test", logger=logger, stats=stats, auto_proxy=True)
    
    # Подключение адаптера
    adapter = TestAdapter(manager)
    manager.attach_adapter(adapter, name="test_adapter")
    
    # Регистрация плагина
    plugin = CustomPlugin()
    manager.register_plugin(plugin)
    
    # Использование всех возможностей
    @manager.monitored(manager_name='logger', level='info', metric_name='test.metric')
    def process_data():
        manager.log_info("Processing")
        manager.record_metric("operations.count")
        return "result"
    
    result = process_data()
    assert result == "result"
    assert len(logger.logs) >= 1
    assert len(stats.metrics) >= 1
    
    # События
    event_called = []
    def handler(data):
        event_called.append(data)
    
    manager.on_event("test_event", handler)
    manager.emit_event("test_event", {"data": "test"})
    assert len(event_called) == 1
    
    # Статистика
    stats_data = manager.get_stats()
    assert stats_data["manager_name"] == "test"
    assert "test_adapter" in stats_data["adapters"]
```

---

### 4. Сценарии с ошибками

**Файл:** `test_error_scenarios.py`

**Сценарии:**
1. ✅ Менеджер не найден → graceful degradation
2. ✅ Метод не найден → graceful degradation
3. ✅ Ошибка в обработчике события → не падает менеджер
4. ✅ Ошибка в адаптере → не падает менеджер
5. ✅ Ошибка в плагине → не падает менеджер
6. ✅ None значения → корректная обработка
7. ✅ Дублирование адаптеров → перезапись или ошибка
8. ✅ Невалидные имена → валидация

**Пример:**
```python
def test_error_handling():
    """Обработка ошибок в различных сценариях."""
    manager = TestManager("test")
    
    # Менеджер не найден
    result = manager._call_manager('nonexistent', 'method')
    assert result is None  # Graceful degradation
    
    # Ошибка в обработчике события
    def bad_handler(data):
        raise Exception("Error in handler")
    
    manager.on_event("test_event", bad_handler)
    # Не должно упасть
    manager.emit_event("test_event", {"data": "test"})
    
    # None адаптер
    manager.attach_adapter(None, name="none")
    assert manager.has_adapter("none") == True  # Зарегистрирован
    # Но использование должно обрабатываться корректно
```

---

## Реализация

### Структура файлов

```
src/multiprocess_framework/refactored/tests/
├── __init__.py
├── test_base_manager_integration.py
├── test_observable_mixin_integration.py
├── test_full_workflow.py
└── test_error_scenarios.py
```

### Зависимости

- `pytest` - для запуска тестов
- `pytest-cov` - для покрытия кода
- Моки из существующих тестов

### Запуск

```bash
# Все интеграционные тесты
pytest src/multiprocess_framework/refactored/tests/ -v

# Конкретный файл
pytest src/multiprocess_framework/refactored/tests/test_base_manager_integration.py -v

# С покрытием
pytest src/multiprocess_framework/refactored/tests/ --cov=multiprocess_framework.refactored.modules.base_manager
```

---

## Приоритеты

### Приоритет 1 (Критично)
1. ✅ BaseManager + BaseAdapter интеграция
2. ✅ ObservableMixin интеграция с менеджерами
3. ✅ Полный workflow использования

### Приоритет 2 (Важно)
4. ✅ Сценарии с ошибками
5. ✅ Производительность (кэширование)

### Приоритет 3 (Желательно)
6. ✅ Конкурентность (если применимо)
7. ✅ Граничные случаи

---

## Ожидаемые результаты

После реализации интеграционных тестов:
- ✅ Полное покрытие взаимодействия компонентов
- ✅ Проверка реальных сценариев использования
- ✅ Выявление проблем интеграции
- ✅ Документация использования через тесты
- ✅ Уверенность в стабильности модуля

