# Факты транспорта до кода фазы 5 (Task 5.0) — 2026-10-02

Лид — сессия 19. Дерево замера — `.claude/worktrees/stand`, detached на `003264912` (main). Стенд под `stand.lock`, режим measure.
Рецепт — `scripts/capacity_bench/recipes/stand.yaml`, 1080p@100, `overflow: every` на processor и inspector. Скрипт — `stand50.py`:
копия `stand47d.py` лида 4.7d плюс полный плоский дамп `introspect.router_stats`, ключи `transit_over_budget` / `ipc_queue_depth`, выборка строк лога.
Снимки: `s0` — после 10 с прогрева, `s1` — конец окна 30 с, `s2` — после паузы камеры и затухания счётчиков.
Предсказания записаны до прогона (`stand50_predictions.md` в scratchpad лида). Все три подтвердились.

## Итог — что меняется в фазе 5

| Факт | Следствие |
|---|---|
| (а) кадры ходят только дверью А, `put_timeout_total = 0` везде | 5.10 по факту не запускается; решает OWNER-3. Инвариант-тест «одна дверь» и ADR — всё равно сейчас |
| (б) `system_ready_event` до детей не доходит | 5.4 — проводка через аргумент `Process` по образцу `system_stop_event`, а не «два файла» |
| (в) транзит и вытеснения набегают на старте, в окне почти 0 | основание 5.4 подтверждено числом; `ipc_queue_depth` нужен максимумом за окно (5.6) |
| (г) 2 из 9 рецептов не стартуют (валидатор + нет `wires:`) | **5.9 заблокирована**: `multi_camera.yaml` падает на валидации. Чинит Task 5.9a (валидатор + провода). Есть `recipes/dualcam_synth.yaml` |
| (д) `delivery_failed` = «ни один из N адресатов не принял» (`:574`) | пачка маркеров теряется на полной очереди соседа — это то, что лечит 5.3 |
| (е) `g7_soak_probe` жива | 0.3 закрыт; набор флагов пробы уйдёт с loan в 5.7 |

## (а) Какой дверью ходят кадры — **дверью А (targets)**

Прогон E (`every`, 30 с, окно 31.16 с, все процессы ≈ 99.9 Гц). Счётчики `introspect.router_stats` на конец прогона (у camera_0 — `s1`, см. «Попутно»):

| процесс | `sent_via_targets.data` | `sent_via_channel` | `put_timeout_total` (все каналы) | `errors_delivery_failed` | `middleware_dropped` |
|---|---|---|---|---|---|
| camera_0 | 4552 | 0 | 0 | 0 | — |
| processor | 9220 | 0 | 0 | 0 | 0 |
| renderer | 1835 | 0 | 0 | 0 | 0 |
| inspector | 9148 | 0 | 0 | 0 | 0 |
| storage | 0 (лист) | 0 | 0 | 0 | 0 |
| gui | 0 | 0 | 0 | 0 | 0 |

**Вывод: data-кадры ходят дверью А; дверь Б (`QueueChannel.put(timeout=1.0)`) data-трафиком не пользуется ни у одного процесса.**
Следствие для 5.10: условие запуска по факту не выполнено. Остаётся решение владельца OWNER-3; без него — инвариант-тест и ADR сейчас, унификация в фазе 6.
Закрывает Task 0.2.

## (б) Доходит ли `system_ready_event` до generic-детей — **нет**

- Событие создаёт лаунчер (`system_launcher.py:107`) и передаёт в PM через bundle (`spawner.py:107-108`). PM читает его (`process_manager_process.py:131`) и взводит сам (`:324-325`, `_announce_ready`).
- При запуске ребёнка реестр явно вырезает его из `custom`: `process_registry.py:189` (`for key in (..., "system_ready_event", ...): custom.pop(key, None)`). Причина в комментарии `:183-188`: mp.Event на Windows-spawn пиклится только через наследование.
- У `SourceProducer` нет точки ожидания: `grep ready process_module/generic/source_producer.py` — пусто.
- Образец проводки для 5.4 — `system_stop_event`. Он идёт отдельным аргументом `Process` (`process_registry.py:246-247`, `args=(class_path, name, stop_event, bundle, self._system_stop_event)`).

