# Ф8 H.2 / GATE G4 — триаж вердиктов и решения владельца

> Создан 2026-07-26 при исполнении H.2. Статусы — ТОЛЬКО в [plan.md](plan.md); здесь —
> доказательная база и решения. **Не путать с [g4-execution-plan.md](g4-execution-plan.md)** —
> тот про Ф7 задачу G.4 (QoS-профили и пулы SHM), совпадение обозначений историческое.
>
> Вход: [plan.md](plan.md) §GATE G0 §Б (13 вердиктов, 2026-07-06), ярусная карта
> [`MODULE_TIERS.md`](../../multiprocess_framework/docs/MODULE_TIERS.md) (Ф8 H.1).
> Ревью пунктов — агент `reviewer` на Fable, инструменты graphify / serena / qex / sentrux.

## 1. Критерий владельца (принят 2026-07-26)

> «Самое главное чтобы был **рабочий и используемый аналог, либо лучший**. Если просто не
> используется — оставляем, так как может ещё пригодиться: это конструктор-фреймворк.»

Отсюда три класса «мёртвого», которые нельзя путать — именно их смешение давало оценку
«~4000 LOC под нож»:

| Класс | Признак | Решение |
|---|---|---|
| Дремлющий рабочий код | не вызывается, но исправен и покрыт тестами | **frozen** — капитал |
| Осиротевший байткод | исходников нет, git каталог не отслеживает | уборка, не решение гейта |
| Врущий API | вызываем, рапортует успех, эффекта не производит | чинить: хранение опаснее |

## 2. Пер-пунктный итог

| # G0 | Пункт | Вердикт G0 | Итог G4 | Основание |
|---|---|---|---|---|
| 1 | `chain_module` FREEZE | KILL-соседний | **core** | Ожил в C6(d) (`22393392`): pipeline-движок стоит на `ChainRunnable`. Ждёт переподтверждения владельца |
| 4 | data_schema-мертвецы ~2118 LOC | KILL | **FREEZE** (владелец) | Не изолированы: внутренние потребители + интерфейсы в публичном `__all__`. Удаление = рефактор API живого core-модуля ради метрик |
| 5 | `WidgetRegistry` | KILL после G2 | **FREEZE** | Отменено гейтом G2 (2026-07-10) |
| 6 | K3 `apply_topology_diff`, K5 `connect_wire` | KILL / оставить | **исправлено, не удалено** | `connect_wire` шлёт `wire.setup` — приёмник ЕСТЬ (`_cmd_wire_setup`, PM:334), метод рабочий. `apply_topology_diff` — врал (см. §3) |
| 7 | K4 `hot_add_process` | KILL | **исправлено, не удалено** | Врал (см. §3) |
| 8 | K6 `CommandPanel`, K7 `ProcessStatusWidget` | KILL | **FREEZE** (владелец) | Функция перекрыта вкладкой «Процессы», но потребителей вне `test_bridge.py` ноль — вреда нет |
| 9 | K8 `TopologyEditorWidget` ~722 LOC | KILL | **УЖЕ ИСПОЛНЕНО** (Ф4-добор H7) | В `widgets/topology/` остались `__init__.py`-tombstone и живой `TopologyPresenter` (`pipeline/presenter.py:127`). Сирот нет |
| 10 | K9 `Services/Operation_crop` 858 LOC | KILL | **мусор, убран** | Исходников нет и в git не было; на диске оставался один `.pyc`. Аналоги живы: `Plugins/processing/{crop,center_crop,roi_crop}` |
| 11 | K1 проводка ActionBus | KILL | **FREEZE целиком** | `_legacy_action_bus` снят Волной B. Каталог `frontend/actions/` — тестовая обвязка механизма **7b, замороженного G2**; отделимой мёртвой части нет (всё стянуто через `bus_factory`). Вердикт G0 №11 помечается superseded вердиктом G2 |

Заодно убран осиротевший байткод в трёх других каталогах: `Services/webcam_camera`,
`Plugins/control/robot_draw` (живые исходники — `Plugins/io/robot_draw`),
`Plugins/control/vfd_control`.

## 3. Врущий API — что было и что сделано (merge `6ef985e7`)

**Симптом.** `TopologyBridge.hot_remove_process` вызывается в проде из
`processes/presenter.py:452` (кнопка удаления процесса). Внутри — каскад `disconnect_wire`
(команда `wire.teardown`, **приёмник есть, отрабатывает**), затем `process.hot_remove`
(**приёмника нет, отбрасывается**). Метод возвращал `True`. Результат: процесс продолжал
работать, но провода ему уже оторвали — «зомби» без ввода-вывода, при видимости успеха.

**Корневая причина (уточнена ревью 2026-07-26 — первая формулировка была неверной).**
Дыра оказалась глубже, чем «нет обработчика ответа». `RouterManager.reply_to_request` —
документированный **no-op без correlation-id** (`router_module/core/router_manager.py:773-775`),
а GUI-путь `CommandSender.send_system_command` → `build_system_command_message`
`request_id` **не проставлял**. То есть PM не «отвечал в пустоту» — он вообще не отвечал,
и добавить один только handler было недостаточно: он молчал бы на всём GUI-трафике.
Живое свидетельство «No handler for key 'process.hot_remove'» было получено через driver
(коррелированный путь), а не через GUI — отсюда и ошибка в первой диагностике.

