# multiprocess_prototype\stage_reports\archived\STAGE_05_GUI_PROCESS.md
# Отчёт: Этап 5 — GuiProcess

**Дата:** 2026-03-15  
**План:** PLAN.md  
**Статус:** ✅ Выполнен

---

## 1. Что сделано

### 1.1 `processes/gui_process.py`

Создан `GuiProcess(ProcessModule)`:

- **Без воркеров:** `_init_application_threads()` — только конфиг
- **Без message_processor:** `_init_system_threads()` / `_stop_system_threads()` — пустые (опрос через QTimer в главном потоке)
- **run():** QApplication.exec_(), QTimer для `_poll_messages` (16 мс), QTimer для `_check_stop` (100 мс)
- **Consumer rendered_frame:** чтение через `shm_actual_name` из `rendered_frame_ready`
- **Методы gui_*:** `gui_start_capture`, `gui_stop_capture`, `gui_set_fps`, `gui_set_threshold` — отправка COMMAND в camera/processor

### 1.2 `gui/main_window.py`

`InspectorWindow(QMainWindow)`:

- QLabel для видео (640×480 min)
- Кнопки Start / Stop
- Слайдер FPS (1–60)
- Слайдер порога (0–255)
- Статус, счётчик кадров
- `update_frame(frame, frame_id)` — BGR→RGB, QImage, QPixmap, scaled

### 1.3 Особенности

- **PyQt в главном потоке** — без воркеров
- **process** передаётся в окно — вызов `process.gui_*` из кнопок/слайдеров
- **macOS:** рекомендуется `spawn` (см. PLAN §5)

---

## 2. Оценки

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| **Полнота** | 10/10 | Все пункты чеклиста Этапа 5 |
| **Соответствие плану** | 10/10 | PyQt, QTimer, gui_* |
| **Архитектура** | 9/10 | Dict at Boundary, consumer через shm_actual_name |
| **Связь с фреймворком** | 9/10 | ProcessModule, ProcessCommunication, без message_processor |

**Итоговая оценка этапа:** 9/10

---

## 3. Модули фреймворка

| Модуль | Роль |
|--------|------|
| **process_module** | ProcessModule, run(), send_message, receive |
| **shared_resources_module** | memory_manager (fallback), QueueRegistry |
| **router_module** | receive через ProcessCommunication |

---

## 4. Чеклист (из плана)

- [x] initialize (конфиг, без воркеров)
- [x] run() — QApplication, QTimer
- [x] _poll_messages — rendered_frame_ready → _handle_new_frame
- [x] gui_start_capture, gui_stop_capture, gui_set_fps, gui_set_threshold
- [x] gui/main_window.py — InspectorWindow

---

## 5. Запуск (требует main.py, этап 6)

```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
```

**Зависимость:** `PyQt5>=5.15` (см. PLAN §Приложение).

**Примечание:** main.py с 5 процессами — этап 6.

---

## 6. Следующий этап

**Этап 6: main.py и интеграция** — SystemLauncher, add_process для 5 процессов через configs.build().

---

*Ожидание команды продолжения.*
