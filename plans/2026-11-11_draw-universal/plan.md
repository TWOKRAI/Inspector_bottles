# Plan: Универсальный рисовальщик — ядро пути показа (`Services/draw` + один `overlay_draw`)

- **Slug:** draw-universal
- **Дата:** 2026-11-11
- **Статус:** DRAFT
- **Plan review:** r1 CHANGES REQUESTED, 18 замечаний ([`review-plan-r1.md`](review-plan-r1.md)); правки внесены до approve, повторное ревью — впереди
- **Ветка:** feat/draw-universal

## Контекст

Сегодня на кадре рисуют пять мест со своим кодом cv2/PIL и своей копией кадра: `overlay_draw`, `circle_draw`,
`contour_draw`, `render_overlay` и подпись в `ml_inference`; кириллицу умеет только последнее. Решения владельца
2026-11-11 — [handoff](../../docs/handoffs/2026-11-11_draw-architecture-to-plan.md) `:13-23`. Архитектура —
[CTO r2](../../docs/reports/2026-11-11_draw-architecture-cto-r2.md) (главный), [CTO r1](../../docs/reports/2026-11-11_draw-architecture-cto.md)
(контракты, замеры). План — только путь показа: Ф0–Ф3, Ф4 по желанию; из готового — [`design.md`](design.md) §2.

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
| Владеет | `Services/draw` (фигуры, `lower`, бэкенд cv2, шрифты, текст-патч, conformance, mapping/styles); плагин `overlay_draw`; `ItemTemplate`/`get_path`/`RateGate` в SDK плагинов framework |
| Берёт | ничего: нижний слой группы |
| Даёт | шрифты и текст-патч → layer-render Ф7; словарь фигур → разметка и layer-render Ф9; `ItemTemplate`/`RateGate` → DS-1 (`backlog.md:77`); `scene` → пары 5a |
| Порядок | первым. Task 1.4 открывает DS-1 (∥ Ф2–Ф3; общий `dataset_circle_capture.yaml` — Task 2.2, не в одной волне). layer-render — после Ф1 (решение 9); dataset-annotation — после В2, DS-1 и Ф1 |

Пересечения с dataset-annotation, где этот план — сторона (рекомендации — в В2–В4):
хранение меток — решение 8 новее отказа от `.json` (`dataset-annotation/plan.md:73-74`): истина — пара кадр + `.json`;
формат фигуры — пиксели `Services/draw` (r1 `:60-66`), доли YOLO только в экспорте (`phase-1-dataset-service.md:27-28`);
экспорт — перевод фигур в `Services/draw/export.py`, снимок датасета — сервис датасета; рамки на канве — интерактив у
canvas layer-render, фигуры и стили у `draw`; обучение — только на чистом кадре (`dataset-annotation/plan.md:100`).

`overlay_draw` правят ещё четыре плана, контракты держит Task 1.1: три — в [`design.md`](design.md) §4, четвёртый
(`plans/dataset-circle-capture.md:29`) только называет плагин. `plans/draw-mode-rework/` — плоттер: совпадение имени, не сосед.

## Бюджет

Оценка, не замер. Формула: **участники × ~56k стартового контекста + работа**. Ставки: ревью спеки ~70k, тестер ~150k,
исполнитель 150–300k, инъекции ~50k, ревью ~100–150k. Числа ревью r1 (п. g) приняты.

| Фаза | Задач | Запусков: план → r1 | Токенов: план → r1 |
|---|---|---|---|
| Ф0 | 1 | 4 → 4 | 0,35M → ~0,37M |
| Ф1 | 4 | ~20 → 24 (по 6) | 2,5M → ~2,7M |
| Ф2 | 3 | ~11 → 13 | 1,3M → ~1,4M |
| Ф3 | 1 | ~4 → 4 | 0,5M → ~0,5M |
| Приёмка `cto` ×2 | — | 2 → 2 | 0,4M → ~0,8M |
| Повторные ревью | — | — → ~1 | — → ~0,35M |
| **Итого Ф0–Ф3** | 9 | ~41 → **~48** | 5,0M → **~6,0M** (5,2–6,8M) |
| Ф4 (опц.) | 2 | ~9 | 1,0M → ~1,1M |

48 × 56k ≈ 2,7M старта + ~3,4M работы. Сумма строк 6,1M, ревью округлило до 6,0M; иной ошибки нет. Задача за 2× своей
доли — стоп и вопрос владельцу. Пересчёт — записью в `amendments.md` после каждой фазы.

