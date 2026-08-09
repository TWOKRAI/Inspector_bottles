---
date: 2026-08-09
topic: observability-review-remediation — фазы B и C закрыты (C1 уехала в план телеметрии), вход в фазу D
machine: Windows
branch: feat/observability-review-remediation
---

## Session goal

Продолжить [`plans/observability-review-remediation.md`](../../plans/observability-review-remediation.md) с того места, где закончилась предыдущая сессия ([хендофф фазы A](2026-08-09_observability-review-remediation-phase-a.md)): фаза B («пульт до честности»), а затем — по решению владельца — фаза C в части, не запертой развилкой Р-2.

## Done

**Фаза B закрыта целиком** (B1 `1cadd890`, B2 `f745a929`, B3 `e2917e70`, статус плана `ee152fd3`).

**B1 — темп стат-плоскости.** Дефект оказался глубже спеки: ветка `stats` в `observability_effective` сторожилась `getattr(stats, "config")`, а у `StatsManager` такого атрибута нет вовсе (его ставит `LoggerCore` — предок логгера и ошибок). Воспроизведено до правки: `observability_effective(stats=mgr)` → `{}`, то есть темп не «эхо запроса», а **отсутствовал** в readback'е. Сделано: `resolve_tempo` (одна позиция формулы `max(flush, aggregation)`, дефолты из схемы), пересборка `AggregationWindow` на `reconfigure` (новое окно ставится ДО остановки старого, старое гасится с финальным flush), WARNING про пол с адресом ключа и обоими числами, `StatsManager.observability_readback()` — темп из ЖИВОГО окна. Live-флип 12 → 36 → 12: **10 → 3 → 10** сбросов за 120 с, отношение 3.33 в обе стороны; `verdict=confirmed`.

**B2 — валидация на границе слоёв.** Воспроизведено: `config.reload {"log_level": "БОЛТОВНЯ"}` → `success=true`, мусор в L3, действует старое. **Дефект был на ТРЁХ ручках**, ревью называло одну (`errors.level` и `stats.log_level` вели себя так же). Правило — одна позиция (`canonical_level_or_raise`), применяется в четырёх точках записи (`replace_layer` для L1/L2, `session_set` для ключа, хендлер `config.reload` для секции; persist наследует через `replace_layer`).

**B3 — порядок останова.** До правки последняя запись `camera_0/system.log` — «LoggerManager shutting down», а «shut down successfully» не было вовсе. Логгер гасится последним; `error_manager.shutdown()`/`stats_manager.shutdown()` не звались нигде — добавлены; отказ гашения логгера уходит в `emergency_log` и не отменяет успех останова. Live: «shut down successfully» у **6 процессов из 6**, снапшоты метрик в хвосте останова 3/2/2/2/2/2.

**Фаза C — C2 и C3 закрыты** (`f6042762`), **C1 по решению владельца Р-2=(в) уехала в план телеметрии как его первая фаза**.

**C2 — разъём ошибок (ADR-PM-030).** Прогон опроверг посылку ревью наполовину: `ctx.health.report_error` уходил в `system.log` через `services.log_warning`, а плоскость ошибок не видела от плагинов **ничего** — единственной дорогой туда оставался `_track_error`, которого у `PluginContext` нет. То есть чинить надо было не «неожиданный маршрут», а отсутствующий. `HealthState` получил зависимость `track`; инцидент едет в плоскость ошибок под тем же дросселем, что строка журнала (счётчик health считает ВСЕ вызовы).

**C3 — симметрия плоскости документов.** Молчали ДВА случая: «плоскости нет» и «сток отказал статусом» (`DocumentStore.dropped` рос, читать его снаружи было нечем). Введены `documents.declared/without_sink/dropped` в `introspect.observability`, два независимых голоса (по одному на класс отказа) и различение диагнозов: `without_sink` лечится конфигом, `dropped` — базой. `dropped=None`, если сток счётчика не ведёт.

**Инъекции: 24 штуки, 60 красных, предсказание совпало 22 раза из 24.** Оба расхождения разобраны (см. ниже).

## What did NOT work

**Все инъекции первого захода не применились: CRLF.** Файлы репозитория с `\r\n`, якоря писались с `\n`, скрипт отказался инъецировать вслепую и напечатал «ANCHOR NOT UNIQUE (0 matches)». Отказ — правильное поведение (негодная инъекция ничего не доказывает), но **скрипт инъекций обязан нормализовать переводы строк с самого начала**: `text = raw.decode().replace("\r\n", "\n")`, а перед записью — обратно.

**Мой собственный новый WARNING оказался шумом — нашёл живой прогон.** Пол темпа срабатывал **12 раз на стоковом старте**: `system.yaml` прототипа явно писал `aggregation_interval: 5.0`, и это значение **не действовало ни разу** (пол `flush_interval=10.0`). Правка — в конфиге прототипа (написано 10.0, темп изменился на ноль), а НЕ в дефолте схемы: при опущенном `flush_interval` значение 5.0 действует, и смена дефолта поменяла бы поведение тем, кто опускает пол. Повторный boot: 0 предупреждений.

