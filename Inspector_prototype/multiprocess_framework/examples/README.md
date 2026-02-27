# Примеры использования multiprocess_framework

Примеры приложений, демонстрирующие использование фреймворка.

## Примеры

### chat_app_declarative.py

Демонстрирует декларативный подход с декораторами `@process` и `@worker`.

**Особенности:**
- Использование декораторов для определения процессов
- Создание процессов через ProcessConfig
- Межпроцессная коммуникация через RouterManager
- PySide6 GUI в процессе

**Запуск:**
```bash
python src/multiprocess_framework/examples/chat_app_declarative.py
```

### multiprocess_chat_app.py

Базовый пример многопроцессного чата.

**Особенности:**
- Создание процессов программно
- Использование ProcessManager
- Простая коммуникация между процессами

**Запуск:**
```bash
python src/multiprocess_framework/examples/multiprocess_chat_app.py
```

### pyqt_example.py

Пример использования PyQt/PySide в процессах.

**Особенности:**
- GUI в отдельном процессе
- Интеграция с фреймворком
- Использование WorkerManager для потоков

**Запуск:**
```bash
python src/multiprocess_framework/examples/pyqt_example.py
```

## Использование в своих проектах

Эти примеры можно использовать как основу для своих приложений.

Скопируйте нужный пример и адаптируйте под свои нужды.


