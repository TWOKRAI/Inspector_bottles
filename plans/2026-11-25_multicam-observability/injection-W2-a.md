# Инъекции W2-a / W2-a1 — предсказания лида (записаны ДО прогона)

Дерево: `mco-inj` (копия `dev/w2-a`, `46950e3f4`). Один прогон = три файла разом (`light`):
`Services/camera_device/tests/{test_link_reconnect_contract, test_link_reconnect_hazards, test_link_plugin_hazards}.py`.
База: 0 красных, собрано 42. Имена тестов без префикса `test_`. Номера строк — `session.py` на этом коммите.

Критерий: названные «обязан» тесты красные. Лишние красные записать поимённо (допустимы, если следуют из мутанта).
Обязанный тест зелёный или 0 красных — находка.

| # | Мутант | Обязан покраснеть |
|---|---|---|
| A1 | `_link_tick`: первая строка `return` | link_block_advances_while_lost_without_produce |
| A2 | стр. 698: переподключения нет никогда (`if True or ...`) | disconnect_event_marks_lost_then_reconnects, busy_at_start_retries_until_free, one_owner_thread_across_reconnects |
| A3 | стр. 1046: правило тишины выключено (`False and ...`) | free_run_silence_is_lost_even_if_probe_answers, reconnect_off_free_run_silence_is_error |
| A4 | стр. 707: `then=` убран; `_enter_reconnect_locked` зовётся отдельным захватом замка ПОСЛЕ `cmd.finish(False)` | apply_in_first_refusal_window_reaches_device |
| A5 | стр. 746: финальный `self._notify(self._on_link)` убран | release_from_failed_state_clears_tree_without_produce |
| A6 | стр. 864-865: команды между попытками не исполняются | list_devices_answers_while_reconnecting |
| A7 | стр. 489: при переподключении принимаются все команды (`or self._reconnecting` без `while_reconnecting`) | describe_params_refused_while_reconnecting, trigger_software_refused_quietly_while_reconnecting |
| A8 | стр. 1048: убрано `and self._link_silence_s <= 0` | first_frame_bound_is_silence_when_silence_set |
| A9 | стр. 1048: ветка ожидания первого кадра выключена целиком | reopen_without_first_frame_retries_when_silence_off |
| A10 | `apply`: при переподключении не обновляются уже стоящие в `_pending` шаги тех же полей (правка п.5 раунда 2) | slow_call_before_drain_keeps_newest_edit |
| A11 | стр. 1027: `self._link = "lost"` перед `_fail` убран | terminal_error_marks_link_lost |
| A12 | стр. 357: `self._link_key = None` убран | ни один (автор: свойство не изолировано) — ожидаемый пробел |
| A13 | стр. 398: `self._reconnecting = False` в `stop` убран | take_after_timed_out_release_is_not_reconnecting |
| A14 | стр. 915-917: правки не сливаются в план при входе в отказ | write_accepted_before_drain_then_loss_reaches_device |
| A15 | `_queue_run_diff_locked`: сразу `return` | apply_during_retry_start_grabbing_reaches_device, apply_while_awaiting_first_frame_reaches_device |
| A16 | `_backoff`: стоп не прерывает паузу (цикл до конца интервала, без `stop_evt`) | stop_during_backoff_returns_promptly |
| A17 | `plugin_base.cmd_take_device`: новая личность не перезапускает цикл | take_with_new_identity_restarts_reconnect_cycle, take_with_new_identity_when_stop_times_out_refuses_explicitly |
| A18 | `plugin_base`: readiness при потере возвращает пустой список | plugin_lost_readiness_is_failure_literal |
| A19 | `plugin_base`: потеря не переводит здоровье в `degraded` | plugin_publishes_link_and_degrades_on_loss |

Не мутируется (тестов или способа нет): порядок публикаций двух потоков в `_sync_events`; поведение на настоящем
SDK; `acquire/release` вокруг команд между попытками (стр. 877-890).
