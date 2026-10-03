# Предсказания стенда фазы 5 (до замера, 2026-10-03, дерево stand @ 978377d7d)
Стенд: stand.yaml, 1080p@100, окно 30 с, every на processor+inspector, events first_n=1/every_mth=1 у inspector.

D100 (transit_ms=100, reject_delay 0), 3 прогона:
- D1 вердиктов (немаркерных строк журнала) за прогон >= 0.9 x (кадров камеры - маркеров). Было 4.7d-5: handled=0. Жду ~4000-4500 строк, как E1-E3.
- D2 lag@inspector за окно <= 100 (было 3008). Жду 5-20, как E1-E3.
- D3 actuation_missed_items — малое число (0..50), late_fires — малое; unscheduled 0.
- D4 dup trace = 0.

P10 (пауза исполнителя processor 10 с, every), 2 прогона:
- P1 errors_delivery_failed processor Δ = 0 за дренаж (было 1076).
- P2 queue_data_evicted processor Δ = 0 за дренаж (было 245).
- P3 сосед inspector/renderer: handled - own = born(processor), разница 0 в окне (было недостача 1317).
- P4 ΔRSS processor <= 1 МиБ. Риск: шум RSS Python-процесса сам по себе ~1 МиБ — может выйти за порог без дефекта.
- P5 дренаж <= 0.1 с. Риск: queue_wait_ms — скользящая метрика; может не упасть ниже 100 мс за 0.1 с даже при пустой очереди.

s0 (preroll, 5.4), 3 прогона (берётся из тех же D100):
- S1 queue_data_evicted в s0 = 0 у всех (было 24-41).
- S2 frame_stale_drops в s0 = 0.
- S3 первый кадр камеры после ready — число (< 1 с); старт системы — число рядом с 7.4 с.
