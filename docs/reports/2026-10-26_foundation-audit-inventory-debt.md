# Аудит фундамента — опись, 1. Костыли и отложенное

Часть описи [2026-10-26_foundation-audit-inventory.md](2026-10-26_foundation-audit-inventory.md) (вход, метод съёма и «Что я оставил открытым»). Только факты, вердикт за CTO.

### 1.1 Сводка по ядру (production-код, без `tests/`)

| модуль | файлов / строк | `ponytail:` | TODO/FIXME/HACK/XXX | проглоченные except¹ | `time.sleep` в коде | слова второго пути² | чтения env |
|---|---|---|---|---|---|---|---|
| process_manager_module | 37 / 13 394 | 2 | 0 | 10 | 11 | 130 | 6 |
| process_module | 81 / 33 617 | 2 | 0 | 6 | 9 | 231 | 6 |
| router_module | 24 / 6 821 | 2 | 0 | 13 | 3 | 74 | 1 |
| channel_routing_module | 24 / 6 034 | 0 | 0 | 1 | 0 | 25 | 1 |
| shared_resources_module | 56 / 6 515 | 2 | 0 | 13 | 3 | 31 | 0 |
| state_store_module | 35 / 7 585 | 0 | 0 | 1 | 0 | 38 | 0 |
| chain_module | 20 / 2 002 | 0 | 0 | 0 | 1 | 2 | 0 |
| worker_module | 19 / 2 884 | 0 | 0 | 0 | 3 | 1 | 0 |
| command_module | 9 / 1 085 | 0 | 0 | 1 | 0 | 2 | 0 |
| message_module | 25 / 2 150 | 0 | 0 | 5 | 0 | 7 | 0 |
| logger_module | 24 / 8 324 | 0 | 0 | 3 | 0 | 60 | 2 |
| **ядро, итого** | 354 / 90 411 | **8** | **0** | **53** | **30** | **601** | **16** |
| остальные 16 модулей + верх `modules/` | — | 4 | 23³ | 61 | 3 | 401 | 13 |

¹ Тело `except …:` — одна строка `pass` / `continue` / `return None`; многострочная регулярка. Однострочные формы и тела с логом не считались, так что это нижняя оценка.
² legacy|fallback|temporar|временн|workaround|обход|костыл|deprecated|compat в коде и комментариях. Большинство совпадений — комментарии и имена параметров (`fallback=`). Это счёт строк, а не классификация.
³ 22 из 23 — шаблон виджета `frontend_module/widgets/_template/`, ещё 1 — `app_header/widget.py:147` («Сброс аварии (TODO)»).

Размер в ядре: самые большие файлы — `process_manager_process.py` (4 470 строк), `builtin_commands.py` (4 220), `observability_reload.py` (2 350), `router_manager.py` (2 244), `logger_core.py` (2 184).

### 1.2 Маркеры `ponytail:` — осознанные упрощения с потолком (12 во framework)

| файл:строка | что упрощено, потолок | дата · коммит | в очереди |
|---|---|---|---|
| process_manager_module/runner/process_runner.py:137 | сторож смерти родителя: родитель жив, но не прямой (будущий start method) | 2026-09-25 · 2951a57de | — |
| process_manager_module/runner/process_runner.py:163 | Windows: no-op, `getppid` не меняется при смерти родителя | 2026-09-25 · 2951a57de | — |
| process_module/commands/builtin_commands.py:1377 | ёмкость `multiprocessing.Queue` читается из CPython-приватного поля | 2026-09-30 · 6601abd2b | — |
| process_module/heartbeat/telemetry.py:442 | предела нет: потолок «писатели × их имена» | 2026-08-20 · d7b82f8c5 | — |
| router_module/channels/socket_channel.py:33 | потолок 8 одновременных `on_inbound` на соединение | 2026-09-24 · 44bbbb60e | — |
| router_module/middleware/frame_shm_middleware.py:391 | счётчик не включён в `get_shm_stats`, набор ключей закреплён | 2026-09-29 · 081127d43 | — |
| shared_resources_module/memory/platform/shm.py:236 | имя SHM длиннее 17 символов усекается до `base[:17]` | 2026-10-01 · 4b773d416 | — |
| **shared_resources_module/queues/core/reader_gone.py:151** | **один poll 20 мс: «если под нагрузкой feeder не успеет дойти до sentinel, ложная строка вернётся»** — код под тестом C-50 | 2026-09-24 · aa1268d0b | — (C-50 его не называет) |
| data_schema_module/core/schema_mixin.py:300 | правка двух связанных полей одним вызовом зависит от порядка ключей | 2026-10-02 · c4dc0bc | — |
| recipe/yaml_io.py:100 | chmod после `os.replace`: окно, когда файл виден с 0600 | 2026-09-27 · 957ee7e | — |
| recipe/yaml_io.py:106 | жёсткая ссылка атомарной заменой | 2026-09-27 · 99d22fb | — |
| statistics_module/core/stats_manager.py:1018 | гейт плоскости в шве сбора, ранний выход в фасаде | 2026-09-01 · fa0b249 | — |

