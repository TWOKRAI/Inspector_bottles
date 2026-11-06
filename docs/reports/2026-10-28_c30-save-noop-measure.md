# C-30: замер «Save без правок» Pipeline-вкладки на `bridge_synth` (до C-30 и на ветке)

Дата: 2026-10-28. Исполнитель: developer (замер, без правок кода, без коммитов).
Вопрос владельца: добавление процесса `devices` и `blueprint.metadata.gui_positions` при Save без правок — норма (design F10) или дефект?

## 1. Короткий ответ

1. Процесс `devices` берётся из фундамента `multiprocess_prototype/backend/topology/base.yaml:27-40` (`protected: true`). Гипотеза лида подтверждена статикой И контрольным прогоном: топология сессии редактора уже слита с base при старте GUI, Save пишет её целиком.
2. Это поведение существовало ДО C-30 (коммит `d45597f73`): тот же сценарий там давал `+55 / -10` строк, из них блок `devices` (23 строки в «сыром» виде модели против 14 на ветке). C-30 убрал шум канонизации (`extras {}`, `restart_policy {}`, пустые ключи, перенос плагин-полей в `config:`, перестановку ключей), но `devices` не тронул — фундамент в рецепт утекал и раньше.
3. На ветке headless-прогон даёт ровно `+19 / -0` = 14 (`devices`) + 5 (`gui_positions`) — совпадает с живым GUI владельца построчно по составу.
4. F10 предсказывал ТОЛЬКО `locked_nodes: []` + позиции (`design.md:24`, `:87`, `:162`). Позиции (+5) — это F10, и ветка уже не пишет `locked_nodes: []` (в дизайне так и задумано). `devices` (+14) — НЕ F10: пробы F9/F10 (`probes/probe_r1b.py:23-33`) брали только `raw["blueprint"]`, слияния с base в них нет.
5. Вывод: +5 — норма (F10); +14 — дефект (утечка фундамента в рецепт), предсуществующий, не регрессия C-30; вред малый (см. §6).

## 2. Откуда `devices` (file:line, дерево `d45597f73`)

| Шаг | Место |
|---|---|
| base.yaml объявляет `devices` (`protected: true`, плагин `DeviceHubPlugin`, `executors.device_io`) | `multiprocess_prototype/backend/topology/base.yaml:27-40` |
| При старте GUI топология = `unwrap_recipe(рецепт)`, затем для каждого фрагмента `manifest.base` — `merge_topologies(base, topology)` | `multiprocess_prototype/frontend/app.py:262-269` |
| Результат кладётся в `TopologyRepositoryStore` — источник истины GUI | `frontend/app.py:292` |
| `merge_topologies`: `merged.processes = base.processes + pipeline.processes` (base первым, дубль из рецепта пропускается) | `multiprocess_prototype/backend/launch.py:151-175` |
| Вкладка Pipeline грузит модель из этого стора: `services.topology.load().to_dict()` → `PipelineModel.from_topology_dict` | `frontend/widgets/tabs/pipeline/layout_controller.py:163-164` |
| Save: `graph_to_blueprint(self._model)` копирует ВСЕ процессы модели без фильтра по `protected` | `layout_controller.py:429`; `frontend/widgets/tabs/pipeline/io.py:82-92` |
| Сборщик: `blueprint["processes"] = list(topology["processes"])` — тоже без фильтра | `multiprocess_prototype/recipes/save.py:126` |
| Запись `save_editor_topology_to_recipe` → `store.save_raw` | `recipes/save.py:175-211` |

Рисование и раскладка protected-процессы пропускают (`graph_codec.py:130-132`, `layout_controller.py:345-348`), поэтому `devices` на холсте не виден, но в модели и в записи он есть. Фильтра `protected`/«происхождение из base» на пути записи нет ни на `d45597f73`, ни на ветке.

На ветке тот же слой: `frontend/app.py:72-74` (то же слияние), `layout_controller.py:170` (та же загрузка), `recipes/save.py:132`.

## 3. Метод

