# multiprocess_prototype\STATUS.md
# multiprocess_prototype — Статус

## Текущий статус

✅ **Этап 8/8 завершён** — Dual Image Display

- Точка входа: `main.py`
- Процессы: Camera, Processor, Renderer, Robot, GUI
- **Два изображения**: оригинал (с контурами) и маска
- **Чекбоксы**: Original, Mask, Contours — команды в Renderer
- **25 FPS** по умолчанию
- SharedMemory: camera_frame, processor_mask, rendered_frame, mask_frame

---

## Выполненные этапы

| Этап | Описание | Отчёт |
|------|----------|-------|
| 0 | Критический баг — гонка system_threads vs worker receive() | STAGE_00_CRITICAL_FIX.md |
| 1 | Очистка — processes/__init__.py, shm_utils | STAGE_01_CLEANUP.md |
| 2 | MessageAdapter для создания сообщений | STAGE_02_MESSAGE_ADAPTER.md |
| 3 | Config-driven SharedMemory | STAGE_03_SHM_CONFIG.md |
| 4 | ProcessConfigBase — базовый класс конфигов | STAGE_04_PROCESS_CONFIG_BASE.md |
| 5 | Логирование — console, DEBUG, context | STAGE_05_LOGGING.md |
| 6 | Интеграционное тестирование | STAGE_06_INTEGRATION_TESTING.md |
| 7 | DECISIONS.md, STATUS.md | — |
| 8 | Dual Image Display — два изображения, контуры, чекбоксы, 25 FPS | docs/ARCHITECTURE_RECOMMENDATIONS.md |

---

## Запуск

```bash
# Из Inspector_bottles
./Inspector_prototype/multiprocess_prototype/run.sh

# Или с PYTHONPATH
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
```

## Переменные окружения

- `INSPECTOR_LOG_LEVEL` — уровень логирования (INFO, DEBUG, WARNING, ERROR, CRITICAL)
- `INSPECTOR_LOG_DIR` — каталог логов (по умолчанию `logs`)
- `DISPLAY` — требуется для GUI (на headless CI тесты с GUI пропускаются)

---

## Известные ограничения

- Реальная камера (cv2.VideoCapture) не реализована — используется FrameGenerator
- pydantic требуется для конфигов (data_schema_module)
