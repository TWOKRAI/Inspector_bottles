# memory — Статус рефакторинга

## Текущий этап: 8 / 8

## Оценки (0-10)

| Критерий | До | После | Комментарий |
|----------|-----|-------|-------------|
| Код | 6 | **8** | Разбит на подмодули: format, platform_ops, validation, types |
| Тесты | 5 | **7** | test_format, test_validation, test_platform_ops; MM skip на macOS |
| Документация | 4 | **8** | README, STATUS, docstrings |
| Кросс-платформенность | 5 | **7** | Явная стратегия Windows/Linux/macOS в platform_ops |
| Связанность | 7 | **8** | Чёткие границы между подмодулями |
| Эффективность | 7 | **7** | Без изменений |

## Чеклист рефакторинга

- [x] types.py — _MemoryMeta
- [x] format.py — calculate_buffer_size, pack_images, unpack_images
- [x] platform_ops.py — create_shm_block, open_shm_block, close_shm, cleanup_stale_shm
- [x] validation.py — validate_memory_access, validate_write_operation, clear_memory_slot
- [x] memory_manager.py — рефакторинг с делегированием
- [x] README.md, STATUS.md
- [x] test_format.py, test_validation.py, test_platform_ops.py
- [x] Обновление test_memory_manager.py

## Известные ограничения

- **macOS M1/M2**: SharedMemory может работать нестабильно (cpython#117262); тесты MM помечены skip
- **reinitialize_handles**: требует чтобы owner ещё не сделал unlink при открытии consumer

## История изменений

| Дата | Что сделано |
|------|-------------|
| 2026-03-15 | Рефакторинг: разбиение на format, platform_ops, validation, types |
| 2026-03-15 | pack_images_fast/legacy, unpack(copy=), docs/FORMATS.md — два режима скорости |
| 2026-03-15 | get_stats через ManagerStatsMixin (mixins/) — эталон для queues, events |
| 2026-03-15 | Структура core/, format/, platform/, validation/ (domain-style) |
