# План: location-transparent транспорт + Join + фильтр виртуальной линии + рендер + io-debug

## Контекст (зачем)

Нужен классический фильтр **виртуальной линии (virtual tripwire / line-crossing)**: на вход — словарь со списком координат `[(x,y),...]`, фильтр проверяет вход точки в зону вдоль линии (или пересечение), копит уникальные объекты, гасит шум ±5 px. Линия: центр, угол, ширина зоны (пунктир с двух сторон). Фильтр сам не рисует (дисплей GUI показывает готовые пиксели) — отдаёт draw-params отдельному плагину-рисовальщику.

Владелец задал архитектурную планку: общение узлов **универсально и эффективно** — единый API через RouterManager+каналы, прозрачный к размещению: **co-located → быстрый локальный канал (передача ссылки, zero-copy); distributed → IPC**. Узел не знает, какой случай. Это продолжение направления transport-router-hub.

## Ключевые факты (расследование кода, HIGH confidence)

- **Zero-copy in-process уже есть**, но НЕ через каналы: прямая цепочка `_execute_chain` (`pipeline_executor.py:188`, по ссылке) + `chain_queue` (`generic_process.py:83`, `queue.Queue`).
- **`{proc}_local` канал создан** на `queue.Queue` (`process_communication.py:102`) — но **заготовка, не подключён** (нет `register_route`, не опрашивается).
- **`QueueChannel` полиморфен** (`queue_channel.py:64` — чистый `put()`): `queue.Queue` → ссылка (zero-copy); `multiprocessing.Queue` → pickle. Готовая основа location-transparency.
- **Нет co-location-проверки:** `_deliver_by_targets` (`router_manager.py:270-330`) всегда шлёт в `multiprocessing.Queue` (pickle; кадры обходят через SHM Claim Check).
- **RouterManager уже принимает multi-process** в `{proc}_data` (`_poll_all_channels:659`). **Новых каналов не нужно.** Async multi-channel / P3 не требуются.
- **`seq_id` штампуется** (`capture/plugin.py:153`), переживает IPC (в `msg["data"]`). **`sender`** ставится на msg-уровне (`process_communication.py:204`), но `_build_item` (`data_receiver.py:199-230`) не пробрасывает его в item. `sender` = имя **процесса** (не плагина) → для co-located различать входы по нему нельзя.
- **Корреляции по ключу нет в generic-виде**, но есть зародыш: `InspectorManager` буферизует по `(camera_id, seq_id)` + timeout-flush (захардкожено под fan-in регионов, count-trigger).

## Итоговая архитектура

Узлы общаются через RouterManager-каналы единым API `send_message(target, msg)`; транспорт прозрачен (local/remote). Многовходовый узел = **Join над входными каналами**, корреляция по `(seq_id, data_type)`. Co-located → локальные каналы → Join дёшев (latency-проблемы нет); distributed → IPC + left-join с малым окном.

```
детектор.detections → line_filter → {filtered(data_type=filtered), overlay(data_type=overlay)}  (seq_id наследуется)
камера/детектор.frame (data_type=frame) ─┐
line_filter.overlay ─────────────────────┤→ Join(seq_id, data_type) → {frame, overlay} → overlay_draw → display
line_filter.filtered ────────────────────────────────────→ (downstream: счётчик/БД/лог — опц.)
```
Транспорт каждого ребра: тот же процесс → `{proc}_local` (`queue.Queue`, ссылка); другой процесс → IPC.

### Этапы

| Этап | Что | Слой |
|------|-----|------|
| **0** | Location-transparent транспорт (Level 1) + теги `sender`/`data_type` + аудит `seq_id` | framework |
| **1** | `JoinInspectorManager` — корреляция N входов по `(seq_id, data_type)` | framework |
| **2** | `line_filter` + категория «Фильтр» | Plugins |
| **3** | `overlay_draw` (многовходовый, через Join) | Plugins |
| **4** | Рефакторинг `PluginRunner` (единый seam) | framework |
| **5** | Generic io-debug панель + «Заморозить» | framework + prototype |

