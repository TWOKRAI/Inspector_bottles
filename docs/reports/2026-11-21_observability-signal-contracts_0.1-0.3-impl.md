# Полоса Н · observability-signal-contracts · Task 0.1–0.3 · реализация

Сессия inspector-bottles-19. Ветка `refactor/observability-signal-contracts`, HEAD на момент отчёта `99423b57a` (worktree `../Inspector_bottles--lane-N`). Отчёт стадии 0 — `docs/reports/2026-11-21_observability-signal-contracts_0.1-0.3-stage0.md`.

- **Итог:** три контракта сигнала сделаны по цепочке INTERFACE → слепой tester (по одному на механизм, дерево без `plans/`) → GREEN → break-injection → ревью стадии 5. Ревью: 0.1 APPROVED (7 minor), 0.3 APPROVED (7 minor), 0.2 CHANGES REQUESTED (2 major) → правки → round 2 APPROVED. Все замечания закрыты, кроме перечисленных в «Открыто».
- **Код:** `outcome_of`, `count_outcome`, `LOSS_KEY_BY_HOP` (0.1, ADR-CRM-019); `freshness.py` — `stamp`, `classify`, `read_value` (0.2, ADR-SS-025); `backend_ctl/verdict.py` — `judge`, `is_refusal` (0.3, BCTL-ADR-010); глобальный ADR-176.
- **Тесты (после правок):** unit — 17 / 65 / 20 passed; каталоги `channel_routing_module/tests` `4 failed, 403 passed`, `state_store_module/tests` `2 failed, 863 passed`; `backend_ctl` (`test_verdict_form` + `test_contract_verified`) `3 failed, 28 passed`. Красные — контракт-тесты на ещё не подключённых экземплярах: 4 (0.1) + 2 `[read_model]` + 2 `[telemetry_snapshot]` (0.2) + 3 (0.3) = **11**; зелёнеют в 0.4–0.6, 0.10, 0.10b, 0.11.
- **Инъекции:** 25 на три задачи, 20 совпали с предсказаниями полностью, 5 расхождений — недоучёт красных (0.3 (3); 0.2 u10 в 1, 6, 7, u9 в 10), пропущенных дефектов нет. Таблица — `plans/…/reports/0.1-0.3.injections.md`, сводка в `plan.md`.
- **Ревью:** `plans/2026-11-21_observability-signal-contracts/reports/0.{1,2,3}.review-stage5.md`, `0.2.review-stage5-r2.md`. Реальные находки: `OverflowError` в `_is_finite_number` на int вне диапазона float; правило `no_data` в `read_value` и копия ответа не держались тестами; форма пробы 0.1 в README была неполной; в ADR устарело «замера нет».
- **Цена:** `outcome_of` на горячем пути 66 → 105 нс на вызов (+39 нс), решение лида — принять (ADR-CRM-019 п.4).
- **Красные вне полосы (внесены в `plans/queue/defects.md`):** C-106 — `test_std_logger_guard` (5 голых `getLogger`); C-107 — `sentrux check .` (`no_god_files`, `test_recipe_1_0.py`).

## Открыто / ненадёжно
- **Слияние среза 0.1–0.3 сделало бы `main` красным на 11 контракт-тестах** (красные по замыслу до 0.4–0.11). Решение координатора — в заявке `docs/handoffs/2026-11-21_N-merge-request.md`.
- Размер Task: `plans_ledger.py amend` отказывает (`TASK_TOO_BIG`, `PLAN_TOO_BIG`), `contract.lock` не обновлён, `CONTRACT_DRIFT` (WARN); решение владельца/координатора. Вето на поправки № 2, 3, 7 координатор снял (приняты).
- Сила контракт-тестов 0.3 до 0.11 доказана не полностью: `rejected[set_register_verified]` и `rejected[telemetry_set]` красные и до инъекций, охрана «попытка записи видна» для них проверяема только после 0.11; инъекции (6)–(10) в 0.11 не перегонялись.
- Контракт 0.1: сломанная ветка проверена эталоном ревьюера в scratch (патчи ревьюера, не 0.4–0.6); совпадение с настоящей реализацией неизвестно. Контракт 0.2: адаптеры `rm.read` и `BackendDriver(clock=)` исполнимы на scratch-эталоне, настоящих читателей нет до 0.10/0.10b.
- Для следующих задач: `count_outcome` не экспортирован из `core/__init__` (импортировать из `core.channel_routing_manager`, решение до 0.5); `is_refusal` не видит вложенный отказ (0.11 подаёт ack как есть или лист); `read_value(sub, "_fresh", …)` читает метку как лист (фильтр в 0.10b); `TreeStore.get_subtree` бросает `KeyError` на отсутствующем пути (читатель 0.10).
- Не исправлено осознанно: Layer `backend_ctl` в коммите `d2a50fbf0` (в хуке такого слоя нет), строка `Decision: ADR-…` в коммитах с ADR; хук субагентов требует `uv sync` — не выполнялся (подменяет CUDA-torch на CPU).
- Не проверено: `make gate`, весь `backend_ctl/tests` и полные наборы `logger_module`, `router_module` после рефакторинга `channel_accepted` (радиус — каталоги задач); `sentrux` на базе `25e35942a` и на `main`.

## agentId (для re-summon)
| роль | agentId |
|---|---|
| reviewer стадия 0: 0.1 / 0.2 / 0.3 | ad3bf1d9fe23e5b23 / a96d79a121eac3503 / a5d26d6dcada507da |
| tech-writer: 0.1,0.4–0.6 / 0.2,0.9,0.10,0.10b,0.13 / 0.3,0.11 / plan,design,amendments | a4645dc72f20195d9 / a3a0d4381aea40d9b / a0dc5758e38b025ee / af1ec3ba5c1800c0b |
| developer 0.1: INTERFACE / GREEN+инъекции+правки ревью | a4745f981a0e84f72 / a17f0660ecabdadb2 |
| developer 0.2: INTERFACE / GREEN+инъекции+правки ревью | ad3cf17fc17bd5f80 / ab16b356104ff765c |
| developer 0.3: INTERFACE / GREEN+инъекции+правки ревью | af216b2dd6f4d4736 / a46d29412354c50b7 |
| tester слепой 0.1 / 0.2 / 0.3 | a66e953f161c3cb4d / ada35adab3bba4ec6 / a0ccd97977fd24fe2 |
| reviewer стадия 5: 0.1 / 0.2 (r1+r2) / 0.3 | a9549813522d19a9a / ad740263288afb938 / ac48f171351de4552 |

Токены (`subagent_tokens`, последний отчёт агента): reviewer 5 — 185k / 213k (после r2) / 173k; developer GREEN 0.1 — 116k, 0.2 — 114k, 0.3 — 101k.
