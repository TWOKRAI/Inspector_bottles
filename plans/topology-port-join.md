# topology-port-join — вход плагина объявляет участие в join отдельно от optional (C-16 + C-17)

**Статус:** активный · **Ветка:** `fix/c16-collector` · **Полоса:** Д (inspector-bottles-66)
**Источник:** реестр `plans/queue/defects.md` строки C-16, C-17; расследование `docs/reports/2026-10-21_defects_C-16.md`.

## Контекст

`7e1640c97` (2026-10-15) сделал вход `overlay_draw.overlay` необязательным (`optional=True`): в qr-рецептах `overlay_draw` рисует кадр без оверлея. `SystemBlueprint.infer_missing_collectors` пропускает провода в optional-порты (`blueprint.py:511`, ADR-PMM-017 п.1). Поэтому у `draw` в `hikvision_letter_robot` остался один источник, join не выводится, а сборка даёт `collector: {}`. В рантайме это fanin вместо join кадра с оверлеем. На main красные `test_build_characterization[hikvision_letter_robot]` и `test_join_collector_from_wires.py` (2 failed).

Корень: `Port.optional` перегружен. Он значит «может быть не подключён» (так написано в его описании) и тайно «не участвует в join».

## Решения владельца (2026-10-21, дословно)

1. Поле контракта порта — **`Port.join: bool | None`** (владелец 2026-10-21).
2. Умолчание — **`None` = `not optional`**: все нынешние плагины ведут себя как сейчас; явно `join=True` ставит только `overlay_draw.overlay` (владелец 2026-10-21).
3. **`metadata.inspector` — deprecated:** 4 рецепта переводятся на `collector: {timeout_sec: 0.25}` без `mode` (join выводится из портов); чтение `metadata.inspector` остаётся с предупреждением в лог; **C-17 — громкая ошибка `check()`**, если в `metadata` задан `mode: join`, а join не выведен (владелец 2026-10-21).
4. Общее требование владельца: «универсально в рецептах и плагинах на будущее»: плагин объявляет семантику входа один раз, рецепт не несёт `mode`/`inputs` вручную.

## Граница (подтверждена координатором inspector-bottles-7f)

Можно править только:
- `multiprocess_framework/modules/process_module/plugins/port.py`;
- `multiprocess_framework/modules/process_manager_module/topology/blueprint.py`;
- раздел ADR-PMM-017 в `multiprocess_framework/modules/process_manager_module/DECISIONS.md`;
- `Plugins/render/overlay_draw/**`;
- рецепты `multiprocess_prototype/recipes/{hikvision_letter_robot,letter_angle_inspect,letter_robot_sim,dataset_circle_capture}.yaml`;
- новые тесты.

Остальное в `process_manager_module/**` и `process_module/**` принадлежит полосе Ф. Если нужен файл вне этого списка — стоп, вопрос лиду (лид спрашивает координатора). `line_filter_inspect.yaml` (там process-level `inspector:`) — только по слову стадии 0.

### Task C16.1 — `Port.join` + вывод join по нему + громкая ошибка C-17 + перевод 4 рецептов

**Level:** Senior+ (публичный контракт framework и вывод топологии)
**Assignee:** developer (Sonnet) после стадии 0 на Opus; дизайн задан здесь
**Goal:** вход плагина объявляет участие в join полем `Port.join`; вывод join считает подключённые входы по этому полю, а не по `optional`; противоречие `metadata` и вывода — громкая ошибка, а не тихий fanin.