Отложено (не предусловие): Level 2 (логические порты узла, проводка `address_aware_channel` в рантайм — настоящий P3); (A) модуляризация inspector_panel; (C) схема DrawCommand; (D) реестр категорий.

---

## Этап 0 — Location-transparent транспорт (Level 1) + теги

**Цель:** `send_message(target, msg)` прозрачно выбирает транспорт; Join различает входы по содержимому; `seq_id` стабилен.

**Транспорт (Level 1 адаптер, ~2-3 точки, reversible):**
- `RouterManager._deliver_by_targets` (`router_manager.py:309-325`) — fast-path: `if process == self.process.name` → слать в `{process}_local` канал (`queue.Queue`, zero-copy ссылка) из `ChannelRegistry`; иначе — существующий remote-путь (`queue_registry.send_to_queue`, IPC). Fallthrough на remote, если local не найден.
- `process_communication.py:99-108` — подключить `{proc}_local` к приёму (он уже создан): либо имя `{proc}_data_local`, либо добавить суффикс в фильтр.
- `data_receiver.py:138` — опрашивать local-канал (расширить `channel_types`).
- **НЕ трогать** `_execute_chain` — внутрицепочечная передача остаётся прямой (zero-copy), каналы ей не навязываем.
- Guard: co-located путь обязан использовать `queue.Queue` (ссылка), не `multiprocessing.Queue` (иначе вернётся pickle).
- **Риск мутабельности** (ссылка делится отправителем/получателем): для data-плоскости безопасно (однонаправленный поток, producer не мутирует после `put` — как уже работает `chain_queue`). Зафиксировать конвенцию «после отправки item не мутируем».

**Теги (для Join и io-debug):**
- `_build_item` (`data_receiver.py:216-228`) — добавить `sender` в пробрасываемые ключи (+1 строка).
- Конвенция `item["data_type]` (`"frame"`/`"overlay"`/`"detections"`/`"filtered"`): источник/плагин помечает выход; Join маппит по `data_type` (надёжно при co-located, в отличие от `sender`). `sender` — для distributed-маршрутизации.
- Аудит `Plugins/processing/*`: `seq_id`/`data_type` не теряются при пересборке item (где dict строится без `**item` — перенести ключи).

**Файлы:** `router_module/core/router_manager.py`, `process_module/communication/process_communication.py`, `process_module/generic/data_receiver.py`, конвенция в docs/ADR.

**Документировать:** `sender` ставится на msg-уровне (`process_communication.py:204`) — переживёт только если перенесён в item.

---

## Этап 1 — `JoinInspectorManager` (корреляция N входов)

Generic-слияние входов по корреляционному ключу — **обобщение `InspectorManager`** (тот же seam, та же timeout-flush механика). Это **вход многовходового узла**.

**Семантика:**
- **N именованных входов**, идентификация по `data_type` (primary = `frame`).
- **Ключ** — `seq_id`. Буфер по ключу собирает набор требуемых `data_type` (trigger = набор имён, **не** count).
- **Эмит** при полном наборе → `{**inputs}` вниз, ключ выселен.
- **Left-join:** primary + истёкшее окно без второстепенных → эмит primary (overlay опционален). **`max_age` 50–100 мс** (не 0.5 с как region-режим). **Auto-passthrough:** если опциональный вход неактивен K кадров (нет маршрута/упал) — не ждём его, эмитим primary немедленно (иначе FPS просядет на ожидании).
- **TTL/`max_buffer`:** протухшие наборы выселяются; счётчик дропов — в `_publish_state`.
- **Слияние значений:** list-ключи (`overlay`) — **конкатенация** («со всех линий суммируются»); скаляры — last-wins.

