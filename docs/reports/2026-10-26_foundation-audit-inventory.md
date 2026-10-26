# Аудит фундамента framework — шаг 1: опись

Дата: 2026-10-26. Полоса А, сессия `inspector-bottles-1a`. Строка очереди: 6а в [ORDER.md](../../plans/queue/ORDER.md).
Назначение: вход для CTO (шаг 2, вместе с приёмкой ProcessManager). Здесь только факты: что, где, с какого времени, чем опасно. Оценок «плохо / хорошо» нет, вердикт за CTO.
Бриф для CTO: [2026-10-26_foundation-audit-cto-brief.md](2026-10-26_foundation-audit-cto-brief.md). Диаграммы: [docs/diagrams/foundation-audit/](../diagrams/foundation-audit/README.md). Сырьё для карты архитектуры: [docs/maps/framework-core.md](../maps/framework-core.md).

## Как снято

- Код не правился, тесты не запускались.
- Срез: HEAD двигался во время описи, от `a4ef84850` до `71bfc55fe`: влита Task 1.9b, слияние `4d2a2f522`, затронуто `process_manager_module`. Номера строк `process_manager_process.py` и `process_registry.py` сверены на `71bfc55fe`. В остальных файлах номера могут разойтись на несколько строк.
- Поиск: `git grep` / `rg` по путям. qex не использовался: Ollama не запущена, индекс от 2026-10-18.
- Структура: sentrux (MCP: scan, health, dsm, test_gaps) и CLI `sentrux check .` через `machine_gate.sh medium`. Граф: graphify (`graph.json` от 2026-10-26 19:47).
- Механику выполняли 8 агентов Explore: 7 на Haiku и 1 на Sonnet (пункт 2). Пункт 2 я сверял по коду построчно, пункты 1, 3, 5 — выборочно. Отметка «сверено» в таблицах значит, что строку проверил лид.
- Дата в таблицах — дата последнего коммита, тронувшего строку (`git blame` или `git log -L`). Для всего, что пришло из снимка `2e829a5b6` от 2026-04-30 («clean: fresh start»), реальный возраст неизвестен: история обрезана.
- Охват: 11 модулей ядра подробно (process_manager, process, router, channel_routing, shared_resources, state_store, chain, worker, command, message, logger), остальные 16 и файлы верхнего уровня `modules/` — коротко.

## 1. Костыли и отложенное

Вынесено в [2026-10-26_foundation-audit-inventory-debt.md](2026-10-26_foundation-audit-inventory-debt.md).

## 2. Лишние слои и дубли механизмов

Вынесено в [2026-10-26_foundation-audit-inventory-layers.md](2026-10-26_foundation-audit-inventory-layers.md).

## 3. Нестабильные тесты как возможные гонки

Ни одна гипотеза не проверена прогоном или инъекцией: тесты не запускались по брифу. Гипотезы мои, по фактам из кода.

