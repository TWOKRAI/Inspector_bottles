# Task 1.6 (lifecycle-stop-ownership) — отчёт разработчика: BLOCKED до кода

**Дата:** 2026-09-25 · **Роль:** developer · **Ветка:** fix/lifecycle-1.6 (worktree `lso-1.6-dev`)
**Статус:** BLOCKED на пункте контракта «`extra["stop_summary"]` — TOP-LEVEL ключ `extra`» —
файлов реализации НЕ трогал (ни строки правки в `process_registry.py` /
`process_runner.py` / `process_manager_process.py`), только чтение + один
эмпирический скрипт против реального `StoreTapChannel`/`ObservabilityStore`.

## Что произошло

Пункт 3 DESIGN («PM publication») требовал буквально:

> The record must land in the store with `extra["stop_summary"]` as a
> TOP-LEVEL key of `extra` — verify with the live test; if the logger nests
> kwargs (e.g. under `extra["context"]`), find the existing way other PM
> records put structured fields top-level and use it; do NOT change the store
> or logger modules — stop and report if impossible.

Прежде чем писать `_cmd`/`shutdown()`-правку, проверил эмпирически (не по
чтению кода), долетает ли `stop_summary=summary` из `self._log_warning(msg,
stop_summary=summary)` до `extra["stop_summary"]` в сторе, как того требует
REDS-тест `test_normal_stop_writes_one_stop_summary_record` (assert
`"stop_summary" in extra` на объекте верхнего уровня).

## Репродукция (input → observed output)

Скрипт напрямую бьёт по `StoreTapChannel.write()` — тому же приёмнику, на
котором в проде стоит `_log_warning`/`_log_info` (маршрут:
`ObservableMixin._log_warning` → `LoggerManager.warning(message, module=...,
**extra)` → `LoggerCore.log()` → `LogRecord(extra=self._build_context(extra))`
→ `.to_dict()["extra"] == {"stop_summary": {...}}` — ЭТО уже проверено чтением
`logger_core.py:1552` и `_build_context`, extra на этом шаге ПЛОСКИЙ, без
обёртки). Дальше — путь стора, который и решает исход:

```python
import time
from multiprocess_framework.modules.channel_routing_module.observability.observability_store import ObservabilityStore
from multiprocess_framework.modules.channel_routing_module.observability.store_tap import StoreTapChannel

store = ObservabilityStore(":memory:")
tap = StoreTapChannel(store, process="ProcessManager")

record_dict = {
    "timestamp": time.time(),
    "level": "WARNING",
    "scope": "system",
    "message": "stop summary: 1 issue",
    "module": "ProcessManager",
    "extra": {"stop_summary": {"gui": {"released": 0, "buffered_dropped": 0, "reported": False}}},
}
res = tap.write(record_dict)
tap.flush(5.0)
for r in store.list_records(limit=10):
    print(r)
```

Вывод (дословно):

```
write result: {'status': 'success', 'channel': 'observability_store_tap.queue', 'dropped': 0}
{'id': 1, 'kind': 'log', 'process': 'ProcessManager', 'module': 'ProcessManager', 'ts': 1790367068.688416,
 'severity': 'warning', 'severity_number': 13, 'metric': None, 'message': 'stop summary: 1 issue',
 'extra': {'context': {'stop_summary': {'gui': {'released': 0, 'buffered_dropped': 0, 'reported': False}}}}}
```

Реальный результат — `extra["context"]["stop_summary"]`, НЕ `extra["stop_summary"]`.
Тестовое утверждение `assert "stop_summary" in extra` (буквально ключ первого
уровня) с этим красное детерминированно, а не по гонке/окружению.

## Причина (по коду, сверено построчно)

- `LoggerCore.log()` кладёт в `LogRecord.extra` ПЛОСКИЙ словарь kwargs
  (`extra=self._build_context(extra)`, `logger_core.py:1552`) — `stop_summary`
  здесь уже верхнего уровня.
- `StoreTapChannel.write()` (`store_tap.py:219-229`) заворачивает ВЕСЬ этот
  словарь в один ключ: `rec["context"] = record_dict.get("extra", {})`. Это
  структурное свойство тапа, не побочный эффект логгера.
- `hub_record_to_display()` (`record_display.py:335-337`, ветка `kind == log`,
  т.е. любой `_log_info`/`_log_warning`) строит финальный `extra` правилом
  «конверта»: `{k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}`.
  `_ENVELOPE_KEYS` (`record_display.py:40`) НЕ включает `"context"` — значит
  `"context"` остаётся единственным ключом второго уровня, и всё, что
  вызывающий передал через `**kwargs`, живёт внутри него.
