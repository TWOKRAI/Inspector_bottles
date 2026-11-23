# C-30 · итоговое ревью ветки `fix/recipe-save-noise` перед merge · 2026-11-07

Ревьюер: reviewer (Opus), только чтение. Область: коммиты `85c4df4a5…36a5481bc` (Task 1.4, 1.5, 1.3, 1.16) поверх
merge-base `c07fb7cb7`; проверка на дереве `f5fa8c237` (ветка + main `cca8fe148`). Пробы — в detached worktree
`lane-d-c30-rev-branch` (снят, `git status` чист). Все тесты — через `machine_gate.sh light inspector-bottles-c7`.

memory hits: `scripts/memory/search.py recipe save writer guard yaml --module recipe` -> `feedback_merge_changes_the_form.md`,
`feedback_ruamel_emitter_no_newline_glues_lines.md` (прочие не по теме); CRAFT-verdict: «дефект на одном пути из трёх».

## Вердикт: APPROVED (с двумя minor до merge или записью в OPEN_QUESTIONS)

Счёт: **0 blocker, 0 major, 2 minor**, 4 advisory.

## Находки

### m1 [minor, quality] Post `recipe.save` шире поведения: legacy `gui_positions` воскрешает очищенные позиции

Вход (проба `probe_service.py`, настоящий `InspectorRecipeFormatHook`): файл v3 с top-level `gui_positions: {cam: [10, 20]}`
без `blueprint.metadata`; `recipe.get` -> body с `blueprint.metadata.gui_positions == {cam: [10, 20]}`; body правится на
`gui_positions: {}`; `recipe.save` с верным `base_rev`.
Наблюдённый выход: `{'success': True}`; `hook.normalize(файл после записи).blueprint.metadata.gui_positions == {'cam': [10, 20]}`;
`normalize(файл) == normalize(body)` -> `False`.
Причина: дельта пишет пустой канонический словарь, legacy остаётся в файле (так и задумано: `DECISIONS.md:567-568`),
а `canonicalize_gui_positions` при пустом каноне поднимает legacy обратно. Post в `service.py:57-58` и
`DECISIONS.md:562-563` («`normalize(файла после записи) == normalize(body)`») для этого входа неверен.
Достижимость: только `recipe.save` хаба, только «очистить все позиции», только 2 рецепта репо с legacy-ключом
(`camera_robot_calibration`, `dataset_circle_capture`: legacy 10/14, канон 10/14). GUI пишет через
`RecipeManager.patch_recipe` (вне этой ветки, не проверял).
Правка: сузить Post в `service.py` и `DECISIONS.md:563` — «кроме ключей, которые `normalize` переносит: пустой канон при
непустом legacy читается как legacy», плюс строка в `OPEN_QUESTIONS.md`; либо закрыть чисткой двух рецептов (полоса C,
«Дальше» плана). Код не менять: удаление legacy в дельте дало бы шум вне поля правки.

### m2 [minor, quality] Открытые пункты 1.16 (A1, A2) не попали в `docs/claude/OPEN_QUESTIONS.md`

Вход: `grep -c -F "expected_rev=None" docs/claude/OPEN_QUESTIONS.md` -> `0`; `grep -F "_EMPTY_GRAPH"` -> пусто.
A1 (ложный отказ, когда в файле только процессы фундамента) и A2 (текст «ревизия неизвестна» при Recipes-Save в ДРУГОЙ
рецепт) записаны только в `docs/reviews/2026-11-07_task-1.16-review.md:37-38` и handoff. Правило §2: вопрос, который
переживает задачу, — в OPEN_QUESTIONS.
Правка: одна запись «C-30 1.16 · охрана пустого графа: ложный отказ A1 и текст A2 · статус: открыт», с входами из ревью 1.16.

## Advisory (не блокируют)

- a1. Стадия 5 у 1.4+1.5, 1.3 и 1.16 закончилась «CHANGES REQUESTED (итерация 1 из 2)»; повторного ревью с APPROVED в
  `docs/reviews/` нет. Ключевые правки я проверил сам: major 1.4+1.5 (самопроверки вхолостую) — в `_IGNORE` теперь
  `import yaml` / `import recipe` (`test_single_writer_guard.py:677,679`); M1 1.16 — тест
  `test_empty_graph_without_base_refuses_when_file_has_foundation_process` есть и краснеет под I1; m1 1.16 —
  `ruff check` / `ruff format --check` по 15 файлам ветки зелёные. Major 1.3 (ключ `0:`) — текст `DECISIONS.md:585-589`
  исправлен, прочитал, запуском не проверял.
