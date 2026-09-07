# Контракт closure ↔ otel-export

Общий файл двух треков. Правило, по которому он заведён (вердикт CTO, 2026-09-06):
**письмом идут решение и опровержение ранее переданного факта; всё остальное — сюда.**
Переписка стала работой в тот момент, когда получатель обязан перепроверять факты из письма,
а не применять решение. За сессию 2026-09-06 таких писем было девять — отсюда этот файл.

Владельцы: `feat/observability-closure` (далее **closure**) и `feat/otel-export` (далее **otel**).
Слияние **одностороннее**: closure → otel по ходу работы; обратно — только на фазовой точке
и рукой ведущего closure.

---

## 1. Пять литералов для Task 2.4 трека otel

Task 2.4 не пишет свой предохранитель — она **импортирует** форму closure. Литералы ниже
закреплены закрытием Task 3.3 и меняться без правки этого файла не должны.

| литерал | что это | где живёт |
|---|---|---|
| `BatchDrainWorker` | класс-предохранитель, сток не знает про стор | `channel_routing_module/observability/batch_drain.py` |
| `store_evicted` | имя счётчика вытеснений **на плоскости closure** | параметр `counter_name`, у otel своё — `dropped_overflow` |
| `history.queue_capacity` | ключ политики, откуда берётся ёмкость | `observability_config.py` → `ObservabilityHistoryConfig` |
| `drop_oldest` | политика переполнения | `bounded_channel.py`, константа `DROP_OLDEST` |
| `store flush: N записано, M потеряно` | строка исхода на останове | `store_tap.py`, `close()` |

**Сигнатура, к которой привязываться:**

```python
BatchDrainWorker(sink, capacity, *, counter_name,
                 overflow=DROP_OLDEST, batch_size, flush_interval_sec)
    .write(record) -> dict
    .flush(timeout) -> (записано, потеряно)
    .close(timeout) -> (записано, потеряно)
```

`sink` — вызываемое, принимающее список записей, **либо** объект с `append_records(list)`.
Слои: `Services → framework` разрешено, импорт легален.

**Имя счётчика — параметр, а не литерал в классе.** Решение ведущего closure: счётчик именует
**плоскость**, а не механизм, поэтому сводить два трека к одному слову отказано. Внутри класса
нет ни одного вхождения `store_evicted` — это стережёт тест, читающий модуль целиком.

## 2. Признак, по которому otel считает closure-задачу закрытой

**Не «закоммичена», а «принята ревью».** Обоснование фактом: на Task 3.2 ревью двигало лексику
уже ПОСЛЕ первого коммита (`13208686` → `757a2d4c`, где критерий переписан вердиктом CTO, →
`1f40ce0d`, правка 19 мест). Старт от первого коммита означал бы переписывание имён вслед.

Сигнал: `[x]` с хэшем принимающего коммита в карточке фазы плюс `merged` в closure.

**Task 3.3 — ПРИНЯТА 2026-09-06**, ревью `APPROVE WITH NITS`, все замечания закрыты.
Гейт фреймворка **9810 passed, 9 skipped, 1 xfailed, 0 failed**. Task 2.4 разблокирована.

## 3. Владение путями

| зона | владелец |
|---|---|
| `multiprocess_framework/**` (код) | closure |
| `backend_ctl/**`, `scripts/validate.py` | closure (правка `validate.py:211` — заявкой) |
| `Services/otel_export/**`, `Plugins/io/otel_export/**`, `tools/otel_stand/**` | otel |
| `multiprocess_prototype/backend/topology/otel_export.yaml` | otel |
| `plans/observability-closure/**` / `plans/otel-export.md` | по треку |
| `multiprocess_framework/docs/observability/CONNECTORS.md` | общий — **только дописывать в свой раздел** |
| `docs/claude/memory/<файл>` | автор файла |
| `MEMORY.md`, `CRAFT.md`, `ARCHIVE.md` | **один владелец за раз**; `merge=union` сюда НЕ ставить — сжатие индекса не append-only, union дал бы обе версии хунков |
| `docs/sessions/*.md` | оба, `merge=union` по `.gitattributes` |

## 4. Дерево и стенд

**Одна пишущая сессия — одно дерево.** Общее дерево принадлежит closure; otel живёт в
`.claude/worktrees/otel`. Venv не заводить: главный `.venv` + `PYTHONPATH=$PWD` из корня worktree.

Довод, измеренный, а не теоретический: pre-commit **на каждом** коммите стешит все незастейдженные
правки tracked-файлов и накладывает обратно (в кэше 1176 патч-файлов, по 77–86 КБ). То есть в общем
дереве чужая работа проходит цикл снятия/наложения при **каждом чьём угодно** коммите — аккуратность
стейджа тут ни при чём. Перед любым `git add` на файл со статусом `M` — `git diff -- <путь>` глазами.

**Стенд `8765` эксклюзивен** (два бэкенда конфликтуют по PID-реестру и SHM-cleanup). По умолчанию
принадлежит closure; окна otel ≤ 10 мин внутри окон closure; коллектор `4318` не эксклюзивен.
Занял — объявил, освободил — объявил.

## 5. Что otel должен знать о поведении, изменившемся в Task 3.3