- Единственный прецедент «поднять поле на верхний уровень `extra`» —
  `ORIGIN_FIELD` (`store_tap.py:237`, `rec[ORIGIN_FIELD] = origin`): это
  ЖЁСТКО зашитое имя `"origin"` внутри самого `store_tap.py`, не общий
  механизм. Других мест, где PM (или любой другой процесс) кладёт
  структурное поле кwargs верхним уровнем `extra` минуя эту обёртку, в
  `process_manager_module`/`channel_routing_module` не нашёл (грепы
  `extra\[` по `backend_ctl/tests` и `process_manager_module` — единственное
  совпадение вне этого плана, `test_observability_broker.py:421`, относится к
  ДРУГОЙ структуре — ответу команды `observability_introspect_extra()`, не к
  колонке `extra` стора).

## Почему это тупик в рамках FILES

`store_tap.py` и `record_display.py` — часть `channel_routing_module`, не
входят в список FILES задачи 1.6, и DESIGN прямо запрещает их трогать
(«do NOT change the store or logger modules»). Добавить туда generic-механизм
(второе имя-маркер вроде `ORIGIN_FIELD`, но для `stop_summary`, или снять
обёртку `"context"` вовсе) — решение вне зоны этой задачи и вне роли
developer (меняет контракт хранения для ВСЕХ потребителей `extra`, не только
Task 1.6).

## Что НЕ пробовал (честно, по правилу openness)

- Не проверял, можно ли добраться до `ObservabilityStore` напрямую из PM в
  обход `_log_warning`/тапа — по чтению кода такой ссылки у PM нет (стор
  живёт только за тапом логгера), а заводить её — тоже правка вне FILES
  (потребовала бы новой проводки в `process_manager_process.py` уровня
  архитектурного решения, не «числа»).
- Не проверял альтернативу «переименовать сообщение так, чтобы
  `_STDERR_LINE_RE`/парсер читал числа из текста `message`, а не из `extra`»
  — это противоречит контракту буквально («`extra` несёт ключ `stop_summary`»)
  и всё равно означало бы редактировать тестовый файл, что запрещено.

## Запрос к лиду (ESCALATION -> teamlead)

```
ESCALATION -> teamlead
Question: extra["stop_summary"] обязан быть TOP-LEVEL ключом extra (буквально по
  контракту и REDS), но реальный store_tap.py заворачивает ВСЕ kwargs логгера в
  extra["context"] без исключений (кроме зашитого "origin"). Как реализовывать
  публикацию сводки — (a) добавить в store_tap.py второй промоут-маркер по
  образцу ORIGIN_FIELD (правка вне FILES, вне роли developer), или (b) переписать
  REDS-тест на extra["context"]["stop_summary"] (то же самое, чем реально кладёт
  ЛЮБОЙ структурный kwarg у ЛЮБОГО PM-лога сегодня)?
Tried: эмпирическая репродукция через StoreTapChannel.write() напрямую (см. выше,
  вывод дословный) + чтение store_tap.py/record_display.py/logger_core.py построчно.
Blocked on: решение о том, чей это контракт — тестера (буква брифа) или стора
  (реальное поведение) — я не вправе поменять ни то, ни другое сам.
Files: multiprocess_framework/modules/channel_routing_module/observability/store_tap.py,
  .../record_display.py (оба вне FILES этой задачи), backend_ctl/tests/test_stop_summary_live.py
  (тестерский, править запрещено).
```

## Что осталось нетронутым

Ни один файл из FILES (1-6) не редактировался. Рабочее дерево чистое кроме
этого отчёта.

## Что я оставляю открытым / ненадёжным в своей работе

- Не запускал сами REDS-тесты (`--backend-live`) — реализации нет, гонять их
  до правки бессмысленно (они уже RED по построению задачи).
- Эмпирическая проверка сделана на `StoreTapChannel` напрямую, не через
  полный `LoggerManager`/`ObservableMixin` стек — но путь `LoggerCore.log()`
  → `LogRecord.extra` проверен чтением (`_build_context` не оборачивает,
  кladёт плоско), так что разрыв между «через логгер» и «напрямую в тап» не
  должен менять вывод; не доказано живым стендом с полным PM.
