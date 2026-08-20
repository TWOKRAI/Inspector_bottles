# process_manager_module — Статус рефакторинга

## Текущий этап: 8 / 8 — доработка 2026-04-10 (план #14)

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Runner расслоён; per-process stop events; bundle_contract |
| Тесты (покрытие) | 9 | +bundle_contract, stop_one, monitor heartbeat |
| Документация (README, interfaces) | 9 | DECISIONS.md модуля, CONFIG_CONTRACT (bundle), README |
| Связанность (меньше = лучше) | 6 | Spawner упрощён; контракт bundle в одном месте |
| Дублирование | 8 | build_bundle единая точка сборки dict |
| Работоспособность | 10 | stop одного процесса, restart, liveness в мониторе |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (убран sys.path.insert из process_runner.py)
- [x] Этап 1: SystemLauncher → ProcessSpawner → ProcessManagerProcess запускается (PID проверен)
- [x] Этап 2: ProcessManager создаёт и запускает Process1Module, Process2Module с воркерами
- [x] Этап 3: Коммуникация через Router (ProcessMonitor broadcasts state changes)
- [x] Этап 4: Архитектура стабилизирована (Dict at Boundary, bundle pattern)
- [x] Этап 5: CommandManager подключён (6 встроенных команд: process.list/start/stop/status, system.shutdown/stats)
- [x] Этап 6: Graceful shutdown работает (signal handler без sys.exit, настраиваемые timeout-ы)
- [x] Этап 7: Unit-тесты написаны и проходят (8 файлов)
- [x] Этап 8: README и interfaces.py готовы (ISystemLauncher, IProcessManagerProcess, IProcessRegistry)

## Обновление 2026-08-16 (Task 3.4 плана `telemetry-stage6`, ADR-PMM-028)

- **Адресная runtime-правка телеметрии переживает respawn своего адресата** — разворот прежнего
  «адресные НЕ персистятся»: оно приравнивало область действия правки к сроку её жизни, живое репро
  2026-08-16 показало потерю ключа метрики из gate целиком.
- **Хранение — ЖУРНАЛ правок** (`_telemetry_delta_log`), а не два уровня с приоритетом. Ревью
  воспроизвело, что «узкий уровень поверх широкого» врёт, когда фан-аутная правка идёт ПОСЛЕ
  адресной: у приёмника нет модели слоёв, у него есть только порядок приёма. Ребёнку доигрывается
  его срез журнала в порядке записи. `_telemetry_runtime_delta` остался видом поверх журнала —
  внешние точки и тесты Task 3.2 не правились.
- Свёртка журнала (стирающая запись / смежные merge), tombstone на адресный сброс, забвение записей
  процессов вне топологии, чтение среза на момент отправки.
- Тесты: `tests/test_telemetry_addressed_delta_persist.py` (независимый тестировщик, 7 — приёмка) +
  `tests/test_telemetry_addressed_delta_hazards.py` (28 авторских: эквивалентность на обоих
  call-site'ах × обеих последовательностях — и у ПРАВЛЕНОГО ребёнка, и у его СОСЕДА, — порядок,
  свежесть, свёртка, сброс, трафик). Модуль: **782 без новых файлов → 817** (+35 тестов, регрессий
  нет). Эквивалентность соседа добавлена по слому ревьюера: свёртка без сверки получателя отнимала
  у соседа его фан-аутную правку при 813 зелёных тестах.

## Обновление 2026-04-10 (план process_manager_module)

- **Per-process `stop_event`** в `ProcessRegistry`; `stop_one` / `remove_process`; `restart_process` + команда `process.restart`; конфиги для рестарта в `_process_configs`.
- **ProcessSpawner**: только SRM + `_ProcessLogger`; `stop_event` оркестратора не в bundle — подстановка в `run_process_function` → `process_data.custom`.
- **Runner**: `class_loader`, `bundle_builder`; `core/bundle_contract.py`.
- **ProcessMonitor**: `_check_heartbeats()` + `crashed_processes` в stats.

## Обновление 2026-04-03

- **`ProcessMonitor`**: цикл опроса вызывает `ProcessStateRegistry.get_all_process_data()` и собирает снимок из `ProcessData` (`status`, `metadata`, `custom`). Ранее вызывался несуществующий `get_all_processes()`, из‑за чего в логах оркестратора сыпался `AttributeError`.

## Обновление 2026-03-30 (ADR-102)

- **`process_runner._build_shared_resources_from_bundle`**: после `register_process_state` заполняется `ConfigStore` pickle-safe срезом `{"process", "managers"}` для текущего процесса и пустым срезом для имён из `routing_map`, чтобы `get_process_config` в child был согласован с контуром родителя.

## Что было сделано в рефакторинге (2026-03-13)

### interfaces.py
- Созданы `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry`
- Полные docstrings с примерами

### ProcessManagerProcess
- Извлечён `_create_components()` из `__init__`
- `ConsoleManager` создаётся только если `console_enabled: true` в конфиге
- `QueueRegistry` берётся из `shared_resources` если доступен
- Добавлен `_handle_critical_error()` с интеграцией error_module
- Зарегистрированы 6 встроенных команд через CommandManager
- Graceful `stop_process()`: stop_event → join → terminate → kill