**Следствие для 5.4:** задача не «на два файла». Нужна проводка `PM → ProcessRegistry → аргумент Process → ProcessModule → GenericProcess → SourceProducer` по образцу `system_stop_event`.

## (в) `transit_over_budget` и `ipc_queue_depth`

| процесс | E: `transit` s0 → s2 | P10: `transit` s0 → s2 | `ipc_queue_depth` (gauge в момент снимка) | E: `queue_data_evicted` s0 → s2 |
|---|---|---|---|---|
| processor | 21 → 23 | 23 → 36 | 0 | 40 → 40 |
| renderer | 48 → 50 | 48 → 509 | 0 | 0 |
| inspector | 50 → 58 | 50 → 337 | 0 | 30 → 30 |
| storage | 47 → 50 | 46 → 56 | 0 | 0 |

- **В установившемся режиме транзит почти не растёт.** За первые 10 с набегает 21–50, за следующие 31 с окна E — ещё +2…8. Стартовые вытеснения (40 у processor, 30 у inspector) все происходят до `s0`; в окне их 0. Это прямое основание для 5.4.
- Под паузой исполнителя (P10) транзит растёт у соседей за processor: renderer +461, inspector +287. Это дренаж хвоста после паузы.
- `ipc_queue_depth` — мгновенный gauge, а не максимум. В момент снимка он 0 у всех. Как сигнал для планирования мощности он слаб: пики между снимками не видны. Для 5.6 предлагаю экспортировать максимум за окно, а не последнее значение.

## (г) Все рецепты `backend/topology` стартуют 30 с без `read-only`

Скрипт `sweep50.py`: каждый `*.yaml` из `multiprocess_prototype/backend/topology/` (кроме `TEMPLATE.yaml`) — `BackendHarness`, 30 с, grep всех логов.

| рецепт | стартовал | старт, с | `read-only` | строк ERROR | примечание |
|---|---|---|---|---|---|
| base.yaml | да | 7.4 | 0 | 0 | |
| hello_world.yaml | да | 5.3 | 0 | 0 | |
| inspection_basic.yaml | **нет** | — | — | — | `SystemExit(1)` на валидации портов, см. ниже |
| inspection_full.yaml | да | 12.2 | 0 | 4 | 25 fps; по одной ERROR-строке на процесс: «выброшено 1 устаревших коллекций за 5 с» на старте (тот же эффект, что лечит 5.4) |
| multi_camera.yaml | **нет** | — | — | — | `SystemExit(1)` на валидации портов, см. ниже |
| observability_sink.yaml | да | 4.8 | 0 | 0 | |
| otel_export.yaml | да | 5.2 | 0 | 1 | нет коллектора на `127.0.0.1:4318` — ожидаемо |
| pilot_widgets.yaml | да | 4.7 | 0 | 0 | |
| telemetry_sink.yaml | да | 4.8 | 0 | 0 | |

**`read-only`: 0 из 7 стартовавших.** Остаток acceptance 4.7 по `read-only` закрыт. Но **два рецепта не стартуют вообще**:

```
[launch] ОШИБКИ валидации topology:
  ✗ color_mask → blob_detector: вход 'frame' (image/bgr (H, W, 3)) несовместим с выходами [mask:image/gray]
  ✗ Вход 'processor.color_mask.frame' (image/bgr) не подключен      (inspection_basic)
  ✗ Вход 'processor_0.color_mask.frame' (image/bgr) не подключен    (multi_camera)
  ✗ Вход 'processor_1.blob_detector.frame' (image/bgr) не подключен
  ✗ Вход 'compositor.renderer_compositor.frame' (image/bgr) не подключен
```

