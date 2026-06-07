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

**Где копать (вероятная причина):** ребёнок виснет в `process_instance.shutdown()/stop()` ДО atexit — скорее всего `worker_manager.stop_all_workers` join'ит воркер-поток, который не выходит по stop_event: блок внутри `queue.put()` в мёртвый receiver ИЛИ `cv2.read()` камеры. `cancel_join_thread` структурно бессилен против потока, застрявшего ВНУТРИ put(). Нужен дефинитивный thread-dump ВНУТРИ зависшего ребёнка в окне 0–5с (не после terminate). Инструмент: `faulthandler.dump_traceback_later` в `run_process_function` перед stop, или прямой дамп воркер-стеков в `stop_all_workers` при превышении дедлайна.

**Стоп-условие владельца:** «если не получится этот подход тормози, в дебри полез уже» — подход cancel_join_thread провалился, дерево откачено к `191732eb` (чистое). Связано с [[project_recipe_hotswap]], [[feedback_fix_framework_forward]].