**`history_query` теперь видит записи с задержкой.** Наблюдено **94–112 мс**, расчётный потолок
≈125 мс (такт дренажа 100 мс + разрешение системного таймера Windows 15.6 мс + транзакция).
Драйвер живёт в другом процессе и чужую очередь дожать не может. Сразу после события ряд может быть
**короче** — это норма, а не дефект наблюдаемости. Названо в `backend_ctl/driver.py`, `AGENTS.md`
и `README.md` модуля.

**Вторая ступень у плоскости otel — внутри SDK.** `BatchProcessor.emit` держит свой `deque(maxlen)`
с той же политикой `drop_oldest` и неблокирующей постановкой, но голосит **WARNING на каждую**
вытесненную запись без окна. Число потерь у 2.4 придёт **из двух источников**; расхождение с
counter'ом предохранителя — не отступление от контракта, а две ступени.

`_export_timeout_millis` в SDK 1.44.0 помечен `# Not used` — дедлайн финального flush держит
вызывающий, отсюда `flush(timeout)` в сигнатуре выше.

## 6. Открытое

- **Правка `scripts/validate.py:211`** (`warnings.append → errors.append` для отсутствующего
  `interfaces.py`) — заявка otel к closure, после Ф1 otel. Посчитано: ровно один сервис без
  `interfaces.py` (`device_hub`), и он вне списка `SERVICES_REQUIRED_INTERFACES` → правка бесплатна.
- **Ручки `batch_size` и `flush_interval_sec`** не выведены в политику (Steps Task 3.3 говорил «из
  политики», ни один критерий приёмки не требовал). Если 2.4 они нужны — заявка к closure.
- **Долги Task 3.3**, которые otel унаследует вместе с классом: оба сторожа гонок держатся на
  искусственно расширенном окне, а не на естественной конкуренции; `weakref.finalize` не покрыт
  тестом; финализатор зовёт `close()` с `join(2.0)` синхронно внутри `config.reload`.


---

## 7. Найдено полосой otel в зоне closure (Task 2.1, 2026-09-07)

Три факта в коде фреймворка. Ни один здесь не чинится — зона closure; записаны,
чтобы не жить в одной голове. Все три воспроизведены запуском, не чтением.

### 7.1 `PluginTestBench` мёртв — им нельзя пользоваться и он этого не говорит

`multiprocess_framework/modules/process_module/plugins/plugin_test_bench.py`
строит контекст вызовом `PluginContext(process_name=..., process=..., ...)`,
которого в сегодняшней сигнатуре `(services, config, io, registers, plugin_name)`
нет. Стенд принимает КЛАСС плагина, и при правильном употреблении падает:

```
класс      -> TypeError: PluginContext.__init__() got an unexpected keyword argument 'process_name'
экземпляр  -> TypeError: 'P' object is not callable
```

Цена молчания: единственный штатный стенд для плагинов не работает, и каждый, кто
пишет тесты плагина, изобретает свой харнесс заново (это уже сделали и слепой
тестер, и реализатор Task 2.1, независимо друг от друга). Отдельно это значит, что
**критерий «тест на настоящем `GenericProcessApp`, не на фейках» сегодня нечем
закрыть** — готового образца сборки живого процесса в дереве нет.

### 7.2 `introspect_plugins` не несёт состояния экземпляра — только каталог

`_cmd_introspect_plugins` (`process_module/commands/builtin_commands.py:869`)
отдаёт `plugins` (name → category), `manifest`, `failed_imports`, `count` — всё из
`PluginRegistry`. Поля состояния конкретного плагина там нет вовсе, а `PluginState`
(`plugins/base.py:70`) знает пять значений (`idle/ready/running/paused/stopped`) и
не знает ни `error`, ни `degraded`.

Для otel это снято переносом критерия на свою команду `otel_export.status`
(правка плана 2026-09-07). Для closure это вопрос, стоит ли вообще выставлять
наружу runtime-состояние плагина — сегодня «плагин жив, но отказал» видно только
по строке `log_error` на буте.

### 7.3 Дверь конфига плагина отказывает БРОСКОМ, а не состоянием

`ProcessModulePlugin._init_register` (`plugins/base.py:1419-1422`) применяет
overrides фрагмента топологии поле за полем через `setattr` при
`validate_assignment=True`. Любое невалидное ЗНАЧЕНИЕ во фрагменте (не отсутствие
ключа — именно значение) даёт `ValidationError` из `configure()`. Оркестратор его
ловит (`plugin_orchestrator.py:175`), процесс поднимается, но плагин остаётся в
`IDLE`: его команд не существует, и причина живёт одной строкой `log_error`.

Замер на `OtelExportRegisters`, пять значений из семи реалистичных:

```
endpoint = ''                  -> ValidationError
level = 'TRACE'                -> ValidationError
headers с литеральным секретом -> ValidationError
max_queue_size = 2             -> ValidationError   (пара с max_export_batch_size=512)
max_queue_size = 0             -> ValidationError
endpoint отсутствует           -> override не применяется, отказ переезжает дальше
endpoint = 'localhost:4318'    -> принят (валидатора схемы URL нет)
```

Ещё одна грань того же: порядок полей берётся из `model_fields`, поэтому
кросс-полевой инвариант (`max_export_batch_size <= max_queue_size`) ломается на
ПРОМЕЖУТОЧНОМ состоянии модели — фрагмент с малой очередью не применится ни при
каком порядке ключей.

Плагин otel обходит это своим `try/except` вокруг `_init_register`; обход
локальный, механизм общий. Родственник — долг Д-1 плана otel
(`plugin_orchestrator._collect_register_schemas` строит регистр без аргументов).
