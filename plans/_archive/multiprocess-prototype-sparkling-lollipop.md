# Архитектурный аудит multiprocess_prototype — советы перед carve-out во фреймворк

## Context

Прототип и фреймворк развиваются параллельно; когда прототип дозреет до продакшена,
универсальные части планируется перенести в `multiprocess_framework`. Задача — оценить
текущую архитектуру прототипа, найти косяки/неправильные направления **сейчас** (пока всё
сырое и дёшево исправляется) и согласовать выводы с готовящимся планом
`plans/robot-calibration.md`.

Аудит проведён 2026-06-10 (2 Explore-агента + точечные проверки). Существующий план выноса —
`plans/prototype-carveout.md` (Этап 0 аудит → Этап 1 пилот SystemBuilder) — остаётся опорным;
этот документ его дополняет, не заменяет.

---

## Вердикт: направление ПРАВИЛЬНОЕ

Крупных «неправильных направлений» не обнаружено. Что подтверждено как здоровое:

1. **Слои `framework → Services → Plugins → prototype` соблюдены в основном коде** — обратных
   импортов нет (есть 3 файла-нарушителя в тестах, см. P0.1).
2. **domain/ + adapters/ — чистый изолированный слой**: 10 протоколов, frozen-entities,
   EventBus без Qt-зависимостей, AppServices как DI-контейнер. Это образцовая структура.
3. **Правило «≥2 потребителей» перед выносом domain/adapters** (из prototype-carveout.md) —
   верное. Не выносить ради выноса.
4. **Пилот SystemBuilder** ([backend/launch.py](multiprocess_prototype/backend/launch.py)) как
   forcing function carve-out-дисциплины — правильная первая цель: чистый шов, помечен в коде,
   зависит только от framework.
5. **Dict at Boundary** соблюдается (BlueprintAssembler, RecipeManager, stores-адаптеры).

Главный риск не в текущем коде, а в **переносе во фреймворк раньше стабилизации контрактов**
(см. P1.3 и P1.4: что именно «закостенеет» как framework-API).

---

## Находки и советы

### P0 — дёшево исправить сейчас (housekeeping, входит в этот план)

**P0.1 — Нарушение слоёв в тестах (3 файла).** Тесты нижних слоёв импортируют прототип:
- `multiprocess_framework/modules/frontend_module/tests/test_register_view_show_toggle.py:14-15`
- `multiprocess_framework/modules/frontend_module/tests/test_section_spec.py:219-225`
- `Services/auth/tests/test_role_update_handler.py:14`

Это подрывает сам carve-out: фреймворк, чьи тесты требуют прототип, не является
самостоятельным. **Совет:** перенести эти тесты в `multiprocess_prototype/**/tests/`
(они проверяют prototype-код: RegisterView, SettingsTab-секции, RoleUpdateHandler) и
расширить `.sentrux/rules.toml`, чтобы boundary-правила покрывали и `tests/`.

**P0.2 — Каталог `robot/` (untracked, сырцы с железа).** Содержит `pc_robot copy.py`,
`__pycache__/`, дубли universal/universal2. Это эталон для Фазы 0 robot-calibration —
терять нельзя, но в корне репо в таком виде он попадёт в qex/sentrux/grep. **Совет:**
закоммитить как референс в выделенное место (`docs/reference/robot/` или
`Services/robot_comm/reference/` при старте Фазы 0), удалить `pc_robot copy.py` и
`__pycache__`, добавить в исключения индексаторов.

**P0.3 — Судьба ActionBus.** По аудиту command-engine (P1.1, память проекта): ActionBus в
проде мёртв (0 потребителей), живой путь — только domain-dispatch
(CommandDispatcherOrchestrator). При этом пакет `frontend/actions/` (handlers, middleware,
undo/redo) продолжает существовать и числится «вторым движком». **Совет:** принять решение
до любого выноса GUI-частей — удалить пакет (git хранит) или письменно зафиксировать его
будущее в ADR. Мёртвый слой искажает оценку «что универсально». Заодно закрыть известную
RBAC-дыру field-edit (или явно принять как долг в ADR).

### P1 — сделать ДО carve-out соответствующих частей (советы, фиксируются как критерии)

