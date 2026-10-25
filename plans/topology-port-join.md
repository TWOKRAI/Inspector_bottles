# topology-port-join — вход плагина объявляет участие в join отдельно от optional (C-16 + C-17 + C-22 + C-25 + C-28)

**Статус:** активный · **Ветка:** `fix/c16-collector` (C16.1, влита `09a925a4b`), `fix/c22-collector-modeless` (C22.1), `fix/c25-c28-blueprint` (C25.1, C28.1) · **Полоса:** Д (inspector-bottles-66; с 2026-10-25 — inspector-bottles-a3)
**Источник:** реестр `plans/queue/defects.md`, строки C-16 и C-17; расследование `docs/reports/2026-10-21_defects_C-16.md`.
**Стадия 0:** reviewer (Opus), 2 итерации — 13 + 5 + 4 правки внесены дословно, стадия закрыта (2026-10-21).

## Контекст

`7e1640c97` (2026-10-15) сделал вход `overlay_draw.overlay` необязательным (`optional=True`), потому что в qr-рецептах `overlay_draw` рисует кадр без оверлея. `SystemBlueprint.infer_missing_collectors` пропускает провода в optional-порты (`blueprint.py:511`, ADR-PMM-017 п.1). Поэтому у `draw` в `hikvision_letter_robot` остаётся один источник, join не выводится, и сборка даёт `collector: {}`. В рантайме это fanin вместо join кадра с оверлеем. На main красные `test_build_characterization[hikvision_letter_robot]` и `test_join_collector_from_wires.py` (2 failed).

Корень: `Port.optional` перегружен. Он значит «может быть не подключён» (так сказано в его описании) и при этом неявно «не участвует в join».

## Решения владельца (2026-10-21, дословно)

1. Поле контракта порта — **`Port.join: bool | None`** (владелец 2026-10-21).
2. Умолчание — **`None` = `not optional`**: все нынешние плагины ведут себя как сейчас; явно `join=True` ставит только `overlay_draw.overlay` (владелец 2026-10-21).
3. **`metadata.inspector` — deprecated:** 4 рецепта переводятся на `collector: {timeout_sec: 0.25}` без `mode` (join выводится из портов); чтение `metadata.inspector` остаётся с предупреждением в лог; **C-17 — громкая ошибка `check()`**, если в `metadata` задан `mode: join`, а join не выведен (владелец 2026-10-21).
4. Общее требование владельца: «универсально в рецептах и плагинах на будущее». Плагин объявляет семантику входа один раз, рецепт не задаёт `mode`/`inputs` вручную.

## Граница (подтверждена координатором inspector-bottles-7f)

