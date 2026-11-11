# Plan: Универсальный рисовальщик — ядро пути показа (`Services/draw` + один `overlay_draw`)

- **Slug:** draw-universal
- **Дата:** 2026-11-11
- **Статус:** APPROVED 2026-11-11
- **Plan review:** CHANGES 2 (r1 — 18 ([`review-plan-r1.md`](review-plan-r1.md)), r2 — 6 блокеров + 7 мелких ([`review-plan-r2.md`](review-plan-r2.md)), правки внесены); владелец утвердил 2026-11-11
- **Ветка:** feat/draw-universal

## Контекст

Сегодня на кадре рисуют пять мест со своим кодом cv2/PIL и своей копией кадра: `overlay_draw`, `circle_draw`,
`contour_draw`, `render_overlay` и подпись в `ml_inference`; кириллицу умеет только последнее. Решения владельца
2026-11-11 — [handoff](../../docs/handoffs/2026-11-11_draw-architecture-to-plan.md) `:13-23`. Архитектура —
[CTO r2](../../docs/reports/2026-11-11_draw-architecture-cto-r2.md) (главный), [CTO r1](../../docs/reports/2026-11-11_draw-architecture-cto.md)
(контракты, замеры). План — только путь показа: Ф0–Ф3, Ф4 по желанию, последней — Task 5.1 (отложено, В5); из готового — [`design.md`](design.md) §2.

## Цели

1. Ф0: базовые числа до любой правки: мс на кадр пяти мест рисования и цепочки `circle_draw` → `overlay_draw`, частота
   показа, дропы за 30 с. Orin — число или строка «недоступен».
2. Ф1: `overlay_draw` рисует через `Services/draw`. 8 рецептов с `overlay_draw` не меняются. Фигуры без текста
   побайтно равны выходу старого кода (эталоны sha256 сняты до правки). Мс на кадр не выше базы Ф0 + 10 %.
3. Ф1: подпись с кириллицей — альфа-патчем; на стенде не меньше чем в 3 раза дешевле полнокадрового
   `_put_text_unicode` (CTO, macOS: 3,36 → 0,63 мс без кэша).
4. Ф2: в процессе `draw` одна копия кадра вместо двух; `circle_draw` и `contour_draw` не стоят ни в одном рецепте (FROZEN,
   код и тесты целы); при входе 100 кадр/с и `max_fps: 30` доля `skipped / (drawn + skipped)` — 0,6–0,8 (ожидаемо 0,75).
5. Ф3: кадр на входе `layout` (там, где он есть) побайтно равен кадру после `center_crop`; подпись рисует ветка `recog_draw`.
6. Ф4 (опц.): ветка показа `inspection_full` на 1080p — рисование не дороже 3 мс на кадр (r1: 35–39 мс).

## Out of scope

Разметка, пары «кадр + `.json`», сортировщик, экспорт YOLO/COCO, контуры, второй бэкенд — «Следующие планы». Правка
`fps_limit` во framework (решение 7) — отдельная необязательная задача. `layer-render` не правится (решение 9), кроме ссылки.

## Группа: рисование и разметка

Карта группы — [`plans/queue/group-draw-dataset.md`](../queue/group-draw-dataset.md): владение, пересечения O1–O11, порядок.

| Этот план | Что |
|---|---|
| Владеет | `Services/draw` (фигуры, `lower`, cv2, шрифты, текст-патч, mapping/styles; conformance — 5.1); `overlay_draw`; `ItemTemplate`/`get_path`/`RateGate` в SDK плагинов |
| Берёт | ничего: нижний слой группы |
| Даёт | шрифты и текст-патч → layer-render Ф7; словарь фигур → разметка и layer-render Ф9; `ItemTemplate`/`RateGate` → DS-1 (`backlog.md:77`); `scene` → пары 5a |
| Порядок | первым. Task 1.4 открывает DS-1 (∥ Ф2–Ф3; общий `dataset_circle_capture.yaml` — Task 2.2, не в одной волне). layer-render — после Ф1 (решение 9); dataset-annotation — после DS-1 и Ф1 (В2 решён) |

Пересечения с dataset-annotation (решения В2–В4 — decisions log): истина меток — пара кадр + `.json` (решение 8 новее
`dataset-annotation/plan.md:73-74`); фигура — пиксели `Services/draw` (r1 `:60-66`), доли YOLO только в экспорте; экспорт —
`Services/draw/export.py`, снимок датасета — сервис датасета; интерактив на канве — layer-render; обучение — на чистом
кадре (`dataset-annotation/plan.md:100`).

