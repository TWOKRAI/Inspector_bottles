# Срез D — устройства при смене рецепта (Explore/haiku, 2026-10-13)

Сырой отчёт агента-разведчика для схемы `docs/maps/recipe-switch.md`. Факты — со строками кода; выводы без запуска помечены.

## Ответ
Активация рецепта: `presenter.py` шлёт `device_sync_set` (fire-and-forget) до `topology.apply`. Hub upsert'ит устройства рецепта, удаляет recipe-устройства прошлого рецепта (bridge первыми), ставит connect в очередь в порядке обхода `set` — порядок недетерминирован (R-10 по коду). Bridge-VFD, которому носитель не готов, ретраит себя сам: 3 попытки по ~3 с, затем «сдался» без автовозобновления. `devices` protected, при apply не перезапускается, sync не теряется.

## 1. Порядок `cmd_device_sync_set` (`Plugins/hub/device_hub/plugin.py`)
- :590 `new_ids: set[str] = set()`; :592-597 upsert в порядке списка `devices`.
- :600-605 stale = recipe-устройства (origin startswith `recipe:`) вне `new_ids`; `stale.sort(key=0 if bridge else 1)` (bridge удаляются первыми).
- :607-611 `cmd_device_remove` для каждого stale; :613-614 `_publish_full_registry`, `_update_counters`.
- :617-622 `for dev_id in new_ids:` → `_conn_queue.put(("connect", dev_id))`. Порядок = обход `set` (хеш строк рандомизирован между процессами). Порядок рецепта не используется. Тесты (`test_device_hub_plugin.py:335-400`) порядок connect не проверяют.
- Защиты «носитель раньше bridge» на стороне connect нет.
- Холодный старт (`plugin.py:195-214`): upsert из `recipe_devices` (origin `recipe_origin`, fallback `"recipe"` :196), connect в порядке `snapshot_registry()` (:211).

## 2. Зависимость носитель/мост
- Объявлена в `transport.bridge` (`transports.py:120-135`, `_build_bridge`; kind носителя == `robot` :126).
- Проверка: `Services/device_hub/manager.py:293-299` (`connect`): носитель `None` или не подключён → `DeviceHubError`. До проверки :290 `_get_or_create_driver` — драйвер моста уже создан.
- Удаление носителя при живых зависимых: `manager.py:252-261` → `RegistryIntegrityError`.
- `plugin.py:295-300`: ошибка connect → `conn=error`, `health.report_error`; повтора из очереди нет.
- Повтор только в tick драйвера: `vfd_driver.py:141-143`, `_attempt_reconnect` :256-285 (пока `desired_connected`). `_ensure_device_workers` (`plugin.py:330-340`).

## 3. Политика переподключения
- `Services/device_hub/drivers/base.py:88` `max_reconnect_attempts` = 3 по умолчанию.
- `base.py:190-217` `_note_reconnect_failed`: на лимите `desired_connected=False`, `reconnect_exhausted=True`, WARNING «сдались после N попыток…» (:211-214).
- Троттлинг: `vfd_driver.py:19` 3.0 с; `robot_driver.py:29` 2.0 с (`_ensure_connected` :535-556, из tick :215). Экспоненциального back-off нет.
- Сброс: `base.py:181-188` `reset_reconnect` — при успешном connect и ручном «Подключить» (`plugin.py:279-284`).
- Автовозобновления при появлении носителя нет; каскад носитель→мост только при disconnect (`manager.py:323-330`, `set_degraded`).
- Оценка без запуска: мост сдаётся через ~6 с, робот — ~3 попытки по 2 с.

## 4. Устройства старого рецепта
- Удаляются: `cmd_device_remove` (`plugin.py:631-654`) → `_stop_device_worker` → `manager.remove` (`manager.py:270-274`) → `_save`.
- Ручные (origin не `recipe:*`) не трогаются (`plugin.py:603`, тест `test_sync_set_preserves_manual_devices`).
- (вывод из кода) Если новый рецепт оставляет мост на старом носителе — носитель не удалится (`RegistryIntegrityError` в `_safe_call`), ответ всё равно `status: ok`.
- Реестр грузится из store при старте (`manager.py:71-76`); `start()` не чистит старые recipe-записи, которых нет в `recipe_devices` (`plugin.py:195-214`).

## 5. Порядок относительно `topology.apply`
- `presenter.py:411-425` — upsert ДО apply; :428-456 `_apply_topology_fn`.
- `tab.py:416-426` `send_action_command("devices","device_sync_set",{devices, origin:"recipe:<slug>", connect:True})` — без ожидания ответа.
- `devices` protected: `backend/topology/base.yaml:27-28`. Планировщик живых protected не заменяет: `planner.py:251` `live_protected`, :258; расхождение только логируется (:257, `_detect_protected_conflicts`).
- `Plugins/hub/device_hub/DECISIONS.md:6-19`: protected = не рестартуется; non-protected отвергнут (replace убивает devices).
- Вывод: sync рестартом не теряется, но конфиг `devices` (`recipe_devices`/`recipe_origin`) после apply остаётся СТАРЫМ; `cmd_device_sync_set` его не обновляет (`plugin.py:562-629`). Источник правды после apply — только sync.
- Docstring `tab.py:406-408` говорит «обрабатывается в supervisor-воркере», по коду тело синхронное (:562-629), в supervisor уходит только connect.

## 6. Маркеры
TODO/FIXME/FROZEN в `Services/device_hub`, `Plugins/hub/device_hub`, `multiprocess_prototype/backend` — нет. Рядом только `presenter.py:613` (`TODO: Task 7a`, не про устройства).

## Что осталось открытым
- R-10 не воспроизводился; вероятность плохого порядка — вывод из кода.
- Тайминги повторов — оценка без учёта `poll_interval_s`.
- Не проверены диспетчер команд `devices` (поток) и гарантия доставки/порядка `send_action_command` относительно `topology.apply`.
- Не проверено, перезаписывает ли рестарт `recipe_devices` из нового рецепта.
- Тесты не запускались.
