# Task 5.11 — Слоты потерь в карточке процесса (ред. 2)

**План:** [`plan.md`](plan.md) · фаза 5 — [`phase-5.md`](phase-5.md).
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой — по функции скорости и виджету), reviewer · **Layer:** prototype
**Редакция 2 (2026-10-03).** Источник — ревью спеки, стадия 0 (CHANGES REQUESTED, 5 блокеров).

**Решение (лид, по поручению владельца «как лучше и правильнее», 2026-10-03).** Слоты потерь появляются в generic-карточке, только если у процесса есть соответствующий лист телеметрии. Единицы — фреймворка («ед./с»), не «кадры».

Почему это не нарушает решение владельца от 2026-08-17 (`process_card.py:66-74`). Там запрещён слот, который у шести процессов из семи показывал бы вечный прочерк, и прикладное понятие «кадров/с» в generic-карточке. Условный слот прочерков не даёт: у процесса без листа слота нет. Подпись в единицах фреймворка не прикладная.

Rejected — отдельная панель «Потери тракта»: новый виджет и ещё один слой ради трёх чисел (правило владельца «меньше слоёв»). Rejected — отложить: потери уже экспортированы в дерево (5.6), а владелец назвал индикатор нужным.

**Goal:** оператор видит потери по процессу без чтения счётчиков.

**Предусловие (лид, до запуска тестера).** Проверить, доходят ли листья воркеров до GUI по умолчанию. Речь о `processes.<P>.state.not_inspected_handled` и `…lag_dropped_items` — или их надо включать через `telemetry.broadcast` (управляемая публикация, `presenter.py:142-190`). Ответ — строкой в этот файл: «доходят» или «нужна подписка X» (тогда X — в Files и DESIGN).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/widgets/process_card.py` (`set_metric` `:195`). `_METRIC_KEYS` (`:74`) не меняется: слоты потерь идут отдельной строкой.
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` (сборка метрик `:245`, `:260`).
- Новый `multiprocess_prototype/frontend/widgets/tabs/processes/loss_rates.py` — чистая функция.
- Тесты `multiprocess_prototype/frontend/widgets/tabs/processes/tests/`.

Домен — `tabs/processes/`, не `pipeline/`. Ред. 1 указывала reorg-документ, а там карточки процесса нет.

**DESIGN:**
- `loss_rates(prev: dict, cur: dict, dt_s: float) -> dict[str, float | None]`. На вход — dict-поддерево `processes.<P>.state` двух снимков. Окно скользящее, 5 с, по меткам снимков. Значение = Δлиста / Δt.
- Слот «Потеряно ед./с» = Δborn / Δt.
  - `born` = `not_inspected_lag + not_inspected_stale_restore + not_inspected_stale_exec + shm.not_inspected_door` (формула 5.6).
  - Слот есть, только если есть все четыре листа.
- Слот «Без вердикта ед./с» = Δ`not_inspected_handled` / Δt. Слот есть, только если есть этот лист.
- Слот «Пропущено ед./с» = Δ`lag_dropped_items` / Δt. Слот есть, только если есть этот лист (процессы с `max_lag_items > 0`).
- Δ < 0 (процесс перезапущен) → значение `None` → на карточке «—».
- Подсветка: только у процессов с листьями `not_inspected_*` (то есть под `every`), при значении > 0, не раньше 10 с после статуса `running`.
  - «Пропущено» под `latest` не подсвечивается: renderer теряет около 60 ед./с по замыслу.
- Виджет и presenter читают только dict-листья `processes.<P>.state.*` (Dict at Boundary). Импортов из `process_module.heartbeat` нет.

**Module contract:** N/A — виджет prototype. У `loss_rates` контракт задан литералами ниже.

**Acceptance criteria:**
- [ ] (tester) `loss_rates`: Δ`not_inspected_handled` = 15 за 5.0 с → «Без вердикта» = 3.0. Δborn по четырём листьям (2, 1, 0, 2) за 5.0 с → «Потеряно» = 1.0. Листа нет → ключа слота нет в результате. Δ < 0 → `None`.
- [ ] (tester) Карточка, pytest-qt:
  - снимок с листьями `not_inspected_*` → три слота видимы;
  - снимок без них → слотов потерь нет (`findChild` по `objectName` возвращает `None`), а не прочерк;
  - метрики `_METRIC_KEYS` на месте.
- [ ] (tester) Подсветка:
  - под `every`, значение > 0, 10 с после `running` → свойство подсветки `True`;
  - те же числа через 9 с → `False`;
  - процесс без `not_inspected_*` и «Пропущено» > 0 → `False`.
- [ ] (tester) `grep -rn "process_module.heartbeat" multiprocess_prototype/frontend/widgets/tabs/processes` → пусто.
- [ ] (лид, живое дерево) Стенд `python -m scripts.stand_gate` (headless GUI), снимок `state_get_subtree("processes")` дважды с паузой 5 с → `loss_rates` на этих снимках = Δлиста / Δt, посчитанному вручную, ±1 ед./с. Числа в отчёте задачи.
- [ ] (лид, Qt) Настоящее окно на рецепте без `every` (`inspection_full.yaml`):
  - `qt_snapshot` — у процессов нет слотов потерь (нет вечных прочерков);
  - разность `qt_messages` между базой (SHA до 5.11) и HEAD пуста.

**Out of scope:** `_METRIC_KEYS`; фреймворк и публикация телеметрии (кроме подписки из предусловия); дашборды, алертинг; GUI на стенде (на `stand.yaml` стоит `HeadlessGuiProcess`, Qt-карточки там нет).