| id | тест | код под тестом | что ждёт тест и где эффект | гипотеза | где гонка | проверена |
|---|---|---|---|---|---|---|
| C-4 | config_module/tests/test_watcher.py:119–157 `test_reload_on_atomic_replace` | `ConfigFileWatcher`: событие `moved` → `_maybe_reload`, дебаунс 0,05 с, отложенный повтор через `threading.Timer` (watcher.py:98–136, правка 2026-10-08 · 541002d8d) | `before = len(reloads)` снимается ДО паузы 0,3 с (:148–149), затем ждётся рост длины, а не значение; итоговое значение проверяется сразу (:155) | запоздалый reload от предыдущей записи (отложенный таймер или повторное событие) приходит в паузу 0,3 с, длина растёт, цикл для `third` выходит до reload `third` → видим `second` | в тесте (ждёт счёт, а не значение) | нет. Дискриминатор: инъекция задержки в `_delayed_reload` при записи `second` — ожидаем красный стабильно |
| C-41 | process_manager_module/tests/test_graceful_stop_acceptance.py:88–111 | `run_process_function` → `_run_lifecycle` (process_runner.py:177–201): `run()` кладёт маркер | `queue.get(timeout=2.0)` (:100) — бюджет 2 с включает spawn и импорт ребёнка; падение `queue.Empty` наступает до `stop_event.set()`, остановка не измерялась | под нагрузкой spawn + импорт > 2 с | в тесте (бюджет включает запуск процесса) | нет. Связь с C-36 по чтению маловероятна: тест берёт простой `ctx.Queue`, `release_feeders_at_exit` пропускает не-`ReaderGoneQueue` (reader_gone.py:129) |
| C-49 | process_manager_module/tests/test_t54_generic_process_preroll_hazards.py:166–177 | преролл `SourceProducer._wait_preroll` (source_producer.py:237–261, срезы 0,05 с), `_sources_ready_event` (process_runner.py:411) | после `own.wait(10)` пауза 0,3 с «кадров нет», затем `ev.set()` и порог задержки первого кадра ≤ 0,0656 с | какой ассерт упал, не записано. Кандидаты: (а) порог 65,6 мс под CPU 44–80 % — тест; (б) кадр до `set()` — код; (в) `own` не за 10 с | не определено | нет. Сначала нужен текст падения |
| C-50 | shared_resources_module/tests/test_writer_outlives_reader_acceptance.py:254–296 | `send_to_queue` → `put_nowait` (queues/core/manager.py:269–309); `release_feeders_at_exit` (reader_gone.py:96–166) | `start` снимается ДО `writer.start()` (:289), `join(timeout=2.0)`: бюджет 2 с включает spawn писателя | под нагрузкой spawn + импорт > 2 с. Второй кандидат — `ponytail` reader_gone.py:151 (один poll 20 мс), но он влияет на ложную строку потерь, а не на время выхода | в тесте (бюджет включает запуск процесса) | нет. Текст падения не записан |
| C-52 | logger_module/tests/test_retention_sweeper.py:82–97 | `_enforce_retention` (logger_core.py:924–953) → `enforce_log_retention` (log_channel.py:623) → `_remove_file` (:535) | тест ждёт исчезновения файла (`_wait_gone`), затем сразу читает счётчик. Порядок в коде: `os.remove` (log_channel.py:535) → `result["deleted"] += 1` (:695) → `return` (:732) → `stats[...] +=` под `_miss_lock` (logger_core.py:949) | «проверил файл, потом прочёл счётчик»: окно между unlink и инкрементом ничем не закрыто | в тесте | нет, совпадает с гипотезой в defects.md. Дискриминатор там же: задержка перед :948 → ожидаем красный 10/10 |

Общий факт по C-41 и C-50: у обоих в двухсекундный бюджет входит запуск spawn-процесса.

## 4. Структура (sentrux, graphify)

| метрика | значение | источник |
|---|---|---|
| `sentrux check .` (весь репо, 41 правило, через `machine_gate.sh medium`) | все правила прошли, Quality 6931, exit 0 | CLI |
| файлы / строки / рёбра импорта `multiprocess_framework/` | 1 929 / 449 165 / 2 519 | MCP scan |
| quality_signal framework | 7243 | MCP health |
| modularity | 3923 (raw 0,088) — узкое место | MCP health |
| acyclicity | 10000 (циклов 0) | MCP health |
| depth | 8889 | MCP health |
| equality | 6454 | MCP health |
| redundancy | 8854 (raw 0,115) | MCP health |
| рёбра между модулями | 2 158 из 2 397 | MCP health |
| DSM | 1 141 узел, 0 рёбер над диагональю, 7 уровней, propagation cost 28 | MCP dsm |
| test_gaps | 634 из 1 042 исходных файлов без теста (покрытие 39 %); список файлов на free-тарифе не выдаётся | MCP test_gaps |
| graphify | 45 038 узлов, 71 358 рёбер, 2 648 сообществ; EXTRACTED 96 % | graph_stats |
| god nodes framework | SchemaBase 322, PluginContext 257, ProcessModulePlugin 182, `get_std_logger` 158, ProcessManagerProcess 154, ObservableMixin 102, LoggerCore 88, ProcessModule 88, RouterManager 84, BuiltinCommands 83 | god_nodes |

