# recipe-format-single-source — единая каноническая схема рецепта (follow-up)

**Статус:** PLANNED (follow-up после `fix/recipe-v3-engine-decouple`)
**Тип:** refactor (снятие долга, «меньше слоёв строго лучше»)
**Источник:** находки code-review ветки `fix/recipe-v3-engine-decouple` (#1, #3).

## Зачем

Hotfix `recipe-v3-engine-decouple` устранил корень порчи рецептов, но ревью выявило
унаследованный долг — две схемы, два write-пути, мёртвый legacy-слой. Сведение к ОДНОЙ
канонической схеме снимет латентные рассогласования и слои.

## Задачи

### Task 1 — единый источник дисплеев (major)
**Проблема:** `Recipe` entity имеет ОБА поля — `blueprint.displays` (Topology.displays,
консумируется и валидируется доменным `_check_display_references`) И top-level
`display_bindings` (НЕ консумируется при активации, НЕ валидируется). Два write-пути
дают разный диск: `RecipeStoreFromManager.write()` (entity→диск) эмитит top-level
`display_bindings` через `recipe.to_dict()`, а `save_raw`-путь — `blueprint.displays`.
Спасает лишь то, что `write()` не имеет прод-вызовов. `DECISIONS.md:18` утверждает
«рецепт хранит `display_bindings`» — расходится с фактическим форматом файлов.

**Решение:** выбрать single source = `blueprint.displays`. Депрекейтнуть/удалить
top-level `display_bindings` из `Recipe` (или сделать его проекцией `blueprint.displays`).
Привести `write()`/`_denormalize`/`DECISIONS.md` в соответствие. Доменный инвариант уже
валидирует `blueprint.displays` — оставить его как канон.

**Файлы:** `domain/entities/recipe.py`, `adapters/stores/recipe_store.py`,
`multiprocess_framework/.../DECISIONS.md` (или локальный), тесты round-trip.

### Task 2 — удалить мёртвый legacy-движок и одну из двух migration-систем (minor→major)
**Проблема:** после фикса `super().load()` (legacy migrate + TreeStore-replay) не
вызывается ни для одного прод-рецепта (все v3). Существуют ДВЕ системы миграции v1→v2:
`recipes/migrations/format_v1_to_v2.py` (формат файла) и
`backend/state/recipes/migrations/v1_to_v2.py` (processing_blocks→nodes) — обе на проде
не исполняются. Wrapper-defaults перетёрты явными kwargs в `app.py`.

**Решение:** убедиться (grep + проверка пользовательских данных), что внешних v1/v2
рецептов нет; затем удалить мёртвый путь — либо упразднить config-snapshot-семантику
RecipeEngine для рецептов прототипа целиком (рецепт = blueprint, не config-snapshot),
либо вынести в архив одну из migration-папок. Цель — «меньше слоёв при той же
функциональности».

**Риск:** требует уверенности в отсутствии legacy-рецептов у пользователя на проде.
НЕ делать без этой проверки.

### Task 3 (опц., системный nit) — comment-preserving запись для settings/prefs/themes
`prefs/store.py`, `theme_presets_manager.py`, `settings/yaml_io.py` тоже стирают
комментарии через `yaml.dump`. Применить `recipes/yaml_io.update_yaml_preserving`
(или вынести его в общий util) для единообразной стратегии записи YAML.

## Acceptance (high-level)
- [ ] Один канонический источник дисплеев в рецепте; `write()`/`save_raw` дают идентичный диск.
- [ ] `DECISIONS.md` соответствует фактическому формату.
- [ ] Мёртвый legacy-путь/лишняя migration-система удалены (после проверки prod-данных).
- [ ] sentrux: меньше слоёв/связей, не хуже baseline.
