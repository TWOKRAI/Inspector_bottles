# Инъекции W1-a / W1-a2 — предсказания лида (записаны ДО прогона)

Дерево: worktree `mco-d-w1-a`, коммит `6d6660b5e`. Один прогон = пять файлов за раз (`light`):
`Services/camera_device/tests/{test_identity_stream_contract, test_stream_health_hazards, test_plugin_observability}.py` и `Services/hikvision_camera/tests/{test_driver_identity_stream, test_driver_mvs}.py`.
Имена тестов — короткие, без префикса `test_`. «C» — слепой тестер, «H» — опасности W1-a, «O» — `test_plugin_observability`, «D» — `test_driver_identity_stream`.
База: 0 красных (число собранных записать).

| # | Мутант (место) | Ожидаемо красные |
|---|---|---|
| A1 | `select_device` (interface.py): при нескольких записях брать первую, фильтр подсети убран, отказа нет | C: select_device_one_in_subnet_among_duplicates, select_device_lowest_host_ip_when_several_in_subnet, select_device_refuses_when_none_in_subnet, duplicate_enumeration_warning_and_identity_block, ambiguous_enumeration_gives_not_found_with_list; D: create_handle_gets_entry_in_camera_subnet, ambiguous_refused_before_create_handle |
| A2 | `select_device`: среди записей в подсети брать первую, а не наименьший `host_ip` | C: select_device_lowest_host_ip_when_several_in_subnet (только он) |
| A3 | `select_device`: ни одной в подсети — не отказывать, брать первую | C: select_device_refuses_when_none_in_subnet, ambiguous_enumeration_gives_not_found_with_list; D: ambiguous_refused_before_create_handle |
| A4 | плагин не пишет WARNING о дублях | C: duplicate_enumeration_warning_and_identity_block; H: concurrent_grabbing_events_log_once |
| A5 | плагин не считает `lost_frames` | C: lost_frames_incomplete_lost_packets; H: baseline_reset_on_opening_not_counted |
| A6 | опора номера кадра не сбрасывается на `opening` | H: baseline_reset_on_opening_not_counted |
| A7 | плагин не считает `incomplete` | C: lost_frames_incomplete_lost_packets; H: reset_stats_races_on_frame (неуверенно) |
| A8 | плагин не считает `trigger_lost` | C: trigger_lost_counts_index_gaps; H: trigger_index_none_keeps_trigger_baseline |
| A9 | `reset_stats` не обнуляет четыре новых счётчика | C: lost_frames_incomplete_lost_packets; H: reset_stats_races_on_frame (неуверенно) |
| A10 | `identity` не сбрасывается на `opening` | H: identity_none_after_release_and_reopen_refused, identity_none_after_refusal |
| A11 | подстановка последней личности при `info is None and state=="grabbing"` убрана | H: identity_survives_regrab |
| A12 | строка INFO «device opened» не пишется | C: stream_block_and_open_info_line; H: concurrent_grabbing_events_log_once, stub_port_without_device_info_logs_dashes |
| A13 | ключ `stream` не публикуется в state | C: stream_block_and_open_info_line; O: сверка_без_смен_не_даёт_merge |
| B1 | драйвер `_select` берёт первую запись вместо `select_device` | D: create_handle_gets_entry_in_camera_subnet, ambiguous_refused_before_create_handle |
| B2 | драйвер не передаёт `mask`/`host_ip`/`mac` в `DeviceInfo` | D: gige_fields_mask_host_ip_mac, create_handle_gets_entry_in_camera_subnet (без маски фильтр не сработает), ambiguous_refused_before_create_handle (неуверенно) |
| B3 | `get_frame` не передаёт `lost_packets`/`trigger_index` (дефолты) | D: get_frame_passes_lost_packets_and_trigger_index |
| B4 | при отказе повторного открытия `device_info` не сбрасывается | D: refused_reopen_leaves_device_info_none |
| B5 | `open` не читает `PixelFormat`/`Width`/`Height` | D: open_reads_format_and_size_once; open_unknown_pixel_value_named_by_hex; MvsContract-тесты не затронуты |

Критерий вердикта: набор красных поимённо. «(неуверенно)» = оба исхода допустимы, но записать фактический.
Заведомые пробелы (не мутируются, тестов нет): порядок событий «grabbing старого цикла после opening нового»; порядок замков; гипотеза `nTriggerIndex 0 -> None` на железе.

## Итог прогона
9 мутантов совпали с предсказанием поимённо. A10 выжил (0 красных) — пробел покрытия, закрыт тестом опасности `28452e3d1`.
