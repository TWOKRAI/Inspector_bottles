# camera-device-service — правила исполнения, точки коммита, риски, открытое

Часть плана [`plan.md`](plan.md). Решения `Р<n>` — [`decisions.md`](decisions.md); сводная таблица, советы и связи —
[`matrix.md`](matrix.md); тела задач — `tasks/<id>.md`.

## Общие правила для всех задач

- **Конвейер — режим волн** (решение владельца 2026-10-18, только для этого плана): роли, стадия 0 Sonnet у 9 задач, слепой
  `tester` у 8, ревью Opus на волну и сразу после 2.1, 2.2, 2.4, 4.2a, инъекции только механизмов — [`wave-protocol.md`](wave-protocol.md).
- **Лимит восстановления:** 2 итерации на любой цикл (тест <-> код, ревью <-> правка); 3-я — `ESCALATION -> <уровень выше>`
  (`junior` -> `developer` -> Opus `teamlead`/ревьюер волны -> `cto` -> владелец). Лимит повторяется в брифе каждого агента (`plans_ledger.py brief <id>`).
- **Gate:** все тест- и стенд-команды — `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" [--timed] <класс> <session> <cmd…>`;
  класс — в шапке задачи; пути из `scripts/machine_gate_timed.txt` (`multiprocess_framework/`, `Services/device_hub/`) — `--timed medium` со своим окном.
- **Наблюдаемость — пункт приёмки** каждой задачи с поведением: ключи лога, метрики (`ctx.declare_metric`/`publish_metric`,
  `ctx.record_metric`/`record_timing`), инциденты (`ctx.health.report_error`), дерево (`processes.<p>.state.plugins.<plugin>.*`),
  команда `backend_ctl`, которая это показывает. Прямой `state_proxy.merge` уровней на каждый кадр запрещён (F8).
- **Тесты:** ожидаемые значения — литералы; тест, который может зависнуть, — в daemon-потоке с дедлайном `join`; набор на
  фейке содержит один тест с настоящими объектами; «невозможно/гарантировано» — только с воспроизведением.
- **Агенты не коммитят и не пушат** (в каждом брифе); коммиты — лидер, `Refs: plans/2026-10-18_camera-device-service/plan.md`.
- Перед стендом с камерой: IDMVS закрыт, VPN выключен, ПК `192.168.1.100/24`; стенд останавливать по PID; прибор отпускается ~10 с.

## Точки коммита (дерево зелёное на каждом коммите)

- Одна задача — один коммит, кроме **К4' = 4.2a + 4.2b + 4.3 + 4.4** (ревью R-c: хаб вне К4'): каждая проходит своё ревью, лидер делает ОДИН коммит
  после последнего APPROVED и прогона `medium` по `Services/hikvision_camera/tests`, `multiprocess_prototype/recipes/tests`,
  `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests`. Причина: между
  переименованием команд в плагине и переводом вкладки и хаба живой потребитель слал бы несуществующие команды, а тесты
  на моках остались бы зелёными.
- Хаб (4.6a–4.6d, P1) — после М2, отдельными коммитами: переименование команд плагина хаб не ломает (`cmd_hik_enum`
  импортирует `enum_devices` напрямую, ревью P2); вкладка перечисляет камеры командой плагина `list_devices`.
- До К4' работает старый плагин `hikvision` с правками 0.2 — на нём стенд MVS 0.5.
- 3.2 переводит `code_reader_sdk` одним коммитом: его команды уже общие, переименования нет.
- Откат любой точки — `git revert` одного коммита; флага миграции нет (совет 10 отклонён, `matrix.md`).

## Порядок с `robot-protocol-v2` T5.3

T5.3 (`plans/robot-protocol-v2/plan.md:293`, очередь владельца п.3) и 4.6b/4.6c/4.6d правят одни файлы: `Plugins/hub/device_hub/plugin.py`
(таблица `commands`) и `Services/device_hub/manager.py:_register_defaults`. Правило: один писатель за раз; 4.6a фиксирует
форму фабрики `factory(entry, proto, *, services)`; кто первым входит в `manager.py`, вводит форму, второй принимает.
Если T5.3 в работе — 4.6b/4.6c/4.6d ждут его коммита. Строка об этом — в связях обоих планов.

