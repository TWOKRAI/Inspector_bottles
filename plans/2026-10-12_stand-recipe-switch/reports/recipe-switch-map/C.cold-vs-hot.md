# Срез C — холодный старт против горячей смены (Explore/haiku, 2026-10-13)

Сырой отчёт агента-разведчика для схемы `docs/maps/recipe-switch.md`. `system.yaml` — `multiprocess_prototype/backend/config/system.yaml:10` (`log_dir: "logs/prototype_2"`).

## 1. Холодный старт
1. `multiprocess_prototype/run.py:42-75` → `main.main`.
2. `main.py:113-159`: `apply_env_aliases`, `resolve_manifest_path`; есть `pipeline_override` → `persist_pipeline_choice` (`main.py:139-149`); `run_app`.
3. `main.py:69-110` → `SystemBuilder.from_manifest` (`backend/launch.py:512-591`): `load_system_config` (534); pipeline = override или `app.pipeline` (535, 400-408); `_load_raw_dict` + `unwrap_recipe` (538-539); **фундамент: `for fragment in app.base: merge_topologies(...)` (545-546)**; presentation overlay (551-554) или `announce_presentation_absent` (560); `extract_recipe_devices(raw)` (573) + `inject_recipe_devices`, origin = `raw.name or bp_path.stem` (580-581).
4. `build()` (`launch.py:615`): discover плагинов (642-650); `normalize_blueprint` (655); **`resolve_log_dir_root` (662)**; `INSPECTOR_LOG_DIR` setdefault (669); `load_companion` с гейтом (704-710); `BlueprintAssembler(log_dir, recipe_path=topology_path)` (712-718); `assemble` (720); `assemble_launcher` (733-770).
5. Ассемблер ставит `cfg.log_dir`, только если поле пустое (`backend/assembly/assembler.py:141-145`).
Правило merge (`launch.py:148-200`): при коллизии имён процессов побеждает base (161-168) + строка «дубль из pipeline пропущен»; wires — base первым (170); metadata/observability — pipeline (181, 197).

## 2. Горячая смена
1. Источники `topology_dict` (`frontend/bridge/process_manager_proxy.py:94`):
   - (a) «Перезапустить» (вкладка Pipeline): `runtime_control.py:224-227` → `graph_to_blueprint` (`pipeline/io.py:96-103`) — модель из СЛИТОЙ топологии (`frontend/app.py:256-269`);
   - (b) «Запустить»: `runtime_control.py` `launch_active_recipe` → `recipe_io.py:57-66` (v3 → сырой dict);
   - (c) «Загрузить» (вкладка Рецепты): `recipes/presenter.py:440-452` → сырой `recipe_data`;
   - (d) `recipe.activate` (хаб): `framework/modules/recipe/service.py:348-356` → `to_topology` (deepcopy, `backend/recipe_format_hook.py:71-72`) + `recipe_path`.
2. PM `_cmd_topology_apply` (`process_manager_process.py:751-786`): debounce → `_retarget_recipe_address(recipe_path)` (780; пусто для a–c) → `apply_topology` (786).
3. `planner.commands` (`backend/assembly/planner.py:216-299`) → `proc_dicts_fn` → `_build_proc_dicts` (`backend/orchestrator_hooks.py:122-195`): `_active_recipe_path()` (manifest первым, 107-115) → `unwrap_recipe` → overlay по снимку config → `extract_recipe_devices(bp)` + inject, origin = `bp.name or stem(recipe_path)` (167-170) → `normalize_blueprint` → `BlueprintAssembler(log_dir=…)` (188-195). **Merge фундамента здесь нет.**
4. Diff: `live_protected` (251), old = живые non-protected (252), new = proc_dicts минус live_protected (260); конфликты protected (257, 305-342).
5. Манифест пишется после успеха: `recipe/service.py:356-360`, `recipes/presenter.py:521`.
Снимок `sys_config` — на boot (`launch.py:765`); discover в PM — один раз (`orchestrator_hooks.py:72-80`).

## 3. Расхождения
| Пункт | Холодный | Горячий | Одинаково? |
|---|---|---|---|
| log_dir | `launch.py:662`: env MULTIPROCESS_LOG_DIR > INSPECTOR_LOG_DIR > yaml (51-76) | `orchestrator_hooks.py:85` только yaml | НЕТ при заданном env (R-9) |
| merge base + pipeline | `launch.py:545-546` | нет в `_build_proc_dicts`; база есть, только если payload уже слит: (a) да, (b)-(d) нет | НЕТ для (b)-(d) |
| `devices` в base и в рецепте | дубль рецепта отброшен (161-168); рецепты с `devices`: `phone_sketch.yaml:74`, `camera_robot_calibration.yaml:82`, `dataset_circle_capture.yaml:58` | (b)-(d): рецептный `devices` единственный в desired; живой protected выживает, расхождение → голос конфликта | НЕТ |
| `recipe_devices` / `recipe_origin` | из сырого файла; origin = `raw.name or stem` (573-581, `recipes/devices_sync.py:84-101`) | из payload; (a) — `devices` нет, инъекции нет; origin = `bp.name or stem(_active_recipe_path)` — при (d) манифест ещё старый | НЕТ |
| какой файл читается | `app.pipeline` или override, на boot | payload; файл читает только (d) и GUI `read_raw`; манифест — только для адреса | НЕТ по источнику |
| plugin list / sys_config | discover в launcher, sys_config из файла | discover в PM один раз, sys_config — снимок boot | правка system.yaml после boot до hot не доходит |
| L2 companion, адрес рецепта | `load_companion` (704-710), recipe_path = файл | `_active_recipe_path()` manifest-first, гейта нет | НЕТ при (d): старый рецепт |
| валидация | `BlueprintInvalid` → `sys.exit(1)` | исключение из `commands` → ошибка apply | та же проверка |
| normalize, obs_section, telemetry | 655, 679, 685 | `orchestrator_hooks.py:84, 93, 171` | да |

## 4. Кто пишет app.yaml
- `run.py <recipe>`: `main.py:139-146` → `persist_pipeline_choice` (`launch.py:424-469`).
- GUI: `frontend/app.py:842-854` `_persist_active_recipe` ← `presenter.py:521-523` (после успеха).
- Хаб `recipe.activate`: `service.py:356-360` (после apply), адаптер `multiprocess_prototype/orchestrator.py:131-147`.
- «Запустить» (b): записи нет.
- Store: `framework/modules/app_module/store.py:121-128`.

## 5. Маркеры
TODO/FIXME/FROZEN на этих путях — нет.

## Что осталось открытым
Хвост `devices_sync.inject_recipe_devices` после :102; отвергает ли `BlueprintAssembler.check()` wire на `devices` в сыром рецепте без base; потребитель `priority:` не найден; вызывающий `recipe.activate` в прототипе не найден (только регистрация `service.py:122`); два класса `AppManifest` не сравнивались; рассинхрон «Запустить» с манифестом не проверен; тестов, гоняющих оба пути на одном рецепте, нет.
