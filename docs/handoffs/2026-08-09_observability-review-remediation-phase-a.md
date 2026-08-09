---
date: 2026-08-09
topic: observability-review-remediation — фаза A закрыта (A1+A2), вход в фазу B
machine: Windows
branch: feat/observability-review-remediation
---

## Session goal

Начать реализацию плана [`plans/observability-review-remediation.md`](../../plans/observability-review-remediation.md) — закрытия находок приёмочного ревью наблюдаемости (вердикт 6/10, 2 блокера, 16 major). Критерий выхода плана: повторное ревью по той же методике даёт 8+.

## Done

**Развилки решены владельцем** (план ред. 4): Р-1=(б) merge предшественника в main и новая ветка; Р-3=(б) `max(flush, agg)` остаётся полом, но объявляется в схеме+readback+WARNING; Р-6=(б) дренирующий стаб `gui` в headless. Р-2/Р-4/Р-5 — по рекомендациям плана, подтверждение перед стартом их задач.

**Р-1б выполнена.** fw-suite 7129 passed → merge `feat/observability-unified-routing` (323 коммита) в `main` = **`23184cc4`** → прогон на слитом main 7129 passed → отведена ветка `feat/observability-review-remediation`. Конфликт был только в двух append-only журналах сессий, разрешён объединением с сортировкой по времени.

**Task A1 закрыта** (`c7157bb4` код+тесты, `a2c75b2d` live). `level` протянут через все 5 звеньев `subscribe_all` и хранится **в намерении брокера** — поэтому переживает переподписку свежей инкарнации и реплей после реконнекта. Дефолт `ERROR` сведён в одну позицию (`ProcessModule.subscribe_observability_tail`).

Оракул «поля схемы ⊇ ключи хендлера» нашёл **4 нарушения вместо одного известного**: `observability.tail.subscribe`/`level` (Б-1б, знали), `config.reload`/`persist`, `introspect.observability`/`resolve`+`flush`, `health.report`/`level`. У первых двух новых защита была **недостижима**: хендлер намеренно отказывает с подсказкой, но при `FW_CONTRACTS_STRICT=1` ключ дропался мидлварью до хендлера.

Live-приёмка на стенде `webcam_sketch`, **9 проверок из 9**: подписка INFO → 10 записей `kind=log` (в ревью было 40 минут → 0 событий); подписка ERROR → INFO 0 / ERROR 3 (пара); `contract_violations` 0→0; при STRICT подписка живёт и доставляет 4 записи; readback брокера `{'backend_ctl.b7542aabcf1c': 'ERROR'}`. Проба: `backend_ctl/probes/probe_a1_tail_level_live.py`.

**Task A2 закрыта** (`f15e8202`). Корень оказался глубже ревью: **три разных списка в трёх местах** — протокол объявлял 3 метода, `ObservableMixin` имел 5, фасад штамповал 2. Приведены к одному списку: протокол, фасад, `MockProcessServices`, два приватных дубля `_Services`.

**Инъекции: 10 из 10 совпали с предсказанием** (A1 — 6 инъекций / 14 красных; A2 — 4 инъекции / 10 красных). Ни одного расхождения.

## What did NOT work

**Оракул в первой редакции не судил НИ ОДНОЙ команды оркестратора.** У ProcessManager третья форма регистрации — словарь `{"имя": (хендлер, "описание")}`, а AST-обход знал только кортеж таблицы и прямой `register_command`. Хуже: страж «оракул видит ≥30 команд» слепоту не ловил, потому что команд процесса и так больше тридцати — порог был взят там, где кандидаты не расходятся. Лечится поимённым стражем обеих поверхностей (`test_oracle_sees_both_command_surfaces`), после чего судится 36 команд вместо 33.

**Инъекция и-2 с первого раза не применилась:** якорь `if level: args["level"] = ...` совпал в driver.py **дважды** — тот же блок уже был в `observability_tail` (на один процесс). Скрипт отказался инъецировать неточно. Негодная инъекция ничего не доказывает, поэтому она была переделана с уникальным якорем, а не засчитана. **Урок для следующих инъекций: проверять уникальность якоря в скрипте, а не полагаться на глаз.**

