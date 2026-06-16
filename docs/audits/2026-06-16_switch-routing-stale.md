# Диагноз: параметры не доходят после переключения рецепта (стейл-маршрут GUI)

**Дата:** 2026-06-16
**Ветка:** feat/pult-control-panel
**Метод:** 3 расследования (investigator) + многоагентный воркфлоу `diagnose-live-tuning-mess` (9 агентов, состязательная проверка)
**Статус:** root cause найден и триангулирован (HIGH). Фикс — выбран «полный» (см. ниже), реализация отдельным этапом.

---

## Симптом

Живой тюнинг параметров плагинов работает на свежем запуске, но **после горячего переключения рецепта** правки полей **молча перестают применяться** — помогает только полный перезапуск приложения. Раньше случалось реже, стало систематически. Плюс само переключение рецепта **тормозит** (~5 с).

## Главная причина (№1): стейл-маршрут очередей в GUI после switch

**Confidence: HIGH.** Каждый процесс держит свою **pickle-копию** `ProcessStateRegistry` (PSR) с объектами `multiprocessing.Queue`, полученную при spawn. GUI-процесс **защищён (protected) и НЕ пересоздаётся** при горячей замене рецепта. При `apply_topology` PM создаёт пересозданным процессам **новые** `Queue` (`QueueRegistry.create_queues` → `Queue(maxsize=...)`, всегда новый объект; `add_queue` перезаписывает в PSR PM), а новые дочерние процессы читают из них через свой свежий bundle. **PSR GUI при этом не обновляется** — в нём для `vision`/`recog`/… остаётся **старая мёртвая очередь** убитого процесса.

Путь живой правки:
```
inspector/пульт → domain SetPluginConfig → PluginConfigChanged
  → app.py:_on_plugin_config_changed
  → command_sender.send_command(process_name, "register_update", {register, field, value})
  → ProcessModule.send_message → ProcessCommunication.send_to_process
  → RouterManager._deliver_by_targets → QueueRegistry.send_to_queue(process, ...)
  → get_queue("vision")  ← СТАРАЯ очередь из стейл-PSR GUI
  → put_nowait → данные в мёртвый pipe → return True → ТИХАЯ ПОТЕРЯ
```
Механизма обновления маршрутизации в GUI после switch **нет** (`grep routing_update` по PM → пусто). Полный перезапуск чинит, потому что GUI пересоздаётся со свежими очередями. Сырой `multiprocessing.Queue` **нельзя переслать через работающую очередь** (только наследование при spawn) — поэтому «дослать новые очереди в GUI» в лоб невозможно; правильный фикс — маршрут через PM-хаб.

Объясняет всё: только после switch · молча (`put_nowait`→True) · лечится перезапуском · стало систематически (см. регрессию).

### Evidence (ключевое)
- `shared_resources_module/core/shared_resources_manager.py:1-12` — SRM это pickle-копия на процесс.
- `process_manager_module/runner/bundle_builder.py:107-116` — дочерний процесс получает routing_map snapshot при spawn.
- `process_manager_module/process/process_manager_process.py:1240-1241` — `_topology_provision` создаёт НОВЫЕ Queue в PSR PM.
- `shared_resources_module/queues/core/manager.py:94` — `Queue(maxsize=...)` всегда новый объект; `:151-161` — `send_to_queue` → `put_nowait` на найденную (старую) очередь → True без ошибки.
- `shared_resources_module/state/process_data.py:170` — `add_queue` перезаписывает.
- `process_manager_module/process/process_manager_process.py` — нет `routing_update`/`unregister_process` при topology change.

## Вторая проблема (№2): graceful-stop debt (лаг + грубый terminate)

**Confidence: HIGH** (подтверждает прежнюю гипотезу из памяти). При switch PM взводит stop всем процессам с общим дедлайном 5 с (`process_registry.py:201` stop_many → `:184` terminate). Воркеры-источники застревают в **блокирующих вызовах**: Hikvision `capture_frame(timeout_ms=1000)` (`Services/hikvision_camera/core/camera.py:284` `MV_CC_GetImageBuffer`) и `cv2.VideoCapture.read()` (`Plugins/sources/capture/plugin.py:151`). `SourceProducer.run_loop` (`source_producer.py:80`) проверяет `stop_event` только в начале итерации, не внутри `produce()`. → join висит → `terminate()` (finally/`plugin.shutdown()` не отрабатывает → камера не освобождается).

