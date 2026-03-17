# multiprocess_prototype\stage_reports\archived\STAGE_08_TESTING.md
# Этап 8: Тестирование

**Дата:** 2026-03-15  
**Статус:** ✅ Выполнено

---

## Цель

Проверка работоспособности прототипа:
- Тест 4 процессов без GUI
- Изолированный тест SharedMemory
- Полный тест 5 процессов с graceful shutdown

---

## Реализовано

### 8.1 Тест без GUI (`tests/test_pipeline.py`)

- **Существующий тест** — Camera + Processor + Renderer + Robot
- Запуск без `managers` (проверка обратной совместимости)
- Проверка: Robot получает reject_item при детекциях

**Запуск:**
```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.tests.test_pipeline
```

### 8.2 Тест SharedMemory (`tests/test_shared_memory.py`)

- SharedResourcesManager → MemoryManager
- create_memory_dict + write_images + read_images
- FrameGenerator для тестового кадра
- Проверка: записанный кадр == прочитанный

**Запуск:**
```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.tests.test_shared_memory
```

### 8.3 Полный тест (`tests/test_full_integration.py`)

- 5 процессов через `process()` конфиги (с managers)
- start() → sleep(3) → stop() → wait()
- Проверка graceful shutdown
- Пропуск на headless CI (нет DISPLAY)

**Запуск:**
```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.tests.test_full_integration
```

---

## Запуск всех тестов

```bash
cd Inspector_prototype
PYTHONPATH=".:multiprocess_framework/refactored/modules" pytest multiprocess_prototype/tests/ -v
```

---

## Известные ограничения

- **test_full_integration**: требует DISPLAY (PyQt5)
- **test_shared_memory**: на macOS SharedMemory может вести себя иначе (см. shared_resources_module)