- Не проверял, обсуждали ли этот же разрыв авторы Task 1.2/1.3 (их записи в
  сторе — тоже `_log_warning`/`_log_error` без kwargs, поэтому у них `extra`
  пуст и разрыв не проявлялся — не нашёл в плане явного упоминания этого
  случая до сих пор).

---

## Часть 2 — после решения лида (option b), реализация и НОВЫЙ блокер (2026-09-25, тот же день)

Лид подтвердил репродукцию из Части 1, поправил контракт и REDS-тест (коммит `377e796b`:
`_stop_summary_of()` читает `extra["context"]["stop_summary"]`) и дал зелёный свет продолжать
реализацию по DESIGN 1-3 буквально.

### Реализовано (FILES 1-3, 5-6)

1. `process_registry.py` — слот `multiprocessing.RawArray('q', 3)` на ВОПЛОЩЕНИЕ (`_create_process`,
   рядом с `parent_pid`), словарь `self._exit_reports`, попы в `remove_process`/провале спавна,
   `exit_report(name) -> dict` (никогда не бросает).
2. `process_runner.py` — kwarg `exit_report`; запись в `finally` СРАЗУ после успешного
   `release_queues_at_exit`, `reported` — ПОСЛЕДНИМ; `shared_resources is None` → `[1,0,0]`; release
   бросил → слот не трогается; запись — в своём `try/except`, новых `emergency_log` не добавлено.
3. `process_manager_process.py` — `_publish_stop_summary()`, зовётся из `shutdown()` между `stop_all`
   и `super().shutdown()`; ОДНА запись, `msg` начинается с `"stop summary:"`, WARNING/INFO по правилу
   брифа, обёрнуто в `try/except`.
5. `DECISIONS.md` — ADR-PMM-033 (полный контекст/решение/контракт/отвергнутое/последствия +
   раздел «Найденный по ходу блокер», см. ниже); `python -m scripts.sync` прогнан,
   `multiprocess_framework/DECISIONS.md` перегенерирован и закоммичен.
6. `STATUS.md` — одна строка про Task 1.6 с явной пометкой BLOCKED.

### Механизм слота (пункты 1-2) — подтверждён живым стендом

Прямая диагностика (`/tmp/stopsummary_diag/diag.py`, не коммитился — временный скрипт):
`processor: queues released to gone readers: 1, buffered dropped: 38` (stderr) в точности совпадает
с тем, что видит PM через `exit_report("processor")` — механизм слота работает корректно.
`test_stop_summary_hazards.py` (4 теста, все PASSED): reported-после-чисел, release-бросает-не-трогает-
слот, пересозданный процесс получает свежий слот без утечки, неизвестное имя не бросает.

### НОВЫЙ блокер (не тот же, что в Части 1) — сводка не доезжает до стора ни в каком виде

Живой прогон трёх REDS (`--backend-live`) — **3 failed** (см. «TESTS» ниже, команда и хвост вывода).
Причина — **не** контракт `extra`, а порядок жизненного цикла: `ProcessModule.stop()`
(`process_module/core/process_module.py:1169-1176`) вызывает `self._flush_observability()`
(снимает/ЗАКРЫВАЕТ store-tap, `self._observability_store = None`) **ДО** `self.shutdown()` — то есть
ДО того, как вообще начинает выполняться `ProcessManagerProcess.shutdown()` (моё переопределение,
где живёт `_publish_stop_summary`).

Подтверждено эмпирически: временная диагностическая строка внутри `_publish_stop_summary` (снята перед
коммитом) печатала `self._observability_store` прямо перед вызовом `_log_warning`/`_log_info` —
результат **оба раза** (`shutdown()` вызывается дважды: изнутри `ProcessModule.stop()`, и повторно
из `finally` `run_process_function`, потому что PM стартует ЧЕРЕЗ ТОТ ЖЕ раннер, что и дети —
`spawner.py:120`):
```
DIAG stop_summary delivered=None store=None
DIAG stop_summary delivered=None store=None
```
Лог-вызов НЕ падает и НЕ исключение — строка видна в stderr/консоли живого прогона дословно
(`2026-09-25 23:17:11,551 [WARNING] [ProcessManager] ProcessManager: stop summary: released=1,
buffered_dropped=38, children=6, not reported/lost: ['processor', 'renderer']`), но `_emit_to_taps`
не находит ни одного tap'а на `logger_manager` после `unwire_observability_store`, и запись НЕ
доезжает до `observability.db` — независимо от формы `extra`.

