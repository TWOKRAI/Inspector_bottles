# multiprocess_prototype\stage_reports\archived\STAGE_00_CRITICAL_FIX.md
# STAGE 00: Исправление критического бага — гонка потоков

**Дата:** 2026-03-15  
**Статус:** Выполнено

## Проблема

Системный поток `message_processor` и воркеры процессов (Processor, Renderer, Robot) одновременно вызывали `router_manager.receive()`, который опрашивал **все** каналы процесса (system + data). Сообщения извлекались из очередей (queue.get), поэтому возникала гонка: системный поток забирал DATA/EVENT сообщения раньше воркеров. В `_handle_message()` для не-command сообщений обработки не было — они терялись.

**Цепочка сбоя:**
1. Camera → send_message("processor", frame_ready) → OK
2. Системный поток Processor → receive() → забирает frame_ready → _handle_message() → тип DATA → ничего не делает → **сообщение потеряно**
3. processing_worker → receive_message() → **пусто** → continue
4. Нет detection_result → Renderer ничего не получает → GUI не получает кадры

## Решение (Вариант C из плана)

Разделение очередей по типу сообщений:
- **system** — команды (command)
- **data** — данные и события (data, event)

Системный поток опрашивает **только** `{process}_system`. Воркеры опрашивают **только** `{process}_data`.

## Изменения

### 1. `router_manager.py`
- Добавлен параметр `channel_types: Optional[List[str]] = None` в `receive()` и `_poll_all_channels()`
- При `channel_types=['system']` опрашиваются только каналы с суффиксом `_system`
- При `channel_types=['data']` — только `_data`

### 2. `process_communication.py`
- **send_to_process:** маршрутизация по `message['type']`: `command` → `system`, иначе → `data`
- **receive**, **receive_message:** добавлен параметр `channel_types` для фильтрации каналов

### 3. `system_threads.py`
- `_message_processing_loop` вызывает `router_manager.receive(timeout=0.0, channel_types=['system'])`
- Системный поток обрабатывает только команды

### 4. `process_module.py`
- `receive()` и `receive_message()` пробрасывают параметр `channel_types`

### 5. Прототип-процессы
- **ProcessorProcess, RendererProcess:** `receive_message(timeout=0.1, channel_types=['data'])`
- **GuiProcess:** `receive(timeout=0.001, channel_types=['data'])`
- **RobotSimulatorProcess:** 
  - `_init_system_threads()` переопределён — pass (system_thread не запускается)
  - `receive(timeout=0.1, channel_types=['system'])` — воркер получает команды из system-очереди

## Тестирование

- Линтер: ошибок нет
- pytest: не запускался (нет pydantic в окружении)
- Рекомендуется: `pytest Inspector_prototype/multiprocess_framework/refactored/modules/process_module/tests/ -v`
- Рекомендуется: запуск `python -m multiprocess_prototype.main`, нажатие Start — кадры должны отображаться в GUI

## Обратная совместимость

- `channel_types=None` — опрос всех каналов (как раньше)
- Существующий код без `channel_types` продолжит работать

## Известные проблемы

- Нет
