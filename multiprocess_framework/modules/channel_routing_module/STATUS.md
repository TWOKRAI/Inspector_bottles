# channel_routing_module — Статус рефакторинга

## Текущий этап: 9 / 9  ✅

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | CRM + ChannelRegistry + 2 буфера + normalize_config + ChannelRoutingConfig + `observability/` (hub, стор, tap'ы, нормализатор записи) — 3 782 строки |
| Тесты | 9 | 4 279 строк; все проходят |
| Документация | 10 | README полный; `DECISIONS.md` (ADR-CRM-001…014); карта плоскости — [`docs/OBSERVABILITY_MAP.md`](../../docs/OBSERVABILITY_MAP.md) и четыре справочника в [`docs/observability/`](../../docs/observability/CONNECTORS.md) |
| Связанность | 10 | Зависит только от base_manager + dispatch_module + data_schema_module. Нет циклов |
| Работоспособность | 9 | Все наследники мигрированы; 155 тестов зелёные |

**Task 3.3 (2026-09-06):** `observability/batch_drain.py` — `BatchDrainWorker`
(очередь + фоновый дренаж пачкой + `flush(timeout) -> (записано, потеряно)`);
`StoreTapChannel.write()` стала асинхронной (цена у эмитента 91.8 → 1.3 мкс/запись,
темп 678 000 зап/с, медиана трёх соло-прогонов); `close_all_taps()` в обоих путях
останова; у `BoundedChannel` `close()` засчитывает остаток в потери, `get_info()`
снимает все числа под одним локом, `drain()` не копирует буфер под локом.
Каталог `channel_routing_module/observability/tests` внесён в `modules/pytest.ini`.

## Чеклист рефакторинга

- [x] Этап 0: interfaces.py (IChannel, IBufferStrategy, IChannelRoutingManager)
- [x] Этап 1: ChannelRegistry (generic, thread-safe, RLock)
- [x] Этап 2: normalize_config (Dict at Boundary: None | dict | RegisterBase → dict)
- [x] Этап 3: Буферы (DirectBuffer, AsyncSenderBuffer; `BatchBuffer` жил здесь до Ф7.4 и снят — см. ADR-LOG-008)
- [x] Этап 4: ChannelRoutingManager (register_channel, unregister_channel, get_channel, flush, get_stats; `route`/`register_route`/`register_broadcast` жили здесь до Ф4.6 и сняты — ADR-CRM-012)
- [x] Этап 5: ChannelRoutingConfig(RegisterBase) — базовый конфиг, observable_config, dispatcher_strategy
- [x] Этап 6: Тесты (test_channel_registry, test_buffers, test_channel_routing_manager) — 58 тестов
- [x] Этап 7: Миграция LoggerManager (Фаза 2) + ErrorManager (Фаза 3)
- [x] Этап 8: Миграция RouterManager (Фаза 4) + документация (Фаза 5)
- [x] Этап 9 (2026-04-09): `DECISIONS.md`, заполнение `ARCHITECTURE.md` §6.4, удалён shim `buffers/base_buffer.py`

## Иерархия наследников

```
ChannelRoutingManager
    ├── LoggerCore  (синхронная запись, гейт по имени источника, ILogChannel(IChannel))
    │       ├── LoggerManager  (LoggerCore + process-singleton)
    │       └── ErrorManager   (severity_routes данными, один _route())
    ├── StatsManager   (AggregationWindow, IMetricChannel)
    └── RouterManager  (AsyncSender + channel_dispatcher, IMessageChannel(IChannel))
```

`ErrorManager` — **брат** `LoggerManager`, а не его наследник: общий предок `LoggerCore`
(Ф0.6/Ф4.2). Прежняя схема рисовала его потомком логгера и буфер у логгера — обоих больше нет.

## Известные ограничения

- **configs/ vs core:** `ChannelRoutingManagerConfig` (реестр/UI) и `ChannelRoutingConfig` в `core/` (база для наследников CRM) — оба нужны; см. **ADR-CRM-005** (бывш. ADR-108)
- `AsyncSenderBuffer.flush()` — не гарантирует синхронное ожидание; используй `stop()` + `start()`.
- **Буфера у плоскости логов и ошибок нет вовсе** (Ф7.4): запись синхронна. Вместе с `BatchBuffer` ушли `max_pending`, `overflow_policy`, `_in_flight`, барьер `flush`, `urgent_flush_requests`, `flush_timeouts`, `dropped_at_stop` и `flush_contract_violations` — искать их в счётчиках больше не надо.
- Учёт потерь — **пять** классов (`LOSS_COUNTER_KEYS`) плюс счётчик доставки; перечень один на объявление, выдачу и публикацию.
- Tap-приёмники живут ОТДЕЛЬНО от реестра каналов и переживают `reconfigure()`; раздача защищена **поточным** счётчиком глубины (D1) — реентрантный tap не даёт лавину, подавленное считается в `tap_reentrant_suppressed`.
- `_emit_to_taps` возвращает **число реально принявших** запись (было `None`), `has_tap(name)` — читающий вопрос о живой подписке без побочных эффектов (Ф5-добор, ADR-CRM-016). Оба читают/пишут `_tap_sinks` без лока — известный потолок, не новый по отношению к `add_tap`/`remove_tap`.
- `RouterManager` не использует `IBufferStrategy` из CRM — см. ADR-CRM-003.
- `RouterManager` унаследовал `set_sink_enabled`, но **командой не адресуем** (whitelist Ф0.6): иначе message-канал IPC снимался бы одной операторской командой.

## История изменений

| Дата | Изменение | Фаза |
|------|-----------|------|
| 2026-09-05 | **Task 3.1, добор по вердикту CTO: форма числа переехала В базу.** `observability/number_record.py` — `NumberRecord(SchemaBase)` и ЕДИНСТВЕННАЯ точка чтения трёх диалектов `from_hub_record()`; вместе с ней переехало правило идентичности `number_metric_identity` (было в `record_display`). `hub_record_to_display` теперь берёт имя числа У ФОРМЫ — ветки одиночной `stats` и `observation` свёрнуты в одну, ветка снапшота осталась отдельной (агрегат не одно число). Через форму идёт ИДЕНТИЧНОСТЬ, а не класс записи: `severity`/`extra` остаются за `kind`. Причина переезда — кольцо импортов (воспроизведено): `observability/__init__ → observability_store → record_display → statistics_module/__init__ → log_stats_channel → store_tap → observability_store`. Цена замерена: лог −0.03 мкс (шум, бюджет Task 3.3 не тронут), числа +2.7 мкс на запись при темпе 0.82 записи/с, ветка снапшота сама стоит 4.2–4.3 мкс. **ADR-CRM-017** (отменяет `OBSERVATION_LEVEL_SEVERITY = "level"` из `statistics_module/DECISIONS.md`). | Ф3 |
| 2026-03-12 | Фаза 1: создан channel_routing_module (interfaces, CRM, buffers, тесты, README) | 1 |
| 2026-03-12 | Фаза 2: ChannelRoutingConfig, observable_config, dispatcher_strategy в CRM | 2 |
| 2026-03-12 | Фаза 2: ILogChannel(IChannel), LogChannel(ILogChannel), LoggerManager мигрирован | 2 |
| 2026-03-12 | Фаза 3: ErrorManagerConfig(ChannelRoutingConfig), _level_to_channel, log() override | 3 |
| 2026-03-12 | Фаза 4: IMessageChannel(IChannel), RouterManager мигрирован | 4 |
| 2026-03-12 | Фаза 5: README полный, DECISIONS.md ADR-013..016, STATUS.md всех модулей | 5 |
| 2026-03-31 | ADR-108: убран дублирующий `build()` у `ChannelRoutingConfig`; зафиксированы две роли схем | — |
| 2026-04-09 | Фаза 0.5 документации: локальный `DECISIONS.md`, §6.4, строка в главном `DECISIONS.md`; удалён `base_buffer.py` | 9 |
| 2026-07-09 | Ф5.15: `observability/` — ObservabilityHub + BoundedChannel + Protocol-контракты (drop-in ObservableMixin, pull-drain, drop_oldest + счётчик потерь, две плоскости фасада); 26 contract-тестов; ADR-CRM-007 | Ф5.15 |
| 2026-07-26 | **Ф0.3:** потолок `BatchBuffer` (`max_pending` + `overflow_policy`), учёт потерь `dropped`/`flush_failed` по каналам, `_in_flight` (один сбрасывающий поток на канал), контракт `flush_fn → int` («записано», а не «отдано»), `urgent_flushes` → `urgent_flush_requests`. Счётчики выходят наружу командой `introspect.observability`. **Редакция 2 по ревью Opus:** первая редакция применяла потолок безусловно — на дефолтах он не срабатывал никогда, а при `max_pending < max_size` ронял записи на здоровом стоке; реальный безлимитный рост был в пачках «в полёте» | Ф0.3 |
| 2026-07-26 | **Ф0.3, редакция 3 (вторая итерация ревью):** механизм `_in_flight` сам принёс два дефекта того же класса. (1) Флаг снимался вне `finally`, а `except Exception` не ловит `KeyboardInterrupt` — один Ctrl+C внутри `ch.write` запирал канал НАВСЕГДА, причём книги при этом сходились (фантомные записи вечно в `in_flight_records`). (2) `flush()` перестал быть барьером: `stop()` возвращался мгновенно, оставляя хвост в `pending` без счётчика, а сброс порядка «контекст раньше ошибки» (Ф0.9) молча становился no-op на занятом канале. Исправлено: учёт в `finally`, `Exception` глушится / `BaseException` пробрасывается, барьер через `Condition` с таймаутом (`flush_timeouts`), `stop()` в два прохода + `dropped_at_stop`. Плюс: враньё стока о числе принятых не кламповится (`flush_contract_violations`) | Ф0.3 |
| 2026-07-26 | **Ф0.6 (подъём в базу):** `set_sink_enabled` (generic disable + хук `_recreate_channel` на enable), `add_tap`/`remove_tap`/`_emit_to_taps`, `_fallback_log` — из `LoggerCore` в CRM; копии у логгера **удалены**, не оставлены делегатами. Ранги уровней вынесены в `levels.py` (закрывает резидуал R6: `error_manager` больше не импортирует вглубь `logger_module`, база не зависит от потомка). `add_log_tap` → `add_tap` по 14 файлам. Промежуточный класс НЕ введён (условие плана). **Риск закрыт whitelist'ом:** `RouterManager` унаследовал `set_sink_enabled`, но командой не адресуем — иначе message-канал IPC снимался бы одной командой | Ф0.6 |
| 2026-07-26 | **Ф0.8:** хук `_on_channels_changed()` — база сообщает наследнику, что состав каналов изменился в рантайме; зовётся ТОЛЬКО при фактическом изменении (неудачный toggle не событие). `LoggerCore` вешает на него инвалидацию `_decision_cache` (плюс `enable/disable_module_logging`). Профилактика до симптома: сегодня решение `should_log` от состава каналов не зависит, с Ф2.2 будет | Ф0.8 |
| 2026-08-05 | **Ф7.4:** `BatchBuffer` снят целиком — запись синхронна на всех уровнях (ADR-LOG-008). Вместе с ним ушли `max_pending`/`overflow_policy`/`_in_flight`/барьер `flush` и их счётчики | Ф7.4 |
| 2026-08-05 | **Ф4.6:** key-based `Dispatcher` снят из базы — через него не проходило ни одной продовой записи ни у одного из четырёх наследников (ADR-CRM-012) | Ф4.6 |
| 2026-08-10 | **D1:** раздача в tap'ы защищена **поточным** счётчиком глубины; подавленное считается именем `tap_reentrant_suppressed` (в `LOSS_COUNTER_KEYS` и в публикации). `ChannelRegistry` перестал логировать под своим локом (AB/BA снят структурно) и перестал молчать без разъёмов | D1 |
| 2026-08-10 | **D3:** `ObservabilityStore` мигрирует унаследованные БД на рабочий `auto_vacuum` по `PRAGMA user_version`; rollback-гипотеза ревью снята воспроизведением, условие атомарности названо (ADR-CRM-014) | D3 |
| 2026-08-26 | **Ф5-добор по ревью (блокеры Б1/З3):** `_emit_to_taps` → `int` (число принявших, было `None`); новый публичный `has_tap(name)` — факт живой подписки без разрушения. Оба нужны потребителю в `statistics_module` (различитель живой/мёртвой плоскости чисел порта наблюдений — ADR-SM-015); существующие вызывающие (`LoggerCore`, `StatsManager._do_flush`) звали `_emit_to_taps` как statement и не затронуты. ADR-CRM-016 | Ф5-добор |
| 2026-08-31 | `StoreTapChannel`: дедуп ПУТЕЙ по маркеру `origin=error_manager` — запись, за которой факт уже записан плоскостью ошибок, кладёт в стор только tap самой плоскости (`owns_error_plane`); маркер поднят на верхний уровень строки. Один инцидент = одна строка (было две). Task 1.3a / ADR-PM-045 | obs-closure |
| 2026-08-31 | **Ревью 1.3a:** владельца `owns_error_plane` раздаёт `wire_observability_store` **по тому, кто реально встал**, а не константой по роли — нет error-tap'а, владение берёт логгер-tap. Иначе на процессе без `ErrorManager` маркированную строку не принимал никто (замер: контроль 1 строка, опыт 0). Обоснование возврата `status="success"` на дедупе переписано: прежнее («иначе поднялся бы `tap_write_errors`») **ложно** — раздача tap'ам судит только факт исключения и возврат `write()` не читает (замер: `status="error"` без исключения → `accepted=1, tap_write_errors=0`) | obs-closure |
| 2026-09-05 | **Ф3/3.1 «одна числовая запись; снапшот в стор один раз и структурно».** `StoreTapChannel` пропускает БЕЗУСЛОВНО (любым tap'ом, включая владельца плоскости ошибок) записи с новым маркером `origin=stats_snapshot` — правило ДРУГОЕ, чем у `origin=error_manager` («не берёт ни один tap» против «берёт ровно один»); ответ — `success` с `skipped_origin`. Снята человеческая копия снапшота, ехавшая в стор второй дорогой: замер живого файла — 781 строка/ч и 962 КиБ/ч, **19 % строк и 39 % байтов** стора, причём копия ещё и усечена пределом 2048 Б. В сторе — колонка `metric` (полное имя `capture.drops` у строк, которые ЕСТЬ одно число; NULL у агрегата окна, лога, ошибки), индекс `(metric, ts)`, фильтр `list_records/search(metric=)`, `user_version` 2→3. Засыпка безусловна, гейт на ДАННЫХ (`metric IS NULL` И «имя вычислимо» — второе условие нужно потому, что NULL здесь законный конец, а не «ещё не посчитали»), ступень 3 берётся только со ступени 2 (иначе сборка без FTS5 навсегда лишала бы файл полнотекстового индекса). `severity` у ВСЕХ числовых форм — одно слово `number` (К7): колонка называет КЛАСС записи, `severity_number` остаётся `UNSPECIFIED`; род метрики переехал из неё в `extra.metric_type`. Task 3.1 | obs-closure |
