# 5.4 — предсказания до прогона (лид)
Ветка feat/transport-t54, HEAD 0bd3fce1f. Набор: process_module/tests/test_t54_source_producer_preroll.py (тестер, 19) + process_manager_module/tests/test_t54_ready_event_wiring.py (тестер, 13) + process_module/tests/test_source_producer*.py (старые). Авторских hazard-тестов у 5.4 нет — бриф лида их не потребовал (дефект брифа лида, записать).
BASE: всё зелёное.
K1 run_loop без вызова `_wait_preroll` → красные в preroll-файле (0 кадров за 200 мс, первый кадр после set, срок с WARNING, стоп во время preroll) ≥ 8; в wiring — spawn «0 кадров до set».
K2 ожидание не видит stop_event (убрать проверку стопа в цикле) → красные тесты «стоп во время preroll» (≈6, три задержки × два вида Event).
K3 срок бесконечный (`if remaining <= 0` → `if False`) → красные тесты срока (≈3).
K4 срок связан при импорте (`timeout_s = 10.0` вместо чтения константы) → те же ≈3 теста срока.
K5 registry не кладёт событие в kwargs → красные registry-тесты и spawn (≈3 + 3).
K6 runner ставит `_sources_ready_event` ПОСЛЕ initialize() → **всё зелёное** (тестер читает атрибут в run(); реального GenericProcess в наборе нет). Ожидаемый пробел, не находка набора — находка покрытия.
K7 GenericProcess не передаёт событие (`ready_event=None`) → **всё зелёное**: проводка последнего звена не покрыта ни одним тестом. Если так — нужен тест на настоящем GenericProcess (автор или стенд).
K8 runner отдаёт событие через `attach_ready_event` вместо атрибута → красные runner-тесты и spawn (ребёнок взводит событие сам).

## Итог прогона (лид, HEAD 0bd3fce1f) — 8 из 8 по предсказанию
- BASE: `59 passed`.
- K1: 14 failed — блок 200 мс ×2, первый кадр ×2, стоп ×6, срок ×2, spawn ×2. **Совпало.**
- K2: 7 failed + 9 errors (teardown утечки потоков) — стоп ×6, stop-before-start, блок 200 мс ×2. **Совпало.**
- K3: 3 failed — тесты срока. **Совпало.**
- K4: 3 failed — те же. **Совпало.**
- K5: 3 failed — registry kwargs + spawn ×2. **Совпало.**
- K6 (атрибут после initialize): `59 passed`. **Совпало — пробел покрытия.**
- K7 (GenericProcess не передаёт событие): `59 passed`. **Совпало — пробел покрытия: последнее звено проводки не охраняет ни один тест.** Требование к исправлению: тест на настоящем `GenericProcess` (источник-плагин + `_sources_ready_event` → 0 кадров до set), убивающий K6 и K7.
- K8: 5 failed — runner ×3 + spawn ×2. **Совпало.**

## Раунд 2 (HEAD cddf05942, hazard-тесты автора) — предсказания до прогона
K6 → красные 5 в test_t54_generic_process_preroll_hazards.py (holds_source, before_initialize, two_sources, warning, system_stop); контроль и 2 рестарта зелёные.
K7 → красные 4 (те же без before_initialize).
K9 `log_warning=None` в GenericProcess → красный 1 (warning_goes_through_the_process_logger).

## Итог раунда 2 (лид) — 3 из 3 по предсказанию
BASE `67 passed`. K6 → 5 красных (как предсказано); K7 → 4; K9 → 1 (`test_preroll_warning_goes_through_the_process_logger_exactly_once`). Пробел K6/K7 закрыт.

## Раунд 3 (HEAD aeaa5e623, якорь own ready_event) — предсказания до прогона
K6 → 5 красных; K7 → 4; K9 → 1 (как в раунде 2).
Итог раунда 3: BASE `67 passed`; K6 → 5, K7 → 4, K9 → 1 — 3 из 3 по предсказанию.
