# Task 5.11 — Слоты потерь в карточке процесса (ред. 3)

**План:** [`plan.md`](plan.md) · фаза 5 — [`phase-5.md`](phase-5.md).
**Level:** Middle+ (Sonnet) · **Assignee:** developer, tester (слепой — по функциям и виджету), reviewer · **Layer:** prototype

**Редакции.**
- Ред. 2 (2026-10-03): ревью спеки стадии 0, раунд 1, CHANGES REQUESTED — 5 блокеров.
- Ред. 3 (2026-10-03): раунд 2 нашёл две ложные посылки о листьях, лид внёс замены. Третьего раунда нет.

**Решение (лид, по поручению владельца «как лучше и правильнее», 2026-10-03).** Слоты потерь появляются в generic-карточке только при наличии соответствующего листа телеметрии. Единицы — фреймворка («ед./с»), не «кадры».

Решение владельца от 2026-08-17 (`process_card.py:66-74`) запрещало две вещи: слот с вечным прочерком у процессов без данных и прикладное понятие «кадров/с». Условный слот не нарушает ни то, ни другое. У процесса без листа слота нет. Подпись — термин фреймворка.

Rejected:
- Отдельная панель «Потери тракта» — новый виджет и лишний слой ради трёх чисел. Владелец просит меньше слоёв.
- Отложить задачу — потери уже экспортированы в дерево (5.6), а владелец назвал индикатор нужным.

**Goal:** оператор видит потери по процессу без чтения счётчиков.

**Факты о листьях (сверено чтением в раунде 2).**
- `not_inspected_handled` есть у любого процесса, через который прошла запись о потере. Ключ ставится всегда (`pipeline_executor.py:171-172`), сумма по воркерам — `telemetry.py:174-185`. В первом прогоне 5.6 renderer и storage под `latest` дали 162 и 171.
- Признак режима `every` — наличие листа `not_inspected_lag` (`data_receiver.py:170-172`). Под `latest` этого листа нет.
- `lag_dropped_items` есть у каждого получателя межпроцессного провода. Блюпринт ставит им `chain_max_lag_items` (`blueprint.py:619-626`), а лист отдаётся при `max_lag_items > 0` (`data_receiver.py:168-169`).
- Под `every` одна lag-жертва попадает и в `lag_dropped_items` (`data_receiver.py:277`), и в `not_inspected_lag`. На этом держится формула 5.6 `born − drops == 0`.

**Предусловие (лид, до запуска тестера).** Проверить, доходят ли листья воркеров до GUI по умолчанию или их нужно включать через `telemetry.broadcast` (управляемая публикация, `presenter.py:142-190`; суммы проходят через `allowed_metrics`, `telemetry.py:157-160,176`). Ответ записать строкой в этот файл: «доходят» или «нужна подписка X». Во втором случае X добавляется в Files и DESIGN.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/widgets/process_card.py` (`set_metric` `:195`). `_METRIC_KEYS` (`:74`) не меняется: слоты потерь идут отдельной строкой.
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` (сборка метрик `:245`, `:260`).
- новый `multiprocess_prototype/frontend/widgets/tabs/processes/loss_rates.py` — чистые функции;
- тесты в `multiprocess_prototype/frontend/widgets/tabs/processes/tests/`.

**DESIGN:**
- `loss_rates(prev: dict, cur: dict, dt_s: float) -> dict[str, float | None]`.
  - На вход — dict-поддерево `processes.<P>.state` двух снимков. Окно скользящее, 5 с, по меткам снимков.
  - Значение слота = Δлиста / Δt.
  - Если Δ < 0 (процесс перезапущен) → `None`, на карточке «—».
  - Ключ слота есть в результате только при условии из таблицы ниже.