**Поправка после разбора CTO 5.1** ([`docs/reviews/2026-10-02_phase5-design-cto.md`](../reviews/2026-10-02_phase5-design-cto.md), решение 9). Первая версия этого отчёта винила один коммит `917ec7ed4`. Это неверно: дефектов два.
- **A (фреймворк).** `validate_chain` (`process_module/plugins/port.py:198-232`) и `_is_covered_by_auto_wiring` (`blueprint.py:1006`) ищут вход узла только среди выходов **непосредственно предыдущего** узла. Проход ключа сквозь узел они не моделируют. `917ec7ed4` (2026-09-30) сделал `color_mask` таким узлом: он отдаёт только `mask` (`color_mask/plugin.py:43-44`). Отсюда одна строка `color_mask → blob_detector` у `inspection_basic`.
- **B (прототип).** У `multi_camera.yaml` и `inspection_basic.yaml` нет секции `wires:` — и не было до `917ec7ed4`. CTO прогнал `check()` на версиях до коммита: те же 3 и 5 ошибок «не подключен». Значит, `multi_camera.yaml` не проходил валидацию и раньше. С какого момента `check()` обязателен на старте — не выяснено.

**Это блокирует Task 5.9** (второй рецепт стенд-гейта). Чинит новая **Task 5.9a** в `phase-5.md`.

Попутно: рецепт **`dualcam_synth.yaml` есть** — в `multiprocess_prototype/recipes/`, а не в `backend/topology/`. Ревью CTO искало только во втором каталоге.
Состав: две `SyntheticFrameSourcePlugin` 640×480@30 и два `FrameCounterPlugin`. Для 5.9 это основа без аппаратных камер (вопрос OWNER-10).

## (д) Строка лога P10 и ветка `_do_send`

Прогон P10 (`every`, пауза `pipeline_executor` у processor 10.1 с, дренаж 0.6 с, RSS processor 228.2 → 228.6 МБ):

```
system.log: [ERROR] [processor] router_processor: RouterSendError @ router.send_error:delivery_failed: [delivery_failed] ни один из 1 адресатов не принял: channel=None command=None type='data' targets=['renderer']
```

**Ветка — «ни один из N адресатов не принял»** (`router_manager.py:574`, блок `_do_send` дверью А). Это не «канал вернул ошибку».
Адресат — renderer (`latest`), отказ — его полная очередь. Числа P10 у processor: `errors_delivery_failed` 1087, `queue_data_evicted` 39 → 263.
Они воспроизводят P10 стенда 4.7d-5 (1076 / 245). Строк такого вида в логах — 2, а счётчик — 1087: логгер схлопывает повторы, счётчик полный.

## (е) Жива ли `g7_soak_probe` — **да**

`python -m backend_ctl.probes.g7_soak_probe --duration 60 --interval 20 --tier live --port 8775`, рецепт `recipes/g1_perf_probe.yaml` (3 процесса):

```
[g7-soak] t=    28s fps[consumer=30.0 synthetic_source=30.01] torn=0 stale=0 exhausted=0 rss_total=726МБ
[g7-soak] t=    60s fps[consumer=30.0 synthetic_source=29.97] torn=0 stale=0 exhausted=0 rss_total=726МБ
  "verdict": "CLEAN",
```

Оговорка: проба сама включает свой набор флагов, в том числе замороженный `FW_SHM_LOAN_PROTOCOL` и `FW_USE_KIND_CHANNELS`.
Её «чисто» относится к этой конфигурации, а не к рецептам по умолчанию. Судьба 0.3/3.1: проба пригодна как инструмент. Набор флагов устарел и уйдёт вместе с loan в 5.7.

## Попутно (вне вопросов, но записать)

- После `worker.pause_all` у camera_0 команда `introspect.status` отвечает `timeout` за 5 с (снимок `s2` пуст в обоих прогонах). Похоже, командный путь камеры уходит в паузу вместе с воркерами. Для 5.6 это значит: «тишину» перед итоговым снимком делать не паузой камеры, либо снимать камеру до паузы (так и сделано в `stand47d.py`).
- Повторяемость: прогон один на кейс. Это наблюдение, не замер с разбросом. Числа P10 совпали с 4.7d-5 в пределах 1–8 %.

## Не проверено

- Разброс по повторам (по одному прогону на E и P10).
- `ipc_queue_depth` как максимум за окно — счётчика нет, есть только gauge.
- Дверь Б под другими рецептами (`multi_camera`, `inspection_full`): (а) снят только на `stand.yaml`.
