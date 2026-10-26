# SPI хаба — результат матрицы инъекций (наблюдение против прогноза)

Worktree `robot-v2-spi-inj`, HEAD fe5014ee8. Исполнитель наблюдает и записывает, вердикт — за лидом. Окно 15:10–16:35; прогон 15:17–15:35.

## Как гонялось

- Прогоны: `machine_gate.sh light inspector-bottles-00 <главный .venv python> -m pytest <файлы поимённо> -q --tb=no -rf -p no:cacheprovider`, без `-k`, передний план, `PYTHONPATH` = корень worktree, `PYTHONUTF8=1`. Тесты framework (`BF`, `TH`, `TB`) — cwd `multiprocess_framework/modules`, остальные — из корня.
- Путь импорта (из корня и из `multiprocess_framework/modules`): `...\.claude\worktrees\robot-v2-spi-inj\multiprocess_framework\__init__.py` — внутри worktree.
- Откат: `git checkout -- <файл>` классификатор прав отклонил (см. «Отказ прав»). Каждая инъекция откатывалась обратной правкой Edit; после каждого отката `git status --short` показывал только `M docs/reviews/2026-10-26_SPI-task-sonnet-review.md` (и, с момента записи этого файла, `?? plans/robot-protocol-v2/tasks/SPI.injections-result.md` — сам отчёт). `git diff` по `Services`, `Plugins`, `multiprocess_framework`, `multiprocess_prototype` пуст после последнего отката.
- Правки делал Edit; автоформатер-хук (PostToolUse) дважды переформатировал правку (строки 8, 22, 30) — откат подгонялся под переформатированный текст, итог проверен `git status`.
- Таблица прогнозов: 37 номеров + 17b = 38 строк (в задании «34»).

## Базы

Один и тот же набор файлов во всех базах и (подмножествами) в строках: `test_spi_acceptance`, `test_spi_contract`, `test_no_private_driver_state`, `test_robot_v2_state_acceptance`, `Services/device_hub/tests/test_manager`, `test_c29_disconnect_acceptance`, `test_c29_probe`, `Plugins/.../test_spi_commands_acceptance`, `test_op_commands`, `test_robot_v2_commands_acceptance`, `backend/tests/test_devices_executors`, `backend/tests/test_build_characterization`, `test_plugin_command_options_acceptance`, `test_plugin_command_options`, `test_blueprint_executors`.

| База | root-группа | framework-группа | всего | время |
|---|---|---|---|---|
| до первой инъекции (15:10) | collected 590, 590 passed, 1 warning | 16 passed, 1 warning | 606 / 606 зелёных | 61 с |
| после последней (15:34) | collected 590, 590 passed, 1 warning | 16 passed, 1 warning | 606 / 606 зелёных | 29 с |

Тяжёлые `test_robot_v2_ops*`, `test_t53r2_*` не гонялись ни в одной строке (прогноз их не называет); `test_c29_*` — строки 12, 13 и дополнительно 29.

## Сокращения

Как в шапке `SPI.injections-predictions.md`. `GUARD` = `Plugins/hub/device_hub/tests/test_robot_v2_commands_acceptance.py`, `SM` = `Services/device_hub/tests/test_manager.py`, `C29` = оба `test_c29_*`, `CHAR` = `test_build_characterization.py`. В колонке «собрано» — collected / красных для файлов строки.

## Таблица

