# План реализации Inspector Prototype

**Версия:** 1.0  
**Дата:** 2026-03-15  
**Цель:** Полнофункциональный прототип из 5 процессов на базе Multiprocess Framework v2.0

---

## Оглавление

1. [Обзор и архитектура](#1-обзор-и-архитектура)
2. [Структура проекта](#2-структура-проекта)
3. [Этапы реализации](#3-этапы-реализации)
4. [Схемы взаимодействия](#4-схемы-взаимодействия)
5. [Риски и упрощения](#5-риски-и-упрощения)
6. [Чеклист](#6-чеклист)

---

## 1. Обзор и архитектура

### 1.1 Пять процессов
ссылка на сам фраемворк   Inspector_prototype/multiprocess_framework

```
ProcessManagerProcess (фреймворк)
    ├── CameraProcess      — захват кадров → shared memory
    ├── ProcessorProcess   — детекция пятен → результаты
    ├── RendererProcess    — отрисовка bbox → shared memory
    ├── RobotSimulatorProcess — логирование отбраковки
    └── GuiProcess         — отображение, управление
```

### 1.2 Роли и Shared Memory

| Процесс | Shared Memory | Команды |
|---------|---------------|---------|
| **camera** | owner: `camera_frame` | `start_capture`, `stop_capture`, `set_fps`, `set_resolution` |
| **processor** | consumer: `camera_frame` | `set_threshold`, `set_min_area` |
| **renderer** | consumer: `camera_frame`, owner: `rendered_frame` | `set_output_dir` |
| **robot** | — | `reject_item` |
| **gui** | consumer: `rendered_frame` | — (отправляет команды другим) |

### 1.3 Ключевые принципы

- **Dict at Boundary** (ADR-008): все данные через Queue/Router — только `dict`
- **SharedMemory по именам** (ADR-019): кадры в shared memory, уведомления — лёгкие DATA
- **Owner/Consumer**: Camera создаёт `camera_frame`, Renderer создаёт `rendered_frame`
- **GUI без воркеров**: PyQt в главном потоке, QTimer для опроса сообщений

---

## 2. Структура проекта

```
multiprocess_prototype/
├── main.py                    # Точка входа: SystemLauncher
├── configs/                   # Схемы SchemaBase
│   ├── camera_config.py
│   ├── processor_config.py
│   ├── renderer_config.py
│   ├── robot_config.py
│   └── gui_config.py
├── processes/
│   ├── camera_process.py
│   ├── processor_process.py
│   ├── renderer_process.py
│   ├── robot_simulator_process.py
│   └── gui_process.py
├── gui/
│   └── main_window.py         # InspectorWindow
└── utils/
    └── frame_generator.py     # Имитация камеры
```

---

## 3. Этапы реализации

### Этап 0: Инфраструктура

| # | Задача | Результат |
|---|--------|------------|
| 0.1 | Создать `utils/frame_generator.py` | Класс `FrameGenerator` — генерация numpy-кадров с цветным пятном |
| 0.2 | Создать `configs/` с 5 схемами | `CameraConfig`, `ProcessorConfig`, `RendererConfig`, `RobotConfig`, `GuiConfig` (SchemaBase) |
| 0.3 | Реализовать `configs/__init__.py` | Реэкспорт всех конфигов |

**Ссылки:** `data_schema_module/README.md`, `config_module/docs/USAGE_GUIDE.md`

---

### Этап 1: CameraProcess

| # | Задача | Результат |
|---|--------|-----------|
| 1.1 | Реализовать `initialize()` | SharedMemory owner `camera_frame`, регистрация команд, создание воркера `capture_worker` |
| 1.2 | Реализовать `_capture_worker` (LOOP) | Генерация кадра → запись в shm → DATA `frame_ready` → processor |
| 1.3 | Реализовать обработчики команд | `_cmd_start`, `_cmd_stop`, `_cmd_set_fps`, `_cmd_set_resolution` |
| 1.4 | Реализовать `shutdown()` | `mm.close_all("camera")` |

**Ключевое:** Уведомление — только метаданные (frame_id, shm_index). Кадр — только в shared memory.

**Ссылки:** `process_module/README.md`, `worker_module/README.md`, `shared_resources_module/README.md`

---

### Этап 2: ProcessorProcess

| # | Задача | Результат |
|---|--------|-----------|
| 2.1 | Реализовать `initialize()` | Регистрация команд, создание воркера `processing_worker` |
| 2.2 | Реализовать `_processing_worker` | Получение `frame_ready` → чтение кадра из shm → детекция → DATA `detection_result` → renderer |
| 2.3 | Реализовать `_detect_color_blobs()` | Поиск пятен по BGR-диапазону, возврат bbox/center/area |
| 2.4 | Добавить обратную связь | EVENT `frame_processed` → camera |

**Ссылки:** `router_module/README.md` (receive_message с timeout)

---

### Этап 3: RendererProcess

| # | Задача | Результат |
|---|--------|-----------|
| 3.1 | Реализовать `initialize()` | SharedMemory owner `rendered_frame`, consumer `camera_frame`, воркер `render_worker` |
| 3.2 | Реализовать `_render_worker` | Получение `detection_result` → чтение кадра → отрисовка bbox → запись в `rendered_frame` → DATA `rendered_frame_ready` → gui |
| 3.3 | Добавить отправку в Robot | COMMAND `reject_item` при наличии детекций |
| 3.4 | Добавить обратную связь | EVENT `frame_rendered` → camera |

---

### Этап 4: RobotSimulatorProcess

| # | Задача | Результат |
|---|--------|-----------|
| 4.1 | Реализовать `initialize()` | Регистрация `reject_item`, воркер `robot_worker` |
| 4.2 | Реализовать `_cmd_reject` | Логирование frame_id, center, area в файл |
| 4.3 | Реализовать `_robot_worker` | Цикл приёма сообщений → вызов command_manager.handle_command |

---

### Этап 5: GuiProcess

| # | Задача | Результат |
|---|--------|-----------|
| 5.1 | Реализовать `initialize()` | Без воркеров, только конфиг |
| 5.2 | Переопределить `run()` | QApplication.exec_(), QTimer для `_poll_messages`, QTimer для `_check_stop` |
| 5.3 | Реализовать `_poll_messages` | Чтение `rendered_frame_ready` → чтение из shm → `_window.update_frame()` |
| 5.4 | Реализовать методы gui_* | `gui_start_capture`, `gui_stop_capture`, `gui_set_fps`, `gui_set_threshold` — отправка COMMAND |
| 5.5 | Создать `gui/main_window.py` | InspectorWindow: QLabel для видео, кнопки Start/Stop, слайдеры FPS и порога |

**Важно:** PyQt в главном потоке. `process` передаётся в окно для вызова gui_* методов.

---

### Этап 6: main.py и интеграция

| # | Задача | Результат |
|---|--------|-----------|
| 6.1 | Создать `main.py` | SystemLauncher, add_process для 5 процессов с config |
| 6.2 | Настроить очереди | system, data для каждого процесса |
| 6.3 | Проверить порядок запуска | Camera создаёт shm до того, как Processor читает |

**Запуск:** `PYTHONPATH=. python -m multiprocess_prototype.main`

---

### Этап 7: Обратная связь и статистика

| # | Задача | Результат |
|---|--------|-----------|
| 7.1 | Убедиться в наличии EVENT | `frame_processed`, `frame_rendered` |
| 7.2 | Добавить логирование метрик | FPS, processing_time через `log_info` |

---

### Этап 8: Тестирование

| # | Задача | Результат |
|---|--------|-----------|
| 8.1 | Тест без GUI | 4 процесса (camera, processor, renderer, robot) |
| 8.2 | Тест shared memory | Изолированный тест write/read |
| 8.3 | Полный тест | 5 процессов, Ctrl+C → graceful shutdown |

---

## 4. Схемы взаимодействия

### Поток данных

```
Camera  ──frame_ready──► Processor ──detection_result──► Renderer ──rendered_frame_ready──► GUI
   ◄──frame_processed──                                    │
   ◄──frame_rendered───                                    └──reject_item──► Robot
```

### Типы сообщений

| Тип | От → К | Содержание |
|-----|--------|------------|
| DATA `frame_ready` | camera → processor | frame_id, shm_index, timestamp |
| DATA `detection_result` | processor → renderer | frame_id, detections[], shm_index |
| DATA `rendered_frame_ready` | renderer → gui | frame_id, shm_index |
| EVENT `frame_processed` | processor → camera | frame_id, processing_time |
| EVENT `frame_rendered` | renderer → camera | frame_id |
| COMMAND `reject_item` | renderer → robot | frame_id, defects[] |

---

## 5. Риски и упрощения

### Риски

| Риск | Решение |
|------|---------|
| SharedMemory не готова при старте consumer | Consumer пропускает итерацию при `read_images() == None` |
| macOS + PyQt + fork | Использовать `spawn` start method |
| GUI зависает | `receive(timeout=0.001)` в `_poll_messages` |

### Упрощения (если нужно)

1. **Без SharedMemory:** передавать `frame.tobytes()` в DATA — проще, но медленнее
2. **Без GUI:** начать с 4 процессов, смотреть логи
3. **coll=1:** без двойной буферизации — проще, возможны гонки

---

## 6. Чеклист

```
Этап 0:  [ ] frame_generator.py  [ ] 5 configs  [ ] configs/__init__.py
Этап 1:  [ ] camera_process.py   [ ] Тест изоляции
Этап 2:  [ ] processor_process.py [ ] Тест Camera+Processor
Этап 3:  [ ] renderer_process.py [ ] Тест пайплайна
Этап 4:  [ ] robot_simulator_process.py
Этап 5:  [ ] gui_process.py  [ ] main_window.py
Этап 6:  [ ] main.py  [ ] Полный запуск
Этап 7:  [ ] Метрики в логах
Этап 8:  [ ] Тесты  [ ] Graceful shutdown
```

---

## Приложение: Зависимости

```
numpy>=1.21
pydantic>=2.0
PyQt5>=5.15
```

OpenCV — опционально. Прототип работает без него.

---

## Ссылки на документацию

| Тема | Документ |
|------|----------|
| ProcessModule | `process_module/README.md` |
| WorkerManager | `worker_module/README.md` |
| RouterManager | `router_module/README.md` |
| CommandManager | `command_module/README.md` |
| MemoryManager | `shared_resources_module/README.md` |
| ADR Dict at Boundary | `DECISIONS.md` ADR-008 |
| ADR SharedMemory | `DECISIONS.md` ADR-019, ADR-021 |

---

**Конец плана.**  
**Обновление:** 2026-03-15
