# Тесты модуля data_schema

## Структура тестов

Тесты разделены на две категории:

### Unit тесты (внутри модуля)
Расположены в `data_schema/tests/` и тестируют изолированные компоненты без внешних зависимостей:

- `test_schema_registry.py` - тесты реестра схем
- `test_converters.py` - тесты конвертеров данных
- `test_validators.py` - тесты валидаторов
- `test_utils.py` - тесты утилит
- `test_factory.py` - тесты фабрики моделей
- `test_version_manager.py` - тесты менеджера версий

### Интеграционные тесты (внешняя папка)
Расположены в `tests/test_data_schema_module/` и тестируют интеграцию с другими модулями:

- Интеграция с ProcessData
- Интеграция с SharedResourcesManager
- Интеграция между компонентами модуля

## Запуск тестов

### Unit тесты
```bash
# Из корня проекта
pytest src/multiprocess_framework/modules/Shared_resources_module/data_schema/tests/

# Или из папки модуля
cd src/multiprocess_framework/modules/Shared_resources_module/data_schema
pytest tests/
```

### Интеграционные тесты
```bash
# Из корня проекта
pytest tests/test_data_schema_module/
```

### Все тесты модуля
```bash
pytest src/multiprocess_framework/modules/Shared_resources_module/data_schema/tests/ tests/test_data_schema_module/
```

## Покрытие тестами

- ✅ SchemaRegistry - регистрация, создание экземпляров, валидация
- ✅ DataConverter - конвертация между форматами
- ✅ DataValidator - валидация данных
- ✅ Utils - вспомогательные функции
- ✅ ModelFactory - создание моделей
- ✅ VersionManager - версионирование и откат

## Принципы тестирования

1. **Изоляция**: Unit тесты не зависят от внешних модулей
2. **Моки**: Используются моки для внешних зависимостей
3. **Фикстуры**: Общие настройки вынесены в фикстуры
4. **Покрытие**: Тестируются основные сценарии и edge cases