Закрыто двумя правками сразу: `send_system_command` проставляет `request_id` (ответа никто
не ждёт, блокировки нет — но PM теперь физически может сообщить об отказе), а handler
`process.command.response` этот отказ логирует.

**Сделано:**
1. `frontend/process.py` — зарегистрирован handler `process.command.response`, неуспех
   логируется WARNING с причиной от PM. Успех не логируется (шум на hot-path).
   `CommandSender.send_system_command` проставляет `request_id` — без него handler был бы
   мёртв на GUI-пути (правка по ревью). Причина отказа читается из `result` **верхнего**
   уровня ответа: первая версия читала `data.result`, которого в форме `reply_to_request`
   нет, и WARNING всегда писал «причина не указана». Handler покрыт 6 тестами
   (`frontend/tests/test_gui_process.py::TestOnCommandResponse`) — их отсутствие и дало
   пройти этой ошибке.
2. `hot_remove_process` — каскад не запускается, пока сам remove неисполним; `False` +
   WARNING. Половина операции хуже отказа целиком.
3. `hot_add_process` — `False` вместо `True`, команда в никуда не отправляется.
4. `apply_topology_diff` — ветки процессов пишутся в `result.errors`, а не в
   `processes_added`/`processes_removed`; каскад отключения снят по той же причине.
5. `presenter.delete_process` — WARNING висел в `except`, а мост исключений не кидал;
   теперь судим по возвращаемому значению.
6. Тесты моста переписаны под честный контракт + регресс-страж
   `test_no_cascade_wire_teardown`.

Код методов и конструкторы команд **сохранены** (ярус frozen): когда приёмник появится,
достаточно снять ранние выходы и вернуть импорт.

**Живой аналог смены топологии — `topology.apply`** (`ProcessManagerProxy.apply_topology`):
прод-вызовы `pipeline/runtime_control.py:142` и `:226`, `recipes/presenter.py:451`;
приёмник `_cmd_topology_apply` (PM:331) считает diff на бэке транзакционно, с rollback.
Покрывает add/remove/diff и строго лучше клиентской декомпозиции. Точечные connect/
disconnect покрыты частично: хендлеры `wire.setup`/`wire.teardown` живы, спит только
GUI-обёртка.

## 4. Реестр остальных «врущих» путей (ревью Fable, П4)

Сверены **все** ключи, уходящие через `send_system_command`, с реестром PM
(`process_manager_process.py:313-346`). Чистые: `process.start/stop/restart`,
`system.shutdown`, `topology.apply/get/diff`, `wire.setup/teardown/status`, `process.relay`,
`telemetry.broadcast`, `supervision.status`.

| # | Путь | Характер | Статус |
|---|---|---|---|
| 1 | PM не мог сообщить об отказе на GUI-пути: `reply_to_request` — no-op без correlation-id, а `send_system_command` не ставил `request_id`; handler'а ответа тоже не было | корневая дыра класса | ✅ закрыто (`6ef985e7` + правки по ревью: `request_id` в отправителе, чтение `result` с верхнего уровня, 6 тестов). **Требует live-подтверждения**: fire-and-forget с request_id → WARNING в GUI-логе |
| 2 | `hot_add_process` | `True` без приёмника | ✅ закрыто |
| 3 | `hot_remove_process` | `True` + частичный разрушительный эффект | ✅ закрыто |
| 4 | `apply_topology_diff` | успех за отброшенные команды | ✅ закрыто |
| 5 | `actions_module/handlers/topology_handler.py:77-81` | исключение моста гасится `logger.debug` под «graceful degradation» | ⏳ открыто (мёртв в проде) |
| 6 | `ProcessManagerProxy._dispatch` (`:140-144`) | `{"success": True, "dispatched": True}` — sync-путь не узнает об отказе PM | ⏳ открыто (пограничный: документированный оптимизм, ключи с приёмниками) |
| 7 | `processes/presenter.py:133` | `cmd_map.get(action_id, action_id)` отправит любой незнакомый ключ сырым | ⏳ открыто (латентная лазейка) |
| 8 | `build_process_start/stop/restart` | 0 прод-вызовов, все шлют сырые dict мимо билдеров | ⏳ открыто (не ложь; «один источник правды» по форме команд не используется) |
| 9 | `TopologyBridge.get_capabilities` | обещал `hot_add: True` / `diff_apply: True` для неисполнимых путей, тест это закреплял | ✅ закрыто правкой по ревью (`hot_add: False`, `diff_apply: False`, `wire: True` — честно) |

## 5. Что не проверено

- **Live-подтверждение через backend_ctl**: «0 приёмников» доказано статически (полный
  реестр PM + отсутствие иных `register_command` вне тестов) плюс чужим живым
  свидетельством H-3 (`presenter.py:435`). Живой бэкенд в этом заходе не поднимался.
- **Полный аудит `send_command` GUI→дочерние процессы** (`worker.*`, field-write,
  register-команды) на приёмники в каждом процессе — вне скоупа П4, покрыт только
  системный конверт `send_system_command`.
- Живость auth/RBAC-ветки (`role_update_handler`, `pre_auth_guard`) — на вердикт §2 п.11
  не влияет (всё равно FREEZE).
