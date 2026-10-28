# Plan: сохранение рецепта из GUI без шума и с комментариями YAML (C-30)

- **Slug:** recipe-save-noise
- **Дата:** 2026-10-26
- **Статус:** DRAFT
- **Plan review:** CHANGES 4 (стадия 0, раунды 1–4; доработан по раунду 4 2026-10-26)
- **Ветка:** `fix/recipe-save-noise`

## Что где живёт

| Что | Где |
|---|---|
| Контракт: цель, задачи одной строкой, гейты, бюджет | этот файл |
| Факты (file:line), контракт движка, подключение, матрица приёмки, риски, журнал решений | [`design.md`](design.md) |
| Тело задачи (TASK/ROLE/CHAIN/DESIGN/FILES/REDS/ACCEPTANCE/TESTS/OUT OF SCOPE/TRAPS) | `tasks/<id>.md` |
| Пробы стадии 0 (спайк F16, репро `efc2612c3`) | [`probes/`](probes/) |
| Изменения после approve | [`amendments.md`](amendments.md) |

## Контекст

Дефект C-30 (`plans/queue/defects.md`; очередь владельца — `plans/queue/ORDER.md` строка 3, полоса Д, после
C-21(б)). Сохранение рецепта из GUI переписывает файл целиком: умолчания модели (`extras: {}`, `restart_policy: {}`,
`src_dtype/tgt_dtype: null`, top-level `gui_positions: {}`), перенос `blueprint.name/description` в `metadata`,
потеря комментариев и flow-стиля. `efc2612c3` воспроизведён побайтно путём «Дисплеи» (`probes/c30_investigation.md`).
Причины: писатель заменяет поддерево целиком (`recipe/yaml_io.py:84`), вызывающие отдают полный дамп модели.

Директива владельца 2026-10-26: «Главное чтоб костылей не было, а делалось к лучшей и правильной архитектуре!!!!
Которая позволяет масштабировать и улучшать систему». Поэтому: **один** дельта-движок во framework; писатель файлов
рецепта — `RecipeManager.patch_recipe` (ревизия под межпроцессным локом, топология и раскладка одной записью), прототип
только делегирует; `Topology` типизирует `name/description`. Подробно — [`design.md`](design.md) §2–4, §9–10.

## Цели

1. Каждый GUI-путь записи рецепта (`design.md` §6: Дисплеи, Recipes-Save, Pipeline-Save, Камера, Устройства,
   раскладка) без правок не меняет файл: байты и `st_mtime_ns` прежние на фикстуре `efc2612c3^` и на 22 рецептах.
2. Одна правка → `diff` только из строк этого поля (литералы); комментарии T3.7 ×2, Task 5.3b, Ф3.8/G1 на месте;
   удаление элемента не уносит комментарий следующего соседа.
3. Галочка дисплея вкл → выкл → файл побайтно прежний; независимо от `PYTHONHASHSEED` (0..3); EOL файла сохраняется.
4. Один движок записи: `grep -n "data\[key\] = value\|meta\[key\] = value" multiprocess_framework/modules/recipe/yaml_io.py`
   → 0 строк; в `recipe_store.py` нет импорта `yaml_io`.
5. Тесты на настоящих `RecipeStoreFromManager` + `RecipeManager` с tmp-файлом; цепочка каталог → store → manager → файл.
6. Ручная правка файла после загрузки в GUI не откатывается молча: запись с устаревшим `rev` → `RecipeConflict`, файл цел,
   GUI показывает «Рецепт изменён снаружи — перезагрузите его»; сверка `rev` и запись атомарны между процессами (хаб и
   GUI — `recipe_file_lock`); вызывающие вне модуля `recipe` адресуют рецепт по slug.
7. Политика канонической формы (ADR-RCP-010, `design.md` §10): один нормализатор на приложение, вызывающие — через
   `read_canonical` и один адаптер; программа не пишет умолчаний; хук проходит общий контракт на 22 рецептах.
8. Обход писателя ловится механически: новый файл с YAML-дампом или импортом писателей движка вне модуля `recipe` и
   allowlist (`design.md` §8) — красный `test_single_writer_guard.py`; каждая инъекция Task 1.5 — красная.

