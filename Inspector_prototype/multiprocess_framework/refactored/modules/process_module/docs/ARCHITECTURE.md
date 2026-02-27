# Архитектура рефакторенного Process Module

## Концепция

ProcessModule теперь наследуется от `BaseManager` и использует `ObservableMixin` для логирования и мониторинга. Это обеспечивает единообразие со всеми менеджерами системы.

## Структура

```
ProcessModule (BaseManager + ObservableMixin)
    ├── initialize() - инициализация процесса (из BaseManager)
    ├── shutdown() - завершение работы (из BaseManager)
    ├── run() - основной цикл процесса
    │
    ├── Компоненты процесса:
    │   ├── ProcessConfigHandler - работа с конфигурацией
    │   ├── ProcessManagers - управление менеджерами (через ObservableMixin)
    │   └── ProcessCommunication - межпроцессная коммуникация
    │
    └── Функциональность ProcessCore интегрирована в:
        ├── initialize() - инициализация очередей, конфигурации
        └── shutdown() - остановка потоков, очистка ресурсов
```

## Изменения по сравнению со старым ProcessModule

### Было:
- ProcessModule наследуется от ProcessCore
- Собственная реализация логирования
- ManagersComponents создает менеджеры вручную

### Стало:
- ProcessModule наследуется от BaseManager + ObservableMixin
- Логирование через ObservableMixin (_log_info, log_info)
- Менеджеры регистрируются через ObservableMixin.register_manager()

## Преимущества

1. ✅ Единообразие - все менеджеры наследуются от BaseManager
2. ✅ ObservableMixin - автоматическое логирование и мониторинг
3. ✅ Стандартный жизненный цикл - initialize/shutdown
4. ✅ Упрощение кода - меньше дублирования
5. ✅ Лучшая тестируемость - стандартные интерфейсы

## Миграция

Старый код:
```python
class MyProcess(ProcessModule):
    def run(self):
        self.log("INFO", "Message", "module")
```

Новый код:
```python
class MyProcess(ProcessModule):
    def run(self):
        self.log_info("Message")  # Через ObservableMixin
        # или
        self._log_info("Message")  # Приватный метод
```

