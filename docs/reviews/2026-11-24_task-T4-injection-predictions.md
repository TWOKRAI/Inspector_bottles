# T4 (метрики тракта кадров и честные надписи): предсказания инъекций лида, записаны ДО кода developer-а и ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t4-dev` (ветка feat/gfp-t4-metrics, база bc82d9363 + T1 + T2 + T3 + тесты tester-а). Правимые модули: `multiprocess_prototype/frontend/frame_intake.py` [F] (новый: `FrameIntake`, `latency_sample`, `fps_text`, `is_frame_message` живёт в `bridge_impl.py`), `bridge_impl.py` [B] (`qt_pending`, предикат кадра), `process.py` [P], `app.py` [A], `windows/main_window.py` [W]. Два набора: [T] = слепой tester (`test_frame_intake_metrics.py`, 10 тестов), [D] = тесты developer-а (`test_gui_process.py` — пять тестов цикла приёма на настоящем `FrameIntake`; плюс тесты, которые добавит сам, например, агрегации и дельты shown по ключу).

Исполнитель — developer T4 (владелец файлов); откат по sha256 от байтовой копии; Git Bash явно. Файл перегрузки T3 (`test_frame_overload_real_objects.py`, класс medium) не гонять в этой матрице; для регресса после матрицы — один прогон на чистом коде. Мутация на каждое решение, записанное лидом в T4.md (правило проекта: решения ADR/брифа попадают в матрицу).

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| H1 | счёт по пачкам: `frames_in += 1` на пачку | F | [T] test_frames_in_counts_messages_not_batches | |
| H2 | `batches` растёт на пустом `receive` | F | [T] test_frames_in_counts_messages_not_batches | |
| H3 | `frames_in` считает не-кадры (сообщение `{"data_type": "status"}`) | F/B | [T] test_frames_in_counts_messages_not_batches | |
| H4 | ключ метрики переименован (например `shown` -> `shown_total`) | F | [T] test_metrics_have_literal_keys; test_worker_status_contains_intake_metrics | |
| H5 | `shown` — максимум по ключам вместо суммы | F | [T] test_pump_metrics_aggregation_and_zero_before_attach | |
| H6 | `max_frame_age_ms` — сумма вместо максимума | F | [T] test_pump_metrics_aggregation_and_zero_before_attach | |
| H7 | насосные метрики до `attach_pump_stats` не 0 (например `None`) | F | [T] test_pump_metrics_aggregation_and_zero_before_attach | |
| H8 | `pump_busy_share` без зажима в [0, 1] | F | [T] test_pump_busy_share_clamped_delta | |
| H9 | отрицательная дельта по сумме, а не по ключу | F | [T] test_pump_busy_share_clamped_delta | |
| H10 | первый вызов `get_cycle_metrics` даёт не 0.0 | F | [T] test_pump_busy_share_clamped_delta | |
| H11 | база берётся при привязке насоса не снимается (всплеск после привязки, 5000.0 -> 1.0) | F | [T] test_pump_busy_share_clamped_delta (сценарий «до привязки -> привязка -> 5000.0 -> 0.0») | |
| H12 | `get_cycle_metrics` вызывает `provider()` с аргументом / не `reset_window=True` в `app.py` (привязка `pump.stats` напрямую) | A/F | [D] если есть тест привязки; иначе НЕТ красного — находка, developer добавляет тест | окно `window_max_age_ms` не сбрасывается |
| H13 | `superseded` не берётся из `mailbox.stats()` (всегда 0) | F | [T] test_superseded_grows_when_qt_blocked | |
| H14 | метрики не доходят до статуса воркера (`get_cycle_metrics` не вызывается / не публичный) | F/P | [T] test_worker_status_contains_intake_metrics | |
| H15 | метка Latency печатает 0.0 при отсутствии замера | W | [T] test_latency_label_dash_without_sample | |
| H16 | `{latency_ms:.1f}` при None (падает) в header | W | [T] test_latency_label_dash_without_sample | |
| H17 | `qt_pending` не растёт при блокированном Qt (handled считается сразу) | B | [T] test_qt_pending_returns_to_zero | |
| H18 | `qt_pending` не возвращается к 0 (handled не увеличивается, например, без try/finally при исключении колбэка) | B | [T] test_qt_pending_returns_to_zero (после обработки 50 -> 0); исключение в колбэке — тест developer-а, иначе НЕТ красного | |
| H19 | `qt_pending` возвращает отрицательное (нет зажима max(0, …)) | B | тест developer-а или НЕТ красного (дыра) | |
| H20 | кадр с `replay: true` в item попадает в среднюю задержку | F | [T] test_replay_frames_excluded_from_latency | |
| H21 | `replay: true` в `item["data"]` не проверяется | F | [T] test_replay_frames_excluded_from_latency | |
| H22 | `replay: False` считается replay (truthy-проверка ключа, а не значения) | F | [T] test_replay_frames_excluded_from_latency (replay False рядом с capture_ts -> 500.0) | |
| H23 | `fps_text` другой формат | F | [T] test_fps_label_shows_shown_and_superseded | |
| H24 | `update_status` без `shown`/`superseded` меняет `FPS: 30.5` | W | [T] test_fps_label_shows_shown_and_superseded; существующий test_main_window.py::test_update_status | |
| H25 | `shown` для строки FPS — разность сумм (а не дельты по ключу с max(0, …)): ключ снят и заведён заново, «показано» отрицательное | A/F | тест developer-а по п.3a (shown 10 -> ключ заведён заново со значением 2 -> 2, не -8); иначе НЕТ красного — находка | в [T] этого сценария нет |
| H26 | `reset_chain_latency()` вызывается дважды в `_update_fps` (второй вызов обнуляет сумму) | A | тест developer-а или НЕТ красного — находка | |
| H27 | предикат «сообщение-кадр» в `dispatch` и в `FrameIntake` расходятся (две копии) | B/F | тест developer-а на единый `is_frame_message` или НЕТ красного — дыра | |
| H28 | `_data_receiver_loop` в `GuiProcess` не делегирует `FrameIntake.run_loop` (старое тело) | P | [D] пять переписанных тестов цикла приёма (на настоящем `FrameIntake`) краснеют, если фасад вызывает не тот путь | уточнить по факту |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) пункты с пометкой «иначе НЕТ красного» (H12, H18, H19, H25, H26, H27) — если красных нет, developer ДОБАВЛЯЕТ тест (таблица пробелов: это решения брифа без стража); (d) H22: если [T] зелёный — тест tester-а слаб.