| № | Инъекция (файл, суть) | Наблюдённые красные | Совпал | Посторонние / замечание | собрано/красных; с |
|---|---|---|---|---|---|
| 1 | `spi.py` `DEFAULT_SOURCES`: удалена строка `OpSource(prefix="vfd", ... ops=VFD_OPS)` | BP: А1 `test_a1_commands_are_exactly_the_72_names`, А19 `test_a19_vfd_commands_call_driver_with_stripped_op`; GUARD `test_catalogue_descriptions`; TO `test_device_hub_plugin_has_72_commands_55_generated`, `test_generated_docs_description_or_fallback`, `test_op_commands_descriptions_are_the_55`. BS красных нет | частично | лишние красные: BP А2 `test_a2_all_72_registered_in_real_command_manager_without_noise`, А3 x5 (`vfd_run`, `vfd_set_freq`, `vfd_stop`, `vfd_reset_fault`, `vfd_get_status`), А4 `[vfd_run]`, А5 `test_a5_vfd_command_for_robot_device_names_expected_kind`, А9 `test_a9_install_op_commands_extends_subclass_only`, А18 `test_a18_executor_metadata_on_data_commands_only` | 257/16; 9 |
| 2 | `plugin.py` `_op_command`: ветка `needs_link is False` -> `_kind_call` | BP `test_a6_exchange_log_get_for_created_unconnected_robot_is_ok`, `test_a6_exchange_log_get_without_driver_literal_error` | да | А4, А5, А7 зелёные | 90/2; 6 |
| 3 | `plugin.py` `_op_command`: ветка `route == "data"` -> `_driver_call` | BP А7 `test_a7_point_list_of_unconnected_robot_with_store_is_ok`; TO `test_route_and_needs_link_choose_the_path` | частично | лишние: BP А17 `test_a17_point_list_through_router_runs_off_router_thread`, BP А23 `test_a23_without_executors_command_registered_sync_one_warning`. А6 зелёный | 104/4; 5 |
| 4 | `plugin.py` `_kind_call`: `if entry.kind != expected_kind:` -> `if False:`. Интерпретация: проверка вида общая у `_kind_call` и `_driver_call`; правлена `_kind_call` | BP `test_a5_robot_command_for_vfd_device_names_expected_kind`, `test_a5_vfd_command_for_robot_device_names_expected_kind` | да | А4, А6 зелёные | 90/2; 6 |
| 5 | `plugin.py` `_kind_call`: `if not dev_id:` -> `if False:` (синхронный путь; `_driver_call` и `_robot_data` не тронуты) | BP `test_a4_missing_device_id_literal_error[robot_stop]`, `[vfd_run]` | да | А22 зелёный | 90/2; 8 |
| 6 | `plugin.py` `install_op_commands`: `_make_op_command(source, spec)` -> `lambda self, data: self._op_command(data, source, spec)` (замыкание на переменные цикла) | BP А19 x3 (`delta_v2`, `delta_universal3`, vfd); TO `test_factory_binds_each_method_to_its_own_operation`; А1 зелёный | частично | лишние (все команды зовут последнюю операцию): BP А5 x2 (`test_a5_robot_command_for_vfd_device_names_expected_kind`, `test_a5_pair_right_kind_does_not_get_the_kind_error`), А6 x2, А7 x2 (`test_a7_point_list_of_unconnected_robot_with_store_is_ok`, `test_a7_servo_of_unconnected_robot_literal_error`), А17, А23; TO `test_generated_docs_description_or_fallback`, `test_route_and_needs_link_choose_the_path` | 104/14; 7 |
| 7 | `robot_driver.py:48` `OP_SPECS = ROBOT_V1_OPS` -> `ROBOT_V1_OPS[:-1]` | TC `test_op_specs_match_driver_ops_table[RobotDriver]`, `test_op_specs_sizes` | да | второй красный той же сути; BP А1 зелёный | 135/2; 7 |
| 8 | `spi.py` `command_table`: `if first_spec != spec:` -> сравнение полей без `description` | BS `test_a10b_same_prefix_same_name_different_description_raises` | частично | прогноз называл и TC: TC красных нет. А10г зелёный | 188/1; 4 |
| 9 | `spi.py` `OpSpec.__post_init__`: `if self.executor is not None and self.immediate:` -> `if False:` | BS `test_a10d_executor_and_immediate_together_raises`; TC `test_opspec_executor_with_immediate_raises_each_alone_ok` | да | А10б, в зелёные | 188/2; 4 |
| 10 | `spi.py` `ROBOT_V2_OPS` `stop`: `immediate=True` -> `immediate=False` | BS `test_a12_immediate_exactly_the_listed_names[ROBOT_V2_OPS]` | да | v1, vfd зелёные | 143/1; 5 |
| 11 | `spi.py` `VFD_OPS` `get_status`: описание `"Статус ПЧ: ..."` -> `"Статус ПЧь: ..."` | BP `test_a3_c2_remaining_34_descriptions_are_literal[vfd_get_status]` | частично | прогноз называл ещё TO/TC литерал 55: красных в TO и TC нет. А1 зелёный. GUARD не гонялся (в прогнозе не назван) | 149/1 (BP+TO+TC); 9 |
| 12 | `plugin.py:386` `driver.disconnect_pending is True` -> `driver.disconnect_pending` | BP `test_a14_magicmock_driver_connect_false_publishes_error_not_disconnecting` | да | C29 (оба файла) зелёные: «красный 1 в А14 и только» | 166/1 (BP+C29); 15 |
| 13 | `plugin.py` `cmd_device_disconnect`: `request_disconnect` после `put`, вне `_workers_lock`. Интерпретация, два варианта | (а) вызов после `put` без `try`: BP `test_a25_request_disconnect_error_is_reported_and_disconnect_completes`. (б) то же, но с `try` и последующим `report_error`: красных нет | нет | ни в одном варианте не красны ни BP А14, ни `test_c29_*` (прогноз). В (а) красный А25 (прогноз: зелёный) | 166/1; 17 и 166/0; 16 |
| 14 | `plugin.py` `cmd_device_disconnect`: `try/except` вокруг `request_disconnect` убран | BP А25 `test_a25_request_disconnect_error_is_reported_and_disconnect_completes` | да | А14 зелёный | 90/1; 6 |
| 15 | `plugin.py` `_report_unconfirmed_stops`: `if not driver.stop_unconfirmed: continue` вынесен перед `try` | BP А24 `test_a24_shutdown_with_plain_object_and_base_driver` | да | А15 зелёный | 90/1; 5 |
| 16 | `manager.py:148` `request_stop_all`: `if drv.stop_aware:` -> `if True:` | красных нет (BP+TC+BS: 278 зелёных) | нет | прогноз: BP А15, TC (соответствие `stop_aware`). У драйвера без `request_stop` обращение `drv.request_stop` бросает `AttributeError` внутри `try` отбора, исключение логируется, поток не создаётся — наблюдаемый результат теста А15 тот же | 278/0; 7 |
| 17 | `manager.py` `_get_connected_driver`: добавлены `d = driver` и `getattr(d, "last_io", None)` (интерпретация: в `manager.py` этого вызова нет, место выбрано мной) | TC `test_no_duck_typing_on_drivers` | да | TN зелёный | 51/1; 5 |
| 17b | `manager.py` `_register_transport`: `driver.transport` -> `driver._client` | TN `test_hub_prod_code_has_no_driver_private_names`; BP А13 `test_a13_device_read_without_register_transport_literal_error` | да | TC duck зелёный | 141/2; 8 |
| 18 | `errors.py` `RegisterTransportUnavailable.__init__`: `super().__init__(self.TEXT)` -> `super().__init__(f"{self.TEXT}: {device_id}")` | BP А13 `test_a13_device_read_without_register_transport_literal_error` | да | BS А13 issubclass зелёный | 233/1; 6 |
| 19 | `plugin.py` `install_op_commands`: оба блока copy-on-write (`commands`, `_op_commands`) убраны | BP А9 `test_a9_install_op_commands_extends_subclass_only`; TO `test_copy_on_write_parent_unchanged`. А1 зелёный | частично | лишние: BP `test_a9_generated_command_reaches_fake_driver_call`; TO `test_device_hub_plugin_has_72_commands_55_generated`, `test_generated_docs_description_or_fallback`, `test_op_commands_descriptions_are_the_55` | 104/6; 7 |
| 20 | `plugin.py`: возвращены `_apply_op_descriptions(ctx)` (`update_command_metadata(name, {"description": ...})`) и вызов первой строкой `start()` | BP А17 `test_a17_point_list_through_router_runs_off_router_thread`, А18 `test_a18_executor_metadata_on_data_commands_only` | частично | прогноз называл ещё TO `command_options`: TO красных нет. А3 зелёный | 104/2; 5 |
| 21 | `base.py` `set_degraded`: умолчание `return False` -> `return True` | BP А20 `test_a20_plain_base_dependent_gets_no_publication_and_no_disconnect`; TC `test_set_degraded_default_and_vfd`; BS А11 `test_a11_hikvision_set_degraded_returns_false` | да | все три названы в прогнозе | 278/3; 6 |
| 22 | `base.py` `transport: Any = None` -> `@property def transport(self) -> Any: return None` | BS А21 `test_a21_subclass_assigning_contract_fields_in_init_is_created_and_returns_them` | частично | прогноз: красный и BS А16 (атрибуты класса); А16 зелёный | 143/1; 3 |
| 23 | `base.py` `_command_registration_options`: фильтр по белому списку -> `return raw` | BF А26 `test_a26_bad_option_key_command_registered_without_option_one_error`; TH `test_unknown_keys_dropped_with_one_error` | да | BF А26 без опций и А27 зелёные | 13/2 (BF+TH); 3 |
| 24 | `base.py` `_auto_register_commands`: `register_command(cmd_name, method)` -> `register_command(cmd_name, method, metadata={})` | BF А26 `test_a26_plugin_without_command_options_registers_with_two_positional_args`; TH `test_without_hook_exactly_two_positional_args_literal`, `test_empty_or_none_options_register_as_without_hook` | да | второй красный TH — та же гарантия «пустые опции = без хука»; BF А27 зелёный | 13/3; 3 |
| 25 | прогноз: литерал `_RESET_TRANSITIONS` без `connect_begin`. Литерал лежит в тесте `test_robot_v2_state_acceptance.py:884`, тесты не правятся; в `state.py` такого имени нет. Прод-аналог (интерпретация, мой): `state.py` `set_ready` вызывает `_latch_reset_locked()` (множество сбросов в AST != литерал) | TL `test_latch_reset_transitions_match_state_ast`, `test_latch_generation_reset_points[set_ready]` | да (по аналогу) | строки «прочие» зелёные. Прямая инъекция по тексту прогноза не выполнена | 168/2; 3 |
| 26 | `state.py` `connect_begin`: `self._connect_reset_locked()` -> `pass` | TL `test_latch_generation_reset_points[connect_begin_go]`, `test_latch_reset_transitions_match_state_ast`, `test_s9_snapshot_reset_by_connect_and_taken_before_stopping` | частично | лишний: `test_s9_snapshot_reset_by_connect_and_taken_before_stopping` | 168/3; 4 |
| 27 | `plugin.py` `_safe_call`: оба `with self._counters_lock:` -> `if True:` | TO `test_safe_call_counters_written_under_lock`, `test_safe_call_counters_exact_under_parallel_calls` | да | — | 14/2; 3 |
| 28 | `manager.py` `disconnect` (каскад): `try/except` вокруг зависимого убран | BP `test_a20_object_without_set_degraded_does_not_block_the_next_dependent` | да | А20 основной зелёный | 90/1; 5 |
| 29 | `plugin.py` `cmd_device_disconnect`: `report_error` вызван внутри `_workers_lock` (в `except` вокруг `request_disconnect`) | красных нет (BP+TO: 104 зелёных; дополнительно C29+TC: 121 зелёных) | нет | теста «замок свободен в момент `report_error`» среди BP, TO, C29, TC нет: `_workers_lock` упомянут только в `test_c29_probe.py`; TH — тесты хука framework, к хабу не относятся | 104/0 и 121/0; 6 и 11 |
| 30 | `base.py` `_register_command_with_options`: `ctx.log_info(... исполнитель не принят ...)` -> `ctx.log_warning(...)` | красных нет (BP 90 + BF 5: зелёные) | нет | прогноз: BP А23. А23 проверяет, что WARNING с текстом «исполнитель не принят» нет, но остаётся зелёным. Причину не проверял: вероятно, ветка запасного пути в риге А23 не выполняется (гипотеза, не подтверждена) | 95/0; 10 |
| 31 | `blueprint.py:329` `if self.executors:` -> `if False:` | TB `test_executors_reach_generic_config_and_proc_dict`, `test_built_config_is_accepted_by_executor_manager`; TD `test_devices_process_declares_device_io_executor[phone_sketch]`, `[hikvision_letter_robot]`, `test_executor_manager_accepts_devices_executors`; CHAR `test_build_matches_snapshot[phone_sketch]`, `[hikvision_letter_robot]` | да | TB (б) зелёный | TB 3/2; TD+CHAR 5/5; 21 |
| 32 | `blueprint.py:329` `if self.executors:` -> `if True:` | красных нет (TB 3/3, TD+CHAR 5/5 зелёных) | нет | прогноз: TB (б). Пустое `executors={}` в `base_kwargs` до `proc_dict["config"]` не доезжает (отбрасывается ниже по цепочке; где именно — не проверял), тест (б) его не видит | 8/0; 11 |
| 33 | `manager.py` `_check_kind`: `if kind not in self._factories:` -> `if False:` | SM `TestKindByFactory::test_unknown_kind_refused_with_literal_text`, `::test_merge_checks_kind_too`, `::test_unknown_kind_in_registry_file_fails_initialize`; SM `TestInitializeAllOrNothing::test_unknown_kind_in_file_loads_nothing`. BP А9-2 зелёный | частично | лишний: `TestInitializeAllOrNothing::test_unknown_kind_in_file_loads_nothing`; в прогнозе один «литерал отказа», красных в `TestKindByFactory` три | 123/4; 6 |
| 34 | `manager.py` `_check_kind`: проверка по `VALID_KINDS` из `registry.entry` вместо фабрик | SM `TestKindByFactory::test_registered_factory_admits_kind`; BP `test_a9_generated_command_reaches_fake_driver_call` (принято за А9-2) | да | остальные `TestKindByFactory` зелёные | 123/2; 7 |
| 35 | `base.py` `BaseDeviceDriver.__init_subclass__`: условие `if hasattr(cls, "request_stop") != bool(cls.stop_aware):` -> `if False:` (тело метода не удалено, результат тот же) | TC `test_class_with_request_stop_without_stop_aware_raises`, `test_class_with_stop_aware_without_request_stop_raises` | да | 5 боевых классов зелёные | 45/2; 4 |
| 36 | `manager.py` `initialize()`: второй цикл присваивания слит с циклом проверки вида (запись за записью) | SM `TestInitializeAllOrNothing::test_unknown_kind_in_file_loads_nothing` | да | `TestKindByFactory` зелёный | 33/1; 2 |
| 37 | `base.py:105` `_last_reconnect = 0.0` -> `float("-inf")` (у v2 своей начальной метки нет, наследует базу; затронут и v1) | TC `test_reconnect_initial_mark_per_class_is_literal`, `test_reconnect_due_gate_opens_once_per_interval` | частично | прогноз: TC интервалы зелёные; красный `test_reconnect_due_gate_opens_once_per_interval` | 45/2; 4 |

