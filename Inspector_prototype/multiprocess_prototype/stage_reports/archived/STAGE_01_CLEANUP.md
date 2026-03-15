# STAGE 01: Очистка тестового приложения

**Дата:** 2026-03-15  
**Статус:** Выполнено

## Действия

### 1. processes/__init__.py
- Удалены импорты `process_1` и `process_2` (Process1Module, Process1Config, Process2Module, Process2Config)
- Устранён риск падения при импорте из-за устаревших модулей

### 2. shm_utils.py
- **Проверка формата:** Сравнение с MemoryManager.write_images/read_images показало полное совпадение:
  - 4 байта: num_images (struct "I")
  - 12 байт: h, w, c (struct "III")
  - 1 байт: dtype char
  - данные изображения
- **Решение:** Оставлен без изменений — формат корректен, используется для прямого доступа по shm_actual_name при кросс-процессном чтении

## Тестирование

- Импорт `from multiprocess_prototype.processes import CameraProcess, ...` — без ошибок

## Известные проблемы

- Нет
