# Уроки по модулям — plugins

Сгенерировано: `python scripts/memory/search.py --by-module --write`; не править вручную. Хаб: [BY-MODULE.md](BY-MODULE.md)

## plugins/calibration (1)

- [project_calibration_gui_progress](project_calibration_gui_progress.md) — Калибровка камера↔робот — баг прогресса визарда (GUI не подписан на calibration…

## plugins/hub (1)

- [project_device_hub](project_device_hub.md) — device-hub — always-on процесс устройств, реестр, YAML-протоколы; статус и след…

## plugins/processing (2)

- [feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub](feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub.md) — numba @njit без boundscheck: нарушенный инвариант пишет за буфер → полный набор…
- [project_strokes_points_perf](project_strokes_points_perf.md) — webcam_sketch FPS-просадка на детальных кадрах = O(n²) sort + пересчёт каждый к…

## plugins/sim (1)

- [feedback_import_guard_substring_vs_ast](feedback_import_guard_substring_vs_ast.md) — A "modules don't import each other" guard test must parse imports via AST, not …

## plugins/sources (2)

- [feedback_default_path_must_match_publisher](feedback_default_path_must_match_publisher.md) — Дефолтный путь/ключ (default path) в конфиге фичи сверять с РЕАЛЬНЫМ публикатор…
- [project_camera_settings_feature](project_camera_settings_feature.md) — Настройки камеры / camera settings РЕАЛИЗОВАНЫ — унифицированный путь через пла…

## plugins_shared (2)

- [feedback_no_shm_hacks](feedback_no_shm_hacks.md) — Plugins must NOT read SHM directly — use framework middleware and managers only…
- [feedback_positional_call_hides_parameter_name_drift](feedback_positional_call_hides_parameter_name_drift.md) — Тест, зовущий испытуемого позиционно, не видит расхождения ИМЁН параметров — за…
