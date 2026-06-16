---
name: project_graceful_stop_debt
description: Graceful-stop 5с-хан­г при switch/shutdown — что НЕ причина (исключено), где копать дальше
metadata:
  type: project
---

При switch рецепта / shutdown все старые процессы дают `Process 'X' did not stop in 5.0s, terminating...` (`process_registry.py:184`, parent `process.join(timeout=5.0)` истекает). Функционально не блокирует (terminate добивает), но это +5с на switch и грубое завершение. Владелец: «graceful-stop воркеров обязательно как надо».

**Исключённые гипотезы (НЕ тратить время повторно, 2026-06-07):**
- ❌ `mp.Queue` feeder-thread atexit-join → `cancel_join_thread()` на очередях в `run_process_function` finally. **Проверено e2e: не помогло.** Дочерние логи показывают, что ребёнок НЕ доходит до finally за 5с (cancel-сообщение не появилось, процесс был terminated). Хан­г РАНЬШЕ atexit.
- ❌ AsyncSender (router) — он не worker_manager-воркер, стопается в `router_manager.shutdown` ПОСЛЕ `stop_all_workers`, на 5с-join не влияет (sentinel `bbdc8a41` корректен, но не про это).
- ❌ `data_receiver` вечный put (`bdcbab96`) — реальный баг, починен, но не ТОТ блокер.

**ПРИЧИНА ПОДТВЕРЖДЕНА (HIGH, 2026-06-16, investigator):** воркер-источник застревает в БЛОКИРУЮЩЕМ `produce()`. `SourceProducer.run_loop` (`source_producer.py:80`) проверяет `stop_event` только в начале итерации, НЕ внутри `produce()`. Блокеры: Hikvision `capture_frame(timeout_ms=1000)` (`Services/hikvision_camera/core/camera.py:284` `MV_CC_GetImageBuffer`) и `cv2.VideoCapture.read()` (`Plugins/sources/capture/plugin.py:151`). → `stop_all_workers` join висит до дедлайна → `terminate()`, finally/`plugin.shutdown()` не отрабатывает (камера не освобождается). Совпало с прежней гипотезой «cv2.read/put».

**Фикс-направление (без костылей):** прерываемый `produce()` — короткий таймаут камеры + проверка `stop_event` в цикле (Hikvision `capture_frame(timeout_ms=100)` с повтором; cv2 `grab()`+`retrieve()` вместо `read()`); гарантированный `plugin.shutdown()` при превышении дедлайна стопа воркеров; guard в `BatchBuffer.stop()` (`batch_buffer.py:99/200`: не звать `_flush_fn` если `_stop_event.is_set()`) — устраняет `ValueError: I/O operation on closed file` (безобидный шум teardown).

**ВАЖНО:** это ОТДЕЛЬНАЯ проблема от тихой потери параметров после switch — см. [[project_switch_routing_stale]] (стейл-PSR GUI возникает и при ЧИСТОМ стопе). Чинить обе.

Связано: [[project_recipe_hotswap]], [[feedback_fix_framework_forward]], [[project_switch_routing_stale]].
