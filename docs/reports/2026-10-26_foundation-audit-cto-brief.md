# Бриф для CTO — аудит фундамента framework, шаг 2

Дата: 2026-10-26. Автор: полоса А (`inspector-bottles-1a`). Когда: вместе с приёмкой ProcessManager, строка 6а в [ORDER.md](../../plans/queue/ORDER.md).
Вход — опись: [inventory](2026-10-26_foundation-audit-inventory.md) → [debt](2026-10-26_foundation-audit-inventory-debt.md) (п. 1), [layers](2026-10-26_foundation-audit-inventory-layers.md) (п. 2), [promises](2026-10-26_foundation-audit-inventory-promises.md) (п. 5). Диаграммы: [docs/diagrams/foundation-audit/](../diagrams/foundation-audit/README.md).
Владелец (2026-10-26): «архитектура без костылей и багов, это фундамент». Нужен ответ на каждый вопрос: **до 1.0 / после 1.0 / не дефект**. Ответы «до 1.0» становятся строками очереди (шаг 3).

## Три линзы

1. **Правильность.** Жизненный цикл процессов, остановка, доставка, гонки; нестабильные тесты — дефект кода или теста.
2. **Меньше слоёв.** Принцип владельца: при равной функции меньше уровней косвенности строго лучше. Мёртвый код замораживают (FREEZE), не удаляют.
3. **Наблюдаемость и управляемость через `backend_ctl`.** Каждое состояние, которое нужно оператору или агенту, видно через `backend_ctl` (supervision, телеметрия, счётчики), и каждое действие делается через него, без чтения исходников.

## Вопросы (по убыванию веса; ссылка — на строку описи)

**Правильность**