### process_runner.py
- Извлечены вспомогательные функции: `_load_process_class`, `_build_shared_resources_from_bundle`, `_run_lifecycle`
- Создан `_ProcessLogger` — лёгкий логгер с fallback на print
- Удалены диагностические print-ы (queue_id/handle)
- Исправлен импорт `Console_module` → `console_module.ConsoleRedirector`
- Два цикла while объединены в один `_run_lifecycle()`
- Удалён alias `_run_process_function`
- Добавлены `_update_process_state()` и `_log_exception_via_error_manager()`

### spawner.py
- Убран `sys.exit(0)` из `_signal_handler` — wait() возвращается естественно
- Добавлен `ErrorManager` (создаётся в `launch_orchestrator`)
- Настраиваемый `stop_timeout`
- Поддержка `on_shutdown` callback
- Каскад stop: stop_event → join(graceful) → terminate → join → kill

### ProcessRegistry
- `stop_all(timeout)` — timeout настраиваемый (по умолчанию 5s)
- Логирование timeout-а для каждого процесса
- `_join_all` логирует процессы, которые не завершились

### SystemLauncher
- Добавлены `stop_timeout` и `on_shutdown` параметры
- `run()` обёрнут в try/except с error_module
- `_create_spawner()` передаёт настройки в ProcessSpawner

### __init__.py
- Экспортируются: ISystemLauncher, IProcessManagerProcess, IProcessRegistry
- Экспортируются: ProcessRegistry, ProcessPriority, ProcessStatusMonitor, ProcessMonitor, ProcessSchemaAdapter (алиас ProcessStatus → ProcessStatusMonitor удалён 2026-05-02, Tier-1 п.1.3)

## Обновление 2026-08-20 (Ф1 «порта наблюдений», Task 1.4, ADR-PMM-021 доп.)

- **Правило супервизии `drops_growing` было убито переездом плагинных метрик в поддерево
  писателя** (`processes.<P>.state.plugins.<писатель>.drops`): оба кандидата резолвились в
  `None`, `_check_counter_alerts` делал `continue`. Флаг `FW_SUPERVISOR_ALERTS` при этом ON
  по умолчанию, то есть отказ был полностью немым.
- **Путь правила получил подстановочный сегмент** `…state.plugins.*.drops`; разрешает его
  `ProcessMonitor._read_state_counter` (читает поддерево, СУММИРУЕТ одноимённые целые листья
  всех писателей). Имя плагина в фреймворковом правиле не появляется. Плоские кандидаты
  оставлены следом — прямая запись мимо `publish_metric` существует.
- **Регресс-страж переписан:** `test_default_drops_rule_uses_real_published_field` сверял
  СТРОКОВУЮ КОНСТАНТУ и остался зелёным на мёртвом правиле. Взамен —
  `TestDropsRuleAgainstRealTickOutput` (настоящий тик heartbeat → настоящий StateStore →
  настоящий `_check_counter_alerts` → алерт в дереве), плюс
  `tests/test_counter_wildcard_hazards.py` (19 hazard-тестов резолвера: нет поддерева,
  пустое поддерево, нечисловой лист, два писателя, сброс, форма пути).
- **Проверено живым стендом** (`webcam_sketch`, 8 процессов, `BACKEND_CTL=1`) — с одной
  честной оговоркой. Сам `drops` на здоровом стенде спровоцировать НЕЛЬЗЯ: он растёт
  только когда `camera.read()` не вернул кадр (`Plugins/sources/capture/plugin.py`), пауза
  потребителя его не двигает — измерено, `drops` простоял 0 при `frame_count` 766 → 3208.
  Поэтому механизм доказан ВРЕМЕННЫМ правилом на той же форме адреса
  (`processes.{process}.state.plugins.*.frame_count`, счётчик растёт ~21/с):
  `system.alerts.camera_0` получил `severity: warning`, `reason: «счётчик вырос на 109
  (сейчас 524)»`. Пара-контроль в ТОМ ЖЕ снимке: `drops_growing` в алертах отсутствует —
  роста нет. Временное правило и расширенный белый список откачены.
- Названный потолок механизма: ПРИХОД писателя с ненулевым первым значением даёт ложный
  алерт (сумма растёт скачком). С `CapturePlugin` недостижимо — он стартует с нуля; с
  `RingBuffer.drops_count` (величина кумулятивная) достижимо. Лечится базой пер-писателя,
  это отдельная задача — форма `_counter_baseline` общая с плоскими кандидатами.
  Сегодняшнее поведение пришпилено `TestNewWriterArrival`, чтобы починка читалась как
  смена ожидания, а не как регрессия.

## Конфигурация (2026-03-17)

- **ProcessSchemaAdapter** делегирует в `config_to_dict` (data_schema_module) при наличии `build()` — один источник правды
- **CONFIG_CONTRACT.md** — документирован контракт proc_dict (обязательные/опциональные поля, потребители)
- **docs/examples/proc_dict_canonical_examples.py** — эталонные dict и демо нормализации (2026-03-30)

## Известные проблемы

- Нет (все известные проблемы устранены)

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Убран sys.path.insert из process_runner.py, STATUS.md создан | 0 |
| 2026-03-11 | Этап 1: SystemLauncher → ProcessManagerProcess запускается, stop_event работает | 1 |
| 2026-03-11 | Этап 2: дочерние процессы создаются; flush=True в prints; graceful stop в spawner | 2 |
| 2026-03-13 | Этапы 3-8: interfaces.py, error_module, graceful shutdown, CommandManager, тесты, документация | 8 |
| 2026-03-30 | Добавлены docs/examples/proc_dict_canonical_examples.py; ссылка в CONFIG_CONTRACT.md и docs/README.md | 8 |