Три маркера записаны не в форме `# ponytail:`: `telemetry.py:442` (`#:`), `frame_shm_middleware.py:391` (внутри строки), `shm.py:236` (docstring). `grep -rnE '(#|//) ?ponytail:'` из скилла ponytail-debt их не находит.

### 1.3 Флаги-переключатели `FW_*`: два пути в коде, выбор через env

Все объявлены в одном месте: `config_module/feature_flags.py`. Приоритет: аргумент конструктора > env > default. По docstring модуля (:8–9) «на нём держится откат dark-launch бит-в-бит»: каждый флаг держит в коде и старый, и новый путь. Ни один флаг не упомянут в `plans/queue/defects.md` и `ORDER.md`, плана снятия флагов в очереди нет. Упоминания есть только в памяти: `docs/claude/memory/`, в том числе `_archive/project_feature_flags_registry.md`.

| флаг | default | что включает | объявлен · коммит |
|---|---|---|---|
| FW_SHM_LOAN_PROTOCOL | off | loan/release слотов SHM (refcount), помечен FROZEN (Task 4.7) | 2026-07-15 · 23c8d68 |
| FW_SHM_PREFIX_CLEANUP | off | стартовая очистка осиротевших SHM | 2026-07-15 · 23c8d68 |
| FW_QOS_PROFILES | off | QoS-профили, кольца RingBuffer на камеру | 2026-07-15 · 23c8d68 |
| FW_DATA_PLANE_DICTS | off | dict вместо Message/Pydantic на data-plane | 2026-07-15 · 23c8d68 |
| FW_PERF_PROBES | off | перф-пробы цикла (p50/p99, FPS) | 2026-07-15 · 23c8d68 |
| FW_GC_FREEZE | off | `gc.freeze()` после старта | 2026-07-15 · 23c8d68 |
| FW_GC_SCHEDULED | off | GC по расписанию (требует FW_GC_FREEZE) | 2026-07-15 · 23c8d68 |
| FW_USE_KIND_CHANNELS | off | kind-каналы доставки. Алиас env `MULTIPROCESS_USE_KIND_CHANNELS` перекрывает конфиг (`router_manager.py:2093`) | 2026-07-15 · 23c8d68 |
| FW_CONTRACTS_STRICT | off | строгая валидация контрактов (extra=forbid) | 2026-07-15 · 23c8d68 |
| FW_PORT_VALIDATE | off | проверка портов плагина при сборке цепочки | 2026-07-15 · 23c8d68 |
| FW_HEALTH_RESTART | off | рестарт по деградации health | 2026-07-15 · 23c8d68 |
| FW_AUTORESTART | on | авто-рестарт детей; `=0` — откат | 2026-07-15 · 23c8d68 |
| FW_DEPENDS_ON_BOOT_ORDER | on | порядок старта по `depends_on` | 2026-07-25 · 8f926d8 |
| FW_ROUTING_REFRESH | on | refresh routing-epoch при смене топологии | 2026-07-15 · 23c8d68 |
| FW_FENCE | on | fencing-токены сообщений; `=0` — откат (`builtin_commands.py:4127`) | 2026-07-15 · 23c8d68 |
| FW_STATE_TOPOLOGY_GATE | on | гейт поздних `state.set` от старой топологии | 2026-07-21 · b1a6ef3 |
| FW_SUPERVISOR_ALERTS | on | алерты поверх событий супервизора | 2026-07-26 · 4083cea |

