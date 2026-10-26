# Стадия 0 · раунд 3 · ревью доработки (15 задач) · 2026-10-26

Ревьюер: reviewer (Sonnet), MODE: plan, только чтение (без pytest, без `sentrux check .`). Вердикт: **CHANGES REQUESTED** (блокируют F1–F3).

## Решения владельца по итогам (2026-10-26, не пересматривать)

- **F1 → межпроцессный лок сразу.** Lock-файл рядом с рецептом, stdlib (`msvcrt` на Windows / `fcntl` на POSIX), без новых зависимостей, в одной функции модуля `recipe`. Им пользуются и `RecipeService` (хаб), и `RecipeManager` (GUI). Сверка `rev` + запись атомарны между процессами. Тот же механизм потом нужен для перехода на папку (две записи).
- **F2 → одна запись.** `RecipeManager.patch_recipe(slug, after, *, expected_rev, layout=None) -> str`, `layout = (positions, locked_nodes)`. Раскладку пишет общий приватный `_apply_layout(doc, positions, locked)`; публичный `save_layout` (автосохранение при перетаскивании) зовёт его же — писатель раскладки один (решение (д)). Цепочка `rev1 → save_layout` в Pipeline-Save исчезает вместе с REDS `..._chains_rev_into_save_layout`.

## Решения лида (2026-10-26)

- F3: держатель базового `rev` — `TopologySession` (см. F3 и п. 4 ниже).
- F4: задачу 1.1a выполняет `teamlead` (Opus). Пробы из scratchpad старой сессии перенести в папку плана, если они ещё на диске.
- Слияния: **1.8 + 1.9**, **1.1d + 1.7**; стадия 5 для 1.6 — экспресс-ревью; порядок **1.1g → 1.7 → 1.1c** (store пишется один раз против финального Protocol).
- В-П1, В-П2, В-П3 закрыть по ответам ниже.

## Находки

**F1 (блок).** `design.md` §9.1 и `tasks/1.1e.md` DESIGN 2 опираются на «файловый лок модуля, переиспользовать `service._lock`». Такого лока нет. `service.py:235-236, 248-250`: `_lock` — метод экземпляра `RecipeService`, внутри `threading.Lock` на имя, реестр в `self._locks`. У `RecipeManager` нет `RecipeService`, а `service.py` не входит в FILES 1.1e. GUI и хаб — разные процессы: `RecipeManager` создаётся в `frontend/app.py:501-524`, `RecipeService` — в `orchestrator.py:139-159`. Ревьюер не сопоставил каталог хаба (`orchestrator.py:149`, `store.load().recipes`) с каталогом GUI (`app.py:495`).

**F2 (блок).** Сегодня позиции пишутся одной записью вместе с топологией (`layout_controller.py:434, 438-443` через `build_recipe_v3_raw`). Если в плане вторая запись падает не конфликтом, `rev1` теряется, и повторный Save получает ложный `RecipeConflict`. Закрыто решением «одна запись».

**F3 (блок).** `tasks/1.8.md` DESIGN 1 ссылается на `app.py:975`, но это `_read_active_recipe` для `_rebuild_displays`, к редактору отношения не имеет. Реальная загрузка: `Project._apply_activate_recipe` (`domain/entities/project.py:920-960`) → `catalogs.recipes.read(slug)` (возвращает `Recipe` без `rev`) → `TopologyRepositoryStore` (`adapters/stores/topology_repository.py:40-78`). Редактор читает в `layout_controller.py:166`. Жизненным циклом управляет `TopologySession` (`domain/topology_session.py`, подписка `app.py:698-710`).

**F4 (major).** 1.1a DESIGN 2 и design F16 оставляют нерешёнными лишнюю пустую строку и удаление элемента 0. Спайк `probe_spike.py` лежит вне репозитория: `…/e877acb2-…/scratchpad/d8review/`. На нём держатся F9, F11, F16, F17.

**F5 (major), дыры в дельте и REDS 1.1a.**
- (i) Отсутствующий промежуточный контейнер. `N(file)` шире файла (F10: в 6 рецептах нет `blueprint.metadata`). Нужны фраза в §2.3 и RED `test_delta_into_absent_container_creates_it`.
- (ii) Якорь и алиас: `dataset_circle_capture.yaml:319` (`gui_positions: &id001`) и `:396` (`*id001`). Правило: менять содержимое на месте, иначе `YamlPatchConflict`. Нужен RED на этом рецепте.
- (iii) В `design.md` §2.1, §4.1 и §4.3 устарела сигнатура `patch_recipe(slug, before, after) -> bool`. Эти разделы читает слепой тестер: пометить «заменено §9/§10».

**F6 (major).** Слепой тестер не может написать REDS, которым нужны сигнатуры из DESIGN:
- 1.2: `..._stale_rev_conflict_no_write`, `..._message_has_no_input_values`;
- 1.1c: `test_store_conflict_on_hand_edit_between_read_and_write` (нужен `read_recipe_rev`).

Правка: перенести эти REDS автору или вынести сигнатуры в ACCEPTANCE.

**F7 (major, гипотеза).** Верхнеуровневые `gui_positions` есть в `camera_robot_calibration`, `dataset_circle_capture`, `letter_robot_sim`. `canonicalize_gui_positions.py:128` переносит их в `blueprint.metadata`, а у `Recipe` своё поле (`domain/entities/recipe.py:91`). Если `read()` raw, а `write` пишет из `read_canonical`, цикл по 22 рецептам может покраснеть. Правка: в 1.1c `read(slug) = recipe_from_canonical(read_canonical(slug)[0])` и RED на legacy-рецепт. Сначала проверить `Recipe.from_dict`.

