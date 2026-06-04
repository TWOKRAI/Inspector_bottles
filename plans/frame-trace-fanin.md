# План: Fan-in trace — пер-сегментная трассировка кадра на ветвлениях пайплайна

- **Slug:** frame-trace-fanin
- **Дата:** 2026-06-04
- **Статус:** DRAFT
- **Ветка:** feat/comm-system-target-architecture (продолжение телеметрии, НЕ новая ветка)
- **Родитель:** [`frame-trace-envelope.md`](frame-trace-envelope.md) (frame-trace v1, линейная цепочка — коммиты 48caea37 / 20b151e3 / 95a122cf), [`telemetry-self-publish-redesign.md`](telemetry-self-publish-redesign.md) (capture_ts = t0 trace)

> **Задача из Out-of-scope v1.** `frame-trace-envelope.md` явно вынес fan-in/fan-out в
> отдельную задачу: «`region_split` (1→N), `stitcher`/merge (N→1) ломают линейный trace —
> v1 поддерживает линейную цепочку; merge — отдельная задача (какой trace наследовать)».
> Здесь чиним нелинейные пайплайны.

---

## Обзор

frame-trace v1 трассирует только **линейную** цепочку (camera→detector→painter→gui):
`item["trace"]` — список спанов, каждый узел дописывает свой. На **ветвлениях**
(`region_split` 1→N, `stitcher` N→1) модель ломается. Цель — корректная семантика
наследования и накопления trace через ветвления, с сохранением гейта
`INSPECTOR_FRAME_TRACE` (в проде no-op) и приёмкой через qt-mcp live smoke на реальном
рецепте `recipes/region_pipeline.yaml`.

## Диагностика текущего поведения (изучено по коду)

Реальный нелинейный пайплайн — `recipes/region_pipeline.yaml`:
`camera_0 → preprocessor(resize) → region_splitter(split 1→3) → {process_negative, process_grayscale, process_flip} → stitcher(merge 3→1) → gui`.

Три точки поломки трассировки:

1. **fan-out (`region_split`, `Plugins/processing/region_split/plugin.py`).**
   `process()` через `@for_each` строит N регионов как `{**item, "frame": crop, ...}`.
   `{**item}` копирует dict поверхностно — **значение ключа `trace` остаётся ССЫЛКОЙ
   на один и тот же list-объект** родителя. Когда декоратор `traced` дописывает
   process-спан в каждый регион (`record_process` → `item.setdefault("trace", []).append`),
   все N регионов мутируют **общий** список → перекрёстное загрязнение спанов между
   ветвями. Плюс `_t_send`/`_from` наследуются одинаково (это менее опасно — снимаются
   на приёме). **Нужно:** глубокая копия `trace` на каждый out-item при fan-out + маркер
   ветви.