## Порядок выполнения

### Phase 0: база

**Цель фазы:** настоящие числа стенда до правок.

- Task 0.1: базовые замеры рисования (стенд, Orin) и скрипт `scripts/draw_bench` [PENDING]

### Phase 1: ядро `Services/draw`

**Цель фазы:** `overlay_draw` рисует через ядро; текст, шрифты, реестр бэкендов, conformance; помощники SDK.

- Task 1.1: ядро: сцена → `lower` → cv2; `scene_from_overlay`; `overlay_draw` через ядро **[VERTICAL SLICE]** [PENDING] (после 0.1)
- Task 1.2: текст альфа-патчем, `FontRegistry`, встроенный шрифт (решение В1) [PENDING] (после 1.1)
- Task 1.3: `rect`, `polyline`, заливка с альфой; правила реестра бэкендов; набор conformance [PENDING] (после 1.2)
- Task 1.4: `ItemTemplate`, `get_path`, `RateGate` в SDK плагинов framework [PENDING] (после 0.1; ∥ 1.1–1.3)

### Phase 2: mapping и замена `circle_draw` / `contour_draw`

**Цель фазы:** узел рисует по правилам из рецепта; одна копия кадра на ветку.

- Task 2.1: регистры `mapping`, `styles`, `burn`, `max_fps`, `backend`; выход `scene`; входы данных [PENDING] (после 1.3, 1.4);
  затем `docs-writer` (`overlay_draw/README.md`) → reviewer; литералы A11 — приложение `tasks/2.1-literals.md` (не задача)
- Task 2.2: рецепты: `circle_draw`, `contour_draw` → правила `overlay_draw` [PENDING] (после 2.1)
- Task 2.3: опись остальных мест рисования; пометки FROZEN [PENDING] (Middle, developer; выход «D — неясно»; после 2.2)

### Phase 3: чистый кадр

**Цель фазы:** узел данных не рисует.

- Task 3.1: `ml_inference` выдаёт только данные; ветка `recog_draw` в трёх рецептах [PENDING] (после 2.2)

### Phase 4: маска и рамки (опционально — решение владельца после Ф3)

**Цель фазы:** `render_overlay` заменён правилами.

- Task 4.1: фигура `mask` патчем по рамке маски [PENDING] (после 1.3)
- Task 4.2: топологии `inspection_basic` / `inspection_full` на `overlay_draw` [PENDING] (после 4.1, 2.1)

## Гейты

- Каждая задача — стадии 0–5 (`.claude/CLAUDE.md` → «Task launch convention»), цепочка — в `Handoff`. Новый механизм —
  слепой `tester` до кода; подключение готового — REDS у исполнителя (`team-protocol` §3, Д47).
- До 1.1 лид правит Task 3.4 плана camera-device-service (`tasks/3.4.md:6,20`): `Plugins/render/overlay_draw/plugin.py` и
  `test_overlay_copy.py` — из её FILES, `:113` → `:120`; запись в её `amendments.md`. Иначе два владельца `plugin.py`.
- `sentrux check .` после 1.1, 1.4, 2.1 — 0 нарушений; границы `Services/draw` вводит Task 1.1.
- Тесты — через `machine_gate.sh`; полный suite — у лида на границе фазы. Рецепт — тем же `SystemBlueprint.check`, что у
  загрузчика (урок `feedback_a_recipe_test_must_run_the_same_check_as_the_launcher.md`); `test_topology_recipes_check.py`
  видит только `backend/topology/`.
- Приёмка `cto` — после Ф1 и Ф3 (Ф2 вместе с Ф3). FREEZE: старые плагины, регистры, тесты не удаляются.

## Риски

- Подписи меняют вид: Hershey → FreeType (1.2), Arial Bold → DejaVu Bold (3.1); принимает владелец глазами на стенде.
- Слепой тест A11 (`overlay_draw/tests/test_overlay_port_join_catalog.py:55-57`) краснеет в 2.1 намеренно; литерал — запись лида.
- Снимок полей регистров `catalog_register_fields.txt`: 9 новых полей краснят `test_catalog_kind_roundtrip.py` (2.1).
- Снимок сборки `hikvision_letter_robot.build.json` краснеет в 2.2 и 3.1: лид — `UPDATE_BUILD_SNAPSHOTS=1`, читает дифф.
- Регистр `show_labels` (`overlay_draw/plugin.py:159`) без пина молча перестаёт работать после 1.2: RED в 1.2.
- Потокобезопасность: `overlay_draw.thread_safe = True` — замок на `drawn`/`skipped` и подмену правил (2.1); `FreeTypeFont` (1.2).
- `letter_robot_sim` и `hikvision_letter_robot` правятся одинаково: `test_letter_robot_sim_diff.py` сверяет их.
- Числа CTO — macOS arm64; Ф0 первой. Остальное — [`design.md`](design.md) §5.