Это опровергает вторую посылку брифа: «Публикация — логом PM в `shutdown()`… логгер PM ещё жив и
пишет в стор» — логгер жив (stderr/console работают), но **стор-tap конкретно** уже закрыт.

**Решение о том, ГДЕ звать `_publish_stop_summary`, чтобы попасть ДО `_flush_observability()`, не
принято мной единолично** — оба очевидных варианта (переопределить `stop()` в PM, чтобы звать
`stop_all()`+публикацию РАНЬШЕ `super().stop()`; либо перенести `_process_registry.stop_all()` из
`shutdown()` в более раннюю точку) трогают порядок, который Task 1.1-1.5 намеренно тюнили под живые
тайминги (5.83→0.7-1.7с и т.д.) — TRAPS брифа прямо запрещает трогать тайминг `stop_many/stop_all`.
Записал как ESCALATION -> teamlead и как раздел ADR-PMM-033.

### ESCALATION -> teamlead (вторая, в том же дне)

```
ESCALATION -> teamlead
Question: ProcessModule.stop() закрывает store-tap (_flush_observability) ДО вызова shutdown() —
  ЛЮБОЙ self._log_warning/_log_info внутри ProcessManagerProcess.shutdown() (включая мою публикацию
  сводки, но ТАКЖЕ существующий self._log_error("shutdown: дети ВЫЖИЛИ...") — Ж-4/RS-3, не новый код)
  физически не может попасть в observability.db. Где по-хорошему звать публикацию сводки, чтобы
  успеть ДО этого закрытия, не трогая тайминг stop_many/stop_all (TRAPS брифа)?
Tried: диагностическая печать self._observability_store перед _log_warning (None оба раза);
  чтение process_module.py:1169-1230 (stop() -> stop_all_workers -> _flush_observability -> shutdown()).
Blocked on: решение по перестройке порядка stop()/shutdown() для PM — вне полномочий developer,
  затрагивает тайминги Task 1.1-1.5.
Files: multiprocess_framework/modules/process_module/core/process_module.py (вне FILES этой задачи,
  общий для ВСЕХ процессов, не только PM), process_manager_process.py (в FILES, но решение не в нём).
```

### TESTS (команды и итог)

```
PYTHONPATH=$PWD .venv/bin/python -m pytest backend_ctl/tests/test_stop_summary_live.py --backend-live -q --tb=short
```
→ `3 failed in 23.26s` — все три: `assert len(matches) == 1` находит 0 записей (кроме первого теста,
где severity-логика тоже не добралась бы до проверки — запись сводки отсутствует в сторе целиком).

```
PYTHONPATH=$PWD .venv/bin/python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_stop_summary_hazards.py multiprocess_framework/modules/process_module/tests/test_f4_task411_voice_at_apply_stage.py -q --tb=short
```
→ `17 passed in 2.81s` (4 новых hazard + 13 закреплённых за инвентарём emergency_log — не выросло).

```
PYTHONPATH=$PWD .venv/bin/python -m pytest multiprocess_framework/modules/process_manager_module/tests -q --tb=line -x
```
→ `996 passed, 1 skipped in 120.89s` — радиус модуля чист, регрессий от правки не внесено.

```
PYTHONPATH=$PWD .venv/bin/python scripts/validate.py
```
→ `Ошибок нет! Предупреждений нет!` (включая раздел 6, синхронизация ADR).

### Что я оставляю открытым / ненадёжным (Часть 2)

- Реализация файлов 1-3 закоммичена НЕ ЗЕЛЁНОЙ по REDS — сознательно, по указанию бюджетной политики
  «коммить то, что работает»: слот-механизм (файлы 1-2) работает и проверен, файл 3 реализован буквально
  по DESIGN и корректен САМ ПО СЕБЕ (сообщение, severity, порядок вызова), но не может достичь цели
  (стор) без правки ВНЕ FILES/вне зоны developer.
- Не проверял, ломает ли тот же разрыв (`_flush_observability` до `shutdown()`) уже СУЩЕСТВУЮЩИЙ
  `self._log_error("shutdown: дети ВЫЖИЛИ...")` (строка появилась до Task 1.6, Ж-4/RS-3) — по чтению
  кода это тот же путь и та же судьба, но живого репро с выжившим ребёнком не делал (вне сути этой
  задачи, но релевантная находка для teamlead).
- Диагностический скрипт `/tmp/stopsummary_diag/*.py` — временный, не в репозитории, но команда для
  воспроизведения (см. выше «репродукция» Части 1 и «DIAG» здесь) достаточна для повтора кем угодно.
