# План рефакторинга RouterModule

## Цель

Отрефакторить RouterModule под новую архитектуру BaseManager + ObservableMixin для:
- Единообразия со всеми менеджерами системы
- Автоматического логирования через ObservableMixin
- Стандартного жизненного цикла (initialize/shutdown)
- Улучшенной расширяемости и тестируемости

## Текущая структура

```
Router_module/
├── router_manager.py      # Основной класс RouterManager
├── channel.py            # MessageChannel и QueueChannel
├── router_adapter.py     # RouterAdapter
└── README.md             # Документация
```

## Новая структура

```
router_module/
├── __init__.py
├── README.md
├── core/
│   ├── __init__.py
│   └── router_manager.py      # RouterManager (BaseManager + ObservableMixin)
├── channels/
│   ├── __init__.py
│   ├── base_channel.py         # MessageChannel (абстрактный)
│   └── queue_channel.py        # QueueChannel
├── adapters/
│   ├── __init__.py
│   └── router_adapter.py       # RouterAdapter (обновленный)
├── dispatchers/
│   ├── __init__.py
│   └── channel_dispatcher.py   # Обертка для Dispatcher (опционально)
├── docs/
│   ├── README.md
│   ├── ARCHITECTURE.md
│   └── DISPATCH_INTEGRATION.md
└── tests/
    ├── __init__.py
    ├── test_router_manager.py
    └── test_channels.py
```

## Изменения

### 1. RouterManager → BaseManager + ObservableMixin

**Было:**
```python
class RouterManager:
    def __init__(self, router_id, logger=None, ...):
        self.router_id = router_id
        self.logger = logger
        # ...
```

**Станет:**
```python
class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, manager_name, process=None, ...):
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, managers={}, config={}, auto_proxy=True)
        # ...
```

### 2. Логирование через ObservableMixin

**Было:**
```python
def _log_info(self, msg):
    if self.logger:
        self.logger.info(msg)
```

**Станет:**
```python
# Автоматически через ObservableMixin
self._log_info(msg)  # или self.log_info(msg) через proxy
```

### 3. Жизненный цикл через BaseManager

**Было:**
```python
def cleanup(self):
    self.stop_listening()
    # очистка
```

**Станет:**
```python
def initialize(self) -> bool:
    # инициализация каналов, диспетчеров
    return True

def shutdown(self) -> bool:
    self.stop_listening()
    # очистка
    return True
```

### 4. Статистика через ObservableMixin

**Было:**
```python
def get_stats(self):
    return {
        'sent': self._stats['sent'],
        # ...
    }
```

**Станет:**
```python
def get_stats(self):
    stats = super().get_stats()  # от BaseManager
    stats.update({
        'router': {
            'sent': self._stats['sent'],
            # ...
        }
    })
    return stats
```

## Сохранение функциональности

### ✅ Сохраняется:
- Dispatcher интеграция (channel_dispatcher, message_dispatcher)
- Реестр каналов (_channels)
- Асинхронное прослушивание
- Статистика
- Все публичные методы (send, receive, register_channel, etc.)

### 🔄 Улучшается:
- Логирование через ObservableMixin
- Жизненный цикл через BaseManager
- Единообразие со всеми менеджерами
- Расширяемость через адаптеры

## План реализации

1. **Создать структуру модуля**
   - Создать папки core/, channels/, adapters/, docs/, tests/
   - Перенести код в новую структуру

2. **Рефакторинг RouterManager**
   - Наследование от BaseManager + ObservableMixin
   - Интеграция жизненного цикла
   - Замена логирования на ObservableMixin

3. **Обновление RouterAdapter**
   - Использование нового BaseAdapter
   - Интеграция с ObservableMixin

4. **Тесты**
   - Юнит-тесты для RouterManager
   - Тесты каналов
   - Интеграционные тесты

5. **Документация**
   - Архитектура модуля
   - Интеграция с Dispatch
   - Примеры использования

## Совместимость

- Старый API сохраняется (обратная совместимость)
- Новые возможности через BaseManager/ObservableMixin
- Постепенная миграция существующего кода