| Слот, `objectName` | Подпись | Значение | Условие показа |
|---|---|---|---|
| `loss_slot_born` | «Потеряно ед./с» | Δborn / Δt; `born` = `not_inspected_lag + not_inspected_stale_restore + not_inspected_stale_exec + shm.not_inspected_door` (формула 5.6) | есть все четыре листа |
| `loss_slot_not_inspected` | «not_inspected ед./с» | Δ`not_inspected_handled` / Δt | есть `not_inspected_handled` **и** `not_inspected_lag` (процесс под `every`) |
| `loss_slot_lag` | «Пропущено ед./с» | Δ`lag_dropped_items` / Δt | есть `lag_dropped_items` **и нет** слота `loss_slot_born` (под `every` те же единицы уже в `born` — двойной счёт) |

- `should_highlight(rates: dict, state: dict, since_running_s: float) -> bool`. Возвращает `True`, только если выполнены все три условия:
  - в `state` есть `not_inspected_lag`;
  - в `rates` значение `loss_slot_born` или `loss_slot_not_inspected` больше 0;
  - `since_running_s ≥ 10.0`.

  Под `latest` подсветки нет никогда: renderer теряет около 60 ед./с по замыслу.
- Виджет и presenter читают только dict-листья `processes.<P>.state.*` — Dict at Boundary. Импортов из `process_module.heartbeat` нет.

**Module contract:** N/A — виджет prototype. Контракт `loss_rates` и `should_highlight` задан литералами ниже.

**Acceptance criteria:**
- [ ] (tester) `loss_rates`, полная фикстура: все четыре листа `born`, `not_inspected_handled`, `not_inspected_lag`, `lag_dropped_items`.
  - Δ`not_inspected_handled` = 15 за 5.0 с → `loss_slot_not_inspected` = 3.0.
  - Δ четырёх листьев `born` = (2, 1, 0, 2) за 5.0 с → `loss_slot_born` = 1.0.
  - Ключа `loss_slot_lag` нет.
- [ ] (tester) `loss_rates`, фикстура `latest`: есть `not_inspected_handled` и `lag_dropped_items`, нет `not_inspected_lag`.
  - Δ`lag_dropped_items` = 300 за 5.0 с → `loss_slot_lag` = 60.0.
  - Ключей `loss_slot_born` и `loss_slot_not_inspected` нет.
- [ ] (tester) `loss_rates`: Δ < 0 у любого листа слота → значение `None`. Поддерево без единого листа → пустой dict.
- [ ] (tester) `should_highlight`:
  - полная фикстура, `loss_slot_born = 1.0`, `since_running_s = 10.0` → `True`;
  - то же при `9.9` → `False`;
  - фикстура `latest` с `loss_slot_lag = 60.0`, `since_running_s = 100` → `False`.
- [ ] (tester) Карточка, pytest-qt:
  - полная фикстура → видимы `loss_slot_born` и `loss_slot_not_inspected`, а `findChild(..., "loss_slot_lag")` возвращает `None`;
  - пустое поддерево → все три `findChild` возвращают `None`, прочерков нет;
  - метрики `_METRIC_KEYS` на месте.
- [ ] (tester) `grep -rn "process_module.heartbeat" multiprocess_prototype/frontend/widgets/tabs/processes` → пусто.
- [ ] (лид, живое дерево) Бэкенд с `BACKEND_CTL=1` на рецепте, отрендеренном рендером стенд-гейта (кейс `E`, 1080p@100, `every` на processor и inspector), под `stand.lock`. Точную команду записать в отчёт задачи.
  - Два снимка `state_get_subtree("processes")` с паузой 5 с.
  - `loss_rates` на этих снимках совпадает с Δлиста / Δt, посчитанным вручную, с точностью ±1 ед./с. Числа — в отчёт.
- [ ] (лид, Qt) Настоящее окно на `inspection_full.yaml`.
  - `qt_snapshot`: у процессов без листьев потерь (ожидаются camera и gui) слотов нет; у процессов со слотами — число, не прочерк. Фактический список процессов со слотами — в отчёт.
  - Разность `qt_messages` между базой (SHA до 5.11) и HEAD пуста.

**Out of scope:**
- `_METRIC_KEYS`;
- фреймворк и публикация телеметрии, кроме подписки из предусловия;
- дашборды, алертинг;
- Qt-карточка на стенде: на `stand.yaml` стоит `HeadlessGuiProcess`.