Соотношение строк тестов к коду по ядру:

| модуль | код | тесты |
|---|---|---|
| process_module | 33 617 | 73 288 |
| process_manager_module | 13 394 | 28 168 |
| logger_module | 8 324 | 21 866 |
| router_module | 6 821 | 14 286 |
| state_store_module | 7 585 | 12 111 |
| channel_routing_module | 6 034 | 8 920 |
| shared_resources_module | 6 515 | 7 248 |
| worker_module | 2 884 | 2 797 |
| message_module | 2 150 | 1 943 |
| command_module | 1 085 | 2 025 |
| chain_module | 2 002 | 1 449 |

Важно: MCP `check_rules` на free-тарифе частичный, в вердикте его не цитировать. Вердикт по границам слоёв даёт только CLI выше.

## 5. Покрытие обещаний документации

Вынесено в [2026-10-26_foundation-audit-inventory-promises.md](2026-10-26_foundation-audit-inventory-promises.md).

## 6. Найдено попутно при сборе карты (воспроизведено, в реестре нет)

| файл:строка | факт | проверка | дата |
|---|---|---|---|
| process_module/__init__.py:118, 122, 126 | ленивый экспорт `SystemBlueprint` / `ProcessConfig` / `Wire` через `from ...process_manager_module…` уходит на уровень выше `modules/` | импорт: `ModuleNotFoundError: No module named 'multiprocess_framework.process_manager_module'`; вызывающих по этим именам нет | 2026-07-11 · 4a1d0a722 |
| shared_resources_module/adapters/data_schema_adapter.py:29–31 | `from ....data_schema_module.storage.storage_manager import StorageManager` → несуществующий `multiprocess_framework.data_schema_module`; `except ImportError: return None` | импорт цели: `ModuleNotFoundError`; значит `get_data_manager()` всегда `None` (модуль лежит в `modules/data_schema_module/storage/`) | ≤ 2026-04-30 |
| router_module/interfaces.py:16 | `from ...message_module import Message` под `TYPE_CHECKING` — тот же лишний уровень | в рантайме не исполняется | — |

Строки реестра заводит координатор. Карта модулей, интерфейсов и рёбер (ast) — [docs/maps/framework-core.md](../maps/framework-core.md).

## Что я оставил открытым / ненадёжным

- Таблица форвардеров (2.1) неполна по state_store, chain, command, message. F3, F15, F18 сверены по отчёту агента, не по коду.
- Сторона приёма в пути 2 и дрейн логов ребёнок → PM в пути 3 не прослежены. «Отдельного писателя логов нет» — непроверенное предположение агента.
- D6 (шесть функций резолва канала) и D8 (таймеры): пересечение по назначению не выяснялось, только перечень.
- Для флагов `FW_*` не проверено, жив ли у каждого старый путь в коде. Классификация по docstring.
- Счёт проглоченных исключений — нижняя оценка: однострочные `except X: pass` и тела с логированием не считались. Тела 53 сайтов ядра не читались, часть может быть в cleanup-пути, где это нормально.
- Пункт 3: все пять гипотез сделаны чтением, ни одна не проверена прогоном. Для C-49 и C-50 в реестре нет текста упавшего ассерта, без него гипотезу не сузить.
- Пункт 5: по логгеру 8 обещаний не проверено, по router / process / shared_resources / state_store ещё 6. «Код + тест» по многим строкам ставился по имени теста и выборочному чтению ассертов. Тесты в `Services/` и `Plugins/` не искались.
- Счёт вызывающих (2.1) подстрочный, это верхняя граница.
- Даты по `git log -L` — последний коммит, тронувший строку, а не построчный blame. Для снимка 2026-04-30 реальный возраст неизвестен.
- test_gaps на free-тарифе не даёт список непокрытых файлов, только число.
- HEAD сдвинулся во время описи (слияние 1.9b). Строки PM сверены на `71bfc55fe`, строки других модулей могут отличаться на несколько.
