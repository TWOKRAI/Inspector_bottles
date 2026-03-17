# multiprocess_prototype\README.md
# multiprocess_prototype

Демо-приложение на базе `multiprocess_framework/refactored`.

- **5 процессов**: Camera, Processor, Renderer, Robot, GUI
- **Два изображения**: оригинал (с контурами) и маска
- **Чекбоксы**: Original, Mask, Contours — включают/выключают отображение, отправляют команды в Renderer
- **25 FPS** по умолчанию
- **Связь** через RouterManager и очереди

## Запуск

**Рекомендуемый способ** — скрипт `run.sh` (выставляет PYTHONPATH и при необходимости чистит SharedMemory):

```bash
# Из корня репозитория (Inspector_bottles)
./Inspector_prototype/multiprocess_prototype/run.sh

# Или из каталога Inspector_prototype
cd Inspector_prototype && ./multiprocess_prototype/run.sh
```

**Запуск через main.py** (удобно из IDE или когда не нужна очистка shm):

```bash
# Из любого места — указать путь к main.py
python Inspector_prototype/multiprocess_prototype/main.py

# Из каталога Inspector_prototype
cd Inspector_prototype && python multiprocess_prototype/main.py

# Из каталога multiprocess_prototype
cd Inspector_prototype/multiprocess_prototype && python main.py
```

**Через модуль с явным PYTHONPATH** (для скриптов/CI):

```bash
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
