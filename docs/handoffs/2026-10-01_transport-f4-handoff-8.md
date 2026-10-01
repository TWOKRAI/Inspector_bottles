# Хендофф: 4.7c переделана и влита в main, пауза перед 4.7b — 2026-10-01 (8)

**main:** `c7992f626` (fast-forward с `feat/t47c-impl`), **не запушен** (8 коммитов впереди `origin/main`).
**Предыдущий:** [`2026-10-01_transport-f4-handoff-7.md`](2026-10-01_transport-f4-handoff-7.md).
**План:** [`task-4.7.md`](../../plans/transport-single-policy/task-4.7.md), статус обновлён. **ADR-173** в
`multiprocess_framework/DECISIONS.md`.

## Что сделано

| Шаг | Итог |
|---|---|
| Ревью `9fc01550b` (4.7a итерация 1) | Opus, APPROVE_WITH_NITS. Инъекции M1–M5 совпали. N-2 (страховка owndata) закрыт в `5dff941f1` |
| Слепой tester (Sonnet) | `da19b452a` на `tests/t47c-requeue`: RED под C1–C4 и провод, старый acceptance «очередь 4» переписан |
| Переделка 4.7c (developer, Sonnet) | `375bbb4b2` + тест mutex `f4f8993c7` + нитки ревью `5dff941f1` |
| Инъекции лида | 11 мутаций, все убили предсказанные тесты. Исключение — `not_full.notify`: он ненаблюдаем (единственный производитель), записано комментарием. Mutex сначала не держал ни один тест — добавлен детерминированный |
| Ревью 4.7c (Opus) | APPROVE_WITH_NITS. 21 рецепт против main: только `inflight_budget: 6` (×70) и `chain_max_lag_items` 0→2 (×68), `queues.data.maxsize` не меняется ни у кого |
| Документы (tech-writer) | ADR-173, план, `OPEN_QUESTIONS.md` (маркер по разрыву `frame_id`) — `c7992f626` |
| Радиус на вершине | process_manager + process_module + router_module + fanin: **4880 passed**, 3 failed — известные `test_socket_channel_hol_*` |

## Следующий шаг

1. **4.7b** — реализация по RED `efd8d3df` (xfail strict). Решение лида до брифа: длинные имена — уникальность
   на хеше `_bounded_name`, «владелец + pid» читаются только если влезают (так принято в 4.7e).
2. **4.7d** — спека. Первым делом выбрать единицу счёта: проверка до цепочки считает ВХОДЫ, после — ВЫХОДЫ
   (ревью: батч 2→1 даёт 2 и 1). От неё зависит acceptance `маркеры = сумма дропов`.
3. **Живой A/B** — `dualcam_synth`, ≥ 3 прогона на сторону, замок стенда. Числа для CTO: `ipc_queue_depth`
   и `transit_over_budget` из `get_cycle_metrics()` — устойчиво > B − lag переворачивает решение (ADR-173).

## Открыто

- Push main — ждёт владельца.
- Решение 4.8c (бенч из GUI через `QProcess`) владелец не подтвердил.
- Красные не наши: `test_socket_channel_hol_*` ×3, `test_remote_frame_source`,
  `test_hot_rebuild_framework_layer_key_count_is_pinned` (38 != 37). Снапшот-тесты прототипа зависят от порядка
  запуска (путь логов) — по одному зелёные.
- По C1 потолок не ограничивает некадровые потоки высокой частоты (только detections) — живьём не перечислены.
- `plans/queue/ORDER.md` не пересобран (строки 53, 81, 83, 144, 145 устарели).
- Worktree'ы `t47a-impl`, `t47a-tester`, `t47c-tester`, `t47c-requeue` можно удалять; `t47b-tester` нужен 4.7b.
