# multiprocess_prototype\docs\ARCHITECTURE_RECOMMENDATIONS.md
# Рекомендации по архитектуре multiprocess_prototype

Документ с рекомендациями по развитию и улучшению архитектуры (Этап 7 плана Dual Image Display).

## Что добавить

### 1. Event-driven обновление GUI

Вместо `poll_interval_ms=16` (60 FPS опроса) можно подписаться на события от Renderer через EventManager (если поддерживается cross-process). Пока оставлен QTimer — проще и надёжнее.

### 2. Централизованный DisplayConfig

Состояние `show_original`, `show_mask`, `draw_contours` можно хранить в ConfigStore (SRM) для persistence между сессиями. На первом этапе — локально в Renderer.

### 3. Метрики отображения

StatsManager: `gui.frames_displayed`, `renderer.contours_drawn` — для мониторинга производительности.

### 4. Валидация сообщений

MessageAdapter/Message имеет `validate()`. Использовать при отладке для проверки формата сообщений на границах.

## Что изменить

### 1. Разделение original/mask в сообщении

`rendered_frame_ready` явно содержит два блока: `rendered` и `mask`. Формат: `data: { rendered_shm_actual_name, rendered_shm_index, mask_shm_actual_name, mask_shm_index, ... }`.

### 2. Processor memory

Processor как owner `processor_mask` создаёт связность Renderer→Processor. Альтернатива: Renderer строит mask из contours (заливка полигонов). Текущая реализация сохраняет точную маску.

### 3. Контуры в сообщении

`contours` как list of np.ndarray — pickle-able. Для 1–2 контуров по ~100 точек — приемлемо. При большом количестве контуров рассмотреть shm.

## Соответствие фреймворку

- **Dict at Boundary** — все сообщения dict, без Pydantic на границах
- **CommandManager** — команды от GUI в Renderer через COMMAND (system queue)
- **MessageAdapter** — command(), data() для всех сообщений
- **MemoryManager** — owner/consumer, coll=2 для double buffering
- **ADR-024** — channel_types разделяет system и data очереди
