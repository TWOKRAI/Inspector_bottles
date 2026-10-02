# 5.3 — предсказания до прогона (лид)
Ветка feat/transport-t53, HEAD ffb698fd9. Набор (cwd multiprocess_framework/modules): 4 файла тестера test_t53_* + авторский test_t53_hazards.py + process_module/tests/test_t47d*.py + router_module/tests/test_t47d*.py.
BASE: зелёный.
L1 count = len(inputs) вместо Σ count → красные: build_gap (count записи-входа), executor 1078 (если вход маркеры — count верен! краснеет только где вход — записи), hazards формула. Ожидаю ≥ 3, в т.ч. test_t53_build_gap про записи на входе.
L2 trace_ids в обратном порядке → красные: литерал 3 маркеров, порядок 1078 у executor, авторский порядок поперёк чанков. ≥ 3.
L3 first/last перепутаны (min↔max) → красные: литерал, None-тесты. ≥ 2.
L4 None не отфильтрован → TypeError в min/max → красные: тесты None (≥ 1) и всё, где capture_ts None (маркеры build_marker без meta).
L5 is_marker не признаёт запись count>1 → запись идёт в коллектор → красные: test_t53_gap_record_reaches_chain (контроли «не в коллектор») и tail-merge. ≥ 2.
L6 дверь без build_gap (старый маркер) → красные: дверной литерал count=1 у тестера и test_t47d3_door. ≥ 2.
L7 handled += число записей → красные: executor +1078, hazards формула, контроль handled тестера. ≥ 2.
L8 reasons не агрегируются (= вместо +=) → красные: литерал {"lag": 2, ...}. ≥ 1.
L9 граница чанка `>=` → красные: 1500/1500/8, rec(1500)+m. ≥ 2.
L10 слияние в хвост без chain.mutex → красный ТОЛЬКО авторский test_tail_merge_holds_chain_mutex_against_executor_get (автор сам это нашёл: набор тестера к замку слеп).
L11 слияние в хвост выключено → красные flood-тесты тестера (qsize ≤ 2) и тесты формы очереди. ≥ 6.
L12 post-chain stale без build_gap → красные изменённые кейсы test_t47d2 «post-chain 2→1». ≥ 1.
L13 build_marker без "count": 1 → красные: литерал build_marker у тестера и test_t47d1_marker_contract. ≥ 2.

## Итог прогона (лид, HEAD ffb698fd9) — 13 из 13 по предсказанию
BASE `199 passed`. (Первый запуск упал на неуникальном якоре L10 и на якоре L13 — дефект заплат лида, исправлены, L10–L13 прогнаны отдельно.)
| инъекция | красных | где |
|---|---|---|
| L1 count = len | 14 | build_gap 6, executor 2, reaches_chain 2, tail_merge 2, hazards 2 |
| L2 обратный порядок trace_ids | 25 | build_gap 11, executor 5, tail_merge 3, hazards 2, t47d2 4 |
| L3 min↔max | 17 | build_gap 7, executor 4, reaches_chain 2, t47d2 4 |
| L4 None не отфильтрован | 3 | build_gap 3 (тесты None) |
| L5 запись count>1 не маркер | 27 | reaches_chain 8, tail_merge 9, executor 3, hazards 2, t47d2 4, build_gap 1 |
| L6 дверь без build_gap | 6 | t47d3_author 3, t47d3_door 2, executor 1 |
| L7 handled = число записей | 12 | executor 4, tail_merge 3, reaches_chain 2, hazards 2, t47d2 1 |
| L8 reasons не агрегируются | 13 | build_gap 7, t47d2 3, executor 2, tail_merge 1 |
| L9 граница чанка >= | 10 | build_gap 8, executor 1, hazards 1 |
| L10 слияние без chain.mutex | **1** | только авторский test_tail_merge_holds_chain_mutex_against_executor_get — набор тестера к замку слеп (автор предупредил; его тест держит окно 0.3 с и может ложно позеленеть под нагрузкой) |
| L11 слияние выключено | 15 | tail_merge 14, hazards 1 |
| L12 post-chain без build_gap | 3 | t47d2 2, t47d2b 1 |
| L13 build_marker без count | 5 | build_gap 2, t47d1 1, t47d2 1, hazards 1 |

## Раунд 2 (HEAD 4a2d27e0a, правки ревью) — предсказания до прогона
L10 без chain.mutex → красный только test_tail_merge_holds_chain_mutex_against_executor_get, теперь на детерминированной пробе (`mutex_free_inside_merge: True`).
L14 `count` убран из _CARRIED_SYSTEM_FIELDS → красный только test_accepting_plugin_returning_fresh_dict_keeps_gap_record_fields; контроль кадра зелёный.
L15 `trace_ids` убран → красный тот же один тест.

## Итог раунда 2 (лид) — 3 из 3 по предсказанию
BASE `201 passed`.
| Заплата | Красные |
|---|---|
| L10 без chain.mutex | 1 — `test_tail_merge_holds_chain_mutex_against_executor_get` (проба замка) |
| L14 без `count` в переносе | 1 — `test_accepting_plugin_returning_fresh_dict_keeps_gap_record_fields` |
| L15 без `trace_ids` в переносе | 1 — тот же |
Открыто (от автора): перенос полей записи идёт в общем движке — ключ `count` у кадра перенёсся бы тоже. Grep по `Plugins/ Services/ multiprocess_prototype/`: `"count"` есть только в ответах команд (`device_hub`, `modbus`), не в кадрах. Fan-in N:1 с записью не первым входом не проверен.