**Первый прогон live-пробы дал 3 FAIL — все три были дефектами пробы, не продукта:**
- предполагалось, что `health.report` даёт пару INFO+ERROR через `state.report_error`. Живьём health-запись идёт на **WARNING** — при ERROR-подписке отсекается законно. Обе половины пары надо провоцировать явно;
- счётчик `contract_violations` искался в секциях `stats` / `stats["stats"]` / `stats["router"]` — правильная **`stats["router_stats"]`**, остальные дают `-1`.

**Методическая ловушка, чуть не сделавшая live-пробу вакуумной.** `driver.observability_records` **сам** режет по объявленному `tail_level` на клиенте. Читай проба с дефолтом — и проверка «сервер фильтрует» прошла бы даже при полностью неработающем сервере: отфильтровал бы клиент. Все чтения обязаны идти с `level="DEBUG"`. Это записано в докстринг `observability_records`.

**A2 дал 25 красных в полном прогоне** — приватные дубли `_Services` в `test_plugin_source_stamping.py` и `test_plugin_context_documents.py` объявляли два `log_*` и молча разошлись с протоколом. Это **механизм сработал**, а не регрессия: фасад теперь падает громко при неполном `services`.

**Прежние тесты ветки «hub недоступен» были зелёными при живом блокере.** `_make_mock_ctx` отдаёт `MagicMock`, который порождает ЛЮБОЙ атрибут — `ctx.log_warning.assert_called_once()` проходил и без метода у фасада. Доказано инъекцией: под и-5 старый тест **остался зелёным**, четыре новых на реальном контексте покраснели.

**`MockProcessServices` выбрасывал `**kwargs`** — а там едет `module=` со штампом имени плагина. Свойство «запись приходит под именем плагина» не мог проверить ни один тест: дубль всегда успешен, потому что не хранит того, что мог бы потерять.

**Ложное утверждение жило в ДВУХ местах.** Абзац «observability.tail форвардит все severity без фильтра, сервер его не срезает» стоял и в `watch.py`, и в `driver.observability_records`. Снят в обоих — починка одного из двух оставила бы дефект живым на соседней развилке.

**Мелочи, стоившие времени:**
- `git merge -F -` не читает stdin — нужен временный файл;
- commit-msg хук не знает тип `merge` (хотя сам предлагает `--no-verify` для слияний) — использован валидный тип `feat`;
- рекурсивный `grep` по корню репозитория упирается в 308 МБ `logs/` и уходит в таймаут — скоуп задавать явно.

## Key decisions made

- **Дефолт `ERROR` живёт в ОДНОЙ позиции** (`ProcessModule.subscribe_observability_tail`). Хендлер, брокер, ПМ и драйвер несут `None` = «уровень не назван». Две позиции одной константы расходятся молча, и совпадение значений маскирует это до первого изменения.
- **Явная пятёрка `log_*`, а не `__getattr__`-проксирование.** Проксирование делает существующим любое имя, то есть превращает опечатку в молчаливый no-op и перестаёт быть проверяемым обязательством.
- **Протокол расширен до пяти методов, а не только фасад.** Иначе `log_debug`/`log_critical` — названный механизм без обязательства, которого не сторожит ничто. Контракт-тест читает список **из протокола**, поэтому добавление метода ломает проверку, а не оставляет дыру.
- **Инъекция и-6 в формулировке плана точки приложения не имеет** (клон строится через `__init__`, свойство структурное). Названо вслух и заменено сломом протокола вместо изобретения искусственного слома ради галочки.
- **Осознанное изменение поведения:** дефолтный `watch_like_gui(tail_level="WARNING")` теперь доставляет WARNING+ вместо фактического ERROR+ — заявленное намерение начинает действовать. Записано в плане явно.
- **`CAPABILITIES` перегенерирован** (`python -m backend_ctl.dump_capabilities`): поля `level`/`persist`/`flush`/`resolve` изменили командную поверхность.