`overlay_draw` правят ещё четыре плана, контракты держит Task 1.1: три — [`design.md`](design.md) §4, четвёртый
(`plans/dataset-circle-capture.md:29`) только называет плагин. `plans/draw-mode-rework/` — плоттер, не сосед.

## Бюджет

Оценка: **участники × ~56k стартового контекста + работа**. Ф0–Ф3 — **~5,95M токенов (5,2–6,7M), ~46 запусков**
(было ~6,2M / ~49: часть 1.3 и 1.4 ушла в 5.1); Task 5.1 отдельно **~0,5M, 5 запусков**; Ф4 ~1,05M. Таблица —
[`amendments.md`](amendments.md) §1–2. Задача за 2× своей доли — стоп и вопрос владельцу; пересчёт — записью в
`amendments.md` после каждой фазы.

## Порядок выполнения

### Phase 0: база

**Цель фазы:** настоящие числа стенда до правок.

- Task 0.1: базовые замеры рисования (стенд, Orin) и скрипт `scripts/draw_bench` [PENDING]

### Phase 1: ядро `Services/draw`

**Цель фазы:** `overlay_draw` рисует через ядро; текст, шрифты, реестр бэкендов; помощники SDK.

- Task 1.1: ядро: сцена → `lower` → cv2; `scene_from_overlay`; `overlay_draw` через ядро **[VERTICAL SLICE]** [PENDING] (после 0.1)
- Task 1.2: текст альфа-патчем, `FontRegistry`, встроенный шрифт (В1: да) [PENDING] (после 1.1)
- Task 1.3: `rect`, `polyline`, заливка с альфой; правила реестра бэкендов [PENDING] (после 1.2)
- Task 1.4: `ItemTemplate`, `get_path`, `RateGate` в SDK плагинов framework [PENDING] (после 0.1; ∥ 1.1–1.3)

### Phase 2: mapping и замена `circle_draw` / `contour_draw`

**Цель фазы:** узел рисует по правилам из рецепта; одна копия кадра на ветку.

- Task 2.1: регистры `mapping`, `styles`, `burn`, `max_fps`, `backend`; выход `scene`; входы данных [PENDING] (после 1.3, 1.4);
  затем `docs-writer` (`overlay_draw/README.md`, раздел «Mapping» в `Services/draw/README.md`) → reviewer; литералы A11 — приложение `tasks/2.1-literals.md` (не задача)
- Task 2.2: рецепты: `circle_draw`, `contour_draw` → правила `overlay_draw` [PENDING] (после 2.1)
- Task 2.3: опись остальных мест рисования; пометки FROZEN [PENDING] (Middle, developer; выход «D — неясно»; после 2.2)

### Phase 3: чистый кадр

**Цель фазы:** узел данных не рисует.

- Task 3.1: `ml_inference` выдаёт только данные; ветка `recog_draw` в трёх рецептах [PENDING] (после 2.2)

### Phase 4: маска и рамки (опционально — решение владельца после Ф3)

**Цель фазы:** `render_overlay` заменён правилами.

- Task 4.1: фигура `mask` патчем по рамке маски [PENDING] (после 1.3)
- Task 4.2: топологии `inspection_basic` / `inspection_full` на `overlay_draw` [PENDING] (после 4.1, 2.1)

### Phase 5: отложенное (В5) — последней, даже если Ф4 не запускалась

**Цель фазы:** набор conformance под второй бэкенд и фильтры `bucket`/`safe`.

- Task 5.1: набор conformance (`check_backend`, сцены) и фильтры `bucket`/`safe` [PENDING] (последняя; после 1.3, 1.4, 4.2)

## Гейты

- Каждая задача — стадии 0–5 (`.claude/CLAUDE.md`), цепочка — в `Handoff`. Новый механизм — слепой `tester` до кода;
  подключение готового — REDS у исполнителя (`team-protocol` §3, Д47).
- Владелец полосы camera-device-service правит её Task 3.4 через `amend` (`tasks/3.4.md:6,20`: `overlay_draw/plugin.py` и
  `test_overlay_copy.py` — из FILES, `:113` → `:120`); 1.1 стартует после записи или после его подтверждения, что 3.4 не
  стартует раньше 1.1. Если 3.4 придёт первой: 1.1 берёт её базу `test_overlay_copy.py` и снимает свой дубль.