## Дефекты хаба -> задача, которая их закрывает

| Дефект | Где | Чем закрыт |
|---|---|---|
| F1 `connect()` -> `True` при отказе | `Services/device_hub/drivers/hikvision_driver.py:67-78` | 4.6b: драйвер снят с фабрики; инвариант `connect() == is_connected` — общий тест; `HikvisionDriver` — `xfail(strict)` |
| F2 `get/set_params` -> `AttributeError` | `hikvision_driver.py:143-159` | 4.6b: путь недостижим (фабрика `hikvision` -> `CameraMirrorDriver`); `read_params` — из зеркала |
| F-DH1 `_op_enum` читает `serial_number`/`ip_address` | `hikvision_driver.py:128` | 4.6b: путь недостижим; перечисление — `camera_list_devices` (4.6d) |
| F-DH2 `hik_release` с `device_id` = индекс `cv2` | `Plugins/sources/camera_service/plugin.py:259-262` | 4.6d: `hik_release` — no-op `ok` для любого `device_id` |

## Риски (механизм -> что делаем)

1. **H1 подтвердится** -> rest и перезахват — `close -> open` в потоке-владельце; обе ветки на фейке (2.2, 2.4); умолчание выбирают 6.2 и 0.5.
2. **`RegistersManager.subscribe` впервые на живом пути** (`git grep -n "\.subscribe(" -- Services Plugins multiprocess_framework/modules/process_module ':!*/tests/*'` -> только `state_proxy.subscribe`) -> не зовётся = дефект framework, `ESCALATION -> teamlead`, fix-forward; wiring-тест в 2.4.
3. **К4' большой** (4.2a 4 + 4.2b 5 + 4.3 6 + 4.4 5 = 20 файлов одним коммитом; ревью A16) -> ревью по задачам, общий прогон перед коммитом, откат одним `revert`.
4. **Фабрика форм не гасит поля** (`git grep -n "setEnabled\|setReadOnly\|readonly" -- multiprocess_prototype/frontend/forms/factory` -> 3 строки, ни одна не читает `meta.readonly`) -> 1.2 строит механизм; объём оценивает стадия 0.
5. **`test_letter_robot_sim_diff.py` красный от чужой правки** `letter_robot_sim.yaml`; 4.3 меняет его базу `hikvision_letter_robot.yaml` -> сверять список расхождений до/после.
6. **Два писателя хаба** (T5.3 и 4.6b/4.6c/4.6d) -> раздел выше.
7. **Две DLL вендоров в процессе `devices`** и перечисление при занятом приборе — не проверены -> опыт в 4.6b (DLL) и 0.5/6.2 (занятый прибор).
8. **Подписка хаба на `processes.*.state.plugins.**`** — объём дельт не измерен -> 4.6a выбирает узкий паттерн на событийные ключи, замер — 4.6c, сужение паттерна амендментом.

## Что оставлено открытым / ненадёжным

- H1–H6 не проверены (камер нет).
- `MV_CC_Initialize` и привязки `Get{Int,Enum,Bool}Value`, `SetEnumValueByString`, `SetCommandValue`, `RegisterExceptionCallBack` — `git grep -c -F "<имя>" -- Services/hikvision_camera` -> пусто на каждое (2026-10-18); экспорты DLL — 0.3.
- Показ `None` в спинбоксе не проверен — поэтому Р5 (флаг группы).
- Поток исполнения команд и колбэка `subscribe` — по чтению (`system_threads.py:81` -> `router_manager.py:1467`), не по запуску.
- `RouterReentrantRequestError` при `get` из команды хаба — из кода (`state_store_module/proxy/state_proxy.py:1506`), не воспроизведён.
- `sentrux check .` не запускался — первая проверка в 0.1.
- Ключи уровня плагина в `hikvision_inspect.yaml:60-72` (без `config:`) — путь в `ctx.config` не проверен; стадия 0 4.2.
- Бюджет — оценка, не замер.

- Хаб как источник настроек камер (вместо register'а процесса-владельца) — решение владельца 2026-10-18: план не меняется,
  зеркало только читает; вопрос оставлен открытым.
- Метрики пилота режима волн до W1 неизвестны; бюджет ~9M — оценка без замера.