1. **Четыре счётчика рестарта** (`incarnation` / `instance_restarts` / `restart_count` монитора / `restart_count` воркера). Расходятся в пяти сценариях — [layers L1](2026-10-26_foundation-audit-inventory-layers.md#23-несколько-механизмов-на-одну-задачу). Какой из них оператор видит как «сколько раз рестартовал процесс»? Свести до 1.0 (вопрос из строки 6а) или развести именами?
2. **Два события остановки у ребёнка** (`stop_event` своё и `system_stop_event` общее) и три класса эскалации стопа (`ChildProcessStop`, `_ChildrenGroupStop`, `ProcessSpawner.stop`) — layers D3 и путь 1. Один ли это механизм в трёх обёртках или три?
3. **Нестабильные тесты C-4, C-41, C-49, C-50, C-52** — [inventory §3](2026-10-26_foundation-audit-inventory.md#3-нестабильные-тесты-как-возможные-гонки). По чтению кода четыре из пяти (C-4, C-41, C-50, C-52) — гонка или бюджет в тесте, а не в коде. У C-41 и C-50 в двухсекундный бюджет входит запуск spawn-процесса. C-49 не определён: нет текста падения. Принять «тест, не код» по чтению или требовать дискриминатор (инъекция задержки, тихая машина ×10)?
4. **`ponytail` в коде под флейком C-50** (`reader_gone.py:151`): один poll 20 мс, «под нагрузкой ложная строка вернётся». Это принятый потолок или дефект до 1.0?
5. **53 проглоченных исключения в ядре**, из них на путях остановки и IPC: `process_runner.py:221, 236` (`except Exception: pass` в цикле ребёнка), `process_tree_guard.py`, `socket_channel.py`, `frame_shm_middleware.py:280` — [debt 1.5](2026-10-26_foundation-audit-inventory-debt.md). Правило для 1.0: каждый `pass` либо логируется, либо помечен «намеренно» с причиной?

**Меньше слоёв**

6. **17 флагов `FW_*`** — 17 развилок «старый / новый путь», объявлены 2026-07-15…07-26, плана снятия в очереди нет — [debt 1.3](2026-10-26_foundation-audit-inventory-debt.md). Какие флаги до 1.0 закрыть удалением старого пути (принцип «флаг закрыт, когда удалён»), а какие остаются осознанными ручками (например `FW_PERF_PROBES`)?
7. **Цепочки-пересыльщики на трёх главных путях**: стоп ребёнка — 8 звеньев, 3 из них только пересылают; сообщение — 9 и 4; лог — 9 и 4 — [layers 2.1–2.2](2026-10-26_foundation-audit-inventory-layers.md). Какие звенья снимаются без потери функции? Кандидаты: `ProcessCommunication.send_message` («алиас»), `ProcessRegistry.stop_many`, `LoggerManager` поверх `LoggerCore`, `SystemLauncher.shutdown`.
8. **Три способа достать данные процесса из SRM** плюс `__getattr__`; свойства помечены `Deprecated`, но вне тестов у них 20 и 28 вызовов — layers D4. До 1.0 оставить один?
9. **Шесть функций резолва имени канала** (layers D6) и мёртвая защита `forget_channel` в базе `ChannelRoutingManager` (D5, комментарий `channel_routing_manager.py:708–716`). Нужна одна точка резолва?
10. **Модуль `generic_process.py` помечен `DEPRECATED`, но это базовый класс всех generic-процессов** — [debt 1.4](2026-10-26_foundation-audit-inventory-debt.md). Снять пометку или класс?

**Наблюдаемость и управляемость**

11. **Документ обещает несуществующее**: `subscribers_snapshot()`, ленивый PySide6 в `GuiStateProxy`, члены `MemoryAccessStatus`, `ProcessModule.create_worker`, `ThreadConfig.auto_restart`, барьер `flush()` снятого `BatchBuffer` с тестом-призраком `test_batch_buffer_limits.py` — [promises 5.1](2026-10-26_foundation-audit-inventory-promises.md). Владелец считает: «обещание контракта, пережившее свой механизм, хуже отсутствующего». Сверка `MODULE_CONTRACTS.md` с кодом — до 1.0? Делать её контракт-тестом, как `MODULE_TIERS.md`?
12. **Обещания без теста на путях конкурентности**: `WorkerPoolDispatcher` (выброс старого, таймаут, потокобезопасность) — ни одного теста поведения; изоляция стопа одного процесса (PM1); потокобезопасность `WorkerManager` и роутера — [promises 5.2](2026-10-26_foundation-audit-inventory-promises.md). Какие из них — блокер 1.0?
13. **Модульность 3923 из 10000** — узкое место sentrux при нуле циклов и чистом DSM. Из 2 397 рёбер импорта 2 158 идут между модулями. Сколько из них ходит в обход `interfaces.py` — в [docs/maps/framework-core.md](../maps/framework-core.md). Это цель до 1.0 или метрика без порога?
14. **Видны ли через `backend_ctl` все четыре счётчика рестарта и оба события стопа?** Проверить на стенде: что `supervision_status` показывает при ручном рестарте, при краш-рестарте монитора и при рестарте группы (rest_for_one), и совпадает ли это с расхождениями из вопроса 1.
15. **Карта архитектуры как часть фундамента.** Последняя схема связей модулей — [modules-overview.mmd](../diagrams/modules-overview.mmd) от 2026-05-14. Кандидат в очередь: модель C4-как-код (LikeC4) со сторожем «модель = импорты» и тегами контуров (IPC, жизненный цикл, обработка, наблюдаемость). Сырьё — `docs/maps/framework-core.md`. До 1.0 или после?

16. **Один вход в топологию.** По решению владельца от 2026-10-13 публичный вход — только `recipe.activate`, а `topology.apply` внутренний (FREEZE). GUI прототипа зовёт `proxy.apply_topology(blueprint)` напрямую (`runtime_control.py:143, 227`) — [карта, уровень 2](../maps/framework-core.md). Это второй путь в обход PM-координатора или разрешённый внутренний вызов?

## Шаг 1б: Services, backend_ctl, библиотеки

Опись: [Services](2026-10-26_foundation-audit-1b-services.md), [backend_ctl и библиотеки](2026-10-26_foundation-audit-1b-backend-ctl-libs.md). Схема процессов — `system-containers.mmd` в [docs/diagrams/foundation-audit/](../diagrams/foundation-audit/README.md).

17. **Управляемость через `backend_ctl` — главный вопрос третьей линзы.** Из 102 команд framework у 32 есть свой инструмент. 70 доступны только через `send_command`, а в режиме read-only он закрыт. Не видны: оба события остановки, значения и источники 17 флагов `FW_*`, активный рецепт. Нет инструментов `recipe.*`, `topology.*`, `process.start/stop`, `wire.*`, `worker.*`. Что из этого обязательно до 1.0? Читатель флагов и активного рецепта — первые кандидаты: принцип владельца №6 ведёт смену рецепта через PM, а агент не может её ни вызвать отдельным инструментом, ни увидеть.
18. **Робот v1 и v2 и имена команд GUI.** GUI шлёт `robot_send_test_job`, `robot_set_mode`, `robot_jog`, `robot_set_servo`, `robot_draw_*`, а в `OPS` драйвера v2 этих операций нет. На `letter_robot_sim` (единственный рецепт с `delta_v2`) ожидается «Неизвестная операция» — [Services B1](2026-10-26_foundation-audit-1b-services.md#3-дубли-механизмов). Сверено по таблицам, но не на стенде. Это дефект до 1.0? Какая версия драйвера целевая — v1 «заморожен как запасной» по плану?
19. **Изоляция сбоев в процессе `devices`.** Драйверы робота, ПЧ и нативный SDK Hikvision живут в одном процессе. Сырой `OSError` pymodbus не преобразуется, `is_connected` остаётся `True`. Упавший поток воркера переходит в ERROR без рестарта: `restart_on_failure` не задан. Принцип №5 говорит: «сбой одного не валит соседей». Нужен ли до 1.0 отдельный процесс для нативного SDK или рестарт воркера?
20. **Шесть реализаций переподключения и 12 загрузчиков YAML в Services** при наличии `CircuitBreaker` и `config_module` во framework — [Services B5, B6](2026-10-26_foundation-audit-1b-services.md). Это кандидат «меньше слоёв» после 1.0?
21. **Зависимости.**
    - 9 пакетов объявлены и нигде не импортируются: NodeGraphQt, pandas, plotly, seaborn, pygame, harvesters, environs, QDarkStyle, pydantic-settings.
    - 4 пакета импортируются, но не объявлены: segno, pyarrow, scikit-image, mediapipe.
    - `aiosqlite` из dev-группы нужен в рантайме.
    - Стек расходится с lock: torch 2.13, а не 2.11; Ultralytics и драйвера PostgreSQL нет.

    Чистка `pyproject.toml` до 1.0? Это дёшево, а сам принцип записан в `pyproject` (loguru сняли: «зависимость без потребителя — не безобидный вес»).
22. **Опора на приватные поля CPython** (`q._thread`, `q._buffer`, `q._notempty`, `_sentinel`, `_maxsize`, `shm._name`): на них держатся отпуск очередей при выходе и ёмкость очереди — [backend_ctl и библиотеки 3.2](2026-10-26_foundation-audit-1b-backend-ctl-libs.md). Нужен ли до 1.0 тест-сторож на версию Python?
23. **Заглушки сервисов и дрейф документов.**
    - «TODO Phase 4+» в `service.py` у auth, sql и hikvision_camera.
    - `phone_gateway` «always-on в base.yaml» — не найден.
    - `backend_ctl/STATUS.md`: 47 инструментов вместо 53.
    - `Services/STATUS.md` не описывает 3 из 17 сервисов.

    Сверку документов с кодом — в того же сторожа (вопросы 11, 15)?

## Найдено попутно (воспроизведено запуском, заведено в реестр)

- C-53: `process_module.SystemBlueprint` / `ProcessConfig` / `Wire` — ленивый экспорт (`process_module/__init__.py:118–126`, 2026-07-11) падает с `ModuleNotFoundError`, в относительном импорте лишняя точка.
- C-54: `DataSchemaAdapter.get_data_manager()` всегда `None`: импорт `data_schema_adapter.py:29` указывает на несуществующий пакет, `except ImportError` глотает ошибку.

## Команды для воспроизведения

Все команды из корня репозитория, через гейт:

```bash
G="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"

# границы слоёв (вердикт; MCP check_rules — частичный, не цитировать)
bash "$G" medium <session> sentrux check .

# флейки по одному (light), затем дискриминатор §6 — тихая машина ×10 (heavy, в окне)
bash "$G" light <session> python -m pytest -q --tb=short \
  multiprocess_framework/modules/logger_module/tests/test_retention_sweeper.py::TestPeriodicSweep::test_stale_file_disappears_without_restart
#   (pytest — из multiprocess_framework/modules, там pytest.ini)

# маркеры и флаги
git grep -n -i "ponytail" -- 'multiprocess_framework/modules/*.py' ':!*/tests/*'
git grep -n "default=" -- multiprocess_framework/modules/config_module/feature_flags.py

# счётчики рестарта: где пишутся
git grep -n -E "_bump_incarnation\(|_instance_restarts =|_restart_history\[" -- multiprocess_framework/modules/process_manager_module
git grep -n "restart_count" -- multiprocess_framework/modules/worker_module ':!*tests*'

# дрейф документа: обещанные имена, которых нет в коде
git grep -n -E "subscribers_snapshot|DEFAULT_FLUSH_BARRIER_TIMEOUT|PLATFORM_LIMIT|auto_restart" -- multiprocess_framework ':!*.md'
```

Live-проверка вопроса 14 через `backend_ctl` (бэкенд с `BACKEND_CTL=1`, окно стенда у координатора): `capabilities` → `supervision_status` → `process_restart_verified` на одном ребёнке → `supervision_status`. Сравнить `incarnation`, `instance_restarts` и `restart_count` до и после.

## Чего в описи нет

- Тесты не запускались, гипотезы по флейкам сделаны только чтением.
- Таблица пересыльщиков неполна по state_store, chain, command, message.
- Для флагов `FW_*` не проверено, жив ли старый путь у каждого.
- Полный список — раздел «Что я оставил открытым / ненадёжным» в [описи](2026-10-26_foundation-audit-inventory.md).
