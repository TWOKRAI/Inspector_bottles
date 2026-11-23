# Пакет фактов для архитектурного ревью — 2026-11-12

**Статус:** только факты из файлов и вывода команд. Оценок и рекомендаций нет. Предположения помечены «не проверено».
**Корень выборки:** worktree `.claude/worktrees/alpha-hard-split`, ветка `feat/alpha-hard-split`. Пути — относительно корня worktree.
**Команды:** `sentrux check .` (CLI), `rg` по путям, `find`/`ls`. Тесты и тяжёлые прогоны не запускались. Код не менялся.

---

## 1. Границы слоёв

### 1.1 Вердикт `sentrux check .` (CLI, код возврата 1)

Вывод дословно (сохранён в scratchpad, файл `sentrux_check.txt`):

```
sentrux check — 43 rules checked

Quality: 5537

✗ [Error] min_quality: Quality signal 0.55 below minimum required 0.60
✗ [Error] min_acyclicity: acyclicity score 0.3333 below minimum required 0.4500

✗ 2 violation(s) found
```

- Число нарушений: **2**. Оба — метрики качества (`min_quality`, `min_acyclicity`). Нарушений правил границ слоёв в выводе нет.
- Правил в `.sentrux/rules.toml`: 34 блока `[[boundaries]]` (подсчёт по строке `^\[\[boundaries\]\]`). Из 43 проверенных правил вывод называет только 2 упавших; какие именно из 43 — граничные, не сопоставлено построчно.
- MCP `check_rules` не цитировался (по правилам проекта он частичный).

### 1.2 Импорты по направлению (`rg`, только `.py` без `tests/` и `test_*.py`)

Шаблон: `^\s*(from|import) <пакет>`.

| Направление (запрет по CLAUDE.md, п.9) | Найдено строк импорта | Файлов |
|---|---|---|
| `multiprocess_framework/` → `multiprocess_prototype` | 0 | 0 |
| `multiprocess_framework/` → `Services` / `Plugins` | 0 | 0 |
| `Services/` → `multiprocess_prototype` | 0 | — |
| `Services/` → `Plugins` | 0 | — |
| `Plugins/` → `multiprocess_prototype` | 0 | — |

Ограничения: шаблон не ловит импорты внутри строк, `importlib`, импорты с обратным слешем продолжения строки. Тесты исключены по дизайну выборки. Не проверено.

---

## 2. Карта ответственности модулей

### 2.1 Фреймворк: `multiprocess_framework/modules/` (27 модулей)

Источники: «за что отвечает» — колонка «Владеет» в `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md` §1 (сокращено); ярус — `multiprocess_framework/docs/MODULE_TIERS.md` §1; наличие файлов — проверка `ls` на диске.

Наличие файлов: у **всех 27** есть `interfaces.py`, `README.md`, `STATUS.md`, `tests/`. Пропусков нет.
Ярусы: core — 17, optional — 10, frozen — 0 (MODULE_TIERS §1, «Итого»; совпадает с подсчётом по таблице).

| Модуль | Ярус | За что отвечает (по MAP) |
|---|---|---|
| `base_manager` | core | lifecycle менеджера, `ObservableMixin`, `BaseAdapter` |
| `message_module` | core | value object IPC (`Message`, `MessageAdapter`) |
| `channel_routing_module` | core | база каналов (CRM), observability-хаб и стор |
| `logger_module` | core | логирование |
| `error_module` | core | ошибки с severity-routing |
| `statistics_module` | core | агрегация метрик, `ObservationManager` |
| `dispatch_module` | core | примитив «ключ → handler» (4 стратегии) |
| `command_module` | core | реестр «имя команды → handler», тонкий фасад над dispatch |
| `router_module` | core | доставка сообщений между процессами |
| `config_module` | core | runtime-конфигурация (dot-notation, env, subscribe) |
| `data_schema_module` | core | чертёж данных: `SchemaBase`, `FieldMeta`, `FieldRouting` |
| `shared_resources_module` | core | межпроцессные ресурсы: очереди, SHM, `EventManager`, `ConfigStore` |
| `process_module` | core | база дочернего процесса (`ProcessModule`) |
| `process_manager_module` | core | оркестратор системы, топология (`SystemBlueprint`) |
| `worker_module` | core | потоки внутри процесса (LOOP/TASK), `KeyedExecutor`, `ExecutorManager` |
| `console_module` | core | терминальный I/O процесса |
| `chain_module` | core (пересмотр вердикта G0) | DAG/Chain-исполнение пайплайна, worker-pool |
| `app_module` | optional | композиционная крыша приложения (манифест, `run_app`) |
| `state_store_module` | optional | глобальное реактивное дерево состояния |
| `registers_module` | optional | runtime экземпляров регистров, routing полей |
| `display_module` | optional | реестр SHM-каналов кадров (blueprint + YAML) |
| `service_module` | optional | реестр сервисов с lifecycle |
| `frontend_module` | optional | PySide6-виджеты ↔ регистры |
| `recipe` | optional | рецепты: snapshot/restore, CRUD, реестр миграций, `yaml_io` |
| `actions_module` | optional | building-blocks undo/redo (`ActionBus`, `SnapshotHistory`) |
| `event_module` | optional | in-proc typed pub/sub (`EventBus`) |
| `telemetry_readmodel_module` | optional | read-model телеметрии для GUI (ADR-136) |

