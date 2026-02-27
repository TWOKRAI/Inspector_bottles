# Тесты для Message_module

## 📋 Обзор

Этот каталог содержит тесты для модуля `Message_module`, который предоставляет универсальную систему сообщений для межпроцессного взаимодействия.

## 📊 Статистика тестов

- **Всего тестов:** 69
- **Покрытие кода:** 91%
- **Статус:** ✅ Все тесты проходят

### Покрытие по модулям

- `message.py`: 96% покрытие
- `message_types.py`: 100% покрытие
- `__init__.py`: 100% покрытие
- `message_adapter.py`: 0% покрытие (заглушка, не используется)

## 🚀 Запуск тестов

### Запуск всех тестов модуля

```bash
# Из корня проекта
python -m pytest tests/Test_Message_module/ -v

# С активацией виртуального окружения
.\venv\Scripts\Activate.ps1
python -m pytest tests/Test_Message_module/ -v
```

### Запуск конкретного файла тестов

```bash
# Тесты для message.py
python -m pytest tests/Test_Message_module/test_message.py -v

# Тесты для message_types.py
python -m pytest tests/Test_Message_module/test_message_type.py -v
```

### Запуск конкретного теста

```bash
python -m pytest tests/Test_Message_module/test_message.py::TestMessageCreation::test_create_basic_message -v
```

### Запуск с покрытием кода

```bash
python -m pytest tests/Test_Message_module/ --cov=src/Modules/Message_module --cov-report=term-missing
```

### Запуск с HTML отчетом покрытия

```bash
python -m pytest tests/Test_Message_module/ --cov=src/Modules/Message_module --cov-report=html
# Откройте htmlcov/index.html в браузере
```

## 📁 Структура тестов

```
Test_Message_module/
├── conftest.py              # Общие фикстуры для всех тестов
├── test_message.py          # Тесты для message.py (57 тестов)
├── test_message_type.py    # Тесты для message_types.py (12 тестов)
└── README.md                # Этот файл
```

## 🧪 Категории тестов

### test_message.py

#### TestMessageCreation (4 теста)
- Создание базовых сообщений
- Создание сообщений разных типов
- Применение дефолтных значений для типов

#### TestFluentAPI (17 тестов)
- Управление приоритетом, получателями, роутерами
- Установка команд, логов, системных действий
- Управление метаданными
- Edge cases (дубликаты, отсутствие аргументов)

#### TestMessageValidation (5 тестов)
- Валидация валидных сообщений
- Проверка обязательных полей
- Обработка невалидных сообщений

#### TestMessageConversion (8 тестов)
- Конвертация в dict, JSON, YAML, text
- Исключение и включение полей
- Обработка отсутствия PyYAML

#### TestMessageParsing (7 тестов)
- Парсинг из dict, JSON, YAML
- Автоматическое определение формата
- Обработка невалидных форматов

#### TestMessageHelpers (8 тестов)
- Получение enum значений
- Клонирование сообщений
- Строковые представления
- Обработка невалидных значений

#### TestConvenienceFunctions (1 тест)
- Вспомогательные функции

#### TestRealWorldScenarios (4 теста)
- Реальные сценарии использования
- Command workflow
- Log workflow
- Request-Response workflow
- Event publishing

### test_message_type.py

#### TestMessageTypes (3 теста)
- Проверка всех enum значений
- MessageType, Priority, LogLevel

#### TestMessageSchema (3 теста)
- Создание схемы сообщения
- Опциональные поля
- Дефолтные значения

#### TestMessageTypeDefaults (5 тестов)
- Конфигурация для всех типов сообщений
- Проверка дефолтных значений

#### TestMessageTypeExcludeFields (1 тест)
- Исключение полей при сериализации

## 🔧 Использование фикстур

В `conftest.py` определены полезные фикстуры для тестов:

### Примеры сообщений

```python
def test_example(sample_general_message):
    """Использование фикстуры GENERAL сообщения."""
    assert sample_general_message.type == "general"
    assert sample_general_message.sender == "test_sender"

def test_command(sample_command_message):
    """Использование фикстуры COMMAND сообщения."""
    assert sample_command_message.command == "process_image"

def test_log(sample_log_message):
    """Использование фикстуры LOG сообщения."""
    assert sample_log_message.level == "error"
```

### Доступные фикстуры

- `sample_general_message` - GENERAL сообщение
- `sample_command_message` - COMMAND сообщение
- `sample_log_message` - LOG сообщение
- `sample_request_message` - REQUEST сообщение
- `sample_response_message` - RESPONSE сообщение (требует request)
- `sample_event_message` - EVENT сообщение
- `sample_broadcast_message` - BROADCAST сообщение
- `sample_system_message` - SYSTEM сообщение
- `sample_data_message` - DATA сообщение
- `message_dict` - Словарь с данными сообщения
- `message_json_string` - JSON строка с данными сообщения
- `yaml_available` - Проверка доступности PyYAML

## 📝 Написание новых тестов

### Пример нового теста

```python
def test_new_feature(sample_general_message):
    """Описание теста."""
    # Arrange
    msg = sample_general_message
    
    # Act
    result = msg.some_method()
    
    # Assert
    assert result == expected_value
```

### Рекомендации

1. **Используйте фикстуры** из `conftest.py` для создания тестовых данных
2. **Группируйте тесты** по классам для лучшей организации
3. **Используйте описательные имена** для тестов и классов
4. **Добавляйте docstrings** для описания тестов
5. **Тестируйте edge cases** - граничные случаи и ошибки

## 🐛 Отладка тестов

### Запуск с выводом print

```bash
python -m pytest tests/Test_Message_module/test_message.py -v -s
```

### Запуск с остановкой на первой ошибке

```bash
python -m pytest tests/Test_Message_module/ -x
```

### Запуск с подробным выводом ошибок

```bash
python -m pytest tests/Test_Message_module/ -v --tb=long
```

## 📚 Дополнительные ресурсы

- [Документация модуля](../../../src/Modules/Message_module/README.md)
- [Оценка модуля](../../../docs/MESSAGE_MODULE_EVALUATION.md)
- [Документация pytest](https://docs.pytest.org/)

## ✅ Чеклист для новых тестов

- [ ] Тест использует фикстуры из `conftest.py`
- [ ] Тест имеет описательное имя и docstring
- [ ] Тест проверяет один конкретный случай
- [ ] Тест использует assert с понятными сообщениями
- [ ] Тест проходит успешно
- [ ] Тест покрывает новый функционал или edge case