Это **отдельная** проблема (не причина №1 — стейл-PSR возникает и при чистом стопе), но даёт +5 с к switch и грубое завершение. `ValueError: I/O operation on closed file` (BatchBuffer `_timer_worker`) — безобидный шум от terminate, не баг. «Процесс gui/devices уже есть — дубль пропущен» — норма (merge_topologies, protected фундамент).

## Третья (№3): часть полей применяется только с reload

Скалярные поля (`roi_crop`, `hsv_mask`, `circle_detector`, `word_layout`, …) читаются из `self._reg` каждый кадр → live мгновенно. Но `ml_inference.model`: смена пишется в `_reg`, а reload ONNX-движка делает только `cmd_set_model` → смена модели «не применяется до перезапуска». Плагины **без register_schema** выпадают из приёма register_update (нет регистра-приёмника). Вторично, проявляется и на свежем старте.

## Четвёртая (№4): мёртвый дубль set_config (boot-шум)

Старый путь `ActionBus→FieldSetHandler→on_field_set→CommandCatalog.resolve_field_command("set_config")→cmd_set_config` в проде **мёртв** (`form_ctx=None` во всех фабриках, `_legacy_action_bus` retained-but-unbound, нет живых `bus.execute(FIELD_SET)` вне tests). Warning'и `Handler 'set_config' already exists` (`ExactMatchStrategy`, при группировке плагинов несколько `register_class` в одном CommandManager) — **безобидный boot-шум, НЕ причина симптома**. Состязательная проверка воркфлоу опровергла первоначальную гипотезу «коллизия set_config = причина». Но дубль стоит удалить как когнитивный долг (fix-forward, функционал полностью покрыт register_update).

## Почему «стало хуже»

Регрессия — накопление, а не один коммит:
- `f959b505` (15.05) — per-plugin регистрация generic set_config (безвредно при 1 плагине/процесс, заложило коллизию).
- `5dc97751` (29.05, G.4.3) — инспектор переведён на domain SetPluginConfig; старый set_config-стек не удалён → два пути.
- `81326a8c` (31.05, Этап 2) — register_update в прод (живой путь).
- `5196ab3b` (16.06) — рецепт hikvision_letter_robot слил 5/3/2/2 плагинов в процесс ради экономии SHM-перегонов.

Тихая потеря при switch (№1) была в архитектуре всегда, но стала заметной/систематической: live-тюнинг появился в конце мая, группировка + блокирующая камера (→terminate каждого процесса на каждом switch) — в июне.

## Выбранный фикс: «полный», без костылей, доработкой существующего хаба

Решение владельца: правильная архитектура, доработать существующий транспортный хаб (RouterManager + центральный ProcessManager), не плодить слои. Инфраструктура уже есть: lifecycle-команды (`process.start/stop/restart`) **уже** ходят через PM (`send_system_command` → `_handle_process_command`) и работают после switch, т.к. PM держит свежие очереди.

- **№1 (главное):** GUI-исходящие live-команды (register_update + action-команды плагинов) маршрутизировать **через PM-хаб** (GUI→PM→target по свежему PSR PM), а не напрямую через стейл-PSR GUI. Reuse `reply_to_request` (ADR-COMM-005) — потеря/ошибка видима, не тихий дроп. Точный механизм проектируется отдельно (relay-endpoint PM).
- **№2:** прерываемый `produce()` камеры (короткий таймаут + проверка stop_event; `grab()/retrieve()` вместо `read()`) + гарантированный `plugin.shutdown()`; guard в `BatchBuffer.stop()`.
- **№4:** удалить мёртвую цепочку set_config (base.py generic-регистрация + cmd_set_config; FieldSetHandler FIELD_SET-ветка; on_field_set/resolve_field_command set_config-конвенция) — снимает boot-warning'и и упрощает.
- **№3:** пометить «reload-поля» в register_schema + дёргать reload-команду из инспектора; зафиксировать инвариант «live-тюнингуемый плагин обязан иметь register_class».

Связано: [[project_switch_routing_stale]], [[project_graceful_stop_debt]], транспортный хаб (RouterManager), `project_recipe_hotswap`, `project_command_result_bridge`.