### 2.2 Прикладной слой: `Services/` (18 сервисов)

Источник: таблица в `Services/STATUS.md` (колонка «Комментарий», сокращено). Наличие файлов — проверка `ls`.

Наличие: все 18 имеют `README.md`, `STATUS.md`, `tests/`. Нет `interfaces.py` у двух: `Services/camera_device/` и `Services/device_hub/`. `Services/tests/` — каталог тестов, не сервис: нет README, STATUS, interfaces.

**Расхождение таблицы и диска:** в `Services/STATUS.md` нет строк для `camera_device`, `control_panel`, `otel_export`, `phone_gateway` (`rg` по именам: 0 вхождений). Эти 4 каталога на диске есть. Их назначение не проверено.

| Сервис | За что отвечает (по `Services/STATUS.md`) | Готовность (STATUS) |
|---|---|---|
| `sql` | SQLManager, Repository, UoW, QuerySet | production |
| `documents` | плоскость документов поверх `Services/sql` | contract |
| `hikvision_camera` | плагин-обёртка над HikSDK | production |
| `modbus` | драйвер Modbus-TCP / RS485 | ready |
| `device_hub` | реестр устройств, DeviceManager, 4 драйвера | ready |
| `robot_comm` | робот Delta поверх modbus | ready |
| `vfd_comm` | ПЧ INVT GD20, транспорт-агностик | ready |
| `auth` | User/Role storage, RBAC API | foundation |
| `ml_inference` | инференс НС (кадр → классы) | foundation |
| `dataset_gen` | генератор синтетического датасета | ready |
| `ml_train` | обучение и выбор моделей | ready |
| `code_reader` | считыватель кодов Hikrobot ID3000 | ready |
| `line_sim` | движок сцены симулятора линии | foundation |
| `layer_render` | ядро рендера слоёв | foundation |
| `camera_device` | не в STATUS; нет `interfaces.py` | не проверено |
| `control_panel` | не в STATUS | не проверено |
| `otel_export` | не в STATUS | не проверено |
| `phone_gateway` | не в STATUS | не проверено |

### 2.3 Плагины: `Plugins/`

- Групп верхнего уровня: 13 (`calibration`, `control`, `filter`, `hub`, `io`, `processing`, `render`, `runtime`, `sim`, `sinks`, `sources`, `utility`, `_shared`), плюс `Plugins/tests/`.
- Каталогов второго уровня (`find -mindepth 2 -maxdepth 2`): **59**, включая `_shared/fanin`.
- `README.md` есть у **13** из 59 (`Plugins/io/{database,telemetry_sink,otel_export}`, `Plugins/render/overlay_draw`, `Plugins/filter/line_filter`, `Plugins/processing/{center_crop,word_layout}`, `Plugins/sim/{mjpeg_sink,layer_preview,robot_host,scene_source,pult_web}`, `Plugins/_shared/fanin`). `STATUS.md` — 12 (`find`).
- `interfaces.py` на уровне плагина: **0** у всех проверенных каталогов второго уровня.
- Групповые каталоги (`Plugins/render`, `Plugins/io` и др.) без `README.md`.
- Таблица «за что отвечает» по плагинам не составлена: для 46 каталогов нет README/STATUS, назначение по имени не проверено.

---

