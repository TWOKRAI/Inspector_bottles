# C-66 — прогноз инъекций (лид, записано до реализации и до прогона)

Наборы: A = test_health_claims_acceptance.py (R1 silence, R2 success, R3 after-open, R4 failed, R5 ok-hide, R6 neighbour, R7 published, S1, S2),
H = test_health_claims_hazards.py (H1–H7), G = Services/ml_inference/tests/test_preflight_c55b_hazards.py (G4 новый, G6, G8, G9, G10).
Прогон только A+H+G; I7 — ещё test_health_schema.py. Расширения вне прогноза — журнал целиком, каждое расхождение — находка.

| № | Инъекция | Свойство | Ожидаемые красные |
|---|---|---|---|
| I1 | закрытие breaker снимает все заявки | 1 | R1, R2, R3, R4, R7, H6, G4 |
| I2 | ok() снимает все заявки, не только свою | 2 | R5, R6, H4 |
| I3 | тяжесть не учитывается: всегда самая поздняя заявка | 3 | R4 |
| I4 | среди равной тяжести — самая ранняя | 4 | R1, R3, R7, H3, H4, H7 |
| I5 | журнал и dirty на каждый вызов, без «изменилось ли» | 5 | H3, H7 |
| I5b | снять _mark_dirty на закрытии в poll | 5 | H6 |
| I6 | вернуть проверку status == "degraded" в _clear_asset_degraded | 6 | G10 |
| I7 | лишнее поле в схеме health | 7 | test_health_schema.py (минимум 1), A+H+G зелёные |
| I8 | повтор той же заявки меняет её позицию | 8 | H7 |
| I9 | HealthReporter не передаёт owner | 2 | R6, H4, H7 |
| I10 | ok("текст") теряет причину при пустых заявках | контракт | H5 |

## Р.1 ревью — прогноз до правок
| I11 | снять очистку в poll при transition None | залипание | H8 |
| I12 | CLOSED заменить на not is_open | half_open держит заявку | H9 |
| I13 | HealthReporter.failed без owner | 2 | H11 |
| I14 | очистка в poll пишет dirty всегда | холостой poll | H10 |
| I15 | читать state вне _lock (проверка до захвата замка) | снятие под одним замком | H12 |
