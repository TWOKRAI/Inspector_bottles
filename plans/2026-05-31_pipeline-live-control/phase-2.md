# Этап 2 — Live-параметры по адресу процесс→плагин (через RouterManager)

> **ПЕРЕПИСАН 2026-05-31** под видение владельца (инкрементальный per-process live) и
> курс «всё общение через RouterManager + каналы». Старый вариант (оживление
> `apply_topology_diff` / full-replace) **отвергнут** — он моргал всей цепочкой.
> Архив старого подхода — в git-истории этого файла.

**Цель этапа:** изменение поля плагина в редакторе (inspector) применяется к **живому**
процессу-владельцу **по адресу процесс→плагин→поле**, без рестарта процесса и без
моргания соседей. Это P3 `transport-router-hub` (granular live по адресу) в применении
к pipeline-параметрам.

**Scope (решение владельца 2026-05-31):** **только параметры**. Add/remove ноды
(инкрементальная мутация живой цепочки плагинов) — отдельный Этап 3 (новая
framework-команда мутации chain; здесь НЕ трогаем).

**Модель адреса (решение владельца):** «воркер» в адресе = сам процесс-исполнитель
(все плагины процесса крутятся ОДНОЙ цепочкой `PipelineExecutor`, не по воркеру на
плагин). Адрес сообщения: **процесс + плагин (register) + поле**. Будущее `proc.worker`
— транспорт уже готов (`_deliver_by_targets` по `address[0]`, `_worker_handlers`), но
здесь достаточно `targets=[process]` + плагин в payload.

**Сложность:** Middle+ · **Риск:** низкий-средний (контракт ключей, резолв плагина).

---

## Корневая находка (investigation 2026-05-31)

Живой field-write GUI→процесс **сейчас не работает**:
- `app.py::_on_plugin_config_changed` зовёт только `registers_manager.set_value(...)` →
  обновляет GUI-rm + виджеты, но IPC НЕ уходит.
- `RegistersManager._send_callback` ставит **только** `FrontendRegistersBridge`
  (`frontend_module/core/registers_bridge.py:91`), который **в v3-прототипе не
  инстанцируется** → `send_callback=None` → ветка IPC в `set_field_value` мертва.
- COMMUNICATION_MAP это и фиксирует («GUI-sender мёртв»; контракт ключей
  `register_name` ≠ `register`).

Приёмник **жив**: `PluginOrchestrator._on_register_update` (handler `register_update`)
→ `rm.set_field_value(register, field, value)` → применяет к регистру плагина
(регистры ключуются по `plugin.name`). Транспорт `register_update` идёт штатно через
RouterManager (`router.register_message_handler`).

**Вывод:** не возрождать `FrontendRegistersBridge`. Послать IPC напрямую из listener'а
через уже живой `CommandSender.send_command` → RouterManager → `_on_register_update`.
Адрес плагина = имя регистра (`plugin_name`), резолвится из editor-топологии по
`(process_name, plugin_index)`. `PluginConfigChanged` уже несёт `plugin_index`.

---

### Task 2.1 — Резолв плагина: (process, plugin_index) → register_name

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** чистая функция-резолвер «имя процесса + индекс плагина → имя регистра плагина»
(= `plugin_name` плагина по индексу в editor-топологии). Нужна listener'у Task 2.2.

**Context:** Внутри процесса `PluginOrchestrator` ключует регистры по `plugin.name`
(`_init_registers`: `schemas[plugin.name]`), а `plugin.name` = `plugin_name` из YAML
(`_load_plugin`: `instance.name = plugin_name`). В редакторе нода=плагин,
`node_id={proc}.{plugin}` (memory `project_pipeline_node_plugin_containers`). Источник
истины топологии — `services.topology.load().to_dict()` → `processes[].plugins[]`.

**Files:**
- `multiprocess_prototype/frontend/bridge/` — новый тонкий хелпер (или метод
  на существующем мосте) `resolve_plugin_register(topology, process_name, plugin_index) -> str | None`.
  Dict at Boundary: работает с dict-топологией.

**Steps:**
1. Найти процесс по `process_name` в `topology["processes"]`.
2. Взять `plugins[plugin_index].plugin_name` (учесть dict и объект).
3. Вернуть `plugin_name` (= register_name) или `None` (процесс/индекс не найден →
   fallback на `process_name` для legacy 1:1, с логом).

**Acceptance criteria:**
- [ ] Возвращает `plugin_name` для валидного `(process, index)`
- [ ] Out-of-range / неизвестный процесс → `None` (или явный fallback с логом), без исключения
- [ ] Unit-тест на dict-топологию (multi-plugin процесс, 1:1 процесс, отсутствующий)
- [ ] `python scripts/run_framework_tests.py` зелёный

**Out of scope:** изменение domain-событий; адрес `proc.worker` (транспорт готов, не нужен здесь).
**Module contract:** lite (одна функция)

---