- Дерево «до C-30»: `git worktree add .claude/worktrees/lane-d-c30-measure d45597f73 --detach` (остаётся на месте).
- Скрипт замера: `C:\Users\INNOTECH\AppData\Local\Temp\claude\d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles\b761246a-7a59-423f-a0ae-ab9c95a5b7e2\scratchpad\measure_save.py` (в репозиторий не кладётся).
- Реальные объекты (не фейки): `unwrap_recipe`, `merge_topologies` с реальным `base.yaml`, `TopologyRepositoryStore`, `RecipeEngine` + `RecipeManager` + `RecipeStoreFromManager` (`set_active("bridge_synth")`), `PipelineModel`, `LayoutController.load_topology_from_config()` и `LayoutController.save_to_active_recipe()`. Подмены: хост (`topology_to_graph` → пустой граф), сцена (одна позиция узла), `QMessageBox` (статические методы → заглушки, окон нет, `QT_QPA_PLATFORM=offscreen`).
- Вход: копия рецепта во временном каталоге, 41 строка, 1813 байт, sha256 `7ea9c594…` — тот же вход, что у владельца. `multiprocess_prototype/recipes/*.yaml` ни в одном дереве не менялся: sha256 файла в дереве замера `7ea9c5944ce4…` как был, `git status` дерева замера пуст; рабочий файл `bridge_synth.yaml` ветки был `M` ДО замера и остался `M` (его sha после замера `689b9fab…`, замер его не читал и не писал; в замер на ветке ушла копия из дерева замера).
- Запуск: `machine_gate.sh light inspector-bottles-01 <main .venv python> measure_save.py …`, `PYTHONPATH=<корень дерева>`. Подтверждение пути импорта (печатает скрипт, assert на принадлежность дереву):
  - `…\lane-d-c30-measure\multiprocess_prototype\__init__.py`
  - `…\lane-d-c30\multiprocess_prototype\__init__.py`

Три варианта входа на каждом дереве:
- `boot_base_scene` — как в живом GUI: топология сессии = base ⊕ рецепт, сцена отдаёт позицию 1 узла (`synthetic_source.synthetic_frame_source` = (120.0, 80.0));
- `boot_base_noscene` — то же, сцены нет (позиции не передаются);
- `boot_nobase_scene` — КОНТРОЛЬ: топология сессии = только рецепт (без слияния с base).

## 4. Результаты

Вход: 41 строка / 1813 байт во всех прогонах.

| Дерево | Вариант | Строк после | Байт после | Добавлено | Удалено | `devices` | `gui_positions` | `locked_nodes` | `extras` | `restart_policy` |
|---|---|---|---|---|---|---|---|---|---|---|
| main до C-30 (`d45597f73`) | base + сцена | 86 | 2925 | +55 | -10 | да (23 стр., с шумом) | да | `[]` | 3 | 3 |
| main до C-30 | base, без сцены | 83 | 2847 | +52 | -10 | да | пустой ключ | `[]` | 3 | 3 |
| main до C-30 | КОНТРОЛЬ: без base + сцена | 64 | 2297 | +27 | -4 | нет | да | `[]` | 2 | 2 |
| ветка (`lane-d-c30`) | base + сцена | 60 | 2390 | +19 | -0 | да (14 стр.) | да (5 стр.) | нет | 0 | 0 |
| ветка | base, без сцены | 55 | 2276 | +14 | -0 | да (14 стр.) | нет | нет | 0 | 0 |
| ветка | КОНТРОЛЬ: без base + сцена | 46 | 1927 | +5 | -0 | нет | да (5 стр.) | нет | 0 | 0 |

Что именно было шумом на `d45597f73` (вариант «base + сцена», диф `out_main/boot_base_scene/diff.txt`):
- `extras: {}` ×3 и `restart_policy: {}` ×3 (по числу процессов), плюс `metadata: {}`;
- пустые ключи без значения: `priority:`, `target_process:`, `description:`, `category:`;
- `protected: false` у `synthetic_source`, `displays: []`, `locked_nodes: []`;
- `source_target_fps: 30` переехал под `extras:`; плагин: плоские поля `camera_id/resolution_*` переехали под `config:`; порядок ключей процесса и плагина переставлен (10 удалённых строк — это перестановка/перенос, а не потеря данных);
- `null dtype` — НЕ проверялось: в этом рецепте нет полей `dtype`;
- потеря комментариев — в этом рецепте не воспроизводится: 10 строк `#` до и после, но все комментарии — заголовочные, внутри `blueprint:` их нет (проверка слабая, см. §6).

Дифф ветки (вариант «base + сцена», `out_branch/boot_base_scene/diff.txt`), целиком:

```
@@ -18,4 +18,18 @@
   processes:
+    - process_name: devices
+      plugins:
+        - plugin_name: device_hub
+          plugin_class: Plugins.hub.device_hub.plugin.DeviceHubPlugin
+          category: hub
+          config:
+            registry_path: data/devices.yaml
+      process_class: multiprocess_prototype.generic_process_app.GenericProcessApp
+      protected: true
+      metadata:
+        executors:
+          device_io:
+            max_workers: 4
+            max_pending: 64
     - process_name: synthetic_source
@@ -40,2 +54,7 @@
   wires: []
+  metadata:
+    gui_positions:
+      synthetic_source.synthetic_frame_source:
+        - 120.0
+        - 80.0
```

Причинная связка по контролю (ветка): без слияния с base `devices` пропадает (+19 → +5); без сцены пропадают позиции (+19 → +14). Два слагаемых независимы: 14 + 5 = 19.

