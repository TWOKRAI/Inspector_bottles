Создай новый ProcessModule для фреймворка Inspector_bottles.

## Чек-лист создания ProcessModule

Пройди каждый пункт последовательно и отметь выполненное.

### 1. Структура файлов
Создай папку в `Inspector_prototype/multiprocess_framework/modules/<module_name>/`:
- [ ] `__init__.py`
- [ ] `<module_name>_module.py` — основной класс, наследник `ProcessModule`
- [ ] `interfaces.py` — публичные интерфейсы и типы
- [ ] `README.md` — назначение, зависимости, примеры
- [ ] `STATUS.md` — текущий статус (DRAFT / STABLE / DEPRECATED)
- [ ] `tests/` — папка с тестами
- [ ] `tests/__init__.py`
- [ ] `tests/test_<module_name>.py`

### 2. Класс модуля
```python
from multiprocess_framework.core.process_module import ProcessModule

class <ModuleName>Module(ProcessModule):
    def setup(self) -> None:
        # Инициализация: подписка на каналы, инициализация ресурсов
        pass

    def handle_message(self, msg: dict) -> None:
        # Обработка входящих сообщений (только dict!)
        pass

    def teardown(self) -> None:
        # Освобождение ресурсов
        pass
```

### 3. Правила (обязательно)
- [ ] Между процессами — только `dict` (никаких Pydantic-объектов на границе)
- [ ] Pydantic-модели — только внутри модуля
- [ ] Зависимости через `interfaces.py`, не прямые импорты
- [ ] Логи через `ObservableMixin` или `LoggerManager`

### 4. Регистрация в SystemLauncher
В `multiprocess_prototype/main.py` (или соответствующем launcher):
```python
launcher.register_module("<process_name>", <ModuleName>Module)
```

### 5. Сообщения (схема)
Определи в `interfaces.py`:
```python
# Входящие сообщения
INCOMING_CHANNELS = ["channel_name"]

# Исходящие сообщения — структура dict
def make_output_message(data: ...) -> dict:
    return {"channel": "output_channel", "payload": ..., "targets": ["target_process"]}
```

### 6. Тесты
- [ ] Тест `setup` / `teardown`
- [ ] Тест обработки корректного сообщения
- [ ] Тест обработки невалидного сообщения
- [ ] Запуск: `cd Inspector_prototype && python -m pytest multiprocess_framework/modules/<module_name>/tests/ -v`

### 7. Документация
- [ ] `README.md` содержит: назначение, входящие/исходящие сообщения, зависимости
- [ ] `STATUS.md` содержит: статус, версию, известные ограничения
- [ ] Если решение нетривиальное — запись в `multiprocess_framework/DECISIONS.md`