### Task 2.2 — Оживить live field-write: PluginConfigChanged → register_update IPC

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `_on_plugin_config_changed` помимо GUI-rm sync **отправляет IPC** в
процесс-владелец через `CommandSender` → RouterManager → `_on_register_update`,
адресуя конкретный плагин (`register` = результат Task 2.1).

**Context:** listener сейчас глотает изменение (только GUI-rm). Контракт ключей: приёмник
`_on_register_update` читает `data = {register, field, value}`
(`plugin_orchestrator.py:296-299`). `CommandSender.send_command(target, command, args)`
шлёт `{type:"command", command, data_type:command, targets:[target], data:args}`.

**ВАЖНО — сверить дисптач-ключ:** handler зарегистрирован
`router.register_message_handler("register_update", ...)` (EXACT_MATCH). Перед кодом —
подтвердить, по какому полю `message_dispatcher` матчит ключ (`command`/`data_type`/`type`),
чтобы сообщение реально дошло до handler (иначе путь снова «мёртв»). См.
`router_module/.../message_dispatcher`. Если ключ ≠ command — слать с правильным полем.

**Files:**
- `multiprocess_prototype/frontend/app.py` (~489-503 `_on_plugin_config_changed`):
  после `registers_manager.set_value(...)` — резолв плагина (Task 2.1) + отправка IPC.
  `set_value` оставить (GUI-rm/виджеты sync), но **с правильным register_name** (плагин,
  не process_name) — иначе для multi-plugin процессов GUI-rm бьёт не туда.
- `multiprocess_prototype/frontend/bridge/command_sender.py` — НЕ менять (reuse `send_command`).

**Steps:**
1. В listener: `register = resolve_plugin_register(topology, process_name, plugin_index)`
   (топологию взять из доступного в app.py `topology_store`/`services.topology`).
2. `registers_manager.set_value(register or process_name, field, value)` (GUI-side).
3. `command_sender.send_command(process_name, "register_update", {"register": register or process_name, "field": field, "value": value})` —
   или с дисптач-ключом, подтверждённым в Context.
4. Debounce slider-burst: рассмотреть `send_field_command(debounce_ms=...)` вместо
   `send_command`, чтобы не залить IPC при перетаскивании слайдера (coalescing уже в
   `CommandSender._pending`). Совместить с domain `coalesce_key`.
5. Логировать отправку на DEBUG (тише терминал — memory `feedback_logger_error_stats_managers`).

**Acceptance criteria:**
- [ ] qt-mcp smoke: запустить proto, изменить поле плагина в inspector Pipeline →
      **эффект меняется на дисплее live**, процесс НЕ перезапущен (qt_snapshot + лог процесса)
- [ ] Multi-plugin процесс: правка поля второго плагина уходит в ЕГО регистр (не первого)
- [ ] IPC идёт через `CommandSender`→RouterManager (не FrontendRegistersBridge, не set_send_callback)
- [ ] Slider-перетаскивание не заваливает терминал/IPC (debounce/coalesce работает)
- [ ] `python scripts/run_framework_tests.py` зелёный; нет регрессий field-edit тестов

**Out of scope:** add/remove ноды (Этап 3); адрес `proc.worker`; rollback/ack от процесса
(fire-and-forget, как Этап 1).
**Edge cases:** процесс ещё не запущен (IPC уходит в никуда — graceful, лог); рецепт не
запущен (нет живых процессов — listener всё равно безопасен); поле без routing
(stateless) — слать всё равно, приёмник проигнорирует неизвестный регистр/поле.
**Dependencies:** Task 2.1. Этап 1 (CommandSender/proxy транспорт).
**Module contract:** impl-only

---

### Task 2.3 — Smoke + memory + DECISIONS

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** зафиксировать живой путь и решение.

**Steps:**
1. qt-mcp smoke по acceptance Task 2.2 (обязательно — memory `feedback_qt_mcp_smoke_verification`).
2. Обновить memory `project_pipeline_live_control_stage1` → Этап 2 (поправить ложную
   заметку «rm.set_value → IPC»: IPC был мёртв, теперь оживлён через RouterManager).
3. Обновить COMMUNICATION_MAP.md строку field-write (alive через CommandSender, а не set_send_callback).
4. ADR (локальный или global): «live field-write идёт через RouterManager command, не
   FrontendRegistersBridge; адрес плагина = register_name из топологии».

**Acceptance criteria:**
- [ ] memory + COMMUNICATION_MAP отражают реальность
- [ ] ADR записан, `python -m scripts.sync` при правке DECISIONS
**Module contract:** docs-only

---

## Связь с другими планами

- **transport-router-hub P3** (`plans/2026-05-31_transport-router-hub/`): этот Этап 2 —
  частный случай P3 (granular live по адресу). Транспорт P0-P2 (адресация, `_worker_handlers`)
  уже на ветке и переиспользуется.
- **Этап 3** (add/remove ноды live): новая framework-команда мутации живой цепочки
  плагинов (`PluginOrchestrator`/`PipelineExecutor` на границе итерации) — отдельный заход.
