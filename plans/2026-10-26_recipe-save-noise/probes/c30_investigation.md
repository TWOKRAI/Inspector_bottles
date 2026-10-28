# C-30 — расследование (investigator, Opus, 2026-10-26)

## Вывод
efc2612c3 записан путём вкладки «Дисплеи»: DisplayCatalogFromRecipe → RecipeStoreFromManager.write(slug, Recipe) — сериализует всю сущность Recipe и пишет каждую верхнеуровневую секцию целиком через update_yaml_preserving. Воспроизведено побайтно: вход `git show efc2612c3^:multiprocess_prototype/recipes/letter_robot_sim.yaml`, скрипт `probes/c30_repro.py` (аргумент — каталог с `before.yaml`) вызывает DisplayCatalogFromRecipe(...).persist() на текущем коде → PYTHONHASHSEED=3 byte-identical с efc2612c3; при сидах 0/1/2 — 2 строки (порядок name/description в metadata: domain/entities/topology.py:172 итерирует множество `_BLUEPRINT_META_KEYS & extra_keys`).
Контроль: путь B (Save рецепта/Pipeline) — 5 строк, без gui_positions, name остаётся; путь C (камера save_raw raw) — 48 строк, без пустых {}.

Атрибуция шума:
- blueprint.name/description → blueprint.metadata: Topology.from_dict (domain/entities/topology.py:146-176), вызов из Recipe.from_dict (recipe.py:221).
- top-level gui_positions: {}: поле-умолчание Recipe.gui_positions (recipe.py:91), Recipe.to_dict() = model_dump(mode="json") (recipe.py:261) без exclude_defaults; ruamel дописывает новый ключ в конец.
- restart_policy: {}, extras: {}, src_dtype/tgt_dtype: null — умолчания Process (process.py:102,121) и Wire, тот же model_dump.
- комментарии внутри devices/blueprint пропали, {P_ZONE_MAX: 6000} стал блочным: update_yaml_preserving (multiprocess_framework/modules/recipe/yaml_io.py:84) делает data[key] = value plain dict → поддерево заменяется целиком. Заголовок и комментарии над top-level ключами уцелели.

Срабатывает: каждая операция вкладки «Дисплеи» (register/update/unregister + _persist() → 2 полные перезаписи): Создать (presenter.py:268,273), Удалить (:284,289), Дублировать (:333,339), галочка «Показывать в главной области» (tab.py:583 → presenter.py:373,378). Дефект жив в HEAD: в letter_robot_sim.yaml сейчас 21 строка шума.

## Все пути записи рецепта из GUI
| Триггер | Цепочка | Писатель | Сериализатор | Комментарии | Умолчания | Что переписывает |
|---|---|---|---|---|---|---|
| Дисплеи: Создать/Удалить/Дублировать/вкл-выкл | displays/presenter.py:268-378 → adapters/catalogs/display_catalog_recipe.py:201,239,274,308 → adapters/stores/recipe_store.py:72-83 (write + _denormalize) | update_yaml_preserving (yaml_io.py:58) | ruamel, внутри Recipe.model_dump(json) | теряет внутри секций | пишет все ({}, null) | все секции Recipe целиком + gui_positions |
| Pipeline «Сохранить» (pipeline/tab.py:250,430) | presenter.py:655 → layout_controller.py:388-446 → recipes/save.py:175-211 → recipe_store.py:98 | то же | ruamel, процессы из graph_to_blueprint | теряет внутри blueprint (и в секциях, что save.py копирует из raw) | зависит от graph_to_blueprint — не проверено | все ключи raw целиком |
| Рецепты «Сохранить» (recipes/tab.py:382) и диалог закрытия (app.py:797-806) | recipes/presenter.py:557-594 → save.py:211 → save_raw | то же | ruamel, процессы/провода из Topology.to_dict() | теряет внутри всех секций | пишет restart_policy/extras/dtype | все ключи raw целиком |
| Камера «Сохранить» | frontend/widgets/tabs/services/camera/presenter.py:91-108 (save_raw(slug, raw)) | то же | ruamel, raw из yaml.safe_load | теряет внутри всех секций | нет | все ключи raw целиком |
| Устройства upsert/remove | frontend/widgets/tabs/services/devices_common/recipe_devices.py:118,130 | то же | ruamel | теряет внутри devices | нет | только devices |
| Перетаскивание ноды (автосохранение раскладки) | layout_controller.py:303 → recipe_store.py:111 | update_blueprint_metadata_preserving (yaml_io.py:128) | ruamel | сохраняет | нет | только blueprint.metadata.{gui_positions,locked_nodes} |
| Рецепты Создать/Дублировать | recipes/presenter.py:243; recipe manager.py:221-227 (copy2 + {"name"}) | то же | ruamel | новый файл / сохраняет | нет | новый файл / только name |

Без живого вызывающего (FREEZE-контракты): layout_controller.py:200 и topology/presenter.py:77 (PyYAML dump всего файла). Не GUI: recipe_engine.py:192,277, service.py:321 (recipe.save, safe_dump).

## Один писатель
Нижний писатель уже один — yaml_io.py. Проблема в семантике: (а) замена поддерева целиком; (б) вызывающие отдают полный дамп модели, а не дельту. update_yaml_preserving менять нельзя: migrations/drop_display_name.py:88 рассчитывает на замену целиком (удаление ключей).

## Открыто (investigator)
- Какое именно действие на «Дисплеях» сделали 2026-10-18 — не установлено.
- Pipeline-Save (graph_to_blueprint) не прогонялся.
- Repro заменяет RecipeManager заглушкой (read_recipe = yaml.safe_load, как manager.py:319); настоящий GUI не запускался.
- Попутно: порядок ключей metadata в Topology.from_dict зависит от hash seed.
