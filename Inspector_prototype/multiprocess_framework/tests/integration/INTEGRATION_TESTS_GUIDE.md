# Руководство по Интеграционным Тестам

## 📋 Обзор

Интеграционные тесты демонстрируют использование всех модулей Multiprocess Framework в реальных сценариях. Они структурированы по папкам и модулям для использования как шаблон и руководство.

## 🏗️ Структура Тестов

```
integration/
├── test_template_application.py      # Базовые тесты шаблонного приложения
├── test_comprehensive_integration.py # Комплексные тесты всех модулей
└── template_app/                     # Шаблонное приложение
    ├── config/                       # Конфигурация
    ├── processes/                    # Процессы
    └── template_application.py     # Главное приложение
```

## 🚀 Запуск Тестов

### Все интеграционные тесты

```bash
pytest src/multiprocess_framework/tests/integration/ -v
```

### Конкретный класс тестов

```bash
pytest src/multiprocess_framework/tests/integration/test_comprehensive_integration.py::TestApplicationLifecycle -v
```

### Конкретный тест

```bash
pytest src/multiprocess_framework/tests/integration/test_comprehensive_integration.py::TestApplicationLifecycle::test_app_initialization -v
```

### С покрытием кода

```bash
pytest src/multiprocess_framework/tests/integration/ --cov=src/multiprocess_framework/tests/integration/template_app --cov-report=html
```

## 📚 Категории Тестов

### 1. TestApplicationLifecycle

Тесты жизненного цикла приложения:
- `test_app_initialization` - Инициализация со всеми модулями
- `test_app_start_stop` - Запуск и остановка
- `test_app_shutdown_cleanup` - Корректная очистка ресурсов

### 2. TestFrameworkModules

Тесты использования всех модулей фреймворка:
- `test_all_modules_initialized` - Проверка инициализации всех модулей
- `test_worker_manager_usage` - Использование WorkerManager
- `test_router_manager_usage` - Использование RouterManager
- `test_command_manager_usage` - Использование CommandManager
- `test_config_manager_usage` - Использование ConfigManager
- `test_data_schema_manager_usage` - Использование DataSchemaManager

### 3. TestInterProcessCommunication

Тесты межпроцессного взаимодействия:
- `test_message_sending` - Отправка сообщений
- `test_message_receiving` - Получение сообщений
- `test_vision_to_ai_communication` - Vision -> AI
- `test_ai_to_db_communication` - AI -> DB
- `test_broadcast_messages` - Широковещательные сообщения

### 4. TestCommandHandling

Тесты обработки команд:
- `test_command_execution` - Выполнение команд
- `test_command_with_data` - Команды с данными

### 5. TestConfigurationAndData

Тесты работы с конфигурациями и данными:
- `test_config_loading` - Загрузка конфигурации
- `test_config_customization` - Кастомизация конфигурации
- `test_data_schema_validation` - Валидация данных по схемам

### 6. TestStatisticsAndMonitoring

Тесты статистики и мониторинга:
- `test_app_stats` - Статистика приложения
- `test_worker_stats` - Статистика воркеров

### 7. TestExtensibility

Тесты расширяемости:
- `test_custom_process_creation` - Создание кастомного процесса
- `test_module_registration` - Регистрация кастомных модулей

## 🎯 Использование как Шаблон

### Создание нового интеграционного теста

1. **Создайте файл теста** в папке `integration/`:

```python
"""
Тесты для вашего функционала.
"""

import pytest
from multiprocess_framework.tests.integration.template_app import (
    TemplateApplication,
    AppConfig
)

class TestMyFeature:
    """Тесты для вашего функционала."""
    
    def test_my_feature(self):
        """Тест вашего функционала."""
        config = AppConfig(
            vision_process_enabled=True,
            ai_process_enabled=False,
            db_process_enabled=False,
            ui_process_enabled=False
        )
        
        app = TemplateApplication(config=config)
        app.initialize()
        
        try:
            # Ваши тесты здесь
            assert app.vision_process is not None
        finally:
            app.stop()
```

2. **Запустите тест**:

```bash
pytest src/multiprocess_framework/tests/integration/test_my_feature.py -v
```

### Использование процессов в тестах

