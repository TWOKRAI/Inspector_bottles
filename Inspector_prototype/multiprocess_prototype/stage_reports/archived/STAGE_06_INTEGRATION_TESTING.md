# Stage 6: Интеграционное тестирование

## Цель

Проверить полный пайплайн, конфиги и graceful shutdown через тесты.

## Изменения

### 1. Тест конфигов (без subprocess)

**`tests/test_configs_build.py`** — проверка `process(Config())`:

- `test_camera_config_build` — memory с camera_frame, managers
- `test_renderer_config_build` — memory с rendered_frame
- `test_processor_config_build` — без memory
- `test_robot_config_build` — priority low, queues 50/20
- `test_gui_config_build` — стандартные queues

### 2. Обновление существующих тестов

**`tests/test_pipeline.py`** — переход на `process(Config())`:

- CameraConfig, ProcessorConfig, RendererConfig, RobotConfig
- Полный config с managers и memory
- RobotConfig с `log_file` и `reject_delay=0.0` для проверки

**`tests/test_camera_process.py`** — переход на `process(CameraConfig())`:

- Используется полный config вместо ручного dict

### 3. Полный интеграционный тест

**`tests/test_full_integration.py`** — без изменений:

- 5 процессов (camera, processor, renderer, robot, gui)
- Требует DISPLAY (пропуск на headless CI)
- Проверка graceful shutdown

## Запуск тестов

```bash
# Из корня Inspector_bottles
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m pytest Inspector_prototype/multiprocess_prototype/tests/ -v

# Только тесты без GUI (без DISPLAY)
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m pytest Inspector_prototype/multiprocess_prototype/tests/test_configs_build.py Inspector_prototype/multiprocess_prototype/tests/test_pipeline.py Inspector_prototype/multiprocess_prototype/tests/test_camera_process.py -v
```

## Результат

- Конфиги проверяются без запуска процессов
- Пайплайн (4 процесса без GUI) тестируется через `process()` конфиги
- Полный тест с GUI выполняется при наличии DISPLAY
