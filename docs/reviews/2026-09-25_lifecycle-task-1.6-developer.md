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
