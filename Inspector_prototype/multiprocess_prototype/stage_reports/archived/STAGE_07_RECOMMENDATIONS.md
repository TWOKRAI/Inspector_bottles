# multiprocess_prototype\stage_reports\archived\STAGE_07_RECOMMENDATIONS.md
# Stage 7: Рекомендации и итоги

## Выполнено

1. **DECISIONS.md** — добавлены ADR-024 (channel_types), ADR-025 (prototype refactoring)
2. **STATUS.md** — карточка здоровья multiprocess_prototype
3. Все этапы 0–6 завершены

---

## Рекомендации по API

### Конфиги

- Использовать `process(Config())` вместо ручного dict — гарантирует managers, memory, queues
- Новый процесс: наследовать `ProcessConfigBase`, переопределить `build()` с `_build_proc_dict()`

### Логирование

- `INSPECTOR_LOG_LEVEL=DEBUG` для отладки
- Контекст `proc_name` автоматически добавляется в ProcessLifecycle
- Для дополнительного контекста: `logger.push_context(key=value)` / `pop_context()`

### SharedMemory

- Память создаётся в процессе-владельце (Camera, Renderer)
- Конфиг: `memory: {names: {...}, coll: N}` в `Config.build()`

### Тестирование

- `test_configs_build.py` — без subprocess, быстрые проверки
- `test_pipeline.py` — 4 процесса без GUI (работает на CI)
- `test_full_integration.py` — 5 процессов с GUI (требует DISPLAY)

---

## Оценка архитектуры

| Компонент | Оценка | Комментарий |
|-----------|--------|-------------|
| Фреймворк (15 модулей) | 8/10 | Модульная структура, Dict at Boundary |
| Prototype (конфиги) | 8/10 | ProcessConfigBase устраняет дублирование |
| Prototype (процессы) | 7/10 | MessageAdapter, channel_types — корректно |
| Логирование | 8/10 | Console, context, INSPECTOR_LOG_LEVEL |
| Тесты | 7/10 | Покрытие конфигов и пайплайна |