**Правка имени плоскости ошибок потребовала ДВУХ заходов, и второй нашёл стенд, а не тест.** Первая редакция считала «имя не задано» = пустой ключ; юнит-тест на словаре без ключа был зелёным, **а стенд не изменился ни на строку**. Причина: машинная раскладка (`managers_payload_for_proc`) МАТЕРИАЛИЗУЕТ дефолт схемы, и в словаре всегда лежит `manager_name: "ErrorManager"`. Теперь дефолт читается из самой схемы (`model_fields[...].default`) и считается «не названо». Урок записан в память: `feedback_materialized_default_hides_absence`.

**Расхождение предсказания и-11 (B3): предсказано 3 красных, факт 4.** Лишний — `test_a_failing_logger_shutdown_is_not_swallowed`: при старой позиции гашение логгера идёт БЕЗ собственного try/except, поэтому его отказ уходит во внешний обработчик и превращает весь останов в `shutdown() → False`. Красный назвал настоящее свойство старого порядка.

**Расхождение предсказания и-16 (C3): предсказано 2, факт 1.** Я предсказывал по неверной модели собственной правки — флагов однократности **два**, по одному на класс отказа, и голос про отсутствие плоскости не может заглушить голос про отказ стока. Расхождение в пользу продукта.

**Первая редакция инъекции и-17 (C2) была слишком грубой.** Она ДОБАВЛЯЛА выдачу инцидента мимо дросселя, оставляя прежнюю на месте, — и давала 2 красных вместо 1, причём второй приходил от дублирования, а не от снятого дросселя. Переделана в перенос, а не засчитана.

**Мелочи, стоившие времени:**
- скрипт-стенд без `if __name__ == "__main__":` на Windows уходит в **форк-бомбу** (spawn переимпортирует модуль) и висит до таймаута;
- рекурсивный `grep` по корню репозитория снова упёрся в 308 МБ `logs/` и ушёл в фон — скоуп задавать явно (или Grep-инструментом);
- pre-commit `ruff format` переформатирует файл и **роняет коммит**: после него обязателен `git add -A` и повторный `git commit`.

## Key decisions made

- **Р-2 = (в)** (владелец): C1 (stats-разъём плагинов + доставка `kind=stats`) — первая фаза плана телеметрии. Ветку `KIND_STATS` в drain **не трогать** (задача D6): на ней стоит это решение.
- **Дефолт схемы `aggregation_interval=5.0` НЕ менялся** — правился конфиг прототипа. Смена дефолта поменяла бы темп тем, кто опускает `flush_interval`.
- **Golden-снапшоты сборки правились точечно** (только `aggregation_interval`, 16 и 22 вхождения). Полная регенерация через `UPDATE_BUILD_SNAPSHOTS=1` втянула бы заодно предсуществующий дрейф (секция `observability.documents` есть в сборке и отсутствует в golden) и молча закрыла бы чужой красный.
- **C2 — вариант (б), а не (а).** Дублирование `ctx.log_error` в error-маршрут превратило бы плоскость ошибок в копию `system.log`. Последствие названо в ADR: `errors.log` начинает получать инциденты плагинов, а ретеншен корневых файлов этой плоскости — слепая зона (задача D5).
- **Инцидент отдаётся плоскости ошибок под ОБЩИМ с логом дросселем** (5 с на пару «тип+контекст»): у плоскости ошибок своего дросселя нет, а `report_error` — типовой сайт горячего цикла. Честность числа держит счётчик health, а не одна запись на вызов.
- **Долг graceful-stop вынесен, а не закрыт:** измерено **5.1 с до и 5.1 с после** B3 — к порядку гашения менеджеров отношения не имеет. Числится в `plans/QUEUE.md` как L-2 (`stop_all_workers`/`put()`).

## Состояние прогонов

| Прогон | Результат |
|---|---|
| fw-suite (`scripts/run_framework_tests.py`) | **7243 passed, 6 skipped** |
| корневой pytest (без `test_build_characterization`) | **2927 passed, 5 skipped** |
| live B1 `webcam_sketch` | **11/11**, `logs_live/2026-08-09_B1_stats-tempo/probe.log` |
| live B2 `webcam_sketch` | **9/9**, `logs_live/2026-08-09_B2_layer-validation/probe.log` |
| live B3 `webcam_sketch` | **5/5**, `logs_live/2026-08-09_B3_shutdown-order/probe.log` |
| прогон C2 (настоящие менеджеры, файлы) | 3 маршрута разведены, `python -m backend_ctl.probes.probe_c2_error_route` |
| прогон C3 (настоящий SQLite) | **5/5**, `python -m backend_ctl.probes.probe_c3_document_plane` |

Два красных корневого прогона — `test_build_characterization[phone_sketch]` и `[hikvision_letter_robot]`. **Остаются красными по ПРЕЖНЕЙ, не нашей причине**: сверено дельтой — 9 и 12 расхождений, все про секцию `observability.documents`, которой нет в golden. Ни одного расхождения про `aggregation_interval` не осталось.

