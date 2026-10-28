# Аудит фундамента — опись, 5. Покрытие обещаний документации

Часть описи [2026-10-26_foundation-audit-inventory.md](2026-10-26_foundation-audit-inventory.md) (вход, метод съёма и «Что я оставил открытым»). Только факты, вердикт за CTO.

Источники: `multiprocess_framework/docs/MODULE_CONTRACTS.md` (последний коммит 2026-10-13, в шапке «Обновлено 2026-07-12»), `MODULES_RESPONSIBILITY_MAP.md` (2026-10-21), README модулей ядра. По модулю выбрано 9–14 проверяемых обещаний. «Код + тест» ставился только там, где агент прочитал ассерт на эффект.

| модуль | код + тест | только код | ни кода, ни теста | не проверено |
|---|---|---|---|---|
| channel_routing | 3 | 4 | 3 | 0 |
| router | 5 | 3 | 0 | 2 |
| process | 4 | 3 | 1 | 1 |
| process_manager | 5 | 4 | 0 | 0 |
| shared_resources | 2 | 4 | 2 | 2 |
| state_store | 4 | 4 | 2 | 1 |
| chain | 4 | 8 | 0 | 0 |
| worker | 10 | 4 | 0 | 0 |
| command | 9 | 1 | 0 | 0 |
| message | 11 | 2 | 0 | 0 |
| logger | 6 | 0 | 0 | 8 |

Счёт уже исправлен по моей сверке, в отчётах агентов он другой: PM10 перенесён из «ни того ни другого» в «код + тест», SS4 — в «только код», ложная строка логгера L1 снята (см. ниже).

### 5.1 Документ обещает то, чего в коде нет (дрейф документа; сверено лидом)

| # | обещание | источник | факт в коде |
|---|---|---|---|
| SS5 | `SubscriptionManager.subscribers_snapshot()` / `subscriptions_for()` | MODULE_CONTRACTS.md:304 | методов нет нигде в `modules/` |
| SS9 | `GuiStateProxy` импортирует PySide6 лениво | MODULE_CONTRACTS.md:300, 317 | импорта PySide6 в коде state_store нет совсем, есть только в DECISIONS.md:149–153 |
| SR3 | `MemoryAccessStatus = OK / NOT_FOUND / PERMISSION / PLATFORM_LIMIT` | MODULE_CONTRACTS.md:252 | в `types/types.py:40–50` другие члены: OK, NO_DATA, INVALID_INDEX, INDEX_OUT_OF_RANGE, HANDLE_MISSING, EXCEEDS_MAX_IMAGES, PARAM_MISSING |
| SR4 | `ConfigStore` = dict (не Pydantic) | MODULE_CONTRACTS.md:259 | `class ConfigStore(IConfigStore)` (config_store.py:17) |
| PC6 | `ProcessModule.create_worker(name, fn, config, auto_start=False)` | MODULE_CONTRACTS.md:495 | у `ProcessModule` метода нет; есть у `WorkerManager` (worker_manager.py:75), `WorkerAdapter` и протокола плагина (plugins/interfaces.py:35) |
| W4 | `ThreadConfig.auto_restart: bool` | MODULE_CONTRACTS.md:432 | поле называется `restart_on_failure` (thread_config.py:54) |
| CR4 | буферы Direct / Batch / AsyncSender | MODULE_CONTRACTS.md:98 | `BatchBuffer` снят (channel_routing_manager.py:712) |
| CR7, CR8 | `flush()` — барьер с `DEFAULT_FLUSH_BARRIER_TIMEOUT`, счётчики `flush_timeouts`, `flush_contract_violations`; «инвариант проверяется тестом `test_batch_buffer_limits.py`» | channel_routing README.md:154–158 (последний коммит README 2026-09-06) | имён нет в коде framework; файла `test_batch_buffer_limits.py` в репо нет — README описывает снятый `BatchBuffer` |
| RT1 | `RouterManager.register_middleware` | MODULE_CONTRACTS.md:140 | метода нет, есть `add_receive_middleware` |

### 5.2 Код есть, теста на обещание нет (выборка)

| # | обещание | код |
|---|---|---|
| C1–C3 | `WorkerPoolDispatcher`: при переполнении выбрасывается самое старое; ответ `timeout`; потокобезопасность (chain README.md:28) | dispatcher.py:215–234, 151–165, 75. Тестов поведения нет: класс упомянут только в двух hazard-файлах как строка списка (base_manager/tests/test_base_manager_template_hazards.py:424, modules/tests/test_manager_shutdown_1_2b_2_acceptance.py:52) |
| C9 | шаги через процессы (`IRemoteExecutable`) во всех трёх исполнителях | тест только у parallel; у chain и dag тестов нет |
| W1 | все публичные методы WorkerManager потокобезопасны | нет теста на конкурентный доступ |
| W4b | auto-restart воркера останавливается после `max_restarts` | тесты проверяют только сам перезапуск, а не остановку после лимита |
| W9 | `KeyedExecutor.request_stop` идемпотентен | нет теста |
| CR2, CR10 | замена и удаление канала атомарны и потокобезопасны | тесты проверяют эффект, а не конкурентность |
| RT6 | `_stats` роутера потокобезопасен | нет теста на конкурентность |
| PM1 | остановка одного процесса не трогает другие (свой stop_event) | изоляция не проверена тестом |
| SR7 | `released_to_gone_readers` / `buffered_dropped_at_exit` в `get_stats` | тест ассертит кортеж `release_feeders_at_exit`, а не `get_stats` |
| MS8 | `request_id` обязателен для REQUEST/RESPONSE | тесты проверяют только успешный путь |
| M8 | исполнитель команды фиксируется при регистрации | нет теста |

### 5.3 Ложные находки агентов, снятые при сверке

- **L1 (логгер):** «в интерфейсе остались поля батчинга». Неверно: `logger_module/interfaces.py:219` прямо пишет, что полей `batching_enabled` / `messages_batched` / `batch_stats` больше нет. `logger_core.py:1598` — комментарий об истории.
- **PM10:** «встроенных команд `process.start/stop/…` в коде нет». Неверно: `process_manager_process.py:543`.
- **SS4:** «дедупликации в DeltaDispatcher нет». Она есть: группировка по подписчику через множество индексов (`delta_dispatcher.py:127–150`). Теста на неё агент не нашёл.
