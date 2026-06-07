# recipe-v3-engine-decouple — отвязка v3-рецептов от legacy RecipeEngine

**Ветка:** `fix/recipe-v3-engine-decouple`
**Дата:** 2026-06-06
**Тип:** fix (корректность + порча данных)

## Проблема (корень)

Три «отдельных» симптома оказались одним корнем:

- **#2** «Загрузить рецепт» в GUI молча ломался.
- **#4** приложение переписывало raw-рецепт (`color_inspect.yaml`), стирая комментарии.
- **#1** persist активного рецепта в `app.yaml` был заблокирован.

**Корень:** framework `RecipeEngine.load()` рассчитан на legacy-формат рецепта
`{meta: {version}, data: {...}}` (config-snapshot для TreeStore) + migrate-on-load.
Рецепты прототипа — формат **v3**: плоский top-level `{name, version, blueprint, ...}`
без envelope `data`. Для v3-файла движок видел `data={}` и отсутствие `meta.version`
(→ version=1 < recipe_version), считал файл legacy и **переписывал** его миграцией
пустого `data`, впрыскивая `meta:{migrated_from_v1}` + `data:{пустой blueprint}` и
затирая `blueprint` + комментарии.

Триггер — `RecipeManager.set_active()` → `engine.load()`:
- при старте (активация рецепта из манифеста, `app.py`),
- при клике «Загрузить».

Битый файл → `Recipe.from_dict` бросает `ValidationError` (meta.name missing + extra
`migrated_from_v1`/`data`) → presenter ловил только `DomainError` → активация молча
падала (#2). Тот же конфликт схем + `raw["data"]["blueprint"]`-вложение в presenter'ах
портил рецепт при ручном сохранении (#4).

## Решение (Option A — отвязка, framework не трогаем; + ruamel для комментариев)

1. **Prototype-wrapper `RecipeEngine.load()`** короткозамыкает v3-рецепты (top-level
   `blueprint`): только пометка active, без migrate/replay/перезаписи. Legacy
   config-snapshot (envelope `data`/`meta`) по-прежнему делегируется в generic-движок.
2. **`app.py`** импортирует prototype-wrapper, а не generic framework-движок (это был
   промах: правка wrapper'а не попадала в путь старта).
3. **Presenter активации** ловит `ValidationError`/прочее и **показывает** ошибку
   (surface-not-mask) вместо тихого провала.
4. **#4 ручное сохранение:** `on_save`/`save_to_active_recipe` пишут top-level
   `blueprint` (displays ВНУТРИ `blueprint.displays`), без legacy `data:`-вложения;
   `save_raw`/`write` пишут через **ruamel round-trip** (`recipes/yaml_io.py`) —
   комментарии и неизменные ключи (name/version/description/active_services) сохраняются.
   Defensive: при сохранении из raw убираются стрелочные `data:`/`meta:` от старой порчи.
5. **persist #1:** при успешной активации `pipeline:` в `app.yaml` обновляется через
   тот же comment-preserving writer (колбэк `RuntimeDeps.persist_active_recipe` →
   presenter `persist_active_fn`). Закрывает loop: активация → app.yaml → restore при старте.

## Acceptance

- [x] v3-рецепт не портится при `load()`/`set_active` (regression-тесты + end-to-end md5).
- [x] «Загрузить» чистого рецепта проходит через dispatch без ValidationError.
- [x] Ручное сохранение пишет top-level v3 (не `data:`), комментарии сохраняются, round-trip
      валиден для `Recipe.from_dict`.
- [x] persist пишет `pipeline:` в app.yaml с сохранением комментариев.
- [x] ruamel.yaml в pyproject; ruff/тесты зелёные.

## Файлы

- `multiprocess_prototype/backend/state/recipes/recipe_engine.py` — wrapper v3 short-circuit
- `multiprocess_prototype/frontend/app.py` — import wrapper + persist-closure
- `multiprocess_prototype/frontend/runtime_deps.py` — поле `persist_active_recipe`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/{presenter,tab}.py` — persist + ValidationError
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — save top-level
- `multiprocess_prototype/adapters/stores/recipe_store.py` — save_raw/write через ruamel
- `multiprocess_prototype/recipes/yaml_io.py` — comment-preserving writer (новый)
- `pyproject.toml` — ruamel.yaml
- тесты: `test_recipe_v3_no_corruption.py`, `test_yaml_io.py`, обновлены `test_save_recipe.py`/`test_recipes_presenter.py`/`test_recipe_store.py`

## Долг / out of scope

- Осиротевший тест `recipes/tests/test_demo_recipe.py` ссылается на удалённый
  `demo_webcam_split_merge.yaml` (коммит 9a29fcb9) — 5 pre-existing падений, удалить отдельно.
- Косметика: 3 ложных unresponsive при старте процессов после replace (безвредны).
- Inner-комментарии внутри `blueprint` при правке графа неизбежно теряются (топология
  переписывается); заголовок и top-level комментарии сохраняются.