Можно править только:
- `multiprocess_framework/modules/process_module/plugins/port.py`;
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py`;
- раздел ADR-PMM-017 в `multiprocess_framework/modules/process_manager_module/DECISIONS.md`;
- `Plugins/render/overlay_draw/**`;
- рецепты `multiprocess_prototype/recipes/{hikvision_letter_robot,letter_angle_inspect,letter_robot_sim,dataset_circle_capture,line_filter_inspect}.yaml`;
- `multiprocess_framework/modules/process_module/commands/builtin_commands.py` — только интроспекция портов (~:1003–1007);
- `multiprocess_framework/modules/process_module/tests/test_blueprint_wire_collector.py` — только docstring :622–655 и тесты «тихого fanin»;
- новые тесты (пути — в Files).

Остальное в `process_manager_module/**` и `process_module/**` — полоса Ф. Нужен файл вне списка — стоп, вопрос лиду.

### Task C16.1 — `Port.join` + вывод join по нему + громкая ошибка C-17 + перевод 5 рецептов

**Level:** Senior+ (публичный контракт framework и вывод топологии)
**Assignee:** developer (Sonnet), дизайн задан здесь; стадия 0 на Opus пройдена
**Goal:** вход плагина объявляет участие в join полем `Port.join`; вывод join считает подключённые входы по этому полю, а не по `optional`; противоречие между `metadata` и выводом даёт громкую ошибку, а не тихий fanin.
**Module contract:** lite. В docstring `Port` — строки Pre/Post/Invariants для `join` и `effective_join`; контракт-тест `test_port_join.py`.

**DESIGN:**
1. **`port.py::Port`.** Добавить поле `join: Annotated[bool | None, FieldMeta("Участвует в join", info="True — подключённый вход коррелируется с primary по seq_id; None — как not optional")] = None` и `@property effective_join -> bool`: `self.join if self.join is not None else not self.optional`. Описание `optional` уточнить: только подключение.
   - Сериализация: `Port.model_dump()` несёт ключ `join`, `Port.model_validate(d)` его читает; dict без `join` даёт `None`.
2. **`blueprint.py`, подсчёт join-источников.** В чистый helper `_joining_sources(self) -> dict[str, dict[str, set[str]]]` (процесс → источник → src-порты) вынести `:483–515` (вместе с `plugin_class_by_addr`). В нём `if tgt_port is None or not tgt_port.effective_join: continue`. Его вызывают и `infer_missing_collectors`, и `check`. В `:517–571` логику не менять; единственная вставка — предупреждение из п.3.
3. **Предупреждение deprecated.** В `infer_missing_collectors`, ДО escape-hatch и порога `< 2`: если `metadata.collector or metadata.inspector` — непустой dict, вызвать `logger.warning` (модульный `logger = get_std_logger("blueprint")`, `blueprint.py:45`) один раз на процесс за один вызов `infer`.
   - Текст называет процесс и штатный ключ `collector`; значение `metadata` в текст не попадает.
   - Глобального множества «уже предупреждён» не заводить; `check()` не предупреждает.
4. **C-17 в `check()` (`blueprint.py:772–889`), результат не зависит от того, вызывался ли `infer`.**
   - Эффективный mode = `mode` явного collector (typed `proc.collector` или `extras`, обе формы ключа — `collector`/`inspector`), если он задан; иначе `"join"` при ≥ 2 источниках из `_joining_sources()`; иначе нет. После `infer` `proc.collector.mode == "join"` ровно при ≥ 2 источниках, поэтому чтение typed-поля даёт тот же ответ, что и без `infer`.
   - Ошибка, если `(metadata.collector or metadata.inspector).get("mode") == "join"` и эффективный mode ≠ `"join"`. Явный `{mode: fanin}` при `metadata` mode=join — тоже ошибка.
   - Текст: `Процесс '<имя>': metadata.<ключ>.mode=join, но join не применён (join-источников: <n>, нужно ≥ 2, или явный collector задаёт иной mode). Штатно: удали metadata.<ключ>; вход, участвующий в join, объявляет Port(join=True); тонкая настройка — collector: {timeout_sec: …} без mode`. Значений из `metadata` в тексте нет.
5. **`Plugins/render/overlay_draw/plugin.py:39`.** `Port(name="overlay", ..., optional=True, join=True, ...)`. В README и STATUS — одна строка про `join=True`.
6. **Рецепты, 8 блоков `metadata.inspector`.** Это `draw` + `recog` в `hikvision_letter_robot` и `letter_robot_sim`; `draw` + `crop` в `letter_angle_inspect` и `dataset_circle_capture`; во всех `timeout_sec: 0.25`.
   - Каждый блок удалить и задать process-level `collector: {timeout_sec: 0.25}` без `mode`. Пустой `metadata:` удалить.
   - `line_filter_inspect.yaml`, процесс `draw`: process-level `inspector: {...}` заменить на `collector: {timeout_sec: 0.25}`.
   - Обновить шапку-комментарий `dataset_circle_capture.yaml:19–21` и комментарий `line_filter_inspect.yaml:11`.
7. **ADR-PMM-017.** Дописать п.7 (дата 2026-10-21, Refs этот план): `Port.join` и `effective_join`, умолчание, deprecated `metadata`, громкая ошибка C-17.
   - П.7 прямо называет частичную отмену отклонённой альтернативы «ошибка валидации вместо тихой деградации» для случая `metadata.mode=join`. К этой альтернативе и к п.1, п.5 — ссылка на п.7, сами пункты не переписывать.
   - В FieldMeta `ProcessConfig.metadata` (`blueprint.py:216`, «Единственный потребитель») добавить `check()` (C-17) и пометку deprecated.
   - Затем `python -m scripts.sync`.
8. **`builtin_commands.py`, команда `catalog.plugins` (`_cmd_catalog_plugins`, `:955`).** В оба генератора словаря порта (`:1002–1005` входы, `:1006–1009` выходы) добавить `"join": p.join` после `"optional"`. `introspect.plugins` не трогать (байтовый contract-тест, `:962–964`). `rev` меняется — так и должно быть. Карточку capabilities (`:866–870`) и остальной файл не трогать — полоса Ф читает его в 1.9b (граница — координатор 2026-10-21).
9. **`test_blueprint_wire_collector.py`.** Переписать один тест — `test_legacy_metadata_inspector_on_optional_ports_degrades_to_fanin` (`:622–655`). `assert layout.collector == {}` оставить. Добавить вызов `bp.check()` до и после `infer`: оба раза ровно одна ошибка, в тексте `'layout'` и `metadata.collector.mode=join`. Docstring — ссылка на ADR-PMM-017 п.7. Тесты `:538`, `:578`, `:591` не трогать.

**Files:**
- граница выше;
- `multiprocess_framework/modules/process_module/plugins/tests/test_port_join.py` (рядом с `test_port_validate_items.py`);
- `multiprocess_framework/modules/process_manager_module/tests/test_infer_join_by_port.py`;
- `multiprocess_prototype/backend/tests/test_recipes_join_contract.py` (A4, A9);
- `Plugins/render/overlay_draw/tests/test_overlay_port_join_catalog.py` (A11): зарегистрировать настоящий `OverlayDrawPlugin`, вызвать настоящий `BuiltinCommands(MockProcessServices(name=…))._cmd_catalog_plugins()` — как в `registers_module/tests/test_field_info_codec_hazards.py:101–119`; реестр снимать и восстанавливать, как в `test_blueprint_wire_collector.py:340`.

**Acceptance criteria:**
- [ ] **A1.** Таблица `(optional, join) → effective_join`: `(F,None)→T`, `(T,None)→F`, `(T,T)→T`, `(F,F)→F`, `(F,T)→T`, `(T,F)→F`.
- [ ] **A2.** Процесс P: вход `frame` (обязательный) от S1 и вход `overlay` (`optional=True, join=True`) от S2. Ожидается `P.collector == {"mode":"join","inputs":["frame","overlay"],"primary":"frame"}`.
  - Без провода S2: `check() == []` и `P.collector == {}`.
  - Обязательный вход с `join=False` от S2: join нет.
  - Фейковые плагины — через снимок и восстановление реестра, как в `test_blueprint_wire_collector.py:340`.
  - Выходной порт S1 называется `frame`, выходной порт S2 — `overlay` (тег = имя source-порта, `blueprint.py:542`).
- [ ] **A3.** `Port.model_validate(Port(name="o", join=X).model_dump()).join == X` для X ∈ {True, False, None}; `Port.model_validate({"name": "o"}).join is None`.
- [ ] **A4.** Обратная совместимость, именованный тест. Значения «до» сняты внешним скриптом сборки на main `aad763838` (стадия 0), в тесте — литералы.
  - До: непустой collector только у `dataset_circle_capture.crop`, `hikvision_letter_robot.recog`, `letter_angle_inspect.crop`, `letter_robot_sim.recog`, `line_filter_inspect.draw` = J и у `region_pipeline.stitcher = {inputs:[frame,region], mode:join, primary:frame}`; у остальных процессов 21 собираемого рецепта — `{}`.
  - После: то же, плюс `draw` = J в `hikvision_letter_robot`, `letter_angle_inspect`, `letter_robot_sim`, `dataset_circle_capture`.
  - J = `{"inputs":["frame","overlay"],"mode":"join","primary":"frame","timeout_sec":0.25}`.
  - `modbus_demo` и `robot_demo` исключены по имени: на main не собираются, SystemExit 1, это не C-16.
- [ ] **A5.** `hikvision_letter_robot`: `draw.collector == J` и `recog.collector == J` (литералы).
- [ ] **A6.** Golden-снимки `phone_sketch` и `hikvision_letter_robot` зелёные без регенерации (`git diff --stat` по `snapshots/` пуст); `test_join_collector_from_wires.py` 5/5.
- [ ] **A7.** C-17: blueprint с `metadata.inspector.mode: join` у процесса с одним join-источником → в `check()` ошибка с именем процесса. Тот же blueprint с двумя источниками → ошибки нет. Явный `collector: {mode: fanin}` при `metadata` mode=join → ошибка. Каждый случай проверить дважды — без `infer` и после `infer`, списки ошибок одинаковые.
- [ ] **A8.** Предупреждение: перехват через `monkeypatch.setattr(StdLoggerFacade, "warning", …)`, как в `process_module/tests/test_blueprint_extras.py:164–168`. Два процесса, `metadata` только у одного → ровно 1 запись с его именем; без `metadata` → 0 записей; `timeout_sec` подмешан.
- [ ] **A9.** Ни один рецепт в `multiprocess_prototype/recipes/` не содержит process-level `inspector`, `metadata.inspector` или `metadata.collector`. Ни один `collector` в рецептах не содержит `mode`, `inputs` или `primary`.
- [ ] **A11.** В ответе `catalog.plugins` для `overlay_draw`: вход `overlay` → `"join": True`, вход `frame` → `"join": None`, выход `frame` → `"join": None`; ключи `name`, `dtype`, `optional`, `shape` — как на main (литералы).
- [ ] **A10.** qr-рецепты (`qr_reader_sdk_demo`, `qr_reader_sdk_dual_demo`, `qr_reader_sdk_dual_selftrigger`) собираются и проходят `check()`, как на main: неподключённый `overlay` — не ошибка.

**REDS до правки src** (пишет независимый tester вслепую, в worktree на коммите плана): A1–A3, A7, A8 красные; A2 частично; A4 «после» и A5, A6 красные; A9 красный (рецепты); A11 красный; переписанный тест DESIGN 9 красный (C-17 ещё нет); пишет tester.

**Break-injection лида (после реализации):**
- в `_joining_sources` вернуть `tgt_port.optional` вместо `effective_join` → красные A2, A5 (`draw`), A6;
- заменить `effective_join` на `join` → красные A2, A4 (`crop`/`recog`/`draw`), A5 (`draw` и `recog`), A6;
- убрать C-17 → красные A7 и `test_legacy_metadata_inspector_on_optional_ports_degrades_to_fanin`;
- убрать `"join"` из словаря `catalog.plugins` → красный A11;
- убрать предупреждение → красный A8.

**Handoff:** tester (REDS вслепую) → developer (реализация по красным) → лид (инъекции) → reviewer ветки (Opus).
**Gate:** pre_report_gate зелёный + pytest радиуса (ниже) + `sentrux check .`.
**Радиус pytest:**
- `multiprocess_framework/modules/process_module/plugins/tests`;
- `multiprocess_framework/modules/process_module/tests/test_blueprint_wire_collector.py`;
- `multiprocess_framework/modules/process_manager_module/tests`;
- `multiprocess_prototype/backend/tests`;
- `multiprocess_prototype/backend/topology/tests`;
- `multiprocess_prototype/backend/assembly/tests`;
- `Plugins/render/overlay_draw/tests`.

**Out of scope:**
- порог `≥ 2` источников и теги (ADR-PMM-017 п.3, п.4, п.6);
- `collector_registry.py`, домен-entity GUI, `builtin_commands.py` вне интроспекции портов, `PortSpec`;
- другие плагины: их `join` остаётся `None`;
- регенерация любых снимков;
- остальные тесты `test_blueprint_wire_collector.py` (полоса Ф).

**Перед слиянием:** framework suite (heavy, окно у координатора), `scripts/validate.py`, радиус выше; ревью ветки на Opus.

**Открыто (для владельца, не в этой задаче):** `collector: {timeout_sec}` без `mode` у процесса, где join не вывелся (например, удалили провод), молча даёт fanin с таймаутом. → **Решено владельцем, Task C22.1 ниже.**

---

## Фаза C-22 — `collector` без `mode` при невыведенном join (2026-10-21)

**Источник:** `plans/queue/defects.md`, строка C-22; handoff `docs/handoffs/2026-10-21_lane-D-C16-C13.md`.
**Стадия 0:** reviewer (Sonnet), итерации 1–2 — 15 правок внесены дословно, APPROVED (2026-10-21).

**Решение владельца (2026-10-21, ~11:50, «да» на формулировку):** `collector` без `mode` = тонкая настройка выведенного join; join не выведен — ошибка `check()` с подсказкой; настройка fanin — только с явным `mode: fanin`. «Не забываем что рецепты у нас универсальная вещь» → правило во framework, действует для рецептов любого приложения.

**Граница (координатор inspector-bottles-7f, 2026-10-21):** `multiprocess_framework/modules/process_manager_module/topology/blueprint.py`; раздел ADR-PMM-017 в `process_manager_module/DECISIONS.md`; `multiprocess_framework/modules/process_module/tests/test_blueprint_wire_collector.py`; новые тесты (Files). Рецепты — только если стадия 0 скажет, и сначала вопрос координатору (стадия 0: рецепты не нужны). Полоса Ф (1.9m) правит `process_module/{process_module.py, core/process_managers.py, types.py, process_launch_config.py}` и `builtin_commands.py` — не трогать. `multiprocess_prototype/backend/tests/test_recipes_join_contract.py` правит Р2 — не трогать.

### Task C22.1 — громкая ошибка `check()` для `collector` без `mode` при невыведенном join

**Level:** Middle (Sonnet) — правка ограничена, по образцу C-17
**Assignee:** developer (Sonnet); стадия 0 — reviewer (Sonnet)
**Goal:** рецепт, где `collector` без `mode` стоит у процесса без выведенного join, не проходит `check()`; тонкая настройка больше не теряется молча.
**Module contract:** не требуется — нового публичного модуля и интерфейса нет; приватные `_explicit_collector` и `_modeless_collector_errors`; изменение поведения `check()` фиксирует ADR-PMM-017 п.8.

**DESIGN:**
1. **Общий helper явной секции.** `_explicit_collector(proc) -> tuple[str, dict]` (модульная функция рядом с `_legacy_metadata_section`, `blueprint.py:1063`): `(ключ, секция)`; ключ — `collector` (typed `proc.collector` или `extras.collector`) либо `inspector` (`extras.inspector`); порядок `proc.collector or extras.collector or extras.inspector`; секции нет или она не dict — `("", {})`. Обе точки (`infer` `:542–548`, `_metadata_join_errors` `:939–945`) перевести на helper; переменную `extras_bag` в `infer` оставить — она нужна в `:591` (`shadow_keys`). Process-level `inspector:` из рецепта к проверке уже typed `collector` (`_accept_legacy_collector_key`, `:241–246`; проверено: `ProcessConfig(inspector={'timeout_sec': 0.25}).collector == {'timeout_sec': 0.25}`, extras пуст), поэтому в тексте будет `collector`; `inspector` в тексте — только из `extras.inspector`.
2. **Новая проверка `_modeless_collector_errors(self) -> list[str]`**, вызов в `check()` сразу после `_metadata_join_errors()`.
   - `joining = self._joining_sources()` — один раз на вызов.
   - Для каждого процесса: `key, explicit = _explicit_collector(proc)`. Ошибка, если `explicit` непуст, `explicit.get("mode")` ложно (нет ключа, `None`, `""` — так же, как escape-hatch в `infer`), и `len(joining.get(proc.process_name, {})) < 2`.
   - Результат не зависит от `infer`: `infer` меняет секцию только при ≥ 2 источниках (тогда ставит `mode: join` → ошибки нет и до, и после); при < 2 секцию не трогает.
   - Проверка живёт в `check()`, не в `check_structure()`: тот намеренно не зависит от PluginRegistry (`blueprint.py:743–771`), а `_joining_sources` зависит.
   - Одна ошибка на процесс. Если у процесса сработал и C-17, обе ошибки остаются: они называют разные поля рецепта.
   - Текст (ключ — из helper; ключи секции — `sorted(str(k) for k in секция)`, через `, `; значений нет):
     `Процесс '<имя>': <ключ> без mode (ключи: <k1, k2>) — тонкая настройка выведенного join, но join не выведен (join-источников: <n>, нужно ≥ 2). Штатно: вход, участвующий в join, объявляет Port(join=True) и подключён проводом; настройка fanin — <ключ>: {mode: fanin, …}; иначе удали <ключ>`.
   - Подсказку C-17 (`blueprint.py:953–954`) согласовать: конец строки заменить на `тонкая настройка — collector: {{timeout_sec: …}} без mode (только при ≥ 2 join-источниках, иначе C-22)`. Этот текст ни один тест не проверяет (`git grep -F "тонкая настройка — collector"` → только `blueprint.py:954`).
3. **Docstring и FieldMeta.** Docstring `check()` (`:799–802`, сейчас пункты 1–4) — добавить пункты: «5. `metadata.<ключ>.mode=join` при невыведенном join — ошибка (C-17); 6. `collector` без mode при невыведенном join — ошибка (C-22)». Docstring `infer_missing_collectors`, абзац о явной секции (`:522–523`) — фраза: «Явный `collector` без `mode` — тонкая настройка: при ≥ 2 join-источниках применяется, при меньшем числе `check()` даёт ошибку (C-22).» FieldMeta `ProcessConfig.collector` (`:169–176`) — одна фраза о правиле.
4. **ADR-PMM-017, п.8** (дата 2026-10-21, Refs этот план): правило владельца дословно; эффективный режим — тот же, что в п.7; `metadata` без `mode` (deprecated) правило НЕ задевает. Ссылка из п.7 на п.8 — одна строка.
   - П.8 прямо называет частичную отмену отклонённой альтернативы «ошибка валидации вместо тихой деградации» для случая mode-less `collector` при < 2 join-источниках (по образцу п.7). Ссылка из этой альтернативы на п.8 — одна строка.
   - В строку `**Refs:**` ADR добавить `plans/topology-port-join.md (п.8: C-22)`.
   - В «Последствиях» п.8 — одна строка: рецепт вне репозитория с mode-less настройкой fanin при < 2 источниках перестаёт собираться; лечение — `mode: fanin` (подсказка в тексте ошибки).
   - Затем `python -m scripts.sync`.
5. **`test_blueprint_wire_collector.py`** — не менять, если ни один его тест не краснеет (стадия 0: `check()` там зовётся только в тесте C-17 без явного collector, `:653/:655`). Краснеет — стоп, вопрос лиду со списком тестов (полоса Ф держит остальную часть файла).

**Files:**
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py`;
- `multiprocess_framework/modules/process_manager_module/DECISIONS.md` (только ADR-PMM-017) + выход `scripts.sync`;
- `multiprocess_framework/modules/process_manager_module/tests/test_modeless_collector_check.py` (новый; tester).

**Acceptance criteria.** Все случаи B1–B8, B10, B11 — `check()` дважды: без `infer` и после `infer`; списки ошибок, отфильтрованные по подстроке ` без mode (ключи:`, одинаковые. Фикстуры — как в `test_infer_join_by_port.py:57–119` (свой реестр плагинов, снимать и восстанавливать). Команда приёмки: `pytest multiprocess_framework/modules/process_manager_module/tests/test_modeless_collector_check.py -q`.
- [x] **B0.** Существующих тестов, краснеющих от C-22: 0 (стадия 0: проба `check()` + C-22 по DESIGN, радиус плана + `recipes/tests`, 0 срабатываний). Любой красный существующий тест — стоп, вопрос лиду со списком (DESIGN 5).
- [x] **B1.** Процесс P, один join-источник (провод только в обязательный вход), typed `collector: {timeout_sec: 0.25}` → ровно одна ошибка C-22; в тексте `'P'`, `collector без mode`, `timeout_sec`, `join-источников: 1`, `mode: fanin`; подстроки `0.25` в тексте нет.
- [x] **B2.** Как B1, но секция в `extras` под ключом `collector` (B2a); затем под ключом `inspector` (B2b) → по одной ошибке; в B2b в тексте `inspector без mode`.
- [x] **B3.** Два join-источника, `collector: {timeout_sec: 0.25}` → ошибок C-22 нет; после `infer` `P.collector == {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame", "timeout_sec": 0.25}`.
- [x] **B4.** Один источник: `collector: {mode: fanin, timeout_sec: 0.25}` → нет ошибки; `collector: {mode: join, inputs: [frame], primary: frame}` → нет ошибки C-22.
- [x] **B5.** Один источник: без `collector` и с `collector: {}` → нет ошибки.
- [x] **B6.** Ноль источников (процесс без входящих проводов), `collector: {timeout_sec: 0.25}` → одна ошибка (после фильтра по преамбуле), `join-источников: 0`.
- [x] **B7.** Один источник: `collector: {mode: None, timeout_sec: 1}` и `{mode: "", timeout_sec: 1}` → по одной ошибке (как mode-less).
- [x] **B8.** Три процесса с joiner-плагином, у каждого ровно один join-источник: A — typed `collector: {timeout_sec: 0.25}`, B — typed `{mode: fanin, timeout_sec: 0.25}`, C — без секции → ровно одна ошибка C-22; в ней `'A'`, нет `'B'` и `'C'`.
- [x] **B9.** Все собираемые рецепты `multiprocess_prototype/recipes/*.yaml` (22 yaml минус `robot_demo`, C-18 = 21 на `ce9589882`) собираются, как на main: `multiprocess_prototype/backend/tests` зелёный, `git diff --stat` по `snapshots/` пуст.
- [x] **B10.** Typed `collector: {timeout_sec: 0.25}` + `metadata: {collector: {mode: join}}`, один источник → до и после infer ровно одна ошибка с `metadata.collector.mode=join` и ровно одна с ` без mode (ключи:`.
- [x] **B11.** `extras.collector = {1: "a", "x": 2}`, один источник → `check()` не бросает, ровно одна ошибка C-22 с `ключи: 1, x`.

**REDS до правки src** (tester вслепую, worktree на коммите плана): B1, B2, B6, B7, B8, B10, B11 красные; B3, B4, B5, B9 зелёные.

**Break-injection лида (после реализации), предсказания:**
- I1: убрать вызов `_modeless_collector_errors()` из `check()` → красные B1, B2, B6, B7, B8, B10, B11;
- I2: в проверке читать `proc.collector.get("mode") != "join"` вместо `_joining_sources()` → красная половина «без infer» в B3;
- I3: `"mode" in explicit` вместо `explicit.get("mode")` → красный B7 (оба варианта);
- I4: только typed `proc.collector` (без `extras`) → красные B2, B11; B8 зелёный (A — typed);
- I5: порог `< 1` вместо `< 2` → красные B1, B2, B7, B8, B10, B11; B6 зелёный;
- I6: ключ в тексте захардкожен `collector` → красный B2b;
- I7: убрать guard непустоты секции → красные B5 и B8 (и B1–B4, B6, B7, B10, B11 по счётчику ошибок: процессы-источники без секции получают ошибку).

**Handoff:** reviewer стадии 0 (Sonnet) → tester (REDS вслепую) → developer → лид (инъекции) → reviewer (Sonnet).
**Gate:** pytest радиуса + `sentrux check .` + `scripts/validate.py`.
**Радиус pytest:** `process_manager_module/tests`, `process_module/tests/test_blueprint_wire_collector.py`, `process_module/tests/test_blueprint_extras.py`, `multiprocess_prototype/backend/tests`, `multiprocess_prototype/backend/topology/tests`, `multiprocess_prototype/backend/assembly/tests`, `multiprocess_prototype/recipes/tests`, `Plugins/_shared/fanin/tests`. `recipes/tests/test_letter_robot_sim_diff.py::test_sim_recipe_differs_only_in_camera_block` красный на main `ce9589882` до C-22 (реестр C-24), не регрессия.

**Out of scope:** порог `≥ 2`, теги и вывод join (ADR-PMM-017 п.3–6); `metadata.collector/inspector` без `mode` (deprecated, уже предупреждение — вопрос владельцу в «Открыто»); `collector_registry.py`, `Plugins/_shared/fanin/**`; рецепты; GUI-сохранение.

**Перед слиянием:** rebase на main, `validate.py` + `multiprocess_prototype/backend/tests` + framework suite (heavy, окно у координатора).

**Открыто (для владельца):**
- `metadata.collector/inspector` без `mode` у процесса без join тоже молча теряется (путь deprecated, в лог — предупреждение). Делать ли его ошибкой — не решено.
- GUI-сохранение идёт через `validate_recipe_blueprint` → `check_structure()` (`recipes/save.py:149–180`), поэтому рецепт с нарушением C-22 сохранится и откажет только при сборке (`assembler.py:135`, `builder.py:249`). Обратная сторона пункта Out of scope «GUI-сохранение».

## Фаза C-25 + C-28 — точка в имени процесса; deprecated `metadata` без применения (2026-10-25)

**Источник:** `plans/queue/defects.md`, строки C-25 и C-28; ревью ветки C-22 (Opus), отчёт `docs/reports/2026-10-21_topology-port-join_C22.1.md` («Открыто»).
**Полоса:** Д (inspector-bottles-a3, после перезапуска — inspector-bottles-d9). **Ветка:** `fix/c25-c28-blueprint`.
**Стадия 0:** reviewer (Sonnet), итерация 1 — CHANGES REQUESTED, 12 правок внесены дословно; итерация 2 — 5 мелких правок и косметика внесены дословно (предел 2 итерации, третьей нет); п.13 (единый источник legacy-секции в `infer`) принят как DESIGN 6 C28.1. Правка тестов A0/M0 — разрешена координатором 2026-10-25. **Решение по `metadata` с `mode: fanin` (координатор по поручению владельца, 2026-10-25, запись main `ef372c6de`): вариант (б)** — любая непустая неприменённая `metadata.collector`/`metadata.inspector` — ошибка, `{mode: fanin}` тоже. Причина: правило «ошибка только при потере настройки» опиралось бы на умолчание fanin; сменится умолчание — `{mode: fanin}` начнёт теряться молча; одно место настройки вместо двух.

**Решения владельца:**
- C-28 (2026-10-21 ~16:50, через координатора): «да — ошибка `check()`, как C-22» — ничего не терять молча; рецепты универсальны.
- C-25 (2026-10-25, через координатора, запись main `0869e86a8`): **вариант Б** — точка в `process_name` — громкая ошибка `check()` и `check_structure()` («точка — разделитель адреса»), одной правкой с C-28. Условия: «0 рецептов с точкой» — прогоном сборки всех рецептов; текст ошибки ссылается на ADR; тест на оба пути; в коде не остаётся второго, противоречащего правила (комментарий `check()` `:821–822`).

**Граница (координатор inspector-bottles-bc, 2026-10-25):** `multiprocess_framework/modules/process_manager_module/topology/blueprint.py`; раздел ADR-PMM-017 в `process_manager_module/DECISIONS.md`; `process_module/tests/test_blueprint_wire_collector.py` (только если краснеет — стоп и вопрос лиду); новые тесты. Остальное `process_manager_module/**`, `command/process/worker_module/**` — полоса Ф, не трогать. Рецепты не меняются. Тесты `process_manager_module/tests/test_t59a_review_author.py` и `test_infer_join_by_port.py` — только ожидания (A0, M0), разрешено координатором 2026-10-25; Ф их не правит, при rebase увидит.

### Факты (проверены чтением и прогоном, 2026-10-25)

- Контракт адресации framework: `message_module/addressing/address.py:11,19` — первый сегмент адреса всегда процесс, доставка между процессами по `process_of(target) = address[0]` (`router_module/core/router_manager.py:2122`). Процесс `draw.a` роутер не адресует: `process_of("draw.a") == "draw"`.
- В `blueprint.py` имя процесса до первой точки берут 5 мест: `:444–445` (`_joining_sources`, C-25), `:627` (chain_targets в бюджете «в полёте»), `:631–632` (провода в бюджете), `:732` (`_unaddressable_chain_targets`, «судится первый сегмент» — по контракту адресации), `:782–783` (циклы, `check_structure`). Только `check()` `:821–823` разбирает адрес через карту `input_origin`.
- YAML репозитория с `processes`: 46, имён процесса с точкой: 0 (скрипт по `git ls-files *.yaml *.yml`).
- Порядок боевой сборки: `assembler.py:133–135` — `infer_missing_collectors()`, затем `check()`. Значит, правило C-28 обязано давать тот же результат после `infer`.

### Task C25.1 — имя процесса с точкой — ошибка структуры (вариант Б)

**Level:** Middle (Sonnet). **Assignee:** developer (Sonnet).
**Module contract:** не требуется — приватные методы, поведение `check()` фиксирует ADR-PMM-017 п.9.
**Files:** `blueprint.py`; `process_manager_module/DECISIONS.md` (только ADR-PMM-017) + выход `scripts.sync`; `process_manager_module/tests/test_dotted_process_name.py` (новый; tester); `process_manager_module/tests/test_t59a_review_author.py` (A0, только ожидание).
**Goal:** рецепт с точкой в `process_name` не проходит ни `check_structure()`, ни `check()`; текст называет процесс и причину (точка — разделитель адреса).

**DESIGN:**
1. Новый приватный метод `_dotted_process_names(self) -> list[str]` рядом с `_duplicate_process_names` (`:661`): одна ошибка на процесс, у которого в `process_name` есть `.` (константа `SEPARATOR` из `message_module.addressing.address`, импорт внутри метода — как `is_broadcast` в `:723`). Текст: `Процесс '<имя>': точка в имени процесса запрещена — точка разделяет уровни адреса (процесс.воркер, процесс.плагин.порт); роутер прочтёт адрес '<имя>' как процесс '<до первой точки>'. Переименуй процесс (например, '<имя с _ вместо .>'), ADR-PMM-017 п.9`.
2. Вызов первым после `_duplicate_process_names()` в обоих гейтах: `check()` (`:813`) и `check_structure()` (`:776`).
3. Остальные места с `split(".")` (кроме `:444–445`, чей дефект и закрывает запрет) не трогать: при запрете точки они корректны. Комментарий у `check()` `:821–822` («имя процесса может содержать точку») — заменить на «точка в имени запрещена (`_dotted_process_names`); карта нужна, чтобы не разбирать адрес повторно».
4. Docstring `check()` — пункт «7. Точка в `process_name` — ошибка (C-25, ADR-PMM-017 п.9); та же проверка в `check_structure()`»; docstring `check_structure()` — первая строка «дубли имён + точка в имени + циклы». Docstring `ProcessConfig.process_name` FieldMeta — одна фраза: «без точки (разделитель адреса)».
5. ADR-PMM-017 — новый п.9 (2026-10-25): правило, причина (контракт адресации, ссылка на `address.py`), рецептов с точкой в репозитории 0, последствие для чужих рецептов (перестают собираться и сохраняться; лечение — переименовать). В `**Refs:**` ADR — «(п.9: C-25; п.10: C-28)»; по строке в «Последствиях» о п.9 и п.10. `python -m scripts.sync`.

**Acceptance (тестер вслепую):** файл `multiprocess_framework/modules/process_manager_module/tests/test_dotted_process_name.py`; реестр плагинов — как в `test_modeless_collector_check.py` (свой, снять/восстановить).
- [ ] A0. Существующий тест, краснеющий от C-25: `process_manager_module/tests/test_t59a_review_author.py::test_dotted_process_name_wire_does_not_cover_the_shorter_named_process` (`proc.a`: `len(check()) == 1` -> 2). Правка (developer, разрешена координатором): ожидать ошибку «точка в имени процесса» про 'proc.a' и прежнюю ошибку про вход `proc.needs_frame.frame`, обе литералом.
- [ ] A1. Процесс `draw.a` (плагин без портов) → `check_structure()` содержит ровно одну ошибку с `'draw.a'` и подстрокой `точка в имени процесса`; то же для `check()`. Текст ошибки содержит `ADR-PMM-017`.
- [ ] A2. `check_structure()` для процессов `draw` и `draw.a`: среди ошибок с подстрокой `точка в имени процесса` ровно одна, она начинается с `Процесс 'draw.a':`; ни одна ошибка не начинается с `Процесс 'draw':`.
- [ ] A3. Имя без точки (`draw_a`) → ни одной ошибки с подстрокой `точка в имени процесса`.
- [ ] A4. `check_structure()` работает при пустом `PluginRegistry` (A1 повторить с очищенным реестром) — ошибка та же.
- [ ] A5. Для каждого из 22 `multiprocess_prototype/recipes/*.yaml` (число в прогоне — литерал 22, `robot_demo` включён) `SystemBuilder.from_manifest(app, recipe).build()` (как `_built_collectors` в `multiprocess_prototype/backend/tests/test_recipes_join_contract.py`) не бросает, и ни одно имя в `launcher._processes` не содержит `.`.
**Команда приёмки:** `pytest multiprocess_framework/modules/process_manager_module/tests/test_dotted_process_name.py -q`.
**REDS до правки src:** A1, A2, A4 красные; A3, A5 зелёные; A0 — зелёный до src, красный после (существующий тест).


### Task C28.1 — `metadata.collector`/`metadata.inspector`, которые не применяются, — ошибка `check()`

**Level:** Middle (Sonnet). **Assignee:** developer (Sonnet). Образец — C22.1 (`_modeless_collector_errors`).
**Module contract:** не требуется — приватные методы, поведение `check()` фиксирует ADR-PMM-017 п.10.
**Files:** `blueprint.py`; `process_manager_module/DECISIONS.md` (только ADR-PMM-017) + выход `scripts.sync`; `process_manager_module/tests/test_unapplied_metadata_check.py` (новый; tester); `process_manager_module/tests/test_infer_join_by_port.py` (M0, только ожидание).
**Dependencies:** после C25.1 (один файл `blueprint.py`, нумерация docstring и ADR п.9/п.10).
**Goal:** deprecated секция `metadata.collector`/`metadata.inspector`, которую сборка не применит, даёт ошибку `check()`; предупреждение deprecated остаётся.

**Когда секция применяется (факт кода, `infer_missing_collectors` `:533–580`):** её не-структурные ключи подмешиваются, только если у процесса ≥ 2 join-источников и явная секция (`_explicit_collector`) не задаёт `mode`. После `infer` такой процесс имеет `collector.mode == "join"`.

**DESIGN:**
1. Новый приватный метод `_unapplied_metadata_errors(self) -> list[str]`, вызов в `check()` сразу после `_modeless_collector_errors()`. `joining = self._joining_sources()` один раз.
2. Для процесса: `meta_key, section = _legacy_metadata_section(proc)`; пусто — пропуск. `exp_key, explicit = _explicit_collector(proc)`; `mode = explicit.get("mode")`; `n = len(joining.get(proc.process_name, {}))`.
   - **Применяется**, если `n >= 2` и `mode` ложно или равно `"join"`. Равенство `"join"` нужно, чтобы результат не зависел от `infer` (после `infer` выведенный join выглядит как явный `mode: join`). Остаток: явный пользовательский `collector: {mode: join, …}` при ≥ 2 источниках + `metadata`-настройка — секция не применяется, но ошибки нет (неотличимо после `infer`); записать в ADR как известную границу.
   - Не применяется → одна ошибка, КРОМЕ процесса, по которому `_metadata_join_errors()` уже вернул ошибку (исключение по имени процесса, не по ключу секции); без дублирования расчёта эффективного режима.
   - Ошибка C-22 по тому же процессу остаётся: она про другое поле.
3. Текст (значений секции нет, кроме значения `mode` в причине (дискриминатор; M4 проверяет `mode=fanin`), ключи — `sorted(str(k))` через `, `):
   `Процесс '<имя>': metadata.<meta_key> (deprecated, ключи: <k1, k2>) не применяется — <причина>. Штатно: перенеси в process-level collector: {<k1>: …, <k2>: …} (те же ключи; без mode — тонкая настройка выведенного join, только при ≥ 2 join-источниках; mode: fanin — настройка fanin) и удали metadata.<meta_key>`.
   Причина: при `n < 2` — `join не выведен (join-источников: <n>, нужно ≥ 2)`; иначе — `явный <exp_key> задаёт mode=<mode>`.
4. Предупреждение deprecated в `infer` (`:538–543`) не менять.
5. Docstring `check()` — пункт «8. `metadata.<ключ>` (deprecated), которая не применится, — ошибка (C-28)». ADR-PMM-017 п.8: фразу «`metadata` … без `mode` (deprecated, п.7) правило НЕ задевает» заменить ссылкой на новый п.10 (C-28): правило владельца, условие применения, исключение C-17, остаток (явный `mode: join` при ≥ 2). `python -m scripts.sync`.
6. Единый источник legacy-секции (стадия 0, п.13): в `infer` (`:572–574`) `legacy = _legacy_metadata_section(proc)[1]` вместо `proc.metadata.get(collector) or proc.metadata.get(inspector)` — иначе truthy не-dict `metadata.collector` прячет `metadata.inspector` от `infer`, а проверка его видит.

**Acceptance (тестер вслепую):** файл `multiprocess_framework/modules/process_manager_module/tests/test_unapplied_metadata_check.py`. Каждый случай — `check()` дважды: без `infer` и после `infer`; списки, отфильтрованные по подстроке `(deprecated, ключи:`, одинаковые. Реестр — свой, как в `test_modeless_collector_check.py`.
- [ ] M0. Существующий тест, краснеющий от C-28: `process_manager_module/tests/test_infer_join_by_port.py::test_a7_metadata_without_mode_join_is_not_an_error[collector|inspector]` (`:250-265`, `assert bp.check() == []`). Правка (developer, разрешена координатором; вариант (б)): тест переименовать в `test_a7_metadata_without_mode_join_is_a_c28_error`; для обоих параметров (`{timeout_sec: 0.7345}` и `{mode: fanin}`) — до и после infer ровно одна ошибка, литералом: начинается с `Процесс 'layout': metadata.<key> (deprecated, ключи: timeout_sec)` и `Процесс 'layout': metadata.<key> (deprecated, ключи: mode)` соответственно; списки до и после равны; подстроки `0.7345` нет.
- [ ] M1. Один join-источник, `metadata: {inspector: {timeout_sec: 0.25}}`, явного collector нет → ровно одна ошибка; в тексте `'P'`, `metadata.inspector`, `timeout_sec`, `join-источников: 1`; подстроки `0.25` нет. В тексте `collector: {timeout_sec: …}`.
- [ ] M2. Как M1, но `metadata.collector` → в тексте `metadata.collector`.
- [ ] M3. Два join-источника, `metadata: {inspector: {timeout_sec: 0.25}}` → ошибки нет; после `infer` `P.collector["timeout_sec"] == 0.25`.
- [ ] M4. Два источника, typed `collector: {mode: fanin}` + `metadata: {inspector: {timeout_sec: 0.25}}` → одна ошибка, в тексте `mode=fanin`.
- [ ] M5. Один источник, `metadata: {inspector: {mode: join, inputs: [frame], primary: frame}}` → ошибка C-17 есть (подстрока `metadata.inspector.mode=join`), ошибок `(deprecated, ключи:` — ноль.
- [ ] M6. Один источник, typed `collector: {timeout_sec: 1}` + `metadata: {inspector: {timeout_sec: 0.25}}` → одна ошибка C-22 (` без mode (ключи:`) и одна C-28.
- [ ] M7. Ноль источников, `metadata: {collector: {timeout_sec: 0.25}}` → одна ошибка, `join-источников: 0`.
- [ ] M8. `metadata: {inspector: {}}` и `metadata: {}` → ни одной ошибки C-28.
- [ ] M9. Три процесса с одним источником каждый: A — `metadata.inspector` с настройкой, B — без `metadata`, C — `metadata: {source_target_fps: 25}` → ровно одна ошибка C-28, про `'A'`.
- [ ] M10. Для каждого из 22 `multiprocess_prototype/recipes/*.yaml`: список процессов с непустой `metadata.collector`/`metadata.inspector` равен `[]` (литерал), и `SystemBuilder.from_manifest(app, recipe).build()` не бросает (число рецептов — 22).
- [ ] M11. Один источник, `metadata: {collector: {timeout_sec: 0.25}, inspector: {mode: join}}` -> есть ошибка `metadata.inspector.mode=join`, ошибок `(deprecated, ключи:` ноль (до и после infer).
- [ ] M12. Два join-источника, `metadata: {collector: 5, inspector: {timeout_sec: 0.25}}` → ошибок `(deprecated, ключи:` ноль; после `infer` `P.collector["timeout_sec"] == 0.25`.
- [ ] M13. Один источник, `metadata: {inspector: {mode: fanin}}` → ровно одна ошибка (до и после infer), в тексте `metadata.inspector (deprecated, ключи: mode)` и `collector: {mode: …}`.
**Команда приёмки:** `pytest multiprocess_framework/modules/process_manager_module/tests/test_unapplied_metadata_check.py -q`.
**REDS до правки src:** M1, M2, M4, M6, M7, M9, M12, M13 красные; M3, M5, M8, M10, M11 зелёные; M0 — существующий тест зелёный до src и красный после (оба параметра `[collector]`, `[inspector]`); после правки developer зелёный.

### Break-injection лида (после реализации), предсказания

C25.1:
- J1: убрать вызов из `check_structure()` → красные A1 (половина structure), A2, A4; A3, A5 зелёные.
- J2: убрать вызов из `check()` → красная половина `check()` в A1.
- J3: проверять `name.count(".") > 1` → красные A1, A2, A4.
C28.1:
- K1: убрать вызов `_unapplied_metadata_errors()` → красные M1, M2, M4, M6, M7, M9.
- K2: условие «применяется» без `== "join"` (только `not mode`) → красная половина «после infer» в M3.
- K3: убрать исключение C-17 → красные M5, M11.
- K4: порог «применяется» `n >= 1` → красные M1, M2, M6, M9; M7 (n = 0) зелёный.
- K5: убрать guard непустоты секции → красные M1–M10 (процессы без `metadata` получают ошибку), не только M8.
- K7: пропускать секцию `{mode: fanin}` без других ключей (правило (а)) → красные M13 и параметр `{mode: fanin}` в M0 (оба ключа); M1–M12 зелёные.
- K6: в `infer` вернуть `metadata.get(collector) or metadata.get(inspector)` → красный M12.

**Handoff:** reviewer стадии 0 (Sonnet) → tester вслепую (worktree на коммите плана) → developer (Sonnet) → лид (инъекции) → reviewer задачи (Sonnet) → ревью ветки (Opus, framework) → слияние.
**Gate:** радиус pytest как у C22.1 + `sentrux check .` + `scripts/validate.py`; перед слиянием framework suite (heavy, окно у координатора).
**Радиус pytest:** `process_manager_module/tests`, `process_module/tests/test_blueprint_wire_collector.py`, `process_module/tests/test_blueprint_extras.py`, `multiprocess_prototype/backend/tests`, `multiprocess_prototype/backend/topology/tests`, `multiprocess_prototype/backend/assembly/tests`, `multiprocess_prototype/recipes/tests`, `Plugins/_shared/fanin/tests` — по одному каталогу (шлюз).

**Перед слиянием:** rebase на main; `process_manager_module/DECISIONS.md` и сводные разделы `multiprocess_framework/DECISIONS.md` общие с полосой Ф — правим только ADR-PMM-017; конфликт в выходе `scripts.sync` руками не мержить: взять main и заново `python -m scripts.sync`; номера п.9/п.10 сверить с main.

**Out of scope:** вывод join, теги, порог (ADR-PMM-017 п.3–6); `metadata.<ключ>.mode=fanin` при ≥ 2 источниках (вывод даёт join — противоречие, не потеря; в «Открыто»); `collector_registry.py`; рецепты; GUI-сохранение (C-30).

**Открыто (для владельца):** `metadata.<ключ>.mode=fanin` при ≥ 2 join-источниках без явного `collector` — вывод даёт join, `mode: fanin` из metadata молча игнорируется (противоречие, не потеря; C-28 его не ловит). Делать ли ошибкой — не решено.