## Открытые долги

- **Независимый `tester` не звался ни в одной задаче B и C** — субагенты отключены ограничением харнесса сессии. Роль независимого автора тестов от acceptance не выполнена; объявлено вслух в каждом «Ходе» плана, как требует правило.
- Радиус Б-2 на живом hikvision по-прежнему не проверен (п.5 «Не проверено» отчёта ревью) — до первого железного прогона.
- Долг graceful-stop (5.1 с) — `plans/QUEUE.md`, L-2.

## Next step

**Фаза D — гигиена, зависимостей нет** (единственная внутренняя: D2.4 после D2.5, A1 и D8; A1 закрыта). Порядок по плану:

- **D8** (Р-6=(б) уже решена владельцем): headless-стаб `gui`, дренирующий данные. Шторм подтверждён живьём в этой сессии — `errors_delivery_failed=12129` за прогон стенда, `targets=['gui']`. Без D8 задача D2.5 переписывает тест, а корень флейка остаётся.
- **D2** (тестовая сетка), **D1** (реентерабельность tap/sink), **D3** (стор: `auto_vacuum` + честность `dropped`), **D5** (слепые зоны ретеншена — и туда же уехало последствие C2 про корневые файлы плоскости ошибок), **D4** (радиус «inspector», развилка Р-4 — подтверждение владельца перед стартом), **D6** (удалить мёртвое; `KIND_STATS` не трогать), **D7** (обходы единственного писателя).

Затем **фаза E** (четыре справочника; асимметрии C2/C3 закрыты, переписывать дважды больше нечего) и **F1** — повторное ревью по методике 2026-08-09, исполнитель внешний к автору фаз.

## Files changed

Семь коммитов поверх хендоффа фазы A (`4a83a65b`):

- `1cadd890` — B1: темп стат-плоскости
- `f745a929` — B2: валидация на границе слоёв
- `e2917e70` — B3: порядок останова
- `ee152fd3` — план, ред. 5
- `b9215420` — память: материализованный дефолт
- `f6042762` — C2+C3
- `42efed98` — `scripts.sync` после ADR-PM-030

```
 backend_ctl/probes/probe_b1_stats_tempo_live.py                 (новый)
 backend_ctl/probes/probe_b2_layer_validation_live.py            (новый)
 backend_ctl/probes/probe_b3_shutdown_order_live.py              (новый)
 backend_ctl/probes/probe_c2_error_route.py                      (новый)
 backend_ctl/probes/probe_c3_document_plane.py                   (новый)
 docs/claude/memory/feedback_materialized_default_hides_absence.md (новый)
 docs/claude/memory/MEMORY.md
 multiprocess_framework/DECISIONS.md
 multiprocess_framework/modules/error_module/core/error_manager.py
 multiprocess_framework/modules/error_module/tests/test_manager_naming.py   (новый)
 multiprocess_framework/modules/logger_module/core/logger_core.py
 multiprocess_framework/modules/process_module/DECISIONS.md
 multiprocess_framework/modules/process_module/commands/builtin_commands.py
 multiprocess_framework/modules/process_module/configs/observability_config.py
 multiprocess_framework/modules/process_module/configs/observability_layers.py
 multiprocess_framework/modules/process_module/health/state.py
 multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py
 multiprocess_framework/modules/process_module/managers/observability_reload.py
 multiprocess_framework/modules/process_module/managers/observability_wiring.py
 multiprocess_framework/modules/process_module/managers/process_managers.py
 multiprocess_framework/modules/process_module/plugins/base.py
 multiprocess_framework/modules/process_module/tests/test_document_plane_symmetry.py  (новый)
 multiprocess_framework/modules/process_module/tests/test_error_route.py              (новый)
 multiprocess_framework/modules/process_module/tests/test_introspect_commands.py
 multiprocess_framework/modules/process_module/tests/test_layer_value_validation.py   (новый)
 multiprocess_framework/modules/process_module/tests/test_shutdown_order.py           (новый)
 multiprocess_framework/modules/process_module/tests/test_stats_tempo_readback.py     (новый)
 multiprocess_framework/modules/statistics_module/README.md
 multiprocess_framework/modules/statistics_module/channels/log_stats_channel.py
 multiprocess_framework/modules/statistics_module/configs/stats_config.py
 multiprocess_framework/modules/statistics_module/core/aggregation_window.py
 multiprocess_framework/modules/statistics_module/core/stats_manager.py
 multiprocess_framework/modules/statistics_module/tests/test_tempo_knob.py            (новый)
 multiprocess_prototype/backend/config/system.yaml
 multiprocess_prototype/backend/tests/snapshots/hikvision_letter_robot.build.json
 multiprocess_prototype/backend/tests/snapshots/phone_sketch.build.json
 plans/observability-review-remediation.md
```

Рабочее дерево чистое, всё закоммичено. Ветка **не** запушена.