## Итог совпадений (по таблице)

- да: 22 — 2, 4, 5, 7, 9, 10, 12, 14, 15, 17, 17b, 18, 21, 23, 24, 25 (аналог), 27, 28, 31, 34, 35, 36.
- частично: 11 — 1, 3, 6, 8, 11, 19, 20, 22, 26, 33, 37.
- нет: 5 — 13, 16, 29, 30, 32.
- всего 38 строк.

«Частично» в этом отчёте: все названные красные есть, но есть лишние (1, 3, 6, 19, 26, 33, 37), либо часть названных красных не наступила (8, 11, 20, 22).

Время одной строки (pytest с гейтом, без правки): среднее 6,9 с, максимум 21 с (строка 31, `backend/tests`), минимум 2 с; 39 прогонов (с учётом двух вариантов строки 13 и дополнительного прогона 29). Базы: 61 с и 29 с. Время на правку и откат в эти цифры не входит.

## Отказ прав

Откат строки 12: `git checkout -- Plugins/hub/device_hub/plugin.py` отклонён. Дословно: «Permission for this action was denied by the Claude Code auto mode classifier. Reason: The server-side auto mode classifier judged this action dangerous (it gave no explanation).» Отклонена и цепочка (откат + две правки + прогон), и одиночная команда `cd <worktree> && git checkout -- Plugins/hub/device_hub/plugin.py && git status --short` («Permission to use Bash with command ... has been denied.»). Правки прод-файлов (python-скрипт, потом Edit) не отклонялись. Откат строк 12–37 выполнен обратной правкой Edit, а не `git checkout`; это отступ от брифа, итог проверен `git status` и `git diff`. Решение лида/владельца: допустим ли такой откат и нужно ли разрешить `git checkout -- <файл>` в этом worktree.