**F8 (major).** В 1.1f `assert_format_hook_contract(hook, docs)` прогоняется в подпроцессах с разным `PYTHONHASHSEED`, и не определено, как передать туда хук. Выбрать одно: `hook_factory: "pkg.mod:Class"` или отдельный контрактный тест. Для `hook_contract.py` нужен lite-скаффолд Purpose / Public API / Stability.

**F9 (minor).** В `plan.md` открытых вопросов «нет», в `design.md` §10.2 открыты В-П1…В-П3. Закрыть оба места.

**F10 (minor).** `recipe_format_hook.py:39-40` мигрирует v1 в v2. Дельта на v1-файле даст гибрид. Нужно правило отказа, симметричное 1.4, и RED. v1-файлов среди 22 сейчас нет.

**F11 (minor).** `format_hook` в 1.1e описан как Protocol с `normalize`, а в 1.1f — как `RecipeFormatHook` (`service.py:137`, 3 метода, `@runtime_checkable`). Выбрать один вариант уже в 1.1e.

**F12 (minor).** 1.1c меняет поведение `list()` (`sorted(glob)`, `recipe_store.py:59` → `RecipeManager.list()`, `manager.py:95-103`) и `delete()` (`unlink` → `RecipeManager.delete`, который сбрасывает `state.recipes.active`, `manager.py:158-164`). Нужен RED на совпадение `list()` на 22 рецептах и строка о побочном эффекте `delete`.

**F13 (minor).** RED 1.1e `test_all_recipes_patch_with_own_body_is_noop` во framework читает файлы прототипа (урок `feedback_framework_tests_cannot_import_prototype`). Перенести в 1.1g или перевести на синтетику.

**F14 (minor).**
- Запусков 35, а не 34.
- Таблица Injections неполна (INJECT есть у 1.6, 1.1b, 1.1e, 1.1f, 1.1g, 1.7, 1.8, 1.9, 1.4, 1.5).
- Нумерация целей идёт 1, 2, 3, 4, 5, 7, 8, 6.
- В HANDOFF IN задачи 1.3 нет 1.1e, 1.1f, 1.1g, 1.7, 1.8, 1.9, 1.4.
- `test_recipe_manager_patch.py` (1.1b) переименовать, например в `test_thin_contracts.py`.

**F15 (minor).** Нет теста «минимизированное и полное одинаково грузятся backend-моделью» (см. В-П2).

## Ответы на открытые вопросы

**В-П1: можно ли GUI импортировать хук из `backend/`.** Можно, переносить хук не нужно.
- `.sentrux/rules.toml` запрещает только `backend/* → frontend/*`.
- `frontend/app.py:155, 172, 260, 474, 510, 516` уже импортируют `backend`.
- Хук не зависит от Qt (`recipe_format_hook.py:16`).
- В 1.1g одна проверка: нет цикла `recipes.save ↔ adapters.recipe_canonical`.
- Шаг 1 из 1.1g убрать.

**В-П2: `minimize` знает только умолчания pydantic.** Допустимо, но с условием. Файл читает backend-модель `SystemBlueprint`, а минимизирует доменная модель. Отсутствие `extras` проверено и безопасно (`process_manager_module/topology/blueprint.py:287`). `restart_policy`, `priority` и `enabled` не проверены. RED в 1.1g: для каждого типа сущности `backend_load(minimize(x)) == backend_load(x)` на 22 рецептах.

**В-П3: хук-тождество для snapshot.** Не нужно. `RecipeEngine.save` по 1.4 DESIGN 3 хук не использует. Диспетчеризация по форме уже есть в `InspectorRecipeFormatHook.normalize` (`recipe_format_hook.py:35-41`). Переформулировать ADR-RCP-010 п. 1: «один нормализатор на приложение, диспетчеризует по форме; конверт meta/data проходит насквозь; запись snapshot нормализатор не использует». RED в 1.1g: `test_v3_hook_is_identity_on_snapshot_envelope`. Конверты пишет `recipe_engine.py:159-196`.

## П. 4: держатель базового `rev`

- Держатель — `TopologySession`: чистый Python, `__slots__`, уже есть `mark_activated` и `mark_saved`.
- Слот `(slug, base_rev)`. Захват на `RecipeActivated` через `read_raw_with_rev(slug)` из Protocol 1.7. Второе чтение после `Project` — зафиксированный остаточный риск. После успешной записи база обновляется.
- `expected_rev` берётся из базы, только если `target_slug` совпадает со slug загрузки. Recipes-Save в другой рецепт (`recipes/presenter.py:557-594`) идёт на `rev` собственного чтения стора.
- `on_create` (`presenter.py:243`) передаёт `expected_rev=None`. Нужен RED в 1.7.
- Хранить базу в `RecipeStoreFromManager` нельзя: чтения Дисплеев, Камеры и Устройств молча обновляли бы её.
- FILES 1.8: добавить `domain/topology_session.py` (`app.py` там уже есть).

## Подтверждено ревьюером

- Порядок задач не нарушает зависимостей.
- FILES существуют.
- Рецептов 22.
- Обратных импортов нет (по тексту `rules.toml`, `sentrux check .` не запускался).
- Чек-лист (a–h) пройден, кроме оценки уровня 1.1a (F4) и числа запусков (F14).

## Не проверено

- Пробы F9, F11, F16, F17 не воспроизводились.
- F7 и F12 — гипотезы.
- В-П2 проверен только для `extras`.
- Инвентарь писателей §8.2 проверен выборочно.
