# multiprocess_prototype\stage_reports\archived\STAGE_03_RENDERER_PROCESS.md
# Отчёт: Этап 3 — RendererProcess

**Дата:** 2026-03-15  
**План:** PLAN.md  
**Статус:** ✅ Выполнен

---

## 1. Что сделано

### 1.1 `processes/renderer_process.py`

Создан `RendererProcess(ProcessModule)`:

- **SharedMemory owner:** `rendered_frame` (1 кадр, 480×640×3, coll=2)
- **Consumer camera_frame:** чтение через `shm_actual_name` из `detection_result`
- **Воркер:** `render_worker` (LOOP) — receive detection_result → read frame → draw bbox → write rendered_frame → send
- **Исходящие сообщения:**
  - DATA `rendered_frame_ready` → gui (frame_id, shm_actual_name, shm_index, width, height)
  - COMMAND `reject_item` → robot (при наличии детекций)
  - EVENT `frame_rendered` → camera

### 1.2 Отрисовка bbox

Функция `_draw_bbox()` — рисование прямоугольника через numpy (без OpenCV):

- Цвет (0, 255, 0) BGR, толщина 2px
- Обработка границ кадра

### 1.3 Опциональное сохранение

При `save_frames=True` — сохранение кадров в `output_dir` как `.npy`.

### 1.4 Изменения в ProcessorProcess

В `detection_result` добавлено поле `shm_actual_name` — передача имени SharedMemory камеры для Renderer.

### 1.5 `utils/shm_utils.py`

Вынесена функция `read_frame_from_shm()` — общая для Processor и Renderer.

### 1.6 Тест

- **test_pipeline.py:** Camera + Processor + Renderer, 4 сек, graceful shutdown

---

## 2. Оценки

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| **Полнота** | 10/10 | Все пункты чеклиста Этапа 3 |
| **Соответствие плану** | 9/10 | shm_actual_name для consumer |
| **Работоспособность** | 10/10 | Тест пайплайна проходит |
| **Архитектура** | 9/10 | Dict at Boundary, owner/consumer |
| **Тестируемость** | 8/10 | Интеграционный тест 3 процессов |

**Итоговая оценка этапа:** 9/10

---

## 3. Тесты

```bash
PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" .venv/bin/python -m multiprocess_prototype.tests.test_pipeline
```

---

## 4. Чеклист (из плана)

- [x] SharedMemory owner `rendered_frame`
- [x] Consumer `camera_frame` (через shm_actual_name)
- [x] `_render_worker` — detection_result → read → draw → write → gui/robot/camera
- [x] COMMAND `reject_item` при наличии детекций
- [x] EVENT `frame_rendered` → camera
- [x] Тест пайплайна

---

## 5. Следующий этап

**Этап 4: RobotSimulatorProcess** — регистрация `reject_item`, воркер `robot_worker`, логирование в файл.

---

*Ожидание команды продолжения.*