## 3. Кандидаты в дубли

### 3а. Рисование на кадре: `cv2.rectangle|circle|putText|polylines`

Шаблон: `*.py` в `multiprocess_framework`, `Services`, `Plugins`, `multiprocess_prototype`. Исключены `tests/`, `test_*.py`, `Services/layer_render/`.

- Файлов: **23**. Вхождений: **44**.

| Файл | Вхождений |
|---|---|
| `Plugins/calibration/camera_robot/plugin.py` | 5 |
| `Plugins/processing/points_render/geometry.py` | 4 |
| `Services/phone_gateway/plugin/plugin.py` | 3 |
| `Services/line_sim/tools/make_demo_catalog.py` | 3 |
| `Plugins/render/overlay_draw/plugin.py` | 3 (стр. 89 — комментарий; 157, 160 — код) |
| `Plugins/render/circle_draw/plugin.py` | 3 (стр. 68, 70, 72) |
| `Services/dataset_gen/tools/align_sprites.py` | 2 |
| `Services/code_reader/tools/mvcr_probe.py` | 2 |
| `Plugins/sources/camera_service/backends/simulator.py` | 2 |
| `Plugins/render/render_overlay/plugin.py` | 2 (стр. 142, 153) |
| `Plugins/processing/segmentation/plugin.py` | 2 (стр. 131, 132 — надпись «SEGMENTATION OFF») |
| `Plugins/processing/circle_detector/plugin.py` | 2 (стр. 215, 217) |
| `multiprocess_framework/modules/shared_resources_module/memory/format/buffer.py` | 1 (смысл не проверено) |
| `Services/ml_inference/plugin/plugin.py` | 1 |
| `Services/line_sim/tools/make_letter_catalog.py` | 1 |
| `Services/dataset_gen/tools/cut_real_disks.py` | 1 |
| `Services/dataset_gen/preview.py` | 1 |
| `Services/dataset_gen/core/realcut.py` | 1 |
| `Services/code_reader/plugin/sdk_registers.py` | 1 |
| `Services/code_reader/plugin/sdk_plugin.py` | 1 |
| `Plugins/sources/synthetic_frame_source/plugin.py` | 1 |
| `Plugins/render/renderer_compositor/plugin.py` | 1 |
| `Plugins/render/overlay_draw/registers.py` | 1 |

Замечание: `Plugins/render/` содержит четыре плагина (`circle_draw`, `overlay_draw`, `render_overlay`, `renderer_compositor`), в каждом есть вызовы рисования либо композиции. Совпадение тем же вызовом у `circle_draw` и `overlay_draw` (`cv2.circle`) — факт по строкам 68 и 157. Что делает каждый — по коду не разбиралось.

### 3б. Сборка изображения объекта из слоёв или спрайтов вне `Services/layer_render`

Шаблон: `compose_layers|load_layer_sprite|composite(|ObjectFactory|render_scene|apply_effects|SpriteCatalog|LayeredObject|RenderedObject`. Шаблон — прокси, не полный поиск (ручной paste массивов numpy не ловится).

| Файл | Вхождений | Примечание |
|---|---|---|
| `Plugins/sim/scene_source/plugin.py` | 12 | потребитель |
| `Services/dataset_gen/core/layer_scene.py` | 6 | |
| `Services/dataset_gen/core/engine.py` | 3 | |
| `Services/dataset_gen/core/symmetry.py` | 2 | |
| `Services/dataset_gen/core/catalog.py` | 2 | по `Services/layer_render/MAP` — реэкспорт того же объекта (`is`) |
| `Services/dataset_gen/core/augment.py` | 2 | по той же карте — реэкспорт |
| `Services/dataset_gen/core/__init__.py` | 2 | |
| `Plugins/sim/layer_preview/plugin.py` | 1 | |

Вне узкого шаблона, по широкому запуску (он включал `paste` и `render_overlay`, поэтому часть совпадений шумная): `Services/line_sim/core/factory.py` 11, `Services/line_sim/core/layered_object.py` 10, `Services/line_sim/core/spawner.py` 9, `Services/line_sim/core/scene_compositor.py` 6, `Services/line_sim/__init__.py` 5, `Services/line_sim/core/__init__.py` 4, `Plugins/processing/crop/plugin.py` 8 (смысл совпадений не проверен). `Services/layer_render/MAP` (`docs/maps/layer_render.md`) фиксирует, что `line_sim.ObjectFactory` — подкласс `layer_render.ObjectFactory`, а старые пути `dataset_gen`/`line_sim` — реэкспорт. Значит часть счётчиков — потребители, а не вторая реализация. Какие строки — дубль, не разобрано.