## 5. Норма F10 или дефект

- `+5` (`blueprint.metadata.gui_positions`): норма по F10 (`design.md:24`, `:87`, `:162`): у рецепта без `blueprint.metadata` непустые позиции сцены — «содержимое пользователя». Дизайн же требует не писать пустые `locked_nodes: []` — и ветка их не пишет (`locked_nodes` count = 0).
- `+14` (`devices`): не F10. Довод 1: F10 о layout-метаданных, процессов не упоминает. Довод 2: пробы F9/F10 не моделируют слияние с base (`probe_r1b.py` берёт `raw["blueprint"]`), поэтому «дельта 0 на 22 рецептах» (F9) верна для канона данных, но не для реального входа GUI. Довод 3: `base.yaml:1-22` прямо описывает фундамент как «НЕ участвует в pipeline» и суммируемый ПРИ ЗАПУСКЕ; рецепт хранит только полезную нагрузку. Довод 4: пункт предсуществующий (есть на `d45597f73`), значит это не регрессия C-30 и не дефект 1.2 как «внесённый шум», а непокрытый класс: «источник записи (сессия) шире рецепта».
- Серьёзность: функционально безвредно сегодня. При запуске `merge_topologies` пропускает дубль из рецепта, побеждает base (`launch.py:163-170`, сообщение в stderr «уже есть в фундаменте — дубль из pipeline пропущен»). Вред: в рецепте появляется вторая копия определения, которая тихо расходится с base при его правке; рецепт перестаёт быть «чистой нагрузкой»; шум в `git diff` каждого рецепта, который кто-то сохранит из Pipeline. Остальные 6 коммит-рецептов с `devices` (`webcam_sketch`, `phone_sketch`, `letter_robot_sim`, `camera_robot_calibration`, `dataset_circle_capture`, `hikvision_letter_robot`) содержат его авторской рукой (в `webcam_sketch.yaml` рядом секция `devices:`), это другая история.

Формулировку ответа владельцу даёт лид; моя оценка: «+5 — норма; +14 — настоящий дефект расследования, не введённый C-30; чинится фильтром на пути записи (исключить процессы, пришедшие из base-фрагментов), отдельной задачей».

## 6. Открыто / ненадёжно

1. Это headless-воспроизведение, не живой GUI. Совпадение с живым результатом владельца: состав и счёт (+19/-0, 14 + 5) совпали, но координаты в `gui_positions` у меня взяты из заглушки сцены ((120.0, 80.0)), реальная сцена Qt не поднималась. Что позиции — одна пара на единственный плагин-узел — следует из счёта 5 строк, не из измерения сцены.
2. Не проверен вариант «горячая активация другого рецепта из вкладки Recipes»: там топологию в стор кладёт `RecipeApplyHandler` (`frontend/actions/handlers/recipe_handler.py:30-38`) из `forward_patch` — сливается ли она с base, я не читал. Если нет, `devices` в сессии (и в Save) не окажется; если да — тот же дефект. Измерен только путь «рецепт задан при старте» (`frontend/app.py:262-269`), то есть сценарий владельца.
3. Если в `app.yaml` включить `observability_sink.yaml` (закомментирован в `base:`), по тому же механизму в рецепт, по всей видимости, попадёт и он. Это экстраполяция по коду, не замер.
4. «Потеря комментариев» и «null dtype» не проверены на этом входе: в `bridge_synth` нет `dtype` и нет комментариев внутри `blueprint:`. Проверка слабая; настоящая — прогон на `dataset_circle_capture.yaml` (там якоря/алиасы и вложенные комментарии), я его не делал (вне задачи).
5. Данные `+25/-1` у `git diff` рабочего файла `bridge_synth.yaml` на ветке отличаются от «+19/-0» владельца и от моего прогона. Вероятное объяснение (не проверено): `git diff` считает CRLF/LF и/или файл с тех пор правился. Состояние рабочего файла ветки я не менял и не анализировал.
6. Из-за CRLF в рабочем дереве Windows (1813 байт против 1772 в blob) байтовые числа привязаны к CRLF-варианту; в строках расхождения нет.
7. Дерево `lane-d-c30-measure` (detached `d45597f73`) оставлено по заданию: `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/lane-d-c30-measure`.
8. Дифы лежат в scratchpad: `…\scratchpad\out_main\<вариант>\{diff.txt,after.yaml}` и `…\scratchpad\out_branch\<вариант>\…`; после очистки temp их не будет — все решающие строки продублированы выше.
9. Проверка графа слоёв/`sentrux`, `ruff`, pytest не запускались: код не менялся.

memory hits: n/a (поиск по памяти не выполнялся — замер без правок).