2. **буфер fan-in (`InspectorManager`, `multiprocess_framework/.../generic/inspector_manager.py`).**
   Буферизует N region-items по `(camera_id, seq_id)` до полной коллекции/timeout, отдаёт
   `list[items]` в `stitcher`. Каждый item несёт свой (после фикса #1 — независимый)
   `trace`, отражающий путь camera→split→ветвь. Буфер сам по себе trace не теряет, но
   он — место, где сходятся N разнопутёвых trace, и именно тут принимается решение
   о merge-семантике (Task 1.2).

3. **fan-in (`stitcher`, `Plugins/processing/stitcher/plugin.py`).**
   `process(items)` собирает canvas и **строит НОВЫЙ dict с нуля** (строки 64–73):
   `seq_id`/`frame_id` берёт из `items[0]`, но `trace`, `capture_ts` и всю историю
   N ветвей **выбрасывает целиком**. Merged-кадр приходит в `gui` с пустым trace →
   разбивка по сегментам на дисплее пуста для нелинейного пайплайна. **Это корневой
   баг fan-in.** Stitcher должен наследовать trace по выбранной merge-семантике.

Также важно: декоратор `traced` (`frame_trace.traced`) делит длительность `process()`
на `len(out)` — для fan-out это «per-region», для fan-in (stitcher 3→1) приписывает
ВСЮ длительность склейки одному out-item. Это корректно, но merge-спан stitcher'а
должен попасть в наследованный trace (Task 1.2).

---

## КЛЮЧЕВОЕ АРХИТЕКТУРНОЕ РЕШЕНИЕ: семантика наследования trace при merge (N→1)

Главный design-вопрос задачи. При N→1 у stitcher на руках N независимых trace
(camera→split→ветвь_i). Какой trace получает merged-кадр?

### Вариант A — «critical path» (наследовать самый медленный путь)

Merged.trace = trace ветви с максимальной суммой `ms` (от capture до stitcher).
Плюс merge-спан самого stitcher.

- **За:** trace остаётся плоским списком (схема v1 не меняется); GUI-таблица «участок · мс»
  работает как есть; размер trace в IPC = O(глубина одной ветви), не растёт от ширины
  fan-out. Семантически «узкое место кадра» — самый медленный путь и есть end-to-end
  латентность (остальные ветви всё равно ждали его в буфере InspectorManager).
- **Против:** теряется детализация быстрых ветвей (не видно, что делал grayscale, если
  медленнее был negative). Для «где тормозит» это приемлемо — медленная ветвь и есть
  ответ. Нужно поле-маркер, какая ветвь выбрана.

### Вариант B — «union» (объединить спаны всех ветвей)

Merged.trace = конкатенация trace всех N ветвей (с пометкой ветви в каждом спане) +
merge-спан.

- **За:** полная наблюдаемость — видно каждую ветвь.
- **Против:** размер trace растёт линейно по ширине fan-out (N×глубина) — едет по IPC
  в `data` каждого кадра (риск из v1 «Размер IPC»). Общий префикс camera→split
  дублируется N раз. GUI-агрегатор `record_trace_spans` усредняет по имени участка —
  при union один и тот же транспорт camera→split попадёт N раз, исказив среднее.
  Требует доработки схемы спана (branch-поле) и GUI-агрегатора.

### Вариант C — «отдельная схема ветвления» (дерево вместо списка)

Merged.trace = структура `{prefix:[...общие спаны...], branches:{name:[...]}, merge:{...}}`.

- **За:** математически точное представление DAG.
- **Против:** ломает плоскую схему v1 целиком (спан больше не `list[dict]`); переписывает
  GUI-панель, агрегатор, FrameTraceChannel; максимальный размер IPC и сложность.
  Оверкилл для текущей цели «прочитать, где тормозит кадр».

### РЕКОМЕНДАЦИЯ: Вариант A (critical path) + минимальная сводка по ветвям

Основной trace merged-кадра = **самый медленный путь** (плоский список, схема v1 цела,
IPC не растёт от ширины, GUI работает без переделки). Дополнительно stitcher кладёт
**лёгкую сводку** `item["trace_branches"]` — `[{"branch": name, "total_ms": сумма, "spans": K}]`
по каждой ветви (без полных спанов, только агрегаты) → наблюдаемость «какая ветвь была
медленная» при околонулевом росте IPC. merge-спан stitcher'а добавляется в конец
основного trace как `{"kind": "process", "node": "stitcher", "plugin": "stitcher", "ms": ...}`,
плюс новый kind `{"kind": "merge", "node": "stitcher", "branches": N, "chosen": name, "ms": fan-in-wait}`
где `ms` — время ожидания полной коллекции в буфере (от первого до последнего региона,
если измеримо; иначе опускаем).

Trade-off принят: жертвуем детализацией быстрых ветвей ради плоской схемы, стабильного
IPC и нулевой переделки GUI. `trace_branches` закрывает 90% потребности «где медленно».
Вариант B/C — будущая задача, если понадобится waterfall-виджет (вариант C из v1).

---

## Vertical slice (tracer bullet)

Фича multi-layer (плагины fan-out/fan-in + framework-буфер + GUI-панель). **Task 1.1 —
обязательный vertical slice:** провести непустой trace через `region_split → InspectorManager →
stitcher → gui` минимальным срезом (fan-out копирует trace, stitcher наследует critical-path
trace, GUI показывает непустую таблицу для region_pipeline). Это даёт feedback loop в первом
же Task: запустили `recipes/region_pipeline.yaml` с `INSPECTOR_FRAME_TRACE=1` → таблица
сегментов непуста. Без slice'а агент починит fan-out, потом fan-in, потом GUI — и впервые
увидит результат только в конце, отлаживая монолит из трёх ветвлений.

---

## Порядок выполнения

### Phase 1: Backend — корректный trace через ветвления

- Task 1.1: **[VERTICAL SLICE]** Прокинуть непустой trace через split→stitcher→gui (минимальный E2E срез) [PENDING]
  - **Module contract:** impl-only
- Task 1.2: Merge-семантика critical-path + trace_branches в stitcher (полная) [PENDING] (углубляет 1.1)
  - **Module contract:** impl-only
- Task 1.3: Helper'ы fan-out/fan-in в `frame_trace.py` (вынести логику из плагинов) [PENDING] (зависит от 1.1, 1.2)
  - **Module contract:** public-api-change

### Phase 2: GUI + наблюдаемость

- Task 2.1: GUI-агрегатор и панель: отображение critical-path + сводки ветвей [PENDING] (зависит от 1.2)
  - **Module contract:** impl-only

### Phase 3: Тесты и приёмка

- Task 3.1: Unit-тесты fan-out/fan-in trace (pytest) [PENDING] (зависит от 1.3)
  - **Module contract:** n/a
- Task 3.2: qt-mcp live smoke на region_pipeline + закрытие плана [PENDING] (зависит от 2.1, 3.1)
  - **Module contract:** n/a

---

### Task 1.1 — [VERTICAL SLICE] Непустой trace через split→stitcher→gui

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** За один проход рецепта `region_pipeline.yaml` с `INSPECTOR_FRAME_TRACE=1` merged-кадр приходит в GUI с НЕпустым `item["trace"]` (минимальная корректная семантика, без полировки).
**Context:** Сейчас fan-out шарит один list-объект trace между регионами, а stitcher строит dict с нуля и теряет trace целиком (см. «Диагностика», пункты 1 и 3). Этот slice чинит обе точки минимально — чтобы получить feedback loop до полной merge-семантики.
**Files:**
- `Plugins/processing/region_split/plugin.py` — в `process()` (через `@for_each`): на каждый out-item делать НЕЗАВИСИМУЮ копию `trace` (`list(item.get("trace", []))`), а не шарить ссылку из `{**item}`. Сохранить `capture_ts`, `_t_send`/`_from` как есть (`{**item}` их и так копирует — они скалярные).
- `Plugins/processing/stitcher/plugin.py` — в `process()` при построении выходного dict наследовать `trace` и `capture_ts` от одного из входных регионов (для slice — от `items[0]`; правильный выбор critical-path делает Task 1.2). НЕ строить trace с нуля.
**Steps:**
1. В `region_split.process` (тело `@for_each`): для ROI-регионов и default-региона при формировании out-dict заменить наследование trace на явную копию: после `**item` присвоить `"trace": list(item.get("trace", []))`. Убедиться, что `crop`-ветвь и `default`-ветвь обе получают независимый список.
2. В `stitcher.process`: к возвращаемому dict добавить `"trace": list(items[0].get("trace", []))` и `"capture_ts": items[0].get("capture_ts")` (пробросить t0, чтобы сквозная задержка на дисплее работала и для merged-кадра). Не трогать `seq_id`/`frame_id` (уже из items[0]).
3. Проверить, что декоратор `traced` (авто на `process`) теперь дописывает process-спаны в независимые списки ветвей и в наследованный trace stitcher'а.
**Acceptance criteria:**
- [ ] qt-mcp live smoke: `python multiprocess_prototype/run.py recipes/region_pipeline.yaml` c `INSPECTOR_FRAME_TRACE=1`; в логе `[FRAME-TRACE]` merged-кадра `trace` НЕ пустой и содержит хотя бы один transport- и один process-спан до stitcher.
- [ ] Без `INSPECTOR_FRAME_TRACE` — поведение не меняется (no-op; копия trace = `list([])` дёшево, но гейтить копирование под `frame_trace.enabled()` чтобы в проде не платить).
- [ ] Регионы не делят общий list-объект: два региона с разными плагинами (negative/grayscale) имеют разные process-спаны.
**Out of scope:** выбор critical-path (Task 1.2), trace_branches-сводка, GUI-полировка, вынос в helper.
**Edge cases:** пустая коллекция в stitcher (`items == []` → возврат `[]`, не падать); кадр без `trace` (флаг выключен) → `list(None or [])`.
**Dependencies:** нет (первый Task).
**Module contract:** impl-only

---

### Task 1.2 — Merge-семантика critical-path + trace_branches

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Stitcher наследует trace ПО САМОМУ МЕДЛЕННОМУ пути (critical path) и добавляет лёгкую сводку `trace_branches` + merge-спан — реализация принятого архитектурного решения (Вариант A).
**Context:** Task 1.1 наследует trace от `items[0]` (произвольная ветвь). Корректная семантика — самый медленный путь (он же end-to-end латентность кадра, т.к. остальные ветви ждали его в буфере InspectorManager). Это главное design-решение плана (см. раздел «КЛЮЧЕВОЕ АРХИТЕКТУРНОЕ РЕШЕНИЕ»).
**Files:**
- `Plugins/processing/stitcher/plugin.py` — заменить `items[0]`-наследование на выбор ветви с max суммой `ms` по её trace; собрать `trace_branches`; добавить merge-спан.
- `multiprocess_framework/modules/process_module/generic/frame_trace.py` — добавить `record_merge(item, node, branches, chosen, ms)` (новый kind `"merge"`), гейтнутый `_ENABLED`. Обновить docstring-контракт спанов (добавить merge-спан и `trace_branches`).
**Steps:**
1. В `stitcher.process`: вычислить для каждого входного item сумму `ms` его trace (`sum(s["ms"] for s in item.get("trace", []))`); выбрать ветвь-победителя (max сумма) → её trace наследует merged-кадр (`list(winner["trace"])`).
2. Собрать `trace_branches`: для каждой ветви `{"branch": item.get("region_name"), "total_ms": сумма, "spans": len(trace)}`; положить в `merged["trace_branches"]` (только под флагом).
3. Через новый `frame_trace.record_merge(merged, node=self._trace_node или "stitcher", branches=N, chosen=winner_name, ms=...)` дописать merge-спан в наследованный trace. `ms` — время ожидания коллекции (если доступно из метаданных; иначе опустить поле или 0). Учесть, что `self._trace_node` ставит оркестратор — взять его, fallback на `self.name`.
4. Всё новое — под `if frame_trace.enabled()`: в проде stitcher строит dict как раньше (нулевой overhead).
5. Обновить контракт-docstring `frame_trace.py`: добавить пример merge-спана и описание `trace_branches`.
**Acceptance criteria:**
- [ ] qt-mcp live smoke на `region_pipeline.yaml` (`INSPECTOR_FRAME_TRACE=1`): в `[FRAME-TRACE]` merged-кадра есть merge-спан `{"kind":"merge","node":"stitcher","branches":3,"chosen":"...","ms":...}` и `trace_branches` с 3 записями.
- [ ] Наследованный trace соответствует ветви с максимальной суммой ms (проверить логикой/логом: chosen == самая медленная).
- [ ] Без флага: stitcher не добавляет ни merge-спан, ни trace_branches (no-op).
- [ ] Размер `trace` merged-кадра = O(глубина одной ветви) + 1 merge-спан (не растёт от числа ветвей).
**Out of scope:** union/дерево (Варианты B/C), waterfall-виджет, изменение InspectorManager.
**Edge cases:** все ветви с пустым trace (флаг включён, но spans нет) → chosen = items[0], merge-спан с `ms=0`; неполная коллекция после timeout (regions < expected) — critical-path по тому, что пришло, `branches` = фактическое число.
**Dependencies:** Task 1.1.
**Module contract:** impl-only (stitcher) + public-api-change (frame_trace: новый публичный `record_merge`)

---

### Task 1.3 — Вынести fan-out/fan-in логику trace в frame_trace.py

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Логика «независимая копия trace при fan-out» и «critical-path-наследование при fan-in» живёт в `frame_trace.py` (framework-generic), плагины зовут helper'ы — не дублируют ad-hoc код.
**Context:** Проектное правило — инструментовка в framework-generic, плагины не должны нести trace-механику (см. `frame-trace-envelope.md`: «без правок каждого плагина»). Task 1.1/1.2 для скорости положили логику в плагины; здесь рефакторим в reusable helper'ы, чтобы будущие fan-out/fan-in плагины переиспользовали.
**Files:**
- `multiprocess_framework/modules/process_module/generic/frame_trace.py` — добавить `fork_trace(item) -> dict` (вернуть независимую копию trace для одного fan-out-выхода, no-op без флага) и `merge_trace(items) -> tuple[list, list]` (вернуть `(critical_path_trace, trace_branches)`).
- `Plugins/processing/region_split/plugin.py` — заменить inline-копию на `frame_trace.fork_trace`.
- `Plugins/processing/stitcher/plugin.py` — заменить inline critical-path логику на `frame_trace.merge_trace`.
**Steps:**
1. Реализовать `fork_trace(item)`: при `_ENABLED` вернуть `{"trace": list(item.get("trace", []))}` (плюс прокинуть `capture_ts`/`_t_send`/`_from` если нужно); при выключенном — пустой dict (плагин делает `{**item, **frame_trace.fork_trace(item)}`).
2. Реализовать `merge_trace(items)`: при `_ENABLED` выбрать critical-path ветвь, собрать `trace_branches`, вернуть `(winner_trace, branches)`; при выключенном — `([], [])`.
3. Переписать `region_split` и `stitcher` на helper'ы; убедиться, что поведение идентично Task 1.1/1.2 (тот же smoke-результат).
4. Обновить docstring frame_trace и таблицу «Точки инструментовки» — добавить fan-out/fan-in строки.
**Acceptance criteria:**
- [ ] qt-mcp live smoke на region_pipeline идентичен Task 1.2 (merge-спан + trace_branches на месте).
- [ ] `region_split`/`stitcher` не содержат inline trace-list-логики — только вызов helper'ов.
- [ ] `frame_trace.fork_trace`/`merge_trace` — no-op (возврат пустого/`([], [])`) без флага, нулевой overhead.
- [ ] Существующие тесты frame-trace (test_frame_trace_channel и пр.) зелёные.
**Out of scope:** менять линейную часть v1 (source_producer/data_receiver/pipeline_executor) — она корректна.
**Edge cases:** plugin без trace (старый плагин, флаг включён) — helper'ы graceful (пустой trace).
**Dependencies:** Task 1.1, Task 1.2.
**Module contract:** public-api-change (frame_trace: новые публичные `fork_trace`/`merge_trace`)

---

### Task 2.1 — GUI: critical-path таблица + сводка ветвей

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Панель trace в «Все процессы» корректно показывает разбивку для нелинейного пайплайна (critical-path сегменты) и сводку по ветвям из `trace_branches`.
**Context:** GUI-агрегатор (`record_trace_spans` + публикация `system.trace_segments`) написан под линейный trace (v1, Task 3 родителя). Для merged-кадра теперь приходит critical-path trace (уже плоский список — агрегатор работает как есть) + новый `trace_branches`. Нужно отобразить ветви и merge-спан, не сломав линейный случай.
**Files:**
- `multiprocess_prototype/frontend/app.py` (`_on_frame_received`, ~строки 675–683) — кроме `record_trace_spans(data.get("trace"))` прокинуть `data.get("trace_branches")` в окно; merge-спан уже в trace (агрегатор подхватит как обычный спан с kind=merge — проверить, что таблица его показывает).
- `multiprocess_prototype/frontend/app.py` (`_setup_timers`, ~строки 714–720) — публиковать `system.trace_branches` раз в секунду рядом с `system.trace_segments`.
- `multiprocess_prototype/frontend/widgets/.../_panels.py` (`AllProcessesPanel._build_trace_panel`, `_on_trace_segments`) — добавить отображение ветвей (компактная строка/мини-таблица «Ветвь · total_ms · spans») + подпись «critical path» к основной таблице. Скрыто без `INSPECTOR_FRAME_TRACE`.
- `multiprocess_prototype/frontend/.../main_window.py` (или где `record_trace_spans`/`reset_trace_segments`) — добавить `record_trace_branches`/`reset_trace_branches` (аккумулятор последней сводки).
**Steps:**
1. Найти точные пути `main_window.py`/`_panels.py` (grep по `record_trace_spans`, `_build_trace_panel`, `_on_trace_segments`).
2. В `MainWindow`: добавить аккумулятор `record_trace_branches(branches)` (хранит последнюю сводку) + `reset_trace_branches()`.
3. В `app.py`: в `_on_frame_received` под флагом вызвать `window.record_trace_branches(data.get("trace_branches"))`; в `_setup_timers` опубликовать `system.trace_branches`.
4. В `_panels.py`: подписаться на `system.trace_branches` через `bind_fanout`; отрисовать компактный блок ветвей под основной таблицей; пометить основную таблицу «critical path».
5. Проверить, что merge-спан (kind=merge) корректно отображается в основной таблице (или фильтруется/именуется осмысленно — «merge @ stitcher»).
**Acceptance criteria:**
- [ ] qt-mcp live smoke на region_pipeline (`INSPECTOR_FRAME_TRACE=1`): вкладка «Все процессы» показывает непустую таблицу critical-path + блок ветвей (3 ветви с total_ms).
- [ ] Линейный пайплайн (например `inspection_basic.yaml`) — таблица работает как в v1, блок ветвей пуст/скрыт (нет fan-in).
- [ ] Без флага — панель скрыта (как в v1).
- [ ] qt_snapshot подтверждает наличие виджетов ветвей; qt-mcp клик по вкладке не падает.
**Out of scope:** waterfall-виджет (вариант C), интерактивный drill-down по ветвям.
**Edge cases:** `trace_branches` отсутствует (линейный кадр) — блок ветвей не рисуется; merge-спан с `ms=0` — показать «—» вместо 0.
**Dependencies:** Task 1.2.
**Module contract:** impl-only

---

### Task 3.1 — Unit-тесты fan-out/fan-in trace

**Level:** Middle (Sonnet, normal)
**Assignee:** tester
**Goal:** pytest покрывает: независимость trace-копий при fan-out, critical-path-выбор и trace_branches при fan-in, no-op без флага.
**Context:** pytest-qt недостаточно для приёмки (см. memory `feedback_qt_mcp_smoke_verification`) — но unit-тесты ловят регрессии логики (выбор critical-path, независимость списков) дёшево и в CI. Приёмка f-аctory всё равно через qt-mcp (Task 3.2).
**Files:**
- `multiprocess_framework/modules/process_module/tests/test_frame_trace_fanin.py` — создать. Тесты helper'ов `fork_trace`/`merge_trace`/`record_merge` (Task 1.3).
- `Plugins/processing/region_split/tests/` и `Plugins/processing/stitcher/tests/` — добавить/расширить тест trace-поведения (если каталоги есть; иначе тесты на уровне framework helper'ов).
**Steps:**
1. Тест `fork_trace`: два out-item из одного item имеют РАЗНЫЕ list-объекты trace (мутация одного не трогает другой); под флагом и без (no-op).
2. Тест `merge_trace`: из 3 items с trace разной суммарной ms выбирается max (critical path); `trace_branches` содержит 3 записи с корректными `total_ms`/`spans`.
3. Тест `record_merge`: дописывает спан kind=merge с branches/chosen; no-op без флага (`frame_trace._ENABLED = False`).
4. Тест граничный: пустая коллекция, items без trace.
5. Переопределять флаг через `frame_trace._ENABLED = True/False` (как в существующих тестах — см. docstring frame_trace).
**Acceptance criteria:**
- [ ] `python scripts/run_framework_tests.py` (или `pytest` из корня) — новые тесты зелёные.
- [ ] Тест независимости fan-out падает на старом коде (shared list) и проходит на новом — доказывает фикс.
- [ ] Тест critical-path проверяет именно max-сумму, не items[0].
**Out of scope:** live-проверка сборки (Task 3.2), GUI-тесты панели.
**Edge cases:** см. Steps 4; clock skew не тестируем (wall-часы одной машины).
**Dependencies:** Task 1.3.
**Module contract:** n/a

---

### Task 3.2 — qt-mcp live smoke на region_pipeline + закрытие плана

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Финальная приёмка на реальном нелинейном пайплайне через qt-mcp + проставить чекбоксы/статус в плане.
**Context:** Обязательная приёмка живой сборкой (memory `feedback_qt_mcp_smoke_verification`): pytest-qt не доказывает реальную сборку трёх ветвей + буфер + стичер. Только запуск `region_pipeline.yaml` с флагом и проверка реального trace на дисплее.
**Files:**
- `plans/frame-trace-fanin.md` — обновить статус и чекбоксы Task'ов с хэшами коммитов.
- (опц.) `docs/claude/memory/` + `~/.claude/.../memory/` — обновить запись `project_telemetry_self_publish` (пункт fan-in trace DONE), dual-write.
**Steps:**
1. Запустить `python multiprocess_prototype/run.py recipes/region_pipeline.yaml` c `INSPECTOR_FRAME_TRACE=1` (на Windows — `$env:INSPECTOR_FRAME_TRACE=1` перед запуском; флаг наследуется spawn-процессами, выставить ДО run.py).
2. qt-mcp: дождаться кадров на дисплее (`main`), открыть вкладку «Все процессы», qt_snapshot панели trace.
3. Проверить: основная таблица critical-path непуста; блок ветвей показывает 3 ветви (region_0/region_1/region_default); в логе `[FRAME-TRACE]` есть merge-спан.
4. Контрольный запуск без флага — панель скрыта, прода-поведение без overhead (визуально кадры идут, trace пуст).
5. Запустить линейный `inspection_basic.yaml` с флагом — убедиться, что регрессии v1 нет (таблица как раньше, блок ветвей скрыт).
6. Проставить `[x]` + хэши в плане, обновить статус на DONE. Коммит `docs(plans):` с `Refs: plans/frame-trace-fanin.md`.
**Acceptance criteria:**
- [ ] qt-mcp snapshot: панель trace «Все процессы» с непустой critical-path таблицей + 3 ветви на region_pipeline.
- [ ] Лог merged-кадра содержит merge-спан и trace_branches.
- [ ] Линейный пайплайн без регрессий (v1 поведение сохранено).
- [ ] Без флага — нет панели, нет overhead.
- [ ] План закрыт: чекбоксы + хэши + статус DONE, memory обновлена (dual-write).
**Out of scope:** новые фичи, распределённые часы (NTP).
**Edge cases:** webcam недоступна (camera_id=0) — использовать симулятор-источник, если есть; иначе зафиксировать как пред-условие smoke.
**Dependencies:** Task 2.1, Task 3.1.
**Module contract:** n/a

---

## Риски и ограничения

- **Размер `trace` в IPC при fan-out.** Вариант A держит trace плоским (O(глубина одной
  ветви)); `trace_branches` — лёгкие агрегаты (без полных спанов). Рост IPC минимален.
  Если выбрать Вариант B (отвергнут) — рост O(N×глубина). Контроль: trace едет только
  под `INSPECTOR_FRAME_TRACE=1`; в проде поля нет.
- **Clock skew (из v1).** `time.time()` (wall) сравним только на одной машине; распределённо
  нужен NTP. critical-path по сумме `ms` корректен только при синхронных часах процессов
  на одном хосте (текущий случай). Отметить в docstring.
- **Overhead.** Все новые helper'ы (`fork_trace`/`merge_trace`/`record_merge`) гейтятся
  `_ENABLED`; в проде — один bool-чек, ноль аллокаций. Критично: НЕ копировать trace
  без флага (Task 1.1 edge case).
- **Семантическая потеря деталей быстрых ветвей** (trade-off Варианта A). Закрыто
  `trace_branches`-сводкой. Если понадобится полный per-branch waterfall — будущая задача
  (Вариант C, вне scope).
- **InspectorManager timeout flush.** При неполной коллекции (regions < expected после
  timeout) critical-path считается по фактически пришедшим — trace не врёт, `branches`
  отражает реальное число. Не падать на частичной коллекции (Task 1.2 edge case).
- **Декоратор `traced` и stitcher.** `traced` делит ms на `len(out)`; для stitcher (N→1,
  out=1) вся склейка пишется одному item — корректно, но merge-спан Task 1.2 добавляется
  ПОВЕРХ process-спана stitcher'а. Проверить, что оба попадают в наследованный trace.

## Out of scope (этой задачи)

- Union-trace и дерево ветвления (Варианты B/C) — будущая задача при необходимости waterfall.
- Распределённые часы (NTP) для multi-host.
- Изменение линейной инструментовки v1 (source_producer/data_receiver/pipeline_executor корректны).
- waterfall-виджет (вариант C визуализации из v1).
