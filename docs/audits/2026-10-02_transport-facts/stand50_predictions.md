# 5.0 — предсказания до прогона (лид, 2026-10-02)
(а) data-кадры ходят дверью А (targets): sent_via_targets > 0 у camera_0/processor/inspector; sent_via_channel(.data) = 0; put_timeout_total = 0.
(в) every E: transit_over_budget processor — десятки за окно; inspector — единицы; ipc_queue_depth ≤ 8.
(д) P10: строка delivery_failed — ветка «ни один из N адресатов не принял» (_do_send:572-575), не «канал вернул ошибку».
