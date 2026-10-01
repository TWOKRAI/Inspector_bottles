# Task T1 — ревью: цепочка инспекции находит объекты (итерация 1)

**Ревьюер:** reviewer (Opus), синхронно. **Diff:** `284e6536..cc6c8c13` ветки `feat/pipeline-node-timing`
(6 коммитов: тестер → fix(plugins) цепочка → fix(topology) без рисования + мс → fix(plugins) sandbox mask/warning →
fix(frontend) правило по dtype ×2). Отчёт сохранён лидом: у роли reviewer нет права писать файлы. Скрипты
воспроизведения — в scratchpad сессии (`/tmp/bench_t1*.py`), в репо не попали. Worktree чист до и после (`git status
--porcelain` — только два untracked dev-notes файла, которые были untracked и до ревью).

## Вердикт: REQUEST_CHANGES (итерация 1 из 2)

Функциональная часть PC-1/PC-2 закрыта чисто и доказана (6/6 тестов с break-injection). Но третий пункт acceptance —
«время цепочки ≤ 5 мс» — в diff'е не проверяется никаким тестом, только упомянут в commit message как факт
прошлого ручного замера; независимый замер на этой машине цепочку в бюджет не укладывает и после фикса.

## Находки

1. **[major, acceptance]** Критерий «цепочка ≤ 5 мс (микробенчмарк)» не имеет ни одного автоматизированного теста
   в diff'е — единственное свидетельство: `Why:` коммита `f7909b49` («ревью T1 — цепочка 5.9–6.3 мс против критерия
   5 мс», затем `draw_contours: false`). Независимый замер (`color_mask.process` → `blob_detector.process`, те же
   параметры из `inspection_full.yaml`, 1080p/6 кругов, `cv2.setNumThreads(2)` как в замере лида, warmup 30,
   N=300): **median 6.33 мс, mean 7.15 мс** — выше 5 мс и после фикса (`draw_contours: false` уже применён).
   Разбивка: `color_mask` (cvtColor BGR2HSV + inRange на 1920×1080) — median 4.80 мс сам по себе; `blob_detector`
   (findContours + фильтрация, маска готова) — median 1.20 мс. Чистый cv2 (без обёртки плагина) на той же
   связке даёт median 5.79 мс — узкое место само HSV-преобразование на этой машине, а не рисование контуров,
   которое чинил коммит. На машине лида числа другие (план: «одно HSV + маска 1ch + контуры» = 4.6 мс) —
   воспроизводимость через машины не гарантирована, поэтому нужен committed-бенчмарк с порогом, а не
   memory/commit-message утверждение.
   **Рекомендация:** добавить `test_pnt_t1_chain_timing_budget` (медиана по N прогонов, явный порог/маркер
   `@pytest.mark.perf`, чтобы не шуметь в CI на слабом раннере) либо явно зафиксировать в плане/ADR, что этот
   критерий проверяется только лидом вручную, и закрыть его отдельной строкой в `docs/sessions/`.

## Прогоны

- `pytest Plugins/processing/blob_detector/tests Plugins/processing/color_mask/tests Plugins/processing/hsv_mask/tests` → **42 passed**.
- `pytest multiprocess_prototype/frontend/widgets/tabs/plugins/tests` → **97 passed**.
- `pytest multiprocess_prototype/backend/topology/tests` → **78 passed** (включая `test_pnt_t1_topology_draw.py` — сторож на `draw_contours: false` / `draw_detections: true` в обеих эталонных топологиях).
- Литеральный acceptance-тест (`test_pnt_t1_full_chain_finds_six_objects`, `test_pnt_t1_basic_chain_finds_six_objects`) — **6 детекций из 6 красных кругов 1080p**, параметры буквально читаются из `inspection_full.yaml`/`inspection_basic.yaml`. Подтверждаю: PC-1 закрыт, реальный путь `color_mask → blob_detector` работает, не мок.
- Сводный прогон всех пяти директорий разом (после восстановления после break-injection) → **217 passed**.

## Break-injection (2 гарантии, предсказание до запуска)