**Подмена в процессе:** конфиг процесса выбирает `JoinInspectorManager` vs `InspectorManager` (флаг режима inspector в `app_cfg`, читается в `GenericProcess._init_data_pipeline` `generic_process.py:87`). Backward-compat: region-режим сохраняется. Co-located → входы через `{proc}_local` → корреляция в том же процессе, дёшево.

**Палитра-обёртка:** узел `sync_join` в `Plugins/runtime/sync_join/` (метаданные+конфиг `inputs`/`primary`/`key_field`/`max_age`/`merge_policy`/`data_type_map`), активирует join-режим inspector процесса.

**Файлы:** `process_module/generic/join_inspector_manager.py` (или обобщить `inspector_manager.py`), правка `generic_process.py` (выбор режима), `Plugins/runtime/sync_join/`.

**Тесты:** порядок (overlay до/после frame), left-join по окну, auto-passthrough при неактивном входе, TTL+счётчик дропов, конкатенация list от 2 источников, backward-compat region-режима.

---

## Этап 2 — `line_filter` + категория «Фильтр»

Плагин-фильтр (категория `filter`), чистая логика. Кадр не трогает; выходы помечены `data_type`.

### Методы (многослойная защита от шума)
1. **Знаковое расстояние точка→линия.** Центр `(cx,cy)`, угол `θ`, нормаль `n=(−sinθ,cosθ)`; `signed_dist=(p−c)·n`. Зона: `|signed_dist|≤zone_width/2`. Линия edge-to-edge — клиппинг Liang–Barsky. **Линия+зона в overlay всегда, с 1-го кадра** (конфиг, не событие).
2. **Центроидный трекинг (SORT-lite):** жадный NN в `max_match_distance`; трек хранит `id`, позицию, прошлый знак, `hits`, `age`.
3. **Temporal confirmation (`min_hits`) + TTL (`max_age`).**
4. **`enter_zone` + гистерезис:** первый вход подтверждённого трека; повтор — после выхода за `w/2 + hysteresis_margin`.
5. **`cross_line` (tripwire):** смена знака `signed_dist`; направление наезд/выезд.
6. **Дедуп (NMS по радиусу):** кандидат отброшен, если есть точка в `dedup_radius` (евклид; cKDTree опц.).
7. **Выдача:** `filtered` (`data_type=filtered`) + `counted_total` + `overlay` (`data_type=overlay`, наследует `seq_id`).

### Поля (registers, дефолты с учётом ревью; **enforce `hysteresis_margin ≥ dedup_radius`** валидатором)
| Поле | Тип | Дефолт |
|------|-----|--------|
| `center_x`,`center_y` | int px | центр кадра |
| `angle` | float ° | 0 |
| `zone_width` | int px | 50 |
| `mode` | Literal[enter_zone,cross_line] | enter_zone |
| `dedup_radius` | int px | 5 |
| `min_hits` | int | 2 |
| `max_age` | int кадров | 30 |
| `max_match_distance` | int px | 20 |
| `hysteresis_margin` | int px (≥dedup_radius) | 6 |
| `emit_mode` | Literal[current,accumulated] | current |

### overlay (draw-params, фигуры с `type`+`group`)
```python
{"lines":[{"p1":[x1,y1],"p2":[x2,y2],"type":"line","group":"f1","thickness":2,"style":"solid"}],
 "dashed_lines":[{"p1":..,"p2":..,"type":"dashed","group":"f1","dash":8,"gap":6},{...}],
 "points":[{"xy":[x,y],"type":"point","group":"f1","radius":5,"label":"#id"}]}
```

### Категория «Фильтр»
- `palette_widget.py`: `CATEGORY_ORDER` += `"filter"`; `CATEGORY_LABELS["filter"]="Фильтр — фильтрация"`.
- `graph/constants.py`: `CATEGORY_COLORS["filter"]="#ff6b9d"`.

### Файлы
`Plugins/filter/__init__.py`, `Plugins/filter/line_filter/{__init__,plugin,config,registers,geometry,tracker}.py`, `tests/{test_plugin,test_geometry,test_tracker}.py`, `README.md`, `STATUS.md`. `thread_safe=False`. Образцы: `blob_detector/`, `contour_finder/`.

