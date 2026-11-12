# Plan: Универсальный рисовальщик — ядро пути показа (`Services/draw` + один `overlay_draw`)

- **Slug:** draw-universal
- **Дата:** 2026-11-11
- **Статус:** DRAFT
- **Plan review:** PENDING (ревью `reviewer` MODE: plan запущено 2026-11-11; вердикт — в handoff `docs/handoffs/2026-11-11_draw-universal-plan.md`)
- **Ветка:** feat/draw-universal

## Контекст

Сегодня на кадре рисуют пять мест со своим кодом cv2/PIL и своей копией кадра: `overlay_draw`, `circle_draw`,
`contour_draw`, `render_overlay` и подпись внутри `ml_inference`; кириллицу умеет только последнее. Решения владельца
2026-11-11 — [handoff](../../docs/handoffs/2026-11-11_draw-architecture-to-plan.md) строки 13–23. Архитектура —
[CTO r2](../../docs/reports/2026-11-11_draw-architecture-cto-r2.md) (главный) и
[CTO r1](../../docs/reports/2026-11-11_draw-architecture-cto.md) (контракты, замеры, фазы). Этот план — только путь
показа: Ф0–Ф3, Ф4 по желанию. Собираем из готового, не пишем заново: что откуда берётся — [`design.md`](design.md) §2.

## Цели

1. Ф0: таблица базовых чисел до любой правки: мс на кадр каждого из пяти мест рисования на стенде, частота показа,
   дропы за 30 с. Orin — число или явная строка «недоступен».
2. Ф1: `overlay_draw` рисует через `Services/draw`. 8 рецептов с `overlay_draw` не меняются. Фигуры без текста
   побайтно равны выходу старого кода (эталоны sha256 сняты до правки). Мс на кадр не выше базы Ф0 + 10 %.
3. Ф1: подпись с кириллицей — альфа-патчем; на стенде не меньше чем в 3 раза дешевле полнокадрового
   `_put_text_unicode` (CTO, macOS: 3,36 → 0,63 мс без кэша).
4. Ф2: в процессе `draw` одна копия кадра вместо двух; `circle_draw` и `contour_draw` не стоят ни в одном рецепте
   (FROZEN, код и тесты целы); при входе 100 кадр/с и `max_fps: 30` доля `skipped / (drawn + skipped)` — 0,6–0,8.
5. Ф3: кадр на входе `layout` побайтно равен кадру после `center_crop`; подпись распознавания рисует ветка `recog_draw`.
6. Ф4 (опц.): ветка показа `inspection_full` на 1080p — рисование не дороже 3 мс на кадр (r1: 35–39 мс).

## Out of scope

Разметка, пары «кадр + `.json`», сортировщик, экспорт YOLO/COCO, контуры, второй бэкенд — раздел «Следующие планы».
Правка `fps_limit` во framework (решение владельца 7) — необязательная отдельная задача. План `layer-render` не
правится (решение владельца 9), кроме обратной ссылки.

## Группа: рисование и разметка

Карта группы — [`plans/queue/group-draw-dataset.md`](../queue/group-draw-dataset.md): состав, владение, пересечения
O1–O11 с file:line, порядок. Здесь — только то, что касается этого плана.

| Этот план | Что |
|---|---|
| Владеет | `Services/draw` (фигуры, `lower`, бэкенд cv2, шрифты, текст-патч, conformance, mapping/styles); плагин `overlay_draw`; `ItemTemplate`/`get_path`/`RateGate` в SDK плагинов framework |
| Берёт | ничего: нижний слой группы |
| Даёт | реестр шрифтов и текст-патч → layer-render Ф7; словарь фигур → разметка и layer-render Ф9; `ItemTemplate`/`RateGate` → DS-1 (`plans/queue/backlog.md:77`); выход `scene` → пары 5a |
| Порядок | первым. Task 1.4 открывает DS-1 (∥ Ф2–Ф3; общий файл `dataset_circle_capture.yaml` — Task 2.2, не в одной волне). Пересмотр layer-render — после Ф1 (решение 9). dataset-annotation — после В2, не раньше DS-1 и Ф1 |