- a2. Страж 1.5 сканирует и неотслеживаемые `.py` (`git ls-files --others`): чужой черновой скрипт в checkout даст
  локальный красный. Сейчас в основном checkout таких файлов 0. При желании — только `--cached`.
- a3. `origin/fix/recipe-save-noise` (линия `-48`, `d81816fdf`) расходится с этой веткой. Merge Mac-линии в main
  делает ту ветку конфликтной; решение о ней — владельцу (handoff это уже фиксирует).
- a4. Инъекция I5 (охрана 1.16 перенесена ПОСЛЕ правила владения, та же функция `_is_empty_graph_over_file_processes`)
  выжила: `6 passed`. Это эквивалентный мутант: правило владения подмешивает только процессы с именами из `foundation`,
  а охрана их не считает. Мутант M1 ревью 1.16 (наивная проверка «список пуст» после правила) — другой; его убивает
  новый тест. Дефекта нет.

## Что проверено и держится

**(1) Писатели рецепта — путь за путём.** Pipeline-Save (`layout_controller.py:472`), Recipes-Save
(`recipes/presenter.py:601`), closeEvent и Camera Save (`app.py:145`, `_save_active_topology`) -> один
`save_editor_topology_to_recipe` -> `save_raw` -> `RecipeManager.patch_recipe`. Раскладка — `save_layout`. Устройства —
`save_raw(slug, {"devices": ...})`. Хаб — `RecipeService.save` -> `patch_yaml_preserving`. `RecipeEngine.save` — дельта;
живых вызывающих `RecipeManager.save` / `RecipeEngine.save` вне тестов нет (`git grep` по `.save(` в
prototype/Services/backend_ctl/recipe). `RecipeEngine.load` после миграции — дельта, `.yaml.bak` — копия.
Поиск обходов вне стража: `git grep -nE "write_text\(|write_bytes\(|shutil\.(copy|copy2|move)\(|os\.replace\(|open\(.*\"w"`
по recipe/prototype/device_hub/backend_ctl — писателей файла рецепта мимо движка нет: `manager.duplicate` (`copy2` +
`update_yaml_preserving`), стендовые зонды `backend_ctl/probes/*` (временные рецепты прогона, в allowlist R2),
`hook_contract.py` (tempdir). `recipe.save` в `Services/device_hub` не вызывается (`git grep` — 0); хаб — `orchestrator.py:143-163`.

**(2) 1.16 против 1.8/1.14b/1.15.** Новый рецепт (`on_create`: `processes: []`) — охрана не срабатывает. Непустой граф при
`expected_rev=None` — пишется, как раньше. Сбой захвата базы на активации (`app.py:115-125` -> `(slug, None)`) — пустой
граф отказывает, это и есть цель D2. closeEvent: отказ показывается, окно не закрывается, следующий диалог даёт «не
сохранять» (`main_window.py:338-345`) — ловушки нет. Камера: `RecipeValidationError(ValueError)` не перехватывается
веткой `RuntimeError`, причина идёт в `last_error`. Ложные отказы — только A1/A2 (m2).

**(3) 1.4.** Проба `probe_service.py`: пустой файл -> `invalid`, байты `b''`; рецепт v1 -> `bad_request`, файл цел;
`save` без правок -> `rev` прежний, байты и `st_mtime_ns` прежние; сырая топология (`processes:` сверху) -> правка
пишется, комментарий `# keep` цел. Сверка `rev` под локом: инъекция I4 (сверка отключена) -> красные
`test_save_stale_base_rev_conflict_file_bytes_unchanged`, `test_manual_disk_edit_makes_editor_save_conflict`,
`test_two_saves_same_base_rev_exactly_one_wins`. `meta.version` только вверх: I2 (`elif <` -> `else`) -> красный
`test_save_over_newer_meta_version_keeps_version`. Дельта от нормализованного текущего файла: I3 (`before = {}`) ->
6 красных, в т.ч. оба параметра `test_real_hook_save_identical_body_keeps_bytes_and_changed_field_keeps_comments`.

**(4) Страж 1.5 на общем дереве.** На `f5fa8c237` (с main `cca8fe148`): `test_single_writer_guard.py` -> `88 passed`.
Проба `guard_lanes.py` (сканер стража по `.py`, изменённым в живых ветках, с allowlist и исключениями):
`feat/gui-close-1.1` (10 файлов), `feat/robot-v2-t53e5` (1), `origin/feat/arch-map` (10),
`origin/fix/lifecycle-boot-stop-c82` (10), `origin/feat/atlas-lookup-map` (16), `origin/fix/recipe-save-noise` (5) —
0 нарушений, 0 протухших строк allowlist у каждой.

