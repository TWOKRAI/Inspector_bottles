# Запрос на слияние: полоса Н (observability-signal-contracts) — срез 0.1–0.3 (2026-11-21)

Автор: лид полосы Н (сессия inspector-bottles-19). Отчёт: `docs/reports/2026-11-21_observability-signal-contracts_0.1-0.3-impl.md`. Ветка `refactor/observability-signal-contracts`, HEAD `99423b57a` (на момент заявки; `git rev-parse refactor/observability-signal-contracts`), worktree `../Inspector_bottles--lane-N`. В `main` я не коммитил; основное дерево лежит на `main`. Слияние делает координатор. Тема слияния — `feat(...): merge …` (хук режет `merge(...)`) + `Why:`/`Layer:`/`Refs: plans/2026-11-21_observability-signal-contracts/plan.md`; сообщение — из файла (`git merge -F -` stdin не читает). `git merge-tree` с актуальным `main` **не проверял** — прошу проверить; ожидаемое место конфликта — `plans/queue/defects.md` (дописаны строки C-102, C-103 в конце) и `multiprocess_framework/DECISIONS.md` (ADR-176).

## БЛОКЕР: решение координатора до слияния

Контракт-тесты красные **по замыслу** (пишутся до экземпляров, зелёнеют в 0.4–0.6, 0.10, 0.10b, 0.11). Слияние среза 0.1–0.3 в `main` оставит в нём 11 красных тестов:

| Файл | Красные | Зелёнеют в |
|---|---|---|
| `multiprocess_framework/modules/channel_routing_module/tests/test_contract_outcome.py` | 4 (`test_broken_hop_not_accepted[…]`) | 0.4–0.6 |
| `multiprocess_framework/modules/state_store_module/tests/test_contract_freshness.py` | 2 (`[read_model]`) | 0.10 |
| `backend_ctl/tests/test_contract_freshness_reader.py` | 2 (`[telemetry_snapshot]`) | 0.10b |
| `backend_ctl/tests/test_contract_verified.py` | 3 (`rejected[set_register_verified]`, `rejected[telemetry_set]`, `test_restore_equal_state_reports_vacuous`) | 0.11 |

Варианты (рекомендую 1):
1. **Держать ветку, слить после 0.4–0.11** одним срезом, когда контракты зелёные. Слот писателя на 0.4+ — по вашему слову.
2. Слить сейчас, красные занести в `defects.md` как «красные по замыслу до 0.4–0.11»; `main` красный на 11 тестах — ломает правило «полный suite перед слиянием» (урок C-11).
3. Слить сейчас, пометить 11 тестов `xfail(strict=True)` с причиной; файлы слепого tester'а правятся ради этого, а на зелёном `xfail` сам краснеет — это лишний проход в каждой из 0.4–0.11.

## Что вошло (код и тесты)
`channel_routing_module` (`outcome_of`, `count_outcome`, `LOSS_KEY_BY_HOP`; `channel_accepted` теперь `outcome_of(...) == "accepted"`, `{"status": "refused"}` больше не принят), `state_store_module/core/freshness.py`, `backend_ctl/verdict.py`, ADR-CRM-019, ADR-SS-025, BCTL-ADR-010, ADR-176; тексты задач 0.1–0.13, `plan.md`, `design.md`, `amendments.md`, отчёты. Затронутое поведение: `channel_accepted` — единственное изменение существующей логики (расширение `refused`; проверено дифф-таблицей 24 значения × 3 формы).

## Проверки на слитом дереве (прошу прогнать после слияния)
- `channel_routing_module/tests` (medium; на ветке `4 failed, 403 passed`), `state_store_module/tests` (medium; `2 failed, 863 passed`), `backend_ctl/tests/test_verdict_form.py` + `test_contract_verified.py` (light; `3 failed, 28 passed`), `python scripts/validate.py` и `python -m scripts.sync --check` — на ветке exit 0.
- Красные сверх перечисленных не ожидаются, кроме C-102 (`test_std_logger_guard`) и C-103 (`sentrux`) — они на ветке красные независимо от полосы.
- Не запускались: `make gate`, `sentrux` на базе, полные `logger_module`/`router_module`/`statistics_module`/`error_module` после рефакторинга `channel_accepted` (heavy/вне радиуса).

## Что нужно от координатора
1. Выбор варианта выше (1/2/3) и, при варианте 1, слот писателя на 0.4–0.6, 0.9–0.11 (границы — по вашему слову).
2. Решение по размеру Task: `plans_ledger.py amend` отказывает (`TASK_TOO_BIG` > 8 КБ, `PLAN_TOO_BIG` > 16 КБ; `contract.lock` не обновлён, `CONTRACT_DRIFT` WARN) — дробить, поднять бюджет или принять превышение.
3. Файлы PM (`process_manager_process.py`), `launcher/spawner.py`, `state_proxy.py` не тронуты; `logger_module/std_facade` — зона C-93 (Д2).