Пересечения с dataset-annotation, где этот план — сторона (рекомендации — в В2–В4):

| Что | dataset-annotation | draw-universal / CTO | Кто владеет (рекомендация) |
|---|---|---|---|
| Хранение меток | SQLite + картинки по хешу; JSON рядом отклонён — `plan.md:67-75` (`:73-74`) | `.json` рядом — решение 8 (handoff `:22`); `pairs.py` — r2 `:85, :100-111` | решение 8 новее: истина — пара |
| Формат фигуры | `boxes_json` `{cls,cx,cy,w,h}` в долях — `phase-1-dataset-service.md:27-28` | словарь фигур в пикселях — r1 `:60-66`, r2 `:84` | `Services/draw`; доли YOLO — только в экспорте |
| Экспорт | `export_yolo.py` — `phase-1:52`; `export.py` — `phase-4-quality-export.md:108, :123` | `Services/draw/export.py` — r1 `:200`, r2 `:84, :123` | перевод фигур — `draw`; снимок датасета — сервис датасета |
| Рамки на канве | элемент сцены Qt — `phase-2-annotation-widget.md:165-168` | канва редактора слоёв — r2 `:72, :88` | интерактив — канва layer-render; фигуры и стили — `draw` |
| Обучение на кадре с рисунком | `renderer.render_overlay.rendered_frame` — `plan.md:100` | чистый кадр — цель 5 | только чистый кадр; рисунок — для показа |

`overlay_draw` правят ещё три плана — их контракты держит Task 1.1, список — [`design.md`](design.md) §4.
`plans/draw-mode-rework/` — рисование роботом-плоттером: совпадение имени, не сосед.

## Бюджет

Оценка, не замер. Ставки прошлых планов на задачу: ревью спеки ~70k, тестер ~150k, исполнитель 150–300k, прогон
инъекций (Haiku) ~50k, ревью ~100–150k.

| Фаза | Задач | Запусков агентов | Токенов |
|---|---|---|---|
| Ф0 | 1 | 4 | ~0,35M |
| Ф1 | 4 | ~20 | ~2,5M |
| Ф2 | 3 | ~11 | ~1,3M |
| Ф3 | 1 | ~4 | ~0,5M |
| Приёмка `cto` после Ф1 и после Ф3 | — | 2 | ~0,4M |
| **Итого Ф0–Ф3** | 9 | ~41 | **~5,0M** |
| Ф4 (опц.) | 2 | ~9 | ~1,0M |

Задача, ушедшая за 2× своей доли, — стоп и вопрос владельцу. Пересчёт — записью в `amendments.md` после каждой фазы.

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

- Task 2.1: регистры `mapping`, `styles`, `burn`, `max_fps`, `backend`; выход `scene`; входы данных [PENDING] (после 1.3, 1.4)
- Task 2.2: рецепты: `circle_draw`, `contour_draw` → правила `overlay_draw` [PENDING] (после 2.1)
- Task 2.3: опись остальных мест рисования; пометки FROZEN [PENDING] (после 2.2)

### Phase 3: чистый кадр

**Цель фазы:** узел данных не рисует.

- Task 3.1: `ml_inference` выдаёт только данные; ветка `recog_draw` в трёх рецептах [PENDING] (после 2.2)

### Phase 4: маска и рамки (опционально — решение владельца после Ф3)

**Цель фазы:** `render_overlay` заменён правилами.

- Task 4.1: фигура `mask` патчем по рамке маски [PENDING] (после 1.3)
- Task 4.2: топологии `inspection_basic` / `inspection_full` на `overlay_draw` [PENDING] (после 4.1, 2.1)

## Гейты

- Каждая задача — стадии 0–5 (`.claude/CLAUDE.md` → «Task launch convention»), цепочка — в поле `Handoff`. Новый
  механизм — слепой `tester` в worktree до кода; подключение готового — REDS у исполнителя (`team-protocol` §3, Д47).