### 3в. Логика «трудного кадра» (`hard_reasons|class_mismatch|below_threshold`)

- `hard_reasons` и `class_mismatch`: **0** вхождений во всех четырёх деревьях, включая тесты.
- `below_threshold`: механизм находится в одном месте — маркировка в `Services/ml_inference/plugin/plugin.py` (стр. 96, 181–182, 211–218, 235, 279, 336–354, 387); поля регистра — `Services/ml_inference/plugin/registers.py` (стр. 44, 75–80).
- Потребитель: `Plugins/processing/word_layout/plugin.py:526` читает `top.get("below_threshold")`. Стр. 332 того же файла: «порог ml_inference здесь неизвестен».
- Тесты с `below_threshold`: `Services/ml_inference/tests/` (test_acceptance_always_label.py 36, test_below_threshold_hazards.py 25 вхождений), `Plugins/processing/word_layout/tests/` (13 + 6 + 3 + 2). Счётчики — число строк `rg`.

### 3г. Сохранение кадров на диск (`imwrite|imwrite_unicode`), вне тестов

| Файл | Вызовов / вхождений | Примечание |
|---|---|---|
| `Plugins/io/drawing_io/store.py` | 1 (стр. 56) | прямой `cv2.imwrite`, без `imwrite_unicode` |
| `Services/layer_render/io.py` | 1 (стр. 31) | определение `imwrite_unicode` |
| `Services/dataset_gen/export.py` | 1 (стр. 81) | `imwrite_unicode` из `dataset_gen.core.catalog` (стр. 30) |
| `Services/line_sim/tools/make_font_letters.py` | 2 | инструмент |
| `Services/line_sim/tools/make_seamless_texture.py` | 1 | инструмент |
| `Services/line_sim/tools/make_letter_catalog.py` | 1 | инструмент |
| `Services/line_sim/tools/make_demo_catalog.py` | 1 | инструмент |
| `Services/line_sim/tools/build_stand_assets.py` | 1 | инструмент |
| `Services/code_reader/tools/mvcr_probe.py` | 1 | инструмент |

- `Plugins/io/frame_saver/plugin.py` (плагин «сохранение кадров», `frame_saver`): вызова `imwrite` в файле не найдено. В стр. 50 — комментарий «cv2.imwrite определяет кодек по расширению». Путь записи этого плагина **не найден** (не проверено; возможно, через модуль без `imwrite` в имени).

### 3д. Таблица «Пересечения» из `plans/queue/group-draw-dataset.md` (дословно, строки 24–36 файла)