**(5) Слои.** `sentrux check .` -> «43 rules checked … ✓ All rules pass», Quality 6014.

**(6) Документы.** ADR-RCP-009: разделы «Изменения поведения `recipe.save` хаба» и «`RecipeEngine`»
(`DECISIONS.md:560-595`) совпадают с кодом и пробами (кроме Post — m1). Ссылки на пути в ADR-RCP-009/010: 69 путей;
нерешённые — сокращённые формы (`recipe/service.py` и т.п., файлы есть) и имена файлов будущей рецепт-папки
(`processes.yaml`, `displays.yaml` …, ADR-RCP-006 v4) — неверной ссылки на код не нашёл. Символы
(`patch_yaml_preserving`, `recipe_file_lock`, `read_canonical`, `RecipeConflict`, `YamlWriteRefused`,
`RecipeLockTimeout`, `topology_to_canonical` …) определены.

**Тесты (все `light`, зелёные):**
- `recipe/tests/{test_service,test_recipe_engine,test_backend_writers_patch,test_file_lock,test_recipe_manager_write_api}.py`
  -> `109 passed, 5 skipped` (skip — Windows-лок).
- `backend/tests/test_recipe_service_real_hook_save.py`, `recipes/tests/{test_save_empty_graph_guard,test_canonicalize_gui_positions}.py`,
  `camera/tests/{test_camera_presenter,test_camera_save_blind}.py`, `pipeline/tests/test_save_conflict_rev.py` -> `91 passed`.
- `recipes/tests/{test_save,test_save_noise_save,test_save_noise_store,test_save_protected_owner,test_save_protected_owner_extra,test_save_display_refs_blind}.py`
  -> `94 passed`.
- I1 (охрана 1.16 выключена) -> ровно 3 предсказанных красных в `test_save_empty_graph_guard.py`.
- `ruff check -q` и `ruff format --check` по 15 `.py` ветки -> exit 0. `secrets_audit.py --root` по
  `multiprocess_framework/modules/recipe` и `multiprocess_prototype/recipes` -> exit 0, findings 0.
- Безопасность: новые чтения — `yaml.safe_load` и ruamel round-trip; тексты ошибок не несут значений (`type(exc).__name__`).

## Что я оставил открытым / ненадёжным (стенда нет)

| Что не проверено | Риск | Почему такая оценка |
|---|---|---|
| Живой GUI-стенд M1–M3, сценарии 1.16 (сбой захвата базы -> отказ Save; причина в статусе Камеры), 1.15 (закрытие после автосейва) | средний | Логика покрыта offscreen-тестами; проводка composition root (`capture_foundation`, `capture_base` на старте) видна только на живом GUI. |
| Полные suite (корневой, framework, `backend/tests`) | средний-низкий | Прогнаны 4 батча по радиусу и репо-широкий страж; полный прогон — у лида в heavy-окне. |
| `backend_ctl/tests/test_recipe_service_live.py` (хаб `recipe.save` вживую) | средний-низкий | Нужен живой бэкенд; путь хаба сменился с `safe_dump` на дельту. Юнит-тесты с настоящим хуком зелёные. |
| `recipe/tests/test_yaml_patch.py` (нет `hypothesis`) | низкий для ветки | `yaml_io.py` в диффе ветки не меняется; свойства движка 1.1a на этой машине не подтверждены. |
| Windows: CRLF вживую, `msvcrt`-лок, повтор `os.replace` при `PermissionError` | средний для 1.5 | Миграция `canonicalize_gui_positions` теперь пишет через движок, EOL сохраняется; CRLF только смоделирован, `test_file_lock.py` здесь пропущен. |
| GUI-путь `patch_recipe` на том же входе, что m1 | низкий | Вне диффа ветки (1.1e); не пробовал. |
| Составные мутации (две правки сразу) | низкий | Инъекции одиночные: мои 5 и матрицы лида. |
| Текст major 1.3 (ключ `0:`) | низкий | Прочитан, не воспроизведён запуском. |
| pre-push sentrux (циклы 0->1 на baseline) | процесс | Воспроизводится на main по handoff, не наш; `sentrux check .` зелёный. Push — решение владельца. |