---

## Этап 3 — `overlay_draw`

Многовходовый узел (`frame`+`overlay`), входы сводит Join (Этап 1) → получает слитый item → **stateless, `thread_safe=True`**.

- **Выход** `rendered_frame`: `frame.copy()` + cv2 (`line` solid, сегментный dashed, `circle`, `putText`). «Суммирование многих линий» — конкатенацией в Join + списком фигур.
- **`color_table`** (list[dict], generic JSON-редактор `forms/factory.py:_build_json`, **высота 120→200px**): резолв `per-shape color → color_table[group] → color_table[type] → дефолт`.
- **Поля:** `color_table` + `default_line_color`/`default_point_color`/`default_thickness`/`default_point_radius`/`show_labels`.

**Файлы:** `Plugins/render/overlay_draw/{plugin,config,registers}.py`, `tests/`, `README.md`, `STATUS.md`. Образец `render_overlay/`.

---

## Этап 4 — Рефакторинг `PluginRunner` (предусловие io-debug) — ✅ DONE (37c7b8d0)

Два места вызова: processing — `PipelineExecutor._execute_chain` (`pipeline_executor.py:188`); source — `plugin.produce()` (`source_producer.py:83`).
- [x] `PluginRunner` с pre/post-хуками; **два метода** `call_process(plugin, items)` и `call_produce(plugin)` (у produce items нет). `for_each` (`base.py:29-52`) совместим — `call_process` зовёт `process(items)` как сейчас.
- [x] `GenericProcess` создаёт ОДИН раннер на процесс → проброшен в PipelineExecutor + SourceProducer (хук покрывает все плагины процесса).
- [x] Раннер прозрачен: исключение плагина пробрасывается (circuit breaker / NotImplementedError-обработка не тронуты); кривой хук изолируется (try/except+log); frame_trace не дублируется.
- [x] **Риск hot path** снят: 8 тестов `test_plugin_runner.py` (хуки, error-propagation, изоляция, overhead < 0.1мс/вызов); `process_module` 332 passed; qt-mcp smoke OK (линия рисуется, кадры текут через раннер).

---

## Этап 5 — Generic io-debug панель + «Заморозить» — ✅ DONE (6d307cd2)

Наблюдение in/out любого узла (фильтр, рендер, modbus, sync_join…).
- [x] **Бэкенд:** pre/post-хуки `PluginRunner` → `summarize_payload(in/out)` → `StateProxy.set` в `processes.{proc}.plugins.{plugin}.io_peek`.
  - [x] Summary **O(1) без пикселей:** `ndarray→{shape,dtype}`; `list→{len,head}`; `dict→ключи+усечённо`; строки усекаются. JSON-safe.
  - [x] **Throttle 1 Гц**, opt-in через поле `io_peek` процесса (default вкл). Грабли: прототип хранит StateProxy в `self._state_proxy` (фолбэк добавлен). **set, не merge** — снимок одной дельтой (merge флэттенит вложенные dict → подписка не видит снимок целиком).
- [x] **Фронтенд:** сворачиваемая секция «I/O (debug)» внизу карточки ноды; **ДВА окна Вход/Выход** равной высоты (QLabel авто-рост, без вложенного скролла, моноширинный шрифт покрупнее/белее по запросу владельца); читаемый статус «обработка/генерация · вход:N · выход:M»; **узкий fan-out** `processes.*.plugins.*.io_peek` + фильтр по активному пути (не glob `processes.*`). Кнопка **«Заморозить»** — UI-снапшот.
- [x] Тесты: 9 io_peek + 6 секции; `process_module`+pipeline 809 passed; qt-mcp smoke OK (line_filter: вход=frame-метаданные, выход=overlay/vlines).

