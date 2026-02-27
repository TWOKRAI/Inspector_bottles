# Быстрый Старт - Шаблонное Приложение

## 🚀 За 5 Минут

### 1. Базовое Использование

```python
from multiprocess_framework.refactored.tests.integration import (
    TemplateApplication,
    AppConfigManager
)

# Создаем конфигурацию
config = AppConfigManager().load_config()

# Создаем и запускаем приложение
app = TemplateApplication(config=config)
app.initialize()
app.start()

# Отправляем тестовое сообщение
app.send_test_message()

# Получаем статистику
stats = app.get_stats()
print(stats)

# Останавливаем
app.stop()
```

### 2. Запуск Тестов

```bash
# Все интеграционные тесты
pytest src/multiprocess_framework/refactored/tests/integration/ -v

# Только шаблонное приложение
pytest src/multiprocess_framework/refactored/tests/integration/test_template_application*.py -v
```

### 3. Создание Собственного Процесса

```python
# 1. Создайте файл your_process.py в template_app/processes/
from multiprocess_framework.refactored.modules.process_module import ProcessModule

class YourProcess(ProcessModule):
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        # Ваша логика здесь
        return True

# 2. Зарегистрируйте в template_application.py
# В методе _create_processes() добавьте:
if self.config.your_process_enabled:
    class_path = 'multiprocess_framework.refactored.tests.integration.template_app.processes.your_process.YourProcess'
    self.process_manager.create_process('your_process', class_path, config={})
```

## 📚 Документация

- [Полное руководство](./TEMPLATE_FRAMEWORK_GUIDE.md)
- [Детальное руководство](./TEMPLATE_USAGE.md)
- [README](./README.md)