Чем опасно: 17 флагов — это до 17 развилок «старый / новый путь» в рантайме. Есть или нет старый путь у каждого флага, по потребителям не проверялось: классификация взята из docstring. Здесь действует принцип владельца «флаг закрыт, когда удалён» (`docs/claude/memory/feedback_flags_must_not_become_crutches.md`).

Другие env-переключатели и алиасы в ядре:

| файл:строка | переменная | что делает | дата | очередь |
|---|---|---|---|---|
| process_module/health/state.py:56–57 | `MULTIPROCESS_HEALTH_LOG_ONLY` (+ алиас `INSPECTOR_…`) | откат health в режим «только лог» | 2026-08-10 · 2942c949c | — |
| logger_module/core/log_paths.py:22 | `MULTIPROCESS_LOG_DIR`, алиас `INSPECTOR_LOG_DIR` | каталог логов | 2026-04-30 · 2e829a5b6 | C-14 |
| logger_module/core/logger_core.py:2134 | `MULTIPROCESS_FRAME_TRACE`, алиас `INSPECTOR_FRAME_TRACE` | вкл/выкл frame-trace | 2026-08-10 · 2942c949c | — |
| router_module/core/router_manager.py:2093 | `MULTIPROCESS_USE_KIND_CHANNELS` | перекрывает конфиг kind-каналов | 2026-07-14 · 40d315b75 | — |

### 1.4 Вторые пути, legacy, fallback (код, не комментарии)

| файл:строка | что делает | дата · коммит | очередь |
|---|---|---|---|
| modules/_fallback.py | `FallbackLogger`: ленивый handle → `std_facade`; `emergency_log` пишет в stdlib мимо менеджера, внутри `except Exception: pass` (:68–69). 18 прямых импортёров вне тестов, один в `Services/documents/wiring.py:23`. Ещё 9 — через реэкспорт `logger_module/utils.py` | создан 2026-05-01 · b136863d5, правка 2026-07-28 · 489d084e1 | — |
| logger_module/core/logger_core.py:484, 519, 528, 647, 905, 1755, 1798, 2182 | `_fallback_log`: второй канал вывода при сбое инициализации, shutdown, свипа, процессора, пола, frame-trace | 2026-07-09…08-05 | — |
| logger_module/adapters/std_facade.py:321, 450 | stdlib-логгер для режима «LoggerManager не поднят» | 2026-07-26 · dc2420a12 | — |
| process_manager_module/launcher/pid_registry.py:62 | второй (legacy) путь PID-файла | 2026-08-10 · 2942c949c | — |
| process_manager_module/launcher/process_tree_guard.py:88 | «примитив ОС не сработал → portable psutil-обход» | 2026-06-04 · de2ee9c19 | — |
| process_manager_module/topology/blueprint.py:231 | `_accept_legacy_collector_key`: приём старого ключа `inspector` | 2026-08-10 · 2942c949c | (C-16 — тот же файл, другая тема) |
| process_module/configs/observation_policy.py:25 | `SOURCE_LEGACY`: легаси-секция `telemetry.publish` переводится в правила | 2026-09-02 · 88dc5b85c | — |
| process_module/generic/generic_process.py:3 | модуль помечен `DEPRECATED: используйте ProcessModule напрямую`; при этом это базовый класс generic-процессов (`GenericProcess(ProcessModule)`, :53) | 2026-05-08 · 5c6a0832b | — |
| router_module/middleware/frame_shm_middleware.py:716 | `_note_pickle_fallback`: кадр уходит pickle, если запись в SHM не удалась | 2026-07-14 · 53cabd5df | (L-6 — тема) |
| chain_module/core/dag.py:143 | ветка legacy-интерфейса `execute(frame, context)` | 2026-05-01 · 75ce34d6b | — |
| message_module/core/message.py:77, 209 | поле `args` (legacy, payload ушёл в `data`), `set_command` deprecated | 2026-07-14 · 5684d4f5b | — |
| message_module/addressing/address.py:15, 66 | обратная совместимость: плоское имя `"proc"` = `["proc"]` | 2026-05-31 · 4e22426e2 | (C-25 — тот же файл) |
| shared_resources_module/core/shared_resources_manager.py:370–393 | свойства `process_state_registry` / `queue_registry` / `config_store` / … помечены `Deprecated`. Вызовы: `.process_state_registry` — 97 всего, 20 вне тестов; `.queue_registry` — 77 / 28 (подстрочный счёт) | 2026-04-30 | — |
| process_module/core/process_module.py (~1210) | блок «МЕТОДЫ ДЕЛЕГИРОВАНИЯ (для совместимости со старым API)» | — | — |
| frontend_module/components/common/legacy_sync.py:15, base/traits/legacy_sync_trait.py | `DeprecationWarning` при импорте; `LegacySyncTrait` в проде не создаётся, только реэкспорт | 2026-04-30 | — |