| # | Что | Где | Предложение |
|---|---|---|---|
| O10 | `dataset-annotation` учит на кадре с оверлеем `render_overlay.rendered_frame`; `draw-universal` Ф3 и DS-1 сохраняют чистый кадр | `dataset-annotation/plan.md:100`; `backlog.md:96,111` | учить на чистом кадре; оверлей — только показ. DS-1 Task 2.3 — после draw-universal 3.1; приёмка: `.png` == выход `center_crop` |
| O8 | Сохранение кадров: новый `dataset_capture` против расширения `frame_saver` | `dataset-annotation/phase-3-capture.md:18,38`, `context.md:14`; `backlog.md:87-89,102`; `dataset-circle-capture.md:28` | **решено (draw-universal В4):** `frame_saver` с DS-1, один писатель пар «кадр + `.json`»; имя можно сменить. DS-1: `join_frame_truth` только дописывает ключи `truth`/`pred`/`delta_angle_deg`/`hard` в готовый `.json` (атомарно), пар не создаёт и не переносит (`2026-11-11_dataset-sidecar-truth/design.md` §4) |
| O6, O7 | Экспорт в `ml_train` и YOLO/COCO описаны в двух местах | `layer-render/plan.md:123-131,156-157`; `dataset-annotation/plan.md:54,166`, `phase-1-dataset-service.md:69`, `phase-4-quality-export.md:108,123` | **решено (В3):** фигуры → YOLO/COCO в `Services/draw/export.py`, раскладка папок — сервис датасета |
| O9 | `overlay_draw` правили четыре плана: вход `image/*`, побайтная копия кадра, необязательный `overlay` | `code-reader-gui.md:35,46,49`; `2026-10-18_camera-device-service/tasks/3.4.md:6,17,20`; `topology-port-join.md:9`; `dataset-circle-capture.md:29` | `draw-universal` сохраняет эти контракты — в приёмке задач. camera-device-service 3.4 ещё PENDING: правило копии кадра входит в draw-universal Task 1.1, а 3.4 убирает `overlay_draw/plugin.py` из своих FILES (`draw-universal/design.md` §4) |
| O11 | `word_layout` + `sidecar.track_id` / `frame_id` | `backlog.md:88,101`; `word-layout/tasks/C-32.md:1,17`; `letter-robot-cycle/plan.md:138,216` | DS-1: для датасета не нужно — `.json` несёт `track_id`/`frame_id` от `center_crop` и ответ `ml_inference`; строка журнала — контракт скрипта α; `2026-11-11_dataset-sidecar-truth` Task 3.2 DEFERRED (DS-В4) |
| O12 | Истина сима для пар: на кадре не едет (MJPEG, решение line-sim 2026-09-21 п.4, тест `test_scene_source_hazards.py:408`) | `plans/line-sim/plan.md:228-231`; `2026-11-11_dataset-sidecar-truth/design.md` §1–§3 | DS-1 (DS-В1): журнал JSONL в `scene_source` + офлайн-сведение `match_job`; прототип про сим не знает |
| O1–O5 | Синтетика: один веб-редактор в `pult_web` у двух планов, Qt `sim.*`, `line_sim/core/factory.py`, `letters_layered.yaml`, `dataset_gen` | `layer-render/phase-5-editor.md:21`, `plan.md:121`, `phase-2-core-2.4b.md:24`; `line-sim-layer-editor/phase-1-canvas-html.md:34`, `phase-1-qt.md:5`, `phase-1-engine.md:16,86` | решить при пересмотре `layer-render` |

---

## 4. Нарушения и долги, заявленные в самих документах

Шаблон: `\b(дубль|временно|костыль|заморожен|deprecated|freeze|temporary)\b|ponytail:` в `*.md` под `Services/`, `Plugins/`, `multiprocess_framework/modules/` (без `tests/`). Слово «одновременно» не считалось (оно содержит «временно» как подстроку). Сырых совпадений по этим каталогам — 170 (с тестами и шумом); ниже выборка, 44 записи, отобрано по контексту «долг / дубль / заморожено / временно / deprecated». Документы `docs/` (кроме `docs/audits/2026-07-10…`) не разбирались.

### 4а. Метки `ponytail:` (сознательные отложенные решения)