**1. `color_mask` не подменяет `frame`, пишет `mask`** (`Plugins/processing/color_mask/plugin.py`,
`_process_item`) — откат на `mask_bgr = cv2.cvtColor(mask, GRAY2BGR); return {**item, "frame": mask_bgr}`.
Предсказание: RED — `test_pnt_t1_color_mask_keeps_frame_and_adds_binary_mask`, `test_pnt_t1_full_chain_finds_six_objects`,
`test_pnt_t1_basic_chain_finds_six_objects` (blob_detector без `item["mask"]` падает на fallback-порог поверх
уже-замаскированного «кадра» → 0 детекций). **Факт: ровно эти три RED** (`assert 0 == 6` ×2, `array_equal` False на
frame), остальные 39 — зелёные. Восстановлено, `git diff --stat` пуст.

**2. `blob_detector` использует `item["mask"]` вместо пересчёта HSV** (`process()`) — откат на безусловный
пересчёт HSV, маска из item полностью игнорируется (вместе с ней — весь механизм валидации/warning). Предсказание:
RED — `test_pnt_t1_blob_detector_uses_upstream_mask_not_colours` (ждёт 1 детекцию по прямоугольной маске, получит 6
по цвету), `test_rejected_mask_warns_exactly_once_over_many_frames`, `test_bool_dtype_mask_warns_exactly_once`
(warning-механизм исчезает вместе с веткой). Предсказал также, что `test_bad_upstream_mask_falls_back_to_own_thresholding`
останется зелёным впустую (сам тест и так ждёт fallback, откат просто делает fallback безусловным) — это и есть
риск «тест не ловит свою гарантию» для этого конкретного теста, фиксирую отдельно. **Факт: ровно 3 RED**
(`assert 6 == 1`, `assert 0 == 1` ×2), 39 зелёных, включая угаданный вхолостую `test_bad_upstream_mask_falls_back_to_own_thresholding`.
Восстановлено, `git diff --stat` пуст.

Обе гарантии умирают предсказуемо и только по своим тестам — реальный contract driving tests, не vacuous
(кроме одного теста, отмеченного выше, который по конструкции не может отличить «правильный fallback» от
«fallback всегда» — не блокер, т.к. соседний `test_pnt_t1_mask_of_different_size_falls_back_to_own_thresholding`
той же категории тоже не различает, но позитивный путь прикрыт `test_pnt_t1_blob_detector_uses_upstream_mask_not_colours`
и обоими warning-тестами).

## Sandbox dtype-правило — проверка на «fake-harness» ловушку

Угроза устранена последним коммитом `cc6c8c13`: `FakePort` в `test_sandbox_presenter.py` теперь реально несёт
`dtype` и `optional` (до этого — только `name`, тест был бы зелёным и под полным откатом правила). Диапазон
коммитов `d2e96ec5` (правило введено без реалистичного порта) → `7a0ded56` (правило переписано под dtype) →
`cc6c8c13` (порт получил атрибуты) показывает, что разработчик сам поймал и исправил это до сдачи.
Параметризованный тест `test_check_input_ports_rule` (9 кейсов) и `test_check_side_effect_category_disabled`
(4 категории) покрывают: optional не блокирует, два обязательных блокирует, имя не dtype судит (`region` BGR под
чужим именем — явный комментарий про `flip`/`negative`), категории io/output/sink/calibration режутся до проверки
портов. `docs/reviews/2026-09-30_task-T1-fix2-developer.md` (untracked self-report разработчика) даёт независимое
подтверждение на реальном реестре 58 плагинов: 36→25 `ok` — явно согласуется с кодом правила.

## Не проверено и ненадёжно

- Живой стенд (`backend_ctl`) не поднимал — только юнит-уровень (прямые вызовы `plugin.process()`), не воспроизводил
  прохождение item через `GenericProcessApp`/`chain_module` внутри реального процесса `processor`.
- ≤5 мс — см. находку 1: контринтуитивный результат на этой машине, нужна перепроверка на машине лида или
  committed-бенчмарк, прежде чем считать критерий закрытым.
- `docs/reviews/2026-09-30_task-T1-fix2-developer.md` (58-строчная таблица реестра) — self-report разработчика,
  принят на веру частично, не прогонял `check_compatibility` по всем 58 плагинам сам.
- Два файла `docs/reviews/2026-09-30_task-T1-fix*-developer.md` остались untracked (не закоммичены ни в одном из
  6 коммитов диапазона) — не блокер, но стоит либо закоммитить как часть истории ревью, либо удалить как черновик.
