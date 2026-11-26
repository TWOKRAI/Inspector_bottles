# Инъекции W1-b — предсказания лида (записаны ДО прогона)

Дерево: worktree `mco-d-w1-b`, коммит `404f35638`. Файлы правок: `Services/code_reader/plugin/sdk_plugin.py`, `plugin/sdk_registers.py`, `core/sdk_reader.py`.
Наборы: `C` = слепой тестер `test_sdk_trigger_live_contract.py` (9 тестов), `H` = исполнитель `test_sdk_trigger_live_hazards.py` (8 собранных: 7 функций, одна с двумя параметрами). Прогон обоих файлов за раз, `light`.
Тесты — по коротким именам без префикса `test_`; «_held»/«_not_held» — параметры `callback_never_raises`.

| # | Мутант | Ожидаемо красные | Остальное |
|---|---|---|---|
| M0 | без правок | 0 из 17 | все зелёные |
| M1 | `cmd_take_device` без `_trigger_lock` | H: concurrent_take_device_waits_for_callback (единственный) | остальные зелёные |
| M2 | `shutdown` без замка | H: shutdown_waits_for_inflight_callback | C: shutdown_unsubscribes зелёный (отписка осталась) |
| M3 | в `_subscribe_trigger` убрать вызов `_unsubscribe_trigger()` | H: reconfigure_does_not_double_subscriptions | остальные зелёные |
| M4 | убрать все `health.set_status("ok")` в колбэке | H: failed_apply_degrades_and_next_successful_restart_clears, failed_apply_degradation_cleared_by_return_to_old_value (2) | остальные зелёные |
| M5 | убрать `apply="restart"` у `trigger_mode` в `sdk_registers.py` | C: trigger_fields_declare_apply_restart (1). Неуверенно: если `RegistersManager` смотрит на `apply` при уведомлении подписчиков, красных будет больше | — |
| M6 | не проверять `param_errors` (узел отказал, но считать применённым) | C: refused_node_write_is_not_reported_as_applied, return_to_old_value_after_node_refusal_keeps_reader_on_old_mode (2) | H: деградация после отказа узла — неуверенно |
| M7 | в ветке (а) при непустом `bad` не откатываться (нет `stop`/`set_trigger(old)`/`_take`) | C: refused_node_write..., return_to_old_value... (2) | — |
| M8 | в ветке (б) (`r` не ok) не откатываться к старому | C: failed_restart_falls_back_to_old_trigger (1) | — |
| M9 | убрать ранний выход `new == _applied_trigger` | C: same_value_does_not_restart, return_to_old_value_after_node_refusal... (2) | H: degradation_cleared_by_return_to_old_value зелёный (успешный перезапуск тоже снимает) |
| M10 | в ветке исключения при `held` не вызывать `_take()` | H: set_trigger_error_reaches_last_error, callback_never_raises[held] (2) | callback_never_raises[not_held] зелёный |
| M11 | убрать из `set_trigger` отказ при живом потоке (`RuntimeError`) | C: set_trigger_refused_while_running (1) | H: set_trigger_error_reaches_last_error зелёный (заглушка) |
| M12 | `set_trigger`: присвоить `self._trigger = trigger` ДО разбора `_parse_trigger` | **0 красных предсказано — пробел покрытия**; красный = сюрприз | все зелёные |
| M13 | `_on_trigger_update` без `with self._trigger_lock` | H: concurrent_take_device_waits_for_callback, shutdown_waits_for_inflight_callback (2) | остальные зелёные |
| M14 | в ветке `held` не вызывать `stop()` перед `set_trigger` (`set_trigger` бросает) | C: минимум live_write_while_grabbing_restarts_and_reaches_device и failed_restart..., refused_node...; ожидаю 3 и больше | H: set_trigger_error..., callback_never_raises[held] — неуверенно |
| M15 | убрать `_unsubscribe_trigger()` первой строкой `shutdown` | C: shutdown_unsubscribes (1) | H: shutdown_waits_for_inflight_callback зелёный |

Критерий вердикта: совпадение набора красных поимённо; M5, M6, M12, M14 — с оговорками выше. «Красный там, где предсказан зелёный» и обратно — находка. M12 зелёный = пробел покрытия: тест на «разбор до присваивания» просить у исполнителя только если владельцем решено, что свойство заявлено.

## Итог прогона
12 из 15 совпали. M12 («присвоить до разбора») дал 0 красных, как предсказано; тест добавлен в `b0ffd9869`.