## Что оставил открытым

- Отчёт не закоммичен; `plans/robot-protocol-v2/tasks/SPI.injections-result.md` в дереве как `??`. Правка `docs/reviews/2026-10-26_SPI-task-sonnet-review.md` (ревьюер) не тронута.
- Откат через Edit, не `git checkout` (см. выше). Содержимое прод-файлов после отката равно HEAD по `git diff` (пусто), но окончания строк файлов Edit/хуком могли быть нормализованы в рабочей копии; `git status` их не показывает.
- Интерпретации, на которых строки держатся: 4 и 5 (правлена только `_kind_call`, не `_driver_call` / `_robot_data`), 13 (два варианта), 17 (место вызова выбрано мной, в `manager.py` его нет), 25 (литерал в тесте, выполнен прод-аналог), 34 (красный `test_a9_generated_command_reaches_fake_driver_call` принят за «А9-2», нумерацию внутри файла не сверял), 35 (`if False:` вместо удаления метода), 37 (инъекция в базу затрагивает и v1).
- Причины несовпадений 16, 29, 30, 32 установлены по поведению кода и тестов только частично (16: `AttributeError` в `try` — прочитано в коде; 30 и 32 — гипотезы, не проверены запуском с отладкой). Это находки для лида: тесты не ловят эти инъекции.
- Строки 29–30: в прогнозах названы тесты «замок свободен» (TO/TH) и А23, которых по факту нет / они не красные; возможно, прогноз опирался на тест, не попавший в набор. Не искал дальше набора из прогноза.
- Строка 11: сочетание «TO/TC литерал 55» не сработало, GUARD в этой строке не гонялся.
- Хук остановки субагента сообщил `pytest: cannot be imported` из worktree (pytest стоит только в главном `.venv`, это известно по брифу); тесты шли через главный `.venv` с `PYTHONPATH` на worktree.

