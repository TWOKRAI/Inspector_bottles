# multiprocess_prototype

Демо-приложение на базе `multiprocess_framework/refactored`.

- **5 процессов**: Camera, Processor, Renderer, Robot, GUI
- **Два изображения**: оригинал (с контурами) и маска
- **Чекбоксы**: Original, Mask, Contours — включают/выключают отображение, отправляют команды в Renderer
- **25 FPS** по умолчанию
- **Связь** через RouterManager и очереди

## Запуск

```bash
# Из Inspector_bottles
./Inspector_prototype/multiprocess_prototype/run.sh

# Или с PYTHONPATH
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
```

## Тесты

```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" pytest Inspector_prototype/multiprocess_prototype/tests/ -v
```

- `test_processor_mask_contours.py` — Processor возвращает mask и contours
- `test_renderer_commands.py` — Renderer обрабатывает команды отображения
- `test_gui_checkboxes.py` — чекбоксы вызывают gui_set_* (требует DISPLAY)
- `test_full_integration.py` — полный запуск 5 процессов (требует DISPLAY)

## Документация

- [docs/INSTRUCTION.md](docs/INSTRUCTION.md) — пошаговая инструкция
- [docs/PROBLEMS_AND_FIXES.md](docs/PROBLEMS_AND_FIXES.md) — проблемы и исправления
- [docs/ARCHITECTURE_RECOMMENDATIONS.md](docs/ARCHITECTURE_RECOMMENDATIONS.md) — рекомендации по архитектуре
