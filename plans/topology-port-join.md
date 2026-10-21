# topology-port-join — вход плагина объявляет участие в join отдельно от optional (C-16 + C-17)

**Статус:** активный · **Ветка:** `fix/c16-collector` · **Полоса:** Д (inspector-bottles-66)
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

**Открыто (для владельца, не в этой задаче):** `collector: {timeout_sec}` без `mode` у процесса, где join не вывелся (например, удалили провод), молча даёт fanin с таймаутом.