**DESIGN:**
1. `port.py::Port`: поле `join: Annotated[bool | None, FieldMeta("Участвует в join", info=...)] = None`. Свойство или функция `joins` (имя — на стадии 0) = `self.join if self.join is not None else not self.optional`. В docstring — Pre/Post/Invariants (module-contract): `optional` говорит только о подключении; `join` — только о корреляции подключённого входа с кадром; `join=None` сохраняет поведение до C-16. Сериализация `PortV1` (`to_dict`/`from_dict`) поле переносит; старый dict без `join` читается как `None`.
2. `blueprint.py::infer_missing_collectors` стр. 511: `if tgt_port is None or not <joins>(tgt_port): continue` вместо проверки `optional`. Порог `< 2` источников, теги, escape-hatch и подмешивание тонкой настройки (стр. 517–560) не меняются.
3. `blueprint.py`: чтение `metadata.inspector` / `metadata.collector` как тонкой настройки остаётся. Если оно сработало — одно предупреждение в лог на процесс (deprecated, указать штатный ключ `collector`).
4. C-17: в `check()` (или в том месте blueprint, где `check` собирает ошибки, — найти; если это не `blueprint.py` — стоп, вопрос лиду) — ошибка, если у процесса `metadata.(inspector|collector).mode == "join"`, а после вывода `proc.collector.get("mode") != "join"`. Текст ошибки называет процесс и штатное исправление.
5. `Plugins/render/overlay_draw/plugin.py:39`: `Port(name="overlay", ..., optional=True, join=True, ...)`; README и STATUS — одна строка о `join=True`.
6. 4 рецепта: каждый блок `metadata.inspector` (9 шт.) удалить. Если процессу нужна только тонкая настройка (`timeout_sec`), задать process-level `collector: {timeout_sec: 0.25}` без `mode`. Если после правки `metadata` пуст — удалить `metadata:`.
7. ADR-PMM-017: дописать пункт 7 (дата 2026-10-21, refs этот план): `Port.join`, умолчание, deprecated `metadata`, громкая ошибка C-17. П.1 и п.5 пометить ссылкой на п.7 (не переписывать). Потом `python -m scripts.sync`.

**Files:** список в «Граница» + новые тесты: `multiprocess_framework/modules/process_module/tests/contract/test_port_join.py` (или рядом с существующими тестами `port.py` — где лежат, там и ставить), `multiprocess_framework/modules/process_manager_module/topology/tests/test_infer_join_by_port.py`, `multiprocess_prototype/backend/tests/test_recipes_no_legacy_inspector.py`.

**Acceptance criteria:**
- [ ] A1 `Port()` без `join`: `joins` == `not optional` для обоих значений `optional` (литералы True/False).
- [ ] A2 `Port(optional=True, join=True)`: подключён из другого процесса → участвует в join; не подключён → `check()` не требует провода.
- [ ] A3 `Port.to_dict` → `from_dict` сохраняет `join` (True/False/None); dict без ключа `join` → `None`.
- [ ] A4 Обратная совместимость (именованный тест): все рецепты `multiprocess_prototype/recipes/*.yaml`, собранные на ветке, дают те же `collector` по каждому процессу, что main до правки (снимок значений до правки — литералами в тесте или фикстурой, снятой с main `aad763838`), **кроме** `draw` в `hikvision_letter_robot`, `letter_angle_inspect`, `letter_robot_sim`, `dataset_circle_capture`, где ожидается join.
- [ ] A5 `hikvision_letter_robot`: `draw.collector == {"inputs": ["frame","overlay"], "mode": "join", "primary": "frame", "timeout_sec": 0.25}` и `recog.collector` — то же значение (литералы); `recipes` не несут `mode`.
- [ ] A6 Golden-снимки `phone_sketch` и `hikvision_letter_robot` зелёные **без регенерации** (`git diff --stat` по `snapshots/` пуст); `test_join_collector_from_wires.py` 5/5.
- [ ] A7 C-17: blueprint с `metadata.inspector.mode: join` у процесса с одним join-источником → `check()` возвращает ошибку с именем процесса; тот же blueprint с двумя источниками → ошибки нет.
- [ ] A8 Предупреждение deprecated: сборка blueprint с `metadata.inspector: {timeout_sec: 1}` → ровно одна запись WARNING в лог про этот процесс, `timeout_sec` подмешан.
- [ ] A9 Ни один рецепт в `multiprocess_prototype/recipes/` не содержит `metadata.inspector` или `metadata.collector` (сторож от возврата формы).
- [ ] A10 qr-рецепты (`qr_reader_sdk_demo*`) собираются и проходят `check()`, как на main (overlay не подключён — не ошибка).

**Out of scope:** порог `≥ 2` источников, теги (ADR-PMM-017 п.3, п.4, п.6), фабрика коллекторов `collector_registry.py`, домен-entity GUI, другие плагины (их `join` остаётся `None`), `line_filter_inspect.yaml` (до слова стадии 0), регенерация любых снимков.

**Перед слиянием:** framework suite (heavy, окно у координатора), `scripts/validate.py`, `multiprocess_prototype/backend/tests`; ревью ветки на Opus.