1. `Services/camera_device/DECISIONS.md:57` — «Дубль таблицы CAP_PROP (~15 строк, `camera_service/backends/webcam_controls.py:24-182` → драйвер OpenCV ядра) — долг `ponytail:` в коде».
2. `Services/line_sim/DECISIONS.md:85` — «ponytail: добавить, когда профилирование покажет, что это горячий путь».
3. `Services/line_sim/DECISIONS.md:129` — «ponytail: добавить лок, если появится одновременный вызывающий».
4. `Services/code_reader/STATUS.md:222` — «предположение, помечено `ponytail:` в коде».
5. `Plugins/sim/pult_web/README.md:246` — «(`ponytail:` в коде — путь наверх — `model_json_schema()` в `preset.get`…».
6. `multiprocess_framework/modules/process_module/DECISIONS.md:2477` — «Помечено `ponytail:` в обоих местах».

### 4б. Дубли: документы их заявляют

7. `docs/audits/2026-07-10_module-responsibility-duplication-map.md:84-92` — таблица D1–D9: D1 normalize_config ×3; D2 пул потоков ×2 (`worker_module` vs `chain_module/thread_pool/pool.py`); D3 deep-merge ×3; D4 движок пайплайна ×2 (`chain_module` vs `process_module/generic`); D5 версия рецепта ×3; D6 wiring миграций ×3; D7 undo/redo ×2; D8 tap/агрегация; D9 «где живёт плагин» ×2. Актуальность против кода не проверена (документ от 2026-07-10).
8. `docs/audits/2026-07-10_module-responsibility-duplication-map.md:32` — `chain_module`: «0 живых потребителей; реальный пайплайн исполняет `process_module/generic` → дубль D4».
9. `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md:100` — «Раздвоение undo-движка (реальный дубль ответственности)»: `actions_module.ActionBus` ↔ domain `CommandDispatcherOrchestrator`.
10. `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md:138` — то же в §4 «Открытые вопросы»: «консолидация отложена».
11. `multiprocess_framework/modules/recipe/DECISIONS.md:70` — «Временный дубль механизма записи (fallback vs prototype ruamel) — снимается в C3».
12. `multiprocess_framework/modules/recipe/DECISIONS.md:162` — «`gui_positions` — настоящий дубль содержимого».
13. `multiprocess_framework/modules/data_schema_module/DECISIONS.md:104` — «C5 / дубль D3 аудита дублирования».
14. `multiprocess_framework/modules/frontend_module/ROADMAP.md:209` — «M1 — RoutedCommandSender + убрать дубль (ядро)».
15. `Services/modbus/DECISIONS.md:33` — «Отвергнуто: pymodbus-обёртка в каждом сервисе устройства — дубль» (отвергнутая альтернатива).
16. `Services/otel_export/README.md:161` и `Plugins/io/otel_export/README.md:132` — «не дубль»: два счётчика в двух плоскостях (документ утверждает отсутствие дубля; код не проверен).

### 4в. Заморожено (FREEZE / заморожен)

17. `multiprocess_framework/docs/MODULE_TIERS.md:65` — `chain_module`: вердикт G0 «frozen» устарел, «Требует переподтверждения владельца», ярус core.
18. `multiprocess_framework/docs/MODULE_TIERS.md:33` — `data_schema_module`: «Мертвецы… — KILL в H.2, не ярус».
19. `multiprocess_framework/docs/MODULE_TIERS.md:88` — те же мертвецы (~2118 LOC): «~~G0 №4: KILL в Ф8~~ → **G4: FREEZE**». Строки 33 и 88 того же документа расходятся (KILL vs FREEZE).
20. `multiprocess_framework/modules/frontend_module/STATUS.md:110` — «Gen-1 заморожен (докстринг-маркеры, не удалён)».
21. `multiprocess_framework/modules/frontend_module/README.md:232` — «freeze, не kill (Р4 `plans/frontend-constructor/plan.md`)».
22. `multiprocess_framework/modules/router_module/STATUS.md:69` — «Известный дефект, не чинится: `_last_loan_exhausted` … под loan-протоколом (заморожен, `FW_SHM_LOAN_PROTOCOL` выключен)».
23. `multiprocess_framework/modules/data_schema_module/README.md:833` — «`core/metrics.py` (`MetricsCollector`) заморожен с 2026-08-26 (ADR-DS-009)».
24. `multiprocess_framework/modules/recipe/DECISIONS.md:546` — «заморожен, не удаляется».
25. `multiprocess_framework/modules/recipe/DECISIONS.md:701` — «FREEZE без живого вызывающего».
26. `multiprocess_framework/modules/recipe/DECISIONS.md:711` — `recipes/save.py` (`build_recipe_v3_raw`): «FREEZE без живого вызова записи».
27. `Services/robot_comm/DECISIONS.md:147` — «v1-регистры и драйвер не трогаются (v1 заморожен)».
28. `Services/robot_comm/DECISIONS.md:400` — «v1-вкладка прототипа … остаётся замороженным запасным UI».
29. `Services/camera_device/DECISIONS.md:187` — `sdk_app`: «**FROZEN, ручной запуск** — выбран».
30. `Services/camera_device/DECISIONS.md:199` — «FREEZE и переименование»: `HikvisionCamera` (`core/camera.py`, у `sdk_app`) остаётся FROZEN.
31. `Services/device_hub/docs/adr/ADR-DH-012.md:141` — «публичный API менеджера до SPI, FREEZE».
32. `multiprocess_framework/modules/base_manager/DECISIONS.md:198` — «FREEZE (очередь владельца 2026-10-12, `14b610faf`): потоки менеджеров на `scope.spawn`, тело `WorkerManager.shutdown`».

### 4г. Временно / legacy / deprecated

33. `multiprocess_framework/modules/message_module/DECISIONS.md:204` — «legacy args-конверт на receive-стороне поддержан временно, до полной миграции отправителей».
34. `multiprocess_framework/modules/chain_module/DECISIONS.md:313` — «Второй `WorkerManager` на процесс — временно».
35. `multiprocess_framework/modules/logger_module/STATUS.md:155` — «Временно, снимается Ф0.9».
36. `multiprocess_framework/modules/app_module/DECISIONS.md:96` — два механизма «временно сосуществуют».
37. `multiprocess_framework/modules/base_manager/DECISIONS.md:133` — «список обёрток совместимости … держит два API одновременно».
38. `multiprocess_framework/modules/process_module/DECISIONS.md:78` — `GenericProcess` deprecated — тонкий shim (404 → 155 LOC), «будет удалён».
39. `multiprocess_framework/modules/process_module/DECISIONS.md:104` — `GenericProcess` → deprecated shim → «будет удалён после миграции прикладного кода».
40. `multiprocess_framework/modules/shared_resources_module/DECISIONS.md:36` — ADR-SRM-005: пять properties помечены deprecated в docstring, без `warnings.warn`.
41. `multiprocess_framework/modules/shared_resources_module/STATUS.md:86` — прямой доступ к `config_store` / `queue_registry` на фасаде помечен deprecated.
42. `multiprocess_framework/modules/frontend_module/DECISIONS.md:91` — `_update_access_level()` — deprecated alias с `DeprecationWarning`.
43. `Services/STATUS.md:23` — `documents` (contract): «**Потребители не подключены**».

### 4д. Прочее (за границей шаблона, из выборки)

44. `multiprocess_framework/modules/router_module/DECISIONS.md:143` — «конвейер заморожен, skipped растёт» — описание открытой fault-инъекции.

---

## Что оставил открытым / ненадёжно

- **Sentrux:** вердикт и число (2) — из прямого запуска CLI, код возврата 1. Какие из 43 правил граничные, сопоставлено только по числу блоков `[[boundaries]]` (34). MCP `check_rules` не использовался.
- **Импорты (1.2):** шаблон построчный, не ловит динамические импорты (`importlib`, строки) и многострочные импорты. Тесты исключены.
- **Рисование и композиция (3а, 3б):** текстовые шаблоны. Не ловят алиасы, ручной paste массивов numpy, рисование другими библиотеками. Счётчики — число строк совпадений, не число функций. Часть совпадений 3б — реэкспорт (по `docs/maps/layer_render.md`), часть — потребители; разделение «дубль / потребитель» по строкам не сделано.
- **Широкий запуск 3б:** включал `paste`, `render_overlay`, `render_background` — поэтому файлы `frontend_module/widgets/tables/*` и `Plugins/processing/crop/*` в списке шумные; смысл не проверен.
- **Сохранение кадров (3г):** путь записи `Plugins/io/frame_saver` **не найден** (в файле только комментарий со словом `cv2.imwrite`). Не проверено, пишет ли плагин через другой модуль.
- **Плагины (2.3):** README есть у 13 из 59 каталогов второго уровня; назначение 46 каталогов без документации не установлено (по имени не описывалось). `interfaces.py` в плагинах не найден ни у одного проверенного каталога.
- **Сервисы (2.2):** README и STATUS самих сервисов не читались построчно; в таблицах взяты строки `Services/STATUS.md`. `camera_device`, `control_panel`, `otel_export`, `phone_gateway` не описаны в `Services/STATUS.md`; их назначение не проверено.
- **Документы (раздел 4):** в выборке отбирались строки по маркерам, не полный перечень. Актуальность документов против кода не проверялась. Строки `MODULE_TIERS.md` 33 и 88 расходятся — зафиксировано как факт текста, какой вариант действует, по коду не установлено.
- **Файлы, прочитанные целиком:** `multiprocess_framework/docs/MODULE_TIERS.md`, `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md`, `multiprocess_framework/MODULES_STATUS.md`, `Services/STATUS.md`, `plans/queue/group-draw-dataset.md`, `docs/maps/layer_render.md`. Из `docs/maps/` остальные 8 карт не читались. `.sentrux/rules.toml` — только имена и количество блоков. Корневой `CLAUDE.md` взят из системного контекста, не перечитывался.
- **Не выполнялось:** тесты, `python scripts/validate.py`, любые прогоны стенда; `git` не менялся; ничего, кроме этого файла, не записано.
