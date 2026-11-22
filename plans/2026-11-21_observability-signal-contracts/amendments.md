# Amendments: observability-signal-contracts

Поправки к плану по ходу работы. Контракт — [`plan.md`](plan.md). Только дописывание.

## 0. Открытие плана (2026-11-21)

| Дата | Почему открыт | Задач | Бюджет |
|---|---|---|---|
| 2026-11-21 | запрос владельца «лучшая архитектура: убрать костыли и баги, улучшить слои и модули, без дублирования» для логов, ошибок, метрик, телеметрии и `backend_ctl`; ревизия `docs/reports/2026-11-21_observability-review.html` (51 находка); решения лида D1–D7; вариант A и метки выпуска — решения владельца 2026-11-21 | 78 после ревью r1 (срез 0: 16, срез 1: 15, из них 1.11 DEFERRED; срез 2: 15; срез 3: 14; фаза 4: 18) | ~36M токенов, 289 стартов, 12 окон стенда (оценка, `design.md` §7) |

## 1. Поправки

| # | Дата | Почему | Δ задач | Δ бюджета |
|---|---|---|---|---|
| 1 | 2026-11-21 | MODIFIED `plan.md`: вопросы В-1…В-4 закрыты решением владельца 2026-11-21 («давай как рекомендуешь») и перенесены в журнал решений; задачи уже написаны по этим рекомендациям, их тексты не менялись | 0 | — |
| 2 | 2026-11-21 | Стадия 0, раунд 1: вердикты [`0.1`](reports/0.1.review-r1.md), [`0.2`](reports/0.2.review-r1.md), [`0.3`](reports/0.3.review-r1.md) и решение лида ([`stage0-r1-lead-decisions.md`](reports/stage0-r1-lead-decisions.md)). MODIFIED `plan.md`: цель 2 -> `channel_refused_records` 4 (ответный `failed`/`refused` звена `channel` считается в `channel_refused_records`; ADR-CRM-011 сохраняется); вынесено на вето владельца/координатора | 0 | — |
| 3 | 2026-11-21 | Стадия 0, раунд 1: вердикты [`0.1`](reports/0.1.review-r1.md), [`0.2`](reports/0.2.review-r1.md), [`0.3`](reports/0.3.review-r1.md) и решение лида ([`stage0-r1-lead-decisions.md`](reports/stage0-r1-lead-decisions.md)). MODIFIED `plan.md`: цель 1 -> 12 passed (фреймворк) / 13 passed (`backend_ctl`): `telemetry_set(verify=True)` — пятый инструмент контракта 0.3 (2 по 0.2 + 11 по 0.3); вынесено на вето владельца/координатора | 0 | — |
| 4 | 2026-11-21 | Стадия 0, раунд 1: вердикты [`0.1`](reports/0.1.review-r1.md), [`0.2`](reports/0.2.review-r1.md), [`0.3`](reports/0.3.review-r1.md) и решение лида ([`stage0-r1-lead-decisions.md`](reports/stage0-r1-lead-decisions.md)). MODIFIED `plan.md`: ключ `tap_refused_records` и `process_module/managers/observability_reload.py` переходят в Task 0.5 (FILES 0.5) | 0 | — |
| 5 | 2026-11-21 | Стадия 0, раунд 1: вердикты [`0.1`](reports/0.1.review-r1.md), [`0.2`](reports/0.2.review-r1.md), [`0.3`](reports/0.3.review-r1.md) и решение лида ([`stage0-r1-lead-decisions.md`](reports/stage0-r1-lead-decisions.md)). MODIFIED `plan.md`: `backend_ctl/driver.py` добавлен в FILES 0.11 (причина `config_reload`, `telemetry_set` verify) | 0 | — |
| 6 | 2026-11-21 | Стадия 0, раунд 1: вердикты [`0.1`](reports/0.1.review-r1.md), [`0.2`](reports/0.2.review-r1.md), [`0.3`](reports/0.3.review-r1.md) и решение лида ([`stage0-r1-lead-decisions.md`](reports/stage0-r1-lead-decisions.md)). MODIFIED `plan.md`: глобальный ADR «три контракта» переносится из 0.1 в 0.3 (`multiprocess_framework/DECISIONS.md`); в 0.1 остаётся ADR-CRM-019 | 0 | — |
| 7 | 2026-11-21 | Стадия 0, раунд 2: вердикты и решения — [`stage0-r2-verdicts-and-decisions.md`](reports/stage0-r2-verdicts-and-decisions.md) (0.3, замечание N7). MODIFIED `plan.md`: цель 10 уточнена — относится к `set_register_verified`; у `register_restore` при равном значении запись не уходит, отвергать нечего (`success` True, `vacuous` = число полей; BCTL-ADR-008). **Вынесено на вето владельца/координатора** | 0 | — |
| 8 | 2026-11-21 | Фаза 0, слияние среза 0.4–0.11 в main: MODIFIED `plan.md` (статус IN PROGRESS, задачи 0.1–0.11 помечены DONE), MODIFIED `tasks/0.4.md`…`tasks/0.11.md` (правки текста по ревью стадии 0: [`0.6`](reports/0.6.review-stage0.md), [`0.9`](reports/0.9.review-stage0.md), [`0.10`](reports/0.10.review-stage0.md), [`0.10b`](reports/0.10b.review-stage0.md); решения владельца: остановленные воркеры исключены из пары fps, синхронный `send` принят до 2.4). `plans_ledger.py amend` отказывает по `PLAN_TOO_BIG`/`TASK_TOO_BIG` (см. `OPEN_QUESTIONS.md`), поэтому `contract.lock` не обновлён — дрейф записан здесь. | 0 | 0 |