### 1.5 Проглоченные ошибки на путях остановки и IPC (выборка)

| файл:строка | что глотает | дата · коммит |
|---|---|---|
| process_manager_module/runner/process_runner.py:221, 236 | `except Exception: pass` в `_run_lifecycle` | 2026-04-30 · 2e829a5b6 |
| process_manager_module/launcher/process_tree_guard.py:297, 324, 330 | `NoSuchProcess, AccessDenied: pass` при обходе и kill дерева | 2026-06-04 / 09-24 |
| router_module/channels/socket_channel.py:180, 553; socket_client.py:272 | `OSError: pass` | 2026-06-01…09-25 |
| router_module/middleware/frame_shm_middleware.py:280 | `except Exception: pass` | 2026-09-29 · dd1491e37 |
| state_store_module/proxy/state_proxy.py:756 | `ValueError: pass` | 2026-07-09 · 3bf97b4ba |
| message_module/factories/message_factory.py:51, 58 | разбор JSON, затем YAML; второй `except Exception: pass` | 2026-04-30 |
| message_module/core/message.py:133, 301, 399 | `ValueError: pass / return None` при defaults, exclude, `get_type()` | 2026-04-30 |
| command_module/adapters/command_adapter.py:102 | `except Exception: pass` вокруг `get_stats()` | 2026-04-30 |
| logger_module/core/error_floor.py:145 | `OSError: pass` при ротации пола (fail-open, `nosec B110`) | 2026-07-27 · 1fd8d2dc3 |

### 1.6 Паузы и опрос вместо события (ядро, выборка)

| файл:строка | что | дата |
|---|---|---|
| process_manager_module/runner/process_runner.py:201 | цикл ребёнка: `time.sleep(0.1)` между проверками двух событий стопа и `should_stop()` | 2026-07-27 · edb674a90 |
| shared_resources_module/queues/core/reader_gone.py:153 | `time.sleep(0.02)` до первой проверки feeder (см. ponytail :151) | 2026-09-24 |
| chain_module/thread_pool/worker_pool_executor.py:201 | drain: `while not queue.empty(): sleep(_DRAIN_POLL_SEC)`, дедлайна в теле цикла нет (вызывающий не проверен) | 2026-07-13 · c1b5d8208 |
| worker_module/core/worker_manager.py:193, 201 | pause: фиксированный `sleep` для воркера без `is_busy`; poll по `is_busy` с дедлайном | 2026-07-14 · c3050f1b7 |
| worker_module/lifecycle/worker_lifecycle.py:244 | `time.sleep(0.1)` перед `_restart_worker_internal` | 2026-04-30 |
| process_manager_module/process/source_producer.py:260 | преролл: `ready.wait(min(0.05, remaining))` — ожидание события срезами | 2026-10-02 · 0bd3fce1f |

Маркеров TODO/FIXME/HACK/XXX в production-коде ядра нет: проверено `rg` по 11 модулям.