- `sentrux check .` после 1.1, 1.4, 2.1 — 0 нарушений; границы `Services/draw` вводит Task 1.1.
- Тесты — через `machine_gate.sh`; полный suite — у лида на границе фазы. Рецепт — тем же `SystemBlueprint.check`,
  что у загрузчика (урок `feedback_a_recipe_test_must_run_the_same_check_as_the_launcher.md`).
- Приёмка `cto` — после Ф1 и после Ф3 (Ф2 вместе с Ф3). FREEZE: старые плагины, регистры, тесты не удаляются.

## Риски

- Подписи меняют вид: Hershey → FreeType (Task 1.2, 8 рецептов), Arial Bold → DejaVu Bold (Task 3.1). Принимает
  владелец глазами на стенде.
- Слепой тест A11 (`overlay_draw/tests/test_overlay_port_join_catalog.py:55-57`) краснеет в Task 2.1 намеренно;
  правку литерала решает лид записью в `amendments.md`.
- Числа CTO — macOS arm64; Ф0 идёт первой. Остальное — [`design.md`](design.md) §5.

## Следующие планы

Не задачи этого плана; порядок — CTO r1 §5, r2 §3.
- 5a: пары `labeling` + `frame_saver` — вместе с DS-1; баги `frame_saver` из handoff `:47`; вопрос r2 №4 (в handoff — №2:
  истина класса — папка).
- 5b: сортировщик по классам. 5c: экспорт YOLO/COCO из `scene`; `validate_scene`, `transform_scene`.
- L2/L3: контуры и режим «Разметка» — после пересмотра layer-render; вопросы r2 №2 (в handoff — №4: LR-001 при Ф7) и
  r2 №5 (L2 до или после Ф5 layer-render).
- Ф6: второй бэкенд — только если ветка показа после Ф4 дороже 5 мс p95 на Orin.
- Остальные места рисования из описи Task 2.3.
- Пересечения внутри синтетики (layer-render против `line-sim-layer-editor`, опись O1–O5) — решить при пересмотре
  layer-render.

## Открытые вопросы

- [ ] **В1 (r2 №3).** Класть DejaVu Sans и Sans Bold (704 128 + 756 072 байт = 1,46 МБ, файлы есть в
  `.venv/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf/`) в `Services/draw/fonts/`? Умолчание CTO — да.
  Лицензию Task 1.2 проверяет до решения. Точка решения — стадия 0 Task 1.2; без ответа 1.2 не стартует. — владелец
- [ ] **В2.** Сведение `dataset-annotation` и `Services/labeling` (таблица пересечений выше). Рекомендация: один пакет;
  решение 8 отменяет отказ от `.json` (`dataset-annotation/plan.md:73-74`); план dataset-annotation пересобрать на
  паре, фигурах `draw` и канве layer-render после DS-1. — владелец
- [ ] **В3 (O6, O7).** Экспорт для `ml_train` и YOLO/COCO планируют трое: layer-render (`plan.md:156-157`, Ф9
  `:123-131`), dataset-annotation (`plan.md:54`, `phase-4-quality-export.md:108`), CTO (`Services/draw/export.py`).
  Рекомендация: перевод фигур в формат — одна функция в `Services/draw/export.py`; раскладку папок для `ml_train`
  («папки по классам») делает одна сторона — сервис датасета. — владелец
- [ ] **В4 (O8).** Сбор кадров: новый `dataset_capture` (`dataset-annotation/phase-3-capture.md:18-20`) или
  `frame_saver` с DS-1 (`backlog.md:77`). Рекомендация: `frame_saver`; кольцо и захват по команде — его режим. — владелец

## Решения (decisions log)

- **2026-11-11:** план собран по handoff и CTO r1/r2; 9 задач на Ф0–Ф3 и 2 на Ф4 вместо фаз 0–6: остальное —
  «Следующие планы» (пожелание владельца «план не раздувать»).
- **2026-11-11:** старые плагины — эталон для литералов sha256 до правки, а не оракул в тестах: после правки они
  идут через то же ядро.

## Итог

<!-- Заполняется перед `plans_ledger.py close`. -->

## Injections

| property | predicted red | observed red |
|---|---|---|