## Out of scope

- Содержимое `multiprocess_prototype/recipes/*.yaml` (полоса C) — чистка шума HEAD в «Дальше».
- `process_manager_module/**`, `Services/device_hub/**`, `Plugins/processing/word_layout`, `Plugins/filter/line_filter`,
  `Services/ml_inference`.
- Слияние правок при конфликте (3-way merge) — строка в `docs/claude/OPEN_QUESTIONS.md` (Task 1.3); конфликт = отказ + сообщение.
- Переход на рецепт-папку (ADR-RCP-006 v4) и раскладка отдельным файлом (решение №20) — не делаются; после C-30 —
  правка только внутри `RecipeManager` (`design.md` §9.6).
- Сопоставление элементов списков по ключу (`id`/`process_name`).

## Бюджет

17 задач (поправка №2: +1.1i, +3 запуска, ≈ +0,6M → ≈ 10,1M). Запуски: стадия 0 (reviewer) × 4 (выполнены); слепой тестер × 1; teamlead (Opus) × 2 (1.1a, 1.1h);
developer (Sonnet) × 13; tech-writer × 1 (1.3); reviewer стадии 5 × 16 (express у 1.6, 1.10, 1.3); ревью ветки (Opus) × 1 —
**38 запусков** × ~56k старта ≈ 2,13M. Сверх старта (оценка): тестер ~0,3M; developer 13 × ~0,25M = 3,25M;
teamlead 2 × ~0,35M = 0,7M; tech-writer ~0,2M; reviewer стадии 5: 13 × ~0,1M + 3 × ~0,05M = 1,45M; стадия 0: 4 × ~0,1M =
0,4M; Opus ветки ~0,4M; инъекции лида (92 правки) ~0,7M. Итого ≈ 2,13 + 7,4 = **9,5M** токенов all-in (оценка).
teamlead сверх 1.1a/1.1h — только эскалация. Пересчёт — записью в `amendments.md` после Task 1.1c.

## Конвейер (`.claude/CLAUDE.md` «Task launch convention»)

стадия 0 reviewer → слепой тестер (один раз на механизм, worktree на коммите до реализации) → исполнители по одному,
режим A: 1.1a → 1.6 → 1.1b → 1.1h → 1.1e → 1.1f → 1.1i → 1.1g → 1.7 → 1.1c → 1.2 → 1.8 → 1.9 → 1.10 → 1.4 → 1.5 → инъекции лида (блок
INJECT задач) → стадия 5 reviewer на задачу → tech-writer 1.3 → ревью ветки (Opus) перед merge. Лимит — 2 итерации на
цикл, третья → `teamlead`, затем `cto`. Порядок 1.1g → 1.7 → 1.1c: стор пишется один раз против финального Protocol.

**Авторы REDS.** Слепой тестер (одним запуском, по `design.md` §2/§6 и ACCEPTANCE) пишет приёмочные файлы:
`recipe/tests/test_yaml_patch.py` (1.1a), `recipes/tests/test_save_noise_store.py` (1.1c),
`recipes/tests/test_save_noise_save.py` (1.2). В остальных задачах исполнитель пишет REDS сам, до правки `src` (файлы —
таблица «Injections»). Коммит задачи не краснеет от тестов следующих; TESTS называет только свои файлы.

**Слепому тестеру запрещено читать** (стадия 1 выполнена): `yaml_io.py`, `manager.py`, стор, `save.py`, `topology.py`, DESIGN/INJECT, `probes/`; читает `design.md` §2, §6, ACCEPTANCE/REDS.

Гейты: `light` — свои тест-файлы; `medium` — каталог тестов модуля; полный набор — лид. Все команды через
`scripts/machine_gate.sh`, сессия `inspector-bottles-d8`.

## Порядок выполнения

### Phase 1: один дельта-движок записи рецепта

**Цель фазы:** GUI сохраняет только изменённое; без правок файл не трогается.

- Task 1.1a: **[VERTICAL SLICE]** часть 1 — дельта-движок (`patch_yaml_preserving`, `apply_delta`, `YamlPatchConflict`); первый шаг — F16 на спайке (teamlead) [DONE]
  - **Module contract:** public-api-change (`recipe/yaml_io.py`, `recipe/__init__.py`)