**P1.1 — Framework-блокеры чинить до выноса, fix-forward.** Известные баги фреймворка
(из памяти проекта), которые после carve-out станут дороже:
- recipe-launch теряет `protected: true` → «Перезапустить» рестартит GUI-процесс;
- плагины без `register_schema` не получают live field-write (configure() кэширует, приёмника нет);
- graceful-stop: 5с-ханг при switch/shutdown (зона `stop_all_workers`/`put()`/`cv2.read()`).

Эти три — кандидаты в первые очереди работ, потому что они же ударят по robot-calibration
(вкладка калибровки шлёт round-trip команды, циклы start/stop при наладке на железе).

**P1.2 — Характеризационные тесты перед каждым переносом.** Для SystemBuilder-пилота (и
далее) — сначала golden-тесты на текущее поведение (`unwrap_recipe`, `merge_topologies`,
`normalize_blueprint` на реальных рецептах из `recipes/*.yaml`), потом перенос. Перенос без
них при «сыром» коде = молчаливые регрессии.

**P1.3 — Один канонический контракт топологии.** Сейчас два представления: typed
`domain.Topology/Project` (GUI) и blueprint-dict (`SystemBlueprint` Pydantic, backend), между
ними толстые мосты (TopologyBridge ~27KB, diff_engine). Это допустимо внутри приложения, но
во фреймворк должен уехать **только blueprint-dict контракт** (схема SystemBlueprint) как
граница; domain-модель — это GUI-глубина приложения. **Совет:** зафиксировать это в ADR при
Этапе 1 carve-out, чтобы не возникло соблазна тащить оба.

**P1.4 — Не «закостенить» full-replace.** Владельцем принято направление: live-применение
изменений **инкрементально per-process** (адресация процесс→воркер→плагин), а не full-replace.
`FullReplacePlanner` (backend/assembly/planner.py) — текущая реализация. **Совет:** при
выносе assembly во фреймворк интерфейс планировщика объявить как `TopologyPlanner` Protocol
(вход: current/target blueprint-dict; выход: список команд), где FullReplace — лишь первая
стратегия. Иначе full-replace станет публичным API фреймворка и инкрементальность будет ломать
контракт. Параллельно: `frontend/bridge/diff_engine.py` и `FullReplacePlanner` считают diff
топологий дважды — проверить на дубль и свести к одному вычислителю до выноса.

**P1.5 — Очередь кандидатов на вынос (уточнение prototype-carveout.md).**
Подтверждаю пилот SystemBuilder; следующими по готовности шва:

| # | Кандидат | Почему | Особенность |
|---|----------|--------|-------------|
| 1 | `SystemBuilder` + `load_topology_dict`/`merge_topologies`/`unwrap_recipe` | чистый шов, помечен в коде | пилот (Этап 1 carveout) |
| 2 | `GenericProcessApp` | на него ссылаются YAML-рецепты строкой `process_class: multiprocess_prototype.generic_process_app...` — путь класса утёк в данные пользователей и станет несовместимым при любом переезде | переносить РАНО = правильно: чем позже, тем больше рецептов мигрировать; оставить alias-shim в прототипе |
| 3 | `BlueprintAssembler` + `normalize` | carve-out-ready, зависит только от framework | ехать вместе с №1 или сразу после |
| 4 | `orchestrator.py` (ProcessManagerProcessApp: topology engine + observability watcher) | generic-логика | после №1-3, вместе с TopologyPlanner Protocol (P1.4) |
| 5 | Ядро `EventBus` (без app-событий) | чистый, generic | events.py (ProcessAdded и т.д.) остаются в приложении |
| — | domain/adapters, frontend, graph-editor, forms | 1 потребитель | ждать 2-е приложение (правило carveout-плана) |

### P2 — согласование с robot-calibration (советы в готовящийся план)

План `plans/robot-calibration.md` качественный (модель владельца соединения, namespace команд,
JPEG-snapshot — всё продумано). Три места, где он пересекается с «лучшей архитектурой»:

