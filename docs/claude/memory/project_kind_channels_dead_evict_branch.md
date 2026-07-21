---
name: project-kind-channels-dead-evict-branch
description: При FW_USE_KIND_CHANNELS=1 кадры не идут через QueueRegistry — вытеснение, data_evicted и on_evict для них мертвы; QueueChannel.send блокирует на 1с вместо drop_oldest
metadata:
  type: project
---

При `FW_USE_KIND_CHANNELS=1` кадровые сообщения резолвятся в kind-канал (`{process}_data`) и уходят через `QueueChannel.send`, **не через `QueueRegistry.send_to_queue`**. Вытеснение из полной очереди, счётчик `queue_data_evicted` и хук `on_evict` живут только на очередном пути — для кадров эта ветка мертва. `router_manager.py:302-309`: при одном разрешённом канале `_do_send` возвращает результат сразу, не доходя до `_deliver_by_targets` — единственного места в репозитории, где навешивается `on_evict`.

Следствия:
- Фикс release-on-evict (`8b8a3c54`, ADR-RTR-010) логически корректен и покрыт юнит-тестом, но на боевой раскладке флагов **не исполняется**. Нули `queue_data_evicted`/`frame_loans_released_on_evict` — свойство конструкции, а не доказательство здоровья.
- `QueueChannel.send` (`queue_channel.py:52-67`) на полной очереди делает `put(block=True, timeout=1.0)` — блокирует поток-отправителя до секунды, потом `{"status": "error"}`. QoS-профиль `data` (best_effort/drop_oldest) на kind-канальном пути **не применяется вовсе**, перегрузка = невидимый стойл writer'а.
- Вторая, независимая причина недостижимости вытеснения: кольцо SHM 4 слота против data-очереди 50 (`process_launch_config.py:14-17`) — займы кончаются задолго до `queue.full()`.
- Инъекция отказа live невозможна: глубина кольца, `maxsize` очереди и сам флаг читаются на старте, регистрами не правятся.

**Why:** день был потрачен на попытку живьём проверить фикс, который на этой раскладке физически не может сработать; без этой записи попытка повторится.

**How to apply:** прежде чем «проверять живьём» что-либо на кадровом тракте — сначала выяснить, каким транспортом кадры реально едут при текущих флагах. Нулевой счётчик может означать «путь мёртв», а не «всё хорошо». Первичная задача — привести kind-канальный путь к QoS `data` (drop_oldest + счётчик вместо блокирующего put); это побочно оживит release-on-evict.

Связано: [[project_f7_g7_num_consumers]], [[project_feature_flags_registry]], [[project_live_verification_2026_07_21]]