## Вердикт лида

Матрица принята; откат через Edit с пустым `git diff` допустим. Несовпадения: строка 32 — эквивалентный мутант (пустой `executors` отбрасывается в `process_launch_config.py:178-181`); строки 8, 11, 20, 22 — ошибки прогноза лида, свойство ловит слепой тест. Выжившие — 13, 16, 29, 30: тесты автора написаны (ниже), каждый проверен красным под инъекцией из матрицы и зелёным без неё.

| № | Тест | Красный под инъекцией | Зелёный без неё |
|---|---|---|---|
| 13 | `Plugins/hub/device_hub/tests/test_spi_hazards.py::test_request_disconnect_runs_under_workers_lock_before_disconnect_is_queued` (замок взят и очередь без `disconnect` в момент `request_disconnect`; после команды `disconnect` в очереди ровно один) | да: вариант (б) матрицы (вызов после `put`, вне замка, с `try`) — `AssertionError: request_disconnect вызван вне _workers_lock` | да |
| 16 | `Services/device_hub/tests/test_manager.py::TestStopFanOutTargets::test_only_stop_aware_driver_gets_stop_and_plain_one_leaves_no_error_record` (стоп получает только `stop_aware`; поток стопа один; записи ERROR менеджера нет) | да: `if True:` вместо `stop_aware` — `["device_hub: стоп-запрос 'v1' не прошёл"]` | да |
| 29 | `Plugins/hub/device_hub/tests/test_spi_hazards.py::test_request_disconnect_failure_is_reported_outside_workers_lock` (`report_error` ровно один раз и при свободном замке; ответ `ok/disconnecting`; `disconnect` в очереди) | да: `report_error` внутри замка — `[True, False]` | да |
| 30 | существующий `multiprocess_framework/modules/process_module/tests/test_plugin_command_options.py::test_executor_refused_fallback_with_metadata_one_info`, дополнен `assert log.of("WARNING") == []` | да: вариант (а) «INFO заменён на WARNING» красный и до дополнения (2 теста TH); вариант (б) «лишний WARNING рядом с INFO» до дополнения выживал (TH 8/8 зелёные), с дополнением красный (`['extra'] == []`) | да |