**P2.1 — `runtime.py` holder делать сразу generic-формы.** Process-local holder живого
соединения — потребность не только робота (камеры Hikvision, Modbus-устройства — та же
модель «владелец публикует, потребители берут»). **Совет:** внутри `Services/robot_comm/runtime.py`
не зашивать робот-специфику в механику (holder = `set/get/clear + Lock` над generic T);
когда появится 2-й потребитель — вынести шаблон в framework как `process_local_handle`.
В плане это уже почти так — просто зафиксировать как осознанный прецедент.

**P2.2 — Namespace команд `{plugin_name}.{command}` (P0.2 плана) реализовать на уровне
фреймворка, не в плагине.** Это первый реальный шаг к принятому направлению «иерархическая
адресация процесс→воркер→плагин». Если namespace сделать ad-hoc внутри calibration-плагина,
появится второй способ адресации. **Совет:** правка в `_auto_register_commands`
(framework, fix-forward) + короткий ADR «команды плагинов регистрируются с префиксом
plugin_name» — тогда robot-calibration просто пользуется штатным механизмом.

**P2.3 — Дискретный snapshot (JPEG по запросу, P1.4 плана) — будущий generic-util.**
Любая инспекция захочет «кадр по запросу через команду» (не поток через SHM). В срезе пусть
живёт в плагине calibration, но кодек/контракт (`cv2.imencode` + лимит размера + формат
ответа) оформить отдельной чистой функцией, чтобы потом переехала без переписывания.

---

## Что НЕ делать (анти-советы)

- **Не выносить domain/adapters сейчас** — 1 потребитель, шов дорогой, ценность нулевая до
  2-го приложения (подтверждаю решение carveout-плана).
- **Не начинать «большой рефакторинг» фронтенда** — 341 файл app-specific, направление
  product-over-engine (решение владельца 2026-05-29) действует.
- **Не плодить вторую pymodbus-обёртку без дедлайна** — в robot-calibration это уже учтено
  (P1.1 плана, миграция на `ModbusDevice.transaction` в Фазе 5) — проследить.

---

## Действия по этому плану (исполняемая часть)

Только P0 — дешёвый housekeeping; P1/P2 — советы, уходящие в существующие планы:

1. **P0.1** Перенести 3 теста-нарушителя в `multiprocess_prototype/`:
   - `test_register_view_show_toggle.py` → `multiprocess_prototype/frontend/forms/tests/`
   - `test_section_spec.py` (только prototype-часть, строки 219-225; остальное остаётся) →
     prototype-импорты заменить/перенести в `multiprocess_prototype/frontend/widgets/tabs/settings/tests/`
   - `Services/auth/tests/test_role_update_handler.py` →
     `multiprocess_prototype/frontend/actions/tests/` (или удалить вместе с ActionBus по P0.3)
   - Расширить `.sentrux/rules.toml` на tests/ + прогнать `mcp__sentrux__check_rules`.
2. **P0.2** Привести в порядок `robot/`: удалить `pc_robot copy.py` и `__pycache__/`,
   переместить в `docs/reference/robot/` (или дождаться Фазы 0 robot-calibration и положить
   в `Services/robot_comm/reference/`), закоммитить.
3. **P0.3** Подготовить короткий ADR-черновик «судьба ActionBus» с двумя вариантами
   (удалить / законсервировать) — решение за владельцем; ничего не удалять без его выбора.
4. Дополнить `plans/prototype-carveout.md` разделом «Очередь кандидатов» (таблица P1.5)
   и критериями P1.2-P1.4 (характеризационные тесты, единый контракт топологии,
   TopologyPlanner Protocol).
5. Дополнить `plans/robot-calibration.md` тремя заметками P2.1-P2.3 (generic holder,
   namespace на уровне фреймворка, snapshot-util как чистая функция).
6. Dual-save: копия этого документа → `plans/architecture-audit-2026-06.md`.

Коммиты: `docs(plans):` / `test(layers):` с trailers `Why:`/`Layer:` и
`Refs: plans/architecture-audit-2026-06.md`.

## Верификация

- `python scripts/validate.py` и `python scripts/run_framework_tests.py` из корня — зелёные
  после переноса тестов.
- `mcp__sentrux__check_rules` — 0 нарушений boundary-правил (включая tests/).
- `pytest multiprocess_prototype/...` для перенесённых тестов — проходят на новом месте.
- Перенесённый `robot/` не индексируется qex/sentrux (проверить исключения).