- `sentrux check .` после 1.1, 1.4, 2.1 — 0 нарушений; границы `Services/draw` вводит Task 1.1.
- Тесты — через `machine_gate.sh`; полный suite — у лида на границе фазы. Рецепт — путём загрузчика
  (`SystemBuilder.from_manifest(...).build()`, урок `feedback_a_recipe_test_must_run_the_same_check_as_the_launcher.md`);
  `test_topology_recipes_check.py` видит только `backend/topology/`.
- Приёмка `cto` — после Ф1 и Ф3 (Ф2 вместе с Ф3). FREEZE: старые плагины, регистры, тесты не удаляются.

## Риски

- Подписи меняют вид: Hershey → FreeType (1.2), Arial Bold → DejaVu Bold (3.1); принимает владелец на стенде.
- Слепой тест A11 (`test_overlay_port_join_catalog.py:55-57`) краснеет в 2.1 намеренно; литерал — запись лида.
- Снимок полей регистров `catalog_register_fields.txt`: 9 новых полей краснят `test_catalog_kind_roundtrip.py` (2.1).
- Снимок сборки `hikvision_letter_robot.build.json` краснеет в 2.2 и 3.1: лид — `UPDATE_BUILD_SNAPSHOTS=1`, читает дифф.
- Регистр `show_labels` (`overlay_draw/plugin.py:159`) без пина молча перестаёт работать после 1.2: RED в 1.2.
- Потокобезопасность (`thread_safe = True`): замок на `drawn`/`skipped` и подмену правил (2.1); `FreeTypeFont` (1.2).
- `letter_robot_sim` и `hikvision_letter_robot` правятся одинаково: `test_letter_robot_sim_diff.py` сверяет их.
- Числа CTO — macOS arm64; Ф0 первой. Остальное — [`design.md`](design.md) §5.

## Следующие планы

Не задачи плана; порядок — CTO r1 §5, r2 §3.
- 5a: пары `labeling` + `frame_saver` с DS-1 (handoff `:47`; вопрос r2 №4). 5b: сортировщик. 5c: экспорт YOLO/COCO из
  `scene`; `validate_scene`, `transform_scene`.
- L2/L3: контуры и режим «Разметка» — после пересмотра layer-render; вопросы r2 №2 (LR-001 при Ф7), №5 (L2 до/после Ф5).
- Ф6: второй бэкенд — только если ветка показа после Ф4 дороже 5 мс p95 на Orin.
- Остальные места рисования (опись 2.3); синтетика O1–O5 — при пересмотре layer-render.

## Открытые вопросы

- [x] **В1 (r2 №3).** Класть DejaVu Sans и Sans Bold (1,46 МБ) в `Services/draw/fonts/`? → решено, см. decisions log.
- [x] **В2.** Сведение `dataset-annotation` и `Services/labeling`: один пакет? → решено, см. decisions log.
- [x] **В3 (O6, O7).** Перевод фигур в YOLO/COCO — `draw/export.py`, раскладка папок — сервис датасета? → решено, см. decisions log.
- [x] **В4 (O8).** Сбор кадров: `frame_saver` вместо нового `dataset_capture`? → решено, см. decisions log.
- [x] **В5 (ревью r1, п. 16).** Оставить conformance 1.3 и фильтры `bucket`/`safe` 1.4 или отложить? → решено, см. decisions log.

## Решения (decisions log)

- **2026-11-11:** 9 задач на Ф0–Ф3 и 2 на Ф4 вместо фаз 0–6, остальное — «Следующие планы» (владелец: «план не раздувать»).
- **2026-11-11:** старые плагины — эталон для литералов sha256 до правки, не оракул в тестах.
- **2026-11-11, владелец, В1:** да — DejaVu Sans и Sans Bold в `Services/draw/fonts/`; Task 1.2 не ждёт ответа.
- **2026-11-11, владелец, В2:** да — один пакет (dataset-annotation + `Services/labeling`); блокирует только dataset-annotation.
- **2026-11-11, владелец, В3:** да — фигура → YOLO/COCO в `Services/draw/export.py`, раскладка папок — в сервисе датасета.
- **2026-11-11, владелец, В4:** да — `frame_saver`; «можно переименовать, если нужно будет».
- **2026-11-11, владелец, В5:** да, но отложить на самый потом — conformance и `bucket`/`safe` остаются в плане, вынесены из 1.3, 1.4, 4.1 в последнюю Task 5.1; бюджет — `amendments.md` §2.

## Итог

<!-- Заполняется перед `plans_ledger.py close`. -->

## Injections

| property | predicted red | observed red |
|---|---|---|