**Файлы:** `process_module/.../plugins/io_peek.py`, `prototype/.../pipeline/inspector/io_debug_section.py`, правки `inspector_panel.py` + `generic_process.py` + конфиги.

---

## Итог: план ЗАВЕРШЁН ✅ (Этапы 0–5)

Все этапы DONE. Отложено (не блокеры, в новый чат при необходимости): Level 2 транспорт (логические порты узла, `address_aware_channel` в рантайм), модуляризация `inspector_panel`, схема DrawCommand, реестр категорий.

---

## Верификация (по этапам)

- **Э0:** unit — co-located `send_message` идёт через `queue.Queue` (zero-copy, не pickle); remote — IPC; `_build_item` пробрасывает `sender`; `data_type`/`seq_id` живут через цепочку. Микробенч: co-located латентность ≪ remote.
- **Э1:** порядок прихода, left-join по окну, auto-passthrough при неактивном входе, TTL+дропы, конкатенация overlay 2 источников, backward-compat region.
- **Э2:** `test_geometry` (signed_dist; клиппинг 0/90/180/−90 + 4 квадранта); `test_tracker`; `test_plugin` (дедуп ±5px→1; enter_zone+гистерезис; cross_line+направление; `min_hits` гасит вспышку; overlay содержит линию+зону на 1-м кадре без объектов; enforce `hysteresis_margin≥dedup_radius`).
- **Э3:** по слитому item рисуются линия/пунктир/точки; резолв цвета per-shape→group→type→дефолт; пустой overlay → кадр без фигур.
- **Э4:** `test_pipeline_executor.py` зелёный; overhead < 0.1 мс; `produce()` через `call_produce`.
- **Э5:** `summarize_payload` (shape/dtype, усечение, JSON-safe, без пикселей); throttle; qt-mcp — секция обновляется, «Заморозить» работает.
- **Сквозной qt-mcp smoke (обязателен — feedback_qt_mcp_smoke_verification):** `/run-proto`, Pipeline → категория «Фильтр», нода `line_filter`; собрать `камера/детектор → line_filter → (Join) → overlay_draw → display`; угол/центр/ширина; `qt_screenshot` — линия edge-to-edge, пунктир ±w/2, отмеченные точки; дрожащий объект не двоится. Проверить co-located (один процесс) и распределённый (line_filter в отдельном процессе) варианты.
- **Архитектура:** `python scripts/validate.py`; `mcp__sentrux__check_rules` (слои не нарушены).

---

## Замечания / память

- **Dict at Boundary:** между процессами JSON-safe dict/list; `overlay` без ndarray; io_peek summary — JSON-safe.
- **fix-forward:** framework-правки (Э0/1/4) — на улучшение, не вырезать ([[feedback_fix_framework_forward]]).
- **Транспорт установлен расследованием:** RouterManager не переделываем — Level 1 адаптер на готовой основе (`QueueChannel` полиморфен, `{proc}_local` есть). Level 2 (логические порты) — отдельный P3. Связь с [[project_transport_router_hub]].
- **`sync_join`/`line_filter` thread_safe = False** (буфер/state); `overlay_draw` = True.
- **Discovery:** `rglob("plugin.py")` — новые `Plugins/filter/`, `Plugins/runtime/sync_join/` обнаружатся.
- **Память владельца:** `Logger/Error/Stats` через ctx.log_*; commit-trailers `Why:`/`Layer:` (Э0/1/4→framework, 2/3→plugins, 5→mixed); dual-save в `plans/2026-06-08_line-filter-virtual.md`; чекбоксы с хешами ([[feedback_plan_checkboxes]]); внутреннее рассуждение EN, вывод RU ([[feedback_think_en_speak_ru]]).
- **Tradeoff product/engine:** Э0/1 — заметная транспортная работа до видимой фичи ([[project_priority_product_over_engine]]); принято осознанно ради «универсально и эффективно». Альтернатива (быстрый старт с co-located chain без Join) — доступна, если приоритет сместится.