- Task 1.6: пин `ruamel.yaml>=0.19.1,<0.20` и тест формы токенов [DONE] (после 1.1a)
  - **Module contract:** n/a
- Task 1.1b: **[VERTICAL SLICE]** часть 2 — тонкие `update_*_preserving` над движком, `compute_rev` в `format.py` [DONE] (после 1.6)
  - **Module contract:** public-api-change (`format.compute_rev`)
- Task 1.1h: межпроцессный лок `recipe_file_lock` (stdlib, `<slug>.yaml.lock`, таймаут → `RecipeLockTimeout`); `RecipeService.save/delete` под ним (teamlead) [DONE] (после 1.1b)
  - **Module contract:** new-lite (`recipe/file_lock.py`)
- Task 1.1e: **[VERTICAL SLICE]** часть 3 — API записи `RecipeManager`: `read_recipe_rev`, `patch_recipe(..., layout=)`, `save_layout`, `RecipeConflict` [DONE] (после 1.1h)
  - **Module contract:** public-api-change (`RecipeManager`, `RecipeManagerProtocol`)
- Task 1.1f: канон во framework — `read_canonical`, `RecipeFormatError`, `on_insert`, контракт хука [DONE] (после 1.1e)
  - **Module contract:** public-api-change (`RecipeManager.read_canonical`, `recipe/hook_contract.py`)
- Task 1.1i: склейка комментариев у `- {}` — корень в движке, `YamlWriteRefused` (teamlead) [DONE] (после 1.1f)
  - **Module contract:** public-api-change (`recipe.YamlWriteRefused`)
- Task 1.1g: хук v3 в GUI, адаптеры `Recipe`/`Topology` ↔ канон, контракт на 22 рецептах [DONE] (после 1.1f)
  - **Module contract:** new-lite (`adapters/recipe_canonical.py`)
- Task 1.7: `Topology` типизирует `name/description` + финальный Protocol `RecipeStore` (`read_canonical`, `read_raw_with_rev`, `expected_rev`, `layout`) и фейк [DONE] (после 1.1g; слито с 1.1d)
  - **Module contract:** public-api-change (Protocol `RecipeStore` прототипа)
- Task 1.1c: **[VERTICAL SLICE]** часть 4 — `RecipeStoreFromManager` по slug через канон и `RecipeManager`; приёмка Дисплеи/Камера/Устройства/раскладка [DONE] (после 1.7)
  - **Module contract:** impl-only
- Task 1.2: Recipes/Pipeline/closeEvent-Save через `topology_to_canonical`, раскладка той же записью; непарсимое — `RecipeValidationError` [DONE] (после 1.1c)
  - **Module contract:** impl-only
- Task 1.8: базовый `rev` редактора в `TopologySession` (старт и активация), конфликт — «Рецепт изменён снаружи — перезагрузите его» [DONE] (после 1.2; `12c4f906b`, `89d906923`; F1 — вердикт CTO, вариант d; отчёт `docs/reports/2026-10-27_task-1.8_C-30.md`)
  - **Module contract:** impl-only
- Task 1.9: Устройства читают `read_canonical`, пишут с базой `TopologySession` и двигают её (вердикт CTO по F1); локальные фейки вкладки [DONE] (после 1.8; `e8a61ecfe`, `4584c8b45`; отчёт `docs/reports/2026-10-27_task-1.9_C-30.md`)
  - **Module contract:** impl-only
- Task 1.10: Камера читает `read_canonical`, пишет с `rev`; конфликт виден в логе [PENDING] (после 1.9)
  - **Module contract:** impl-only
- Task 1.4: `recipe.save` хаба и snapshot `RecipeEngine` через движок [PENDING] (после 1.10)
  - **Module contract:** impl-only
- Task 1.5: страж — AST R1/R2/R3/R4 с allowlist, `canonicalize_gui_positions` через движок [PENDING] (после 1.4)
  - **Module contract:** impl-only
- Task 1.3: ADR-RCP-009 (движок, ревизия и лок, папка, решение №20), ADR-RCP-010 (каноническая форма), правка ADR-RCP-006, README/STATUS, OPEN_QUESTIONS, sync [PENDING] (после 1.5)
  - **Module contract:** n/a