## Следующие планы

Не задачи плана; порядок — CTO r1 §5, r2 §3.
- 5a: пары `labeling` + `frame_saver` с DS-1 (баги `frame_saver` — handoff `:47`; вопрос r2 №4). 5b: сортировщик. 5c: экспорт
  YOLO/COCO из `scene`; `validate_scene`, `transform_scene`.
- L2/L3: контуры и режим «Разметка» — после пересмотра layer-render; вопросы r2 №2 (LR-001 при Ф7), №5 (L2 до/после Ф5).
- Ф6: второй бэкенд — только если ветка показа после Ф4 дороже 5 мс p95 на Orin.
- Остальные места рисования из описи Task 2.3; пересечения синтетики O1–O5 — при пересмотре layer-render.

## Открытые вопросы

- [ ] **В1 (r2 №3).** Класть DejaVu Sans и Sans Bold (1,46 МБ, `.venv/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf/`,
  лицензия `LICENSE_DEJAVU` — лид цитирует в вопросе) в `Services/draw/fonts/`? Спрашивается **при одобрении плана**,
  параллельно с Ф0, 1.1, 1.4 (они не ждут; 1.2 ждёт). Умолчание — да. «Нет» = только системный шрифт (список как
  `_FONT_CANDIDATES`, `ml_inference/plugin/plugin.py:40-45`); реестр и `data/fonts/` остаются, `fonts/` не создаётся.
  Видимо: вид и ширина подписей зависят от машины (DejaVu Bold 252 px, Arial Bold 200 px, r2 `:197`), тесты текста — с
  допуском. Пересборки 1.2 нет: лид правит её шаг 0 записью в `amendments.md`. — владелец
- [ ] **В2.** Сведение `dataset-annotation` и `Services/labeling` (таблица выше). Рекомендация: один пакет; план
  dataset-annotation пересобрать на паре и фигурах `draw` после DS-1. Блокирует только dataset-annotation. — владелец
- [ ] **В3 (O6, O7).** Экспорт для `ml_train` и YOLO/COCO планируют трое: layer-render (`plan.md:156-157`), dataset-annotation
  (`phase-4-quality-export.md:108`), CTO (`Services/draw/export.py`). Рекомендация: перевод фигур — одна функция в
  `draw/export.py`; раскладка папок — сервис датасета. Задач этого плана не блокирует. — владелец
- [ ] **В4 (O8).** Сбор кадров: новый `dataset_capture` (`dataset-annotation/phase-3-capture.md:18-20`) или `frame_saver` с
  DS-1 (`backlog.md:77`). Рекомендация: `frame_saver`. Задач этого плана не блокирует. — владелец
- [ ] **В5 (ревью r1, п. 16).** Оставить ли в плане набор conformance 1.3 под второй бэкенд (`check_backend`, `exact_as`,
  `reference=`, `auto`, три фейковых бэкенда, ≥ 8 сцен) и фильтры `bucket`/`safe` 1.4 (только для DS-1, плана нет) или отложить?
  Ревью (ponytail): отложить — второй бэкенд не раньше Ф6, ценность для cv2 (двойное смешивание, защита вне рамки) — 2–3
  пиксельных теста, фильтры — в DS-1. CTO (r1 §5; решения владельца 2, 6): оставить — набор есть контракт сменной
  реализации, фильтры идут в общий помощник сразу. Не решено; бюджет при «отложить» не пересчитан. — владелец

## Решения (decisions log)

- **2026-11-11:** план собран по handoff и CTO r1/r2; 9 задач на Ф0–Ф3 и 2 на Ф4 вместо фаз 0–6, остальное — «Следующие
  планы» (владелец: «план не раздувать»).
- **2026-11-11:** старые плагины — эталон для литералов sha256 до правки, не оракул в тестах.

## Итог

<!-- Заполняется перед `plans_ledger.py close`. -->

## Injections

| property | predicted red | observed red |
|---|---|---|