```python
def test_process_usage():
    """Пример использования процесса в тесте."""
    config = AppConfig(vision_process_enabled=True)
    app = TemplateApplication(config=config)
    app.initialize()
    app.start()
    
    try:
        # Используем процесс
        vision = app.vision_process
        
        # Отправляем сообщение
        app.send_test_message()
        
        # Выполняем команду
        result = vision.command_manager.handle_command('start_processing', {})
        assert result['status'] == 'success'
        
        # Получаем статистику
        stats = vision.worker_manager.get_stats()
        assert stats is not None
        
    finally:
        app.stop()
```

## 🔧 Расширение Тестов

### Добавление теста для нового процесса

1. Создайте процесс в `template_app/processes/`
2. Добавьте тесты в соответствующий класс
3. Используйте паттерн из существующих тестов

### Добавление теста для нового модуля

1. Используйте `register_manager()` для регистрации модуля
2. Создайте тесты проверяющие функциональность модуля
3. Используйте ObservableMixin прокси-методы для доступа

## 📖 Примеры Использования

### Пример 1: Тест инициализации

```python
def test_initialization():
    """Тест инициализации приложения."""
    config = AppConfig()
    app = TemplateApplication(config=config)
    
    assert app.initialize() is True
    assert app.shared_resources is not None
    assert app.config_manager is not None
    
    app.stop()
```

### Пример 2: Тест межпроцессного взаимодействия

```python
def test_inter_process_communication():
    """Тест взаимодействия между процессами."""
    config = AppConfig(
        vision_process_enabled=True,
        ai_process_enabled=True
    )
    
    app = TemplateApplication(config=config)
    app.initialize()
    app.start()
    
    try:
        # Отправляем сообщение
        app.send_test_message()
        
        # Ждем обработки
        time.sleep(2)
        
        # Проверяем результаты
        # ...
        
    finally:
        app.stop()
```

### Пример 3: Тест работы с конфигурацией

```python
def test_configuration():
    """Тест работы с конфигурацией."""
    config = AppConfig()
    app = TemplateApplication(config=config)
    app.initialize()
    
    try:
        # Получаем конфигурацию
        app_config = app.config_manager.get_config('app')
        assert app_config is not None
        
        # Изменяем конфигурацию
        app_config.set('vision_process_enabled', False)
        
        # Проверяем изменения
        updated = app.config_manager.get_config('app')
        assert updated.get('vision_process_enabled') is False
        
    finally:
        app.stop()
```

## ⚠️ Важные Замечания

1. **Всегда используйте try/finally**:
   ```python
   try:
       # Ваши тесты
   finally:
       app.stop()  # Всегда очищайте ресурсы
   ```

2. **Используйте time.sleep()** для синхронизации:
   ```python
   app.start()
   time.sleep(0.5)  # Даем время процессам запуститься
   # Ваши тесты
   ```

3. **Проверяйте инициализацию**:
   ```python
   assert app.initialize() is True
   assert process.is_initialized is True
   ```

4. **Используйте моки** для внешних зависимостей:
   ```python
   from unittest.mock import Mock
   mock_manager = Mock()
   process.register_manager('mock', mock_manager)
   ```

## 📚 Дополнительные Ресурсы

- [Руководство по использованию шаблона](TEMPLATE_USAGE.md)
- [README интеграционных тестов](README.md)
- [Архитектура фреймворка](../../docs/ARCHITECTURE_REFERENCE.md)
- [Обзор фреймворка](../../docs/FRAMEWORK_OVERVIEW.md)

## 🎓 Лучшие Практики

1. **Один тест - одна проверка**: Каждый тест должен проверять одну вещь
2. **Используйте фикстуры**: Для переиспользования кода
3. **Параметризуйте тесты**: Для проверки разных конфигураций
4. **Документируйте тесты**: Описывайте что проверяет каждый тест
5. **Изолируйте тесты**: Каждый тест должен быть независимым

## 🔍 Отладка Тестов

### Запуск с подробным выводом

```bash
pytest src/multiprocess_framework/tests/integration/ -v -s
```

### Запуск с остановкой на первой ошибке

```bash
pytest src/multiprocess_framework/tests/integration/ -x
```

### Запуск конкретного теста с отладкой

```bash
pytest src/multiprocess_framework/tests/integration/test_comprehensive_integration.py::TestApplicationLifecycle::test_app_initialization -v -s --pdb
```