## Состояние прогонов

| Прогон | Результат |
|---|---|
| fw-suite (`scripts/run_framework_tests.py`) | **7178 passed, 6 skipped** |
| корневой pytest (`make test`) | **2927 passed**, 2 красных |
| live `webcam_sketch` (A1) | **9/9**, лог `logs_live/2026-08-09_A1_tail-level/probe.log` |

Два красных корневого прогона — `test_build_characterization[phone_sketch]` и `[hikvision_letter_robot]`. **Воспроизведены на `main` в отдельном worktree — предсуществующий чужой долг**, в скоуп плана не входит.

Гейт состоит из ДВУХ независимых списков testpaths: `make test` (корневой pytest — видит `Services/`, `Plugins/`, прототип) и `make test-fw` (видит `multiprocess_framework/modules`). Тест в `Plugins/` фреймворк-suite **не** увидит — судить по конфигу нужного прогона.

## Открытые долги фазы A

- **Независимый `tester` не звался** ни в A1, ни в A2 — субагенты отключены ограничением харнесса этой сессии. Роль независимого автора тестов от acceptance не выполнена; объявлено вслух, как требует правило.
- Радиус Б-2 на **живом hikvision** не проверен (стенд webcam) — п.5 «Не проверено» отчёта ревью остаётся открытым до первого железного прогона.

## Next step

Начать **Task B1** — `aggregation_interval` по варианту **Р-3б**: `max(flush_interval, aggregation_interval)` остаётся полом, но объявляется в схеме, отдаётся в readback **из живого буфера** (`buffer.flush_interval`, не из конфига), и при значении ниже пола пишется WARNING «действует X»; `AggregationWindow` пересобирается на `reconfigure` с финальным flush старого окна. Якоря: `statistics_module/core/stats_manager.py:74-78` и `:118-133`, `process_module/managers/observability_reload.py:189`. Числа live-флипа брать **вне дефолтов 5.0/10.0** (иначе тест проверяет дефолт, а не ручку) — план предлагает 12 → 36 → 12.

## Files changed

Три коммита поверх `main` (`23184cc4`):

- `c7157bb4` — A1: код + 12 тестов + оракул
- `a2c75b2d` — A1: live-проба + правка второго докстринга
- `f15e8202` — A2: пятёрка `log_*` + протокол + дубли + CAPABILITIES

```
 backend_ctl/driver.py
 backend_ctl/probes/probe_a1_tail_level_live.py            (новый)
 backend_ctl/tests/test_driver.py
 backend_ctl/watch.py
 docs/contracts/CAPABILITIES.yaml
 multiprocess_framework/modules/process_manager_module/process/observability_broker.py
 multiprocess_framework/modules/process_manager_module/process/process_manager_process.py
 multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py
 multiprocess_framework/modules/process_module/commands/builtin_commands.py
 multiprocess_framework/modules/process_module/commands/command_contracts.py
 multiprocess_framework/modules/process_module/core/process_module.py
 multiprocess_framework/modules/process_module/plugins/base.py
 multiprocess_framework/modules/process_module/plugins/interfaces.py
 multiprocess_framework/modules/process_module/plugins/testing.py
 multiprocess_framework/modules/process_module/tests/test_command_contract_oracle.py   (новый)
 multiprocess_framework/modules/process_module/tests/test_observability_tail_delivery.py
 multiprocess_framework/modules/process_module/tests/test_plugin_context_documents.py
 multiprocess_framework/modules/process_module/tests/test_plugin_context_protocol.py
 multiprocess_framework/modules/process_module/tests/test_plugin_source_stamping.py
 Plugins/sources/camera_service/tests/test_plugin.py
 plans/observability-review-remediation.md
 docs/sessions/2026-08-09.md
```

Рабочее дерево чистое, всё закоммичено. Ветка **не** запушена.
