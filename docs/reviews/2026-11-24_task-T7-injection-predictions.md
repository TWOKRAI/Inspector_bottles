# T7 (gui_overload_synth): предсказания инъекций лида, записаны ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t7-dev` (ветка feat/gfp-t7-synth-recipe, база bc82d9363). Мутации применяются к файлам worktree текстовой подменой с байтовой копией и откатом по sha256. «Красный набор» — тесты, которые должны упасть; остальное зелёное. Опора: раздел «Инъекции (план)» в T7.md (reviewer стадии 0 воспроизвёл часть check()/build() запусками) и 15 тестов developer-а.

Базовая линия (до мутации, из отчёта developer-а): test_gui_overload_synth_recipe.py 15 passed; test_dotted_process_name.py -k gui_overload_synth 1 passed; test_unapplied_metadata_check.py -k gui_overload_synth 1 passed; adapters/tests/test_recipe_canonical.py 189 passed; backend/tests/test_recipes_join_contract.py 103 passed; backend/tests/test_recipe_format_hook.py 31 passed.

| № | мутация (yaml gui_overload_synth.yaml, если не сказано иное) | ожидаемый красный набор | ожидаемо зелёное |
|---|---|---|---|
| M1 | у camera_0 `chain_targets: [gui]` -> `[gui_x]` | test_recipe_validates; test_a5_built_recipe_has_no_dotted_process_name[gui_overload_synth] (test_dotted_process_name.py); test_m10_recipe_builds_without_raising[gui_overload_synth] (test_unapplied_metadata_check.py) | test_display_fps_limit_and_size, test_source_size_and_fps_per_camera, test_no_hardware_plugins |
| M2 | привязка дисплея camera_0: `node_id` camera_0.synthetic_frame_source.frame -> camera_1.synthetic_frame_source.frame | test_four_sources_routed_to_four_displays; test_frame_routing_via_build_frame_routing | test_recipe_validates (check() узкий, даёт []), test_source_size_and_fps_per_camera |
| M3 | `fps_limit` дисплея camera_0: 30.0 -> 60.0 | test_display_fps_limit_and_size | test_recipe_validates и все остальные |
| M4 | в processes.camera_3 plugin_class заменён на `Plugins.sources.capture.plugin.CapturePlugin` (любой не-синтетический) | test_no_hardware_plugins | test_recipe_validates (неизвестный плагин check() не видит) |
| M5 | у camera_1 ключ `source_target_fps` убран с уровня процесса и вписан внутрь `plugins[]` | test_source_size_and_fps_per_camera[camera_1] | test_recipe_validates; canon-страж — не уверен: может стать красным, это не расхождение, а наблюдение |
| M6 | camera_2 `source_target_fps` 50 -> 25 | test_source_size_and_fps_per_camera[camera_2] | остальные |
| M7 | camera_0 `resolution_width`/`resolution_height` 1440x1080 -> 1280x1024 | test_source_size_and_fps_per_camera[camera_0] | test_display_fps_limit_and_size (размеры дисплея заданы отдельно) |
| M8 | gui `process_class` -> `multiprocess_prototype.frontend.process.GuiProcess` | test_gui_process_is_headless_class | остальные |
| M9 | добавлен пятый камерный процесс camera_4 (копия camera_3, без привязки дисплея) | test_process_names_and_order; test_no_hardware_plugins (плагинов не 4) | test_display_fps_limit_and_size |
| M10 | в test_dotted_process_name.py `RECIPE_COUNT = 29` -> 28 (мутация файла теста счёта) | test_a5_recipe_set_has_the_literal_count_and_robot_demo | остальные тесты файла |
| M11 | camera_1 `camera_id: 1` -> 0 | test_cameras_have_distinct_ids | остальные |
| M12 | у дисплея camera_3 `ring_buffer_blocks` 3 -> 8 | test_display_names_fit_and_ring_buffer | остальные |

Критерий расхождения: любой тест не из «красного набора», ставший красным, и любой тест из набора, оставшийся зелёным, — находка; мутация, после отката давшая не ту же sha256, — провал прогона.

Файлы прогона после каждой мутации (по одному, через `bash scripts/machine_gate.sh light inspector-bottles-K ../../../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider <файл> [-k gui_overload_synth]`): recipes/tests/test_gui_overload_synth_recipe.py; process_manager_module/tests/test_dotted_process_name.py -k gui_overload_synth; process_manager_module/tests/test_unapplied_metadata_check.py -k gui_overload_synth; adapters/tests/test_recipe_canonical.py -k gui_overload_synth.