Срез 1.1a → 1.1b → 1.1h → 1.1e → 1.1f → 1.1g → 1.7 → 1.1c — вертикальный (движок → `RecipeManager` → store → каталог →
файл); разделён по лимиту REDS ≤ 10 на бриф и одному свойству на тест.

## Injections

Лид правит код по блоку INJECT и сверяет красные с предсказанными; 97 правок.

| Task | INJECT | файл тестов (предсказанные красные — в блоке INJECT) | observed red |
|---|---|---|---|
| 1.1a | 13 | `recipe/tests/test_yaml_patch.py` | |
| 1.6 | 2 | `recipe/tests/test_ruamel_contract.py` | |
| 1.1b | 3 | `recipe/tests/test_thin_contracts.py` | |
| 1.1h | 5 | `recipe/tests/test_file_lock.py` | |
| 1.1i | 5 | `recipe/tests/test_yaml_patch.py` | |
| 1.1e | 8 | `recipe/tests/test_recipe_manager_write_api.py` | |
| 1.1f | 6 | `recipe/tests/test_canonical_form.py` | |
| 1.1g | 4 | `adapters/tests/test_recipe_canonical.py` | |
| 1.7 | 5 | `recipes/tests/test_save_noise_topology.py`, `domain/tests/test_fakes_contract.py` | |
| 1.1c | 9 | `recipes/tests/test_save_noise_store.py` | |
| 1.2 | 8 | `recipes/tests/test_save_noise_save.py` | |
| 1.8 | 6 | `pipeline/tests/test_save_conflict_rev.py` | |
| 1.9 | 3 | `devices_common/tests/test_recipe_devices.py`, `domain/tests/test_fakes_contract.py` | |
| 1.10 | 3 | `camera/tests/test_camera_presenter.py` | |
| 1.4 | 7 | `recipe/tests/test_backend_writers_patch.py` | |
| 1.5 | 10 | `recipe/tests/test_single_writer_guard.py`, `recipes/tests/test_canonicalize_gui_positions.py` | |

## Открытые вопросы (владельцу)

Нет. В-П1…В-П3 закрыты ответами ревью раунда 3 (`design.md` §10.2); решения владельца и лида — `design.md` §11.

## Дальше (вне плана)

- Чистка 21 строки шума в HEAD `letter_robot_sim.yaml` и возврат комментариев, legacy top-level `gui_positions` в
  `camera_robot_calibration`, `dataset_circle_capture`, `letter_robot_sim` — отдельный коммит с полосой C.
- F3 (решение владельца 2026-10-28; отдельная задача после merge 13/17, не в C-30): слоты Устройств не ловят
  `RecipeLockTimeout` / `RecipeFormatError` / `YamlWriteRefused` — `docs/claude/OPEN_QUESTIONS.md`, `add_page.py:176`,
  `crud_actions.py:93,179`.
- Дисплеи (`display_catalog_recipe.py`) не двигают базу сессии: `unregister` с привязками — в 2.0 (владелец 2026-10-28); `register`/`update` с базой — задачи нет; окно принято (`amendments.md` №8).
- Строка C-30 в `plans/queue/defects.md`, строка 3 `ORDER.md` — лид при закрытии.

## Связи с соседними планами

- [`plans/app-active-recipe-state.md`](../app-active-recipe-state.md) (C-21(б)) — владеет писателем `app.yaml`
  (`ManifestStore.set_pipeline`, `<stem>.state.yaml`, свой лок `<manifest>.lock`); этот план — файлами рецептов
  (`<slug>.yaml.lock`). Пересечения по файлам нет. Обратная ссылка — в его «Out of scope» C21.1.
- [`plans/release-1.0/design.md`](../release-1.0/design.md) строка «#3 (полоса Д): C-21(б), C-30, R1» — условие
  «чистое дерево после прогона»: после C-30 сохранение без правок файл рецепта не меняет; lock-файлы игнорирует
  `.gitignore:150` (`*.yaml.lock`).

## Решения (decisions log)

Журнал — [`design.md`](design.md) §11.
