# ProcessManager Builders

## Статус: В разработке

Этот модуль предназначен для реализации паттерна Builder для создания ProcessManager.

## Планируемая функциональность

```python
from src.Modules.Process_manager_module.builders import ProcessManagerBuilder

# Создание ProcessManager через Builder
pm = (ProcessManagerBuilder()
    .with_base_config("config/processes.yaml")
    .with_process_config("vision_process", "config/vision.yaml")
    .with_queue("vision_process", "image", maxsize=10)
    .with_console("vision_process", enabled=True, title="Vision Processor")
    .with_worker("vision_process", "camera_capture", "VisionModule.CameraWorker")
    .build())

# Запуск процессов
pm.start_processes()
```

## Преимущества Builder паттерна

- **Читаемость**: Последовательность действий очевидна
- **Гибкость**: Можно комбинировать разные способы конфигурации
- **Валидация**: Проверка на этапе сборки
- **Переиспользование**: Можно создавать шаблоны

## Когда использовать

- Сложная конфигурация с множеством процессов
- Динамическое создание конфигурации
- Когда нужна валидация перед созданием

## Когда НЕ использовать

- Простая конфигурация из одного YAML файла
- Когда достаточно методов `register_process()`, `register_queue()` и т.д.

