# Невидимые отказы становятся видимыми

> Фаза Ф1 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф1 — Невидимые отказы становятся видимыми

### Task 1.1 — `install_process_hooks`: исключения потоков и `warnings` в плоскость ошибок (C3)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** любое необработанное исключение в любом потоке процесса и любой `warnings.warn` оставляют след в плоскости ошибок/логов с адресом потока и трассой; хук — один на процесс, ставится фреймворком.
**Files:** новый `multiprocess_framework/modules/logger_module/core/process_hooks.py`, `process_module/core/process_module.py`
(точка после подъёма `LoggerManager`), `process_module/lifecycle/*` (снятие при останове), `error_module/core/error_manager.py`
(маршрут `thread_exception`), `channel_routing_module/core/channel_routing_manager.py:46` (`LOSS_COUNTER_KEYS` — новые счётчики).
**Steps:**
1. `install_process_hooks(services)`: `threading.excepthook`, `sys.excepthook`, `logging.captureWarnings(True)`; каждый хук — тонкий: собирает `(thread_name, exc, tb)` и зовёт `services.report_error(..., context=...)`; при мёртвом менеджере — `_fallback.emergency_log` + счётчик.
2. Счётчики `thread_exceptions`, `warnings_captured`, `hook_delivery_failures` — в readback `introspect.observability.counters.error` и в `system_overview.anomalies`.
3. Снятие хуков при останове процесса (восстановить прежние), чтобы тесты не текли (фикстура).
4. Тесты автора: реентрантность (исключение внутри хука), хук при остановленном менеджере, порядок «до/после LoggerManager».
**Acceptance criteria:**
- [x] (`4724f220`, `28cf8fd3`) Юнит: исключение в `threading.Thread` → одна запись `kind=error` с `thread=<имя>` и трассой в сторе, `thread_exceptions == 1`, health-счётчик ошибок вырос; `warnings.warn` → одна запись `kind=log severity=warning` с категорией.
- [x] (`28cf8fd3`, стенд 2026-08-29) Живьём: `health.report`-аналог — команда диагностики `diag.thread_raise` (или зонд) → запись в `errors.log` + стор + `system_overview.anomalies`.
- [x] (матрица I1/I3/I4 + A3/A4) Пара инъекций: хук снят → 0 записей при 728 байтах в stderr (красный); хук стоит, менеджер мёртв → `hook_delivery_failures == 1`, не тишина.
- [x] (`28cf8fd3`, проверка C3 в docs_verify) `CONNECTORS.md`: раздел «что ловится автоматически» с этими тремя механизмами.
**Out of scope:** fd-перехват нативного stderr (9.2), `faulthandler` в останове (§13 плана порта).

**Статус: ЗАКРЫТА 2026-08-29.** Коммиты: `4724f220` (17 красных тестов тестера, worktree `D:/wtb04` на `0c7f3724`) →
`28cf8fd3` (механизм + 14 авторских тестов + документы) → `3513dfef` (8 сторожей по ревью) → `3096cd06` (боевая
проводка `diag.*`, ADR). Гейты на `3096cd06`: фреймворк **9034 passed / 8 skipped / 1 xfailed**, корневой
**7243 passed / 64 skipped**, `docs_verify` 15 проверок / 0, `sentrux check .` 36 rules pass.

- **Механизм:** `logger_module/core/process_hooks.py` — `install_process_hooks(services)`, одиночка на процесс, три
  хука; счётчики `thread_exceptions / warnings_captured / hook_delivery_failures` в `ErrorManager.stats` →
  `PLANE_COUNTER_KEYS` → `introspect.observability.counters.error`; `HealthState.report_error(**fields)` (адрес
  потока и трасса едут в запись); `ProcessModule.report_error`; снятие в lifecycle между остановом воркеров и
  гашением плоскостей; команды `diag.thread_raise` (readback `joined`, `join_timeout_sec`) / `diag.warn`; аномалия
  `thread_exceptions` в `system_overview`, `hook_delivery_failures` ∈ `OBSERVABILITY_LOSS_KEYS`. ADR-LOG-011.
- **Инъекции (предсказания до прогона):** серия 1 — 23 заплатки, 17 совпали, 6 разошлись в сторону «больше
  красных»; I19a (реентрантность на пути исключений) — 0 красных, ветка недостижима по построению (потоковый
  сторож + `finally`); I16 — страж `test_loss_keys_match_the_real_publisher` односторонний, снятый ключ держит
  только A9b тестера. Серия 2 (после ревью) — 8/8 совпали. Заплатка «лишний kwarg в `register_command`» уронила
  8 тестов, а не 1: фейковый менеджер повторяет сигнатуру строго — патча «краснеет только боевая проводка» нет.
- **Живой стенд** (`webcam_sketch`, 7 процессов + ПМ, `logs_live/f1_task11`): `pult` `0/0/0 → 1/1/0`, контроль
  `lines` `0/0/0`; `errors.log` 0 → 10 строк с трассой (`_raise_diagnostic_error`); стор — ровно одна `kind=error`
  (`extra.context.thread`, `hook`, трасса) + `[health]`-строка `kind=log` + `py.warnings` `kind=log
  category=UserWarning`; `health.status`: `errors 1`, `last_error.context = thread:live-hooked-worker`; аномалия
  `thread_exceptions=1` — драйвером из свежего процесса (MCP-сервер держал `backend_ctl` до правок — как в 0.5).
  Ревьюер добавил: троттл health 5 с — два инцидента одного потока за 3.86 с → счётчик 2, запись одна
  (задокументировано в CONNECTORS/ADR); дедуп `warnings` тем же текстом → `warnings_captured` не растёт
  (`success: true`, число в ответе и есть детектор); `gui` под хуками — нули.
- **Ревью:** итерация 1 — CHANGES REQUESTED без блокеров: 6 заявленных свойств без сторожа (71 зелёных при
  снятом свойстве) и литерал `DIAG_JOIN_TIMEOUT_SEC` без readback значения (§1.2); итерация 2 — **APPROVED**
  (8/8 собственных заплаток ревьюера, утечек слотов нет); minor по тексту ADR закрыт в `3096cd06`. Правка
  теста тестера A4 признана законной: pytest занимает `threading.excepthook` на сессию и в stderr не пишет
  (0 байт против 648) — восстановлена предпосылка, не ослаблен критерий.
- **Отклонения от буквы задачи, названные:** дорога инцидента — `services.report_error` → `HealthState`
  (не прямой `_track_error`; Task 1.3 обобщит на миксин); свой `warnings.showwarning`, а не
  `logging.captureWarnings` (не уводить в соседнюю систему записи); прежний `showwarning` не зовётся,
  прежние `excepthook`'и — зовутся.
- **Открыто:** одиночка хуков — на интерпретатор, не на объект процесса (`docs/claude/OPEN_QUESTIONS.md`;
  в тестах и на стенде сценария нет); у повтора записи под троттлем нет своего счётчика (наследие C2).
  Числа для соседей: `ProcessManager.counters.logger.unresolved_channel_records = 12` на чистом старте
  (Task 1.2); один инцидент = две строки в сторе — `[health]` + `kind=error` (Task 1.3 / M8).

### Task 1.2 — Лаунчер и ранние записи не теряются (M14, m3)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** INFO лаунчера виден в файле; у `ProcessManager` `unresolved_channel_records == 0` на старте; отказ уборки SHM — не `except: pass`.
**Files:** `process_manager_module/launcher/system_launcher.py:160-190`, `process_manager_module/launcher/spawner.py:73`,
`shared_resources_module/buffers/cleanup.py:160`, `logger_module/adapters/std_facade.py:150-170`, подъём логгера ПМ
(`process_manager_module/process/process_manager_process.py` — точка регистрации каналов).
**Steps:**
1. Лаунчер поднимает минимальный `LoggerManager` (console + `launcher/system.log` в `INSPECTOR_LOG_DIR`) тем же конфигом слоёв, что процессы, — не отдельный механизм.
2. `except: pass` вокруг уборки SHM → `log_error` с исключением + счётчик `shm_cleanup_failures`; успех — INFO с числом сегментов.
3. У ПМ каналы регистрируются до первой записи (или ранние записи идут в ранний буфер и сливаются) — цель `unresolved_channel_records == 0`.
**Acceptance criteria:**
- [x] Живьём: `launcher/system.log` содержит `cleanup_stale_shm: очищено N`; `introspect.observability(ProcessManager).counters.logger.unresolved_channel_records == 0`; `system_overview.anomalies` без `observability_loss` у ПМ на чистом старте.
- [x] Инъекция: сломать уборку (несуществующий путь) → ERROR с трассой в `errors.log`, счётчик 1.
**Out of scope:** формат каталога логов (m1 — Ф3.2).

**Ревью, итерация 1 (2026-08-31): CHANGES REQUESTED, 10 находок — все закрыты правкой или
переписанным утверждением.** Подробности решений — ADR-PMM-029 («Итерация 1 ревью») и
ADR-PM-044 («Итерация 1 ревью»). Коротко: уборка SHM на Windows считала НЕ убранное (F1);
ленивый подъём был идемпотентен только на успехе (F2); `stop()` не был терминальным (F3);
база каталога логов резолвилась двумя разными функциями (F4); «конфиг отверг бы telemetry» —
неправда (F5); у `shm_cleanup_segments` три состояния, а описано было два (F6); два заявленных
свойства не охранялись ничем (F7); голый `except: pass` уцелел на реапе PID-реестра (F8);
число строк журнала в ADR не совпадало с живым замером (F10).

**Открыто (F9), формулировка исправлена:** счётчик `unresolved_channel_records` у дочерних
процессов на ЗАКРЫТИИ даёт ту же величину, что чинила эта задача на РОЖДЕНИИ. Прежде это было
названо «другим классом, вне рамок» — неверно: **причина другая, наблюдаемое неразличимое**
(мой прогон: после `shutdown()` + 3 записи — `6`, `{'system_file': 3, 'messages_file': 3}`).
Значит критерий 1 — утверждение о моменте, а не о свойстве. Тот же корень у давнего вопроса
про `sink.disable`. Записано в `docs/claude/OPEN_QUESTIONS.md` (2026-08-31, F9); кода счётчика
задача не трогает — это отдельный долг.

**Статус: ЗАКРЫТА 2026-08-31.** Коммиты: `d4deba58` (5 красных приёмочных тестера, worktree
`D:/wtb05` на `035c0cc8`) → `3badcf83` (реализация) → `e1867a60` (мой сторож «один разъём на
точку») → `0a075682` (десять находок ревью) → `8cecc306` (остатки Р1/Р5).

| Стадия | Результат |
|---|---|
| Тестер (worktree на предреализационном коммите) | 5 красных, причины совпали с предсказанными; нашёл ловушку ложно-зелёного — на минимальной 2-процессной топологии дефект не воспроизводится вовсе |
| Реализация | Причина оказалась НЕ той, что предполагал план: не «запись раньше регистрации канала», а две дороги к одному конфигу. `expand_observability` эмитит частичный набор каналов, Pydantic заменяет набор целиком, `scopes` остаются дефолтом схемы и ведут в `system_file`/`messages_file`, которых в реестре нет → ровно 6 записей × 2 приёмника. Лечится швом `compose_managers_payload`, а не ранним буфером |
| Мои инъекции, серия 1 (6 заплаток) | 5 попаданий из 6; М5 дала 0 красных → дыра, проверена руками с контролем (без заплатки маркер x0/x3, с заплаткой x1/x3 при всех 34 зелёных) → сторож `TestOneConnectorPerPoint` |
| Живой стенд | `unresolved_channel_records` 12 → **0**, `unresolved_channels = {}`; аномалий 0 при 8 процессах; `launcher/system.log` — 10 строк, из них 6 не от лаунчера (spawner, PluginRegistry, Hikvision SDK, devices_sync) — до задачи они уходили в stdlib-фолбэк без хендлеров |
| Ревью, итерация 1 | CHANGES REQUESTED, 10 находок с воспроизведениями |
| Мои инъекции, серия 2 (контроль другим объективом) | база 43/1s; Д1 предсказал 1 → 2, Д2 предсказал 0 → 1 (ожидаемой дыры НЕТ), Д3 1 → 1 |
| Ревью, итерация 2 | **APPROVED.** Собственная матрица ревьюера: 12 заплаток, 10/10 совпадений по числу И по имени умершего сторожа, 2 зонда подтвердили 2 дыры |

**Гейты на финале:** фреймворк **9058 passed / 9 skipped / 1 xfailed**, `validate.py` без ошибок
и предупреждений, `sentrux check .` — 36 правил, живая пара `--backend-live` 2 passed.

**Ревьюер закрыл открытый конец крупнее, чем тот был заявлен:** до правки F4 в дерево
репозитория уезжал не только журнал лаунчера, но и пересборка L0 (`base_managers_payload`) —
то есть каждый процесс, поднятый без готовой секции менеджеров.

**Остатки ревью итерации 2.** Р1 и Р5 закрыты коммитом `8cecc306`; Р2–Р4 — долги, не блокеры:

- **Р1 (закрыт):** README обещал, что записи после `stop()` «не теряются». Замер: WARNING и
  ERROR доходят до stderr, INFO при ненастроенном stdlib отбрасывается (нет хендлеров,
  эффективный уровень корня WARNING). Формулировка заменена на измеренную; там же названа цена
  сторожа — он подменяет сам `emergency_log`, то есть охраняет факт вызова, а не выживание записи.
- **Р5 (закрыт):** префиксный блок уборки молчал о платформе, хотя его гейт СТРОЖЕ первого
  (Linux, не POSIX): на Windows enumeration недоступен, на macOS нет `/dev/shm`. Оговорка
  добавлена, сторож `TestPrefixCleanupTellsThePlatform` краснеет под снятием оговорки (1 из 17).
- **Р2 (долг):** маршрут после закрытия не охраняется у `_log_warning` и `_log_error`; у
  последнего он вдобавок избыточен — ветка `if error is None` уже уводит в аварийный выход.
- **Р3 (долг):** второй адресат F8 — отказ `clear()` в `stop()` — не охраняется ничем;
  `pid_registry_failures` растёт из двух мест, тестируется одно.
- **Р4 (долг):** `is_posix()` — белый список `("Linux", "Darwin")`, поэтому ранний возврат
  глушит уборку на любом другом POSIX (FreeBSD/AIX), где `unlink` работал бы. Документация
  всюду говорит «Windows». Для платформ проекта последствий нет.

**Не проверено никем (честный конец):** POSIX-половина уборки (`test_on_posix_cleanup_takes_the_name_away`)
на Windows пропускается, и ни одна инъекция здесь её не убьёт — доказательством был бы прогон
на Linux. Гонка в `_ensure_observability` (окно между проверкой флага и присваиванием) сужена,
но не закрыта; сценария с параллельной записью не построено, достижимость окна неизвестна.

### Task 1.3 — Плоскость ошибок: решение Р-1 и проводка (M8)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework, plugins
**Goal:** по решению Р-1(а): `errors.log`, health и breaker видят отказы подсистем; один инцидент — одна строка в сторе.
**Files:** `process_module/generic/plugin_orchestrator.py:157,180,202`, `worker_module/` (5 точек `_log_error`),
`router_module/channels/socket_channel.py:132,341`, `router_module/core/router_manager.py:398-399`,
`Plugins/sources/capture/plugin.py:288`, `base_manager/mixins/observable_mixin.py` (`report_error` с параметром `also_log=False`),
`multiprocess_framework/docs/observability/CONNECTORS.md`, новый страж `multiprocess_framework/modules/tests/test_one_connector_per_point.py`.
**Steps:**
1. Инвентарь: список из 226 `_log_error` классифицировать скриптом на «отказ подсистемы» / «ошибка обработки данных» (первые → `report_error`, вторые остаются логом). Список в задаче, не в голове.
2. Правило «один разъём на точку»: AST-страж — соседние вызовы `_log_error` и `_track_error`/`report_error` в одной функции запрещены (whitelist с причиной).
3. `report_error` пишет ОДНУ запись (error-плоскость) с полным Resource-контекстом; логгер-tap стора не дублирует записи, у которых `origin=error_manager` (маркер в `extra`).
4. Живой отказ для приёмки: камера не открывается headless (`capture/plugin.py:288`) — сейчас `log_error` мимо плоскости ошибок.
**Acceptance criteria:**
- [ ] Живьём на стенде без камеры: `errors.log` содержит отказ открытия камеры; в сторе по нему одна строка `kind=error`; `health.status` показывает ошибку; `system_overview.anomalies` — тоже.
- [ ] `health.report` даёт одну строку в сторе (было три).
- [ ] Инъекция: вернуть пару `_log_error + _track_error` в `router_manager.py:398` → страж красный по адресу; снять маркер `origin` → тест дубля красный.
- [ ] `CONNECTORS.md`: таблица «какая дорога для какого класса события» + ссылка на страж.
**Out of scope:** fingerprint/группировка (9.1).

**Развилка Р-9 решена владельцем 2026-08-31: мигрировать все 46 адресов, страж широкий,
whitelist'а нет** (обоснование и отвергнутые варианты — `plan.md`, «Решённые развилки»).
Инвентарь точек — [`inventory-log-error.md`](./inventory-log-error.md): **315** адресов, из них
A (отказ подсистемы) 240, B 51, C 14, W (переклад чужого сообщения) 10. Число «226» из шапки
задачи устарело и мерило только семейство `_log_error`, пропуская 66 вызовов `.log_error` —
включая три из четырёх адресов, названных спекой.

**Три опасности миграции — приёмочные, закрываются числом, а не рассуждением.** Измерено мной
по коду `process_module/health/state.py` на `0e0953ef`:

1. **Дроссель.** `HealthState.report_error` пишет строку в журнал не чаще `DEFAULT_THROTTLE = 5.0` с
   на ключ, `ctx.log_error` не дросселируется вовсе. После снятия соседа часть инцидентов перейдёт
   с «строка на событие» на «строка на окно». Счётчик при этом растёт всегда (строки 259-262) —
   то есть потеря видимости компенсируется числом, но это надо ПОКАЗАТЬ замером «было/стало», а не
   объявить. Ф1 борется с невидимыми отказами; молча уменьшить частоту голоса внутри неё нельзя.
2. **Ключ дросселя — пара `(тип исключения, context)`** (строка 256: `key = f"{etype}|{ctx}"`).
   `report_error` требует **объект исключения**, а заметная часть класса A отказывает **кодом
   возврата**: камера вернула `False` (`Plugins/sources/capture/plugin.py:288`), `create_worker`
   вернул `False` (`device_hub:401`). Если такие точки мигрировать через общее синтетическое
   `RuntimeError`, ключ выродится в `RuntimeError|<context>` и **разные отказы в одном контексте
   начнут глушить друг друга**. Требование: у каждого класса отказа — свой тип исключения;
   страж на вырождение ключа (два разных отказа в одном контексте дают две строки, не одну).
3. **Текст.** У соседнего `ctx.log_error` текст обычно богаче, чем `str(exc)`. Снять вызов, не
   перенеся детали в `**fields` (они уезжают в контекст записи плоскости ошибок, не в health-снапшот
   — докстринг 244-247), значит обменять дубль на потерю. Приёмка: по каждому мигрированному адресу
   деталь либо в `context`, либо в `fields`.

**Побочный эффект, который надо оформить:** ADR-PM-030 не отменяется, но его докстринг
(`process_module/plugins/base.py:190-210`) продолжает учить старому правилу «разъёмы разведены по
намерению». Нужен ADR-дополнение о снятии страховки и правка докстринга — иначе следующий автор
поставит пару заново, и страж покраснеет на новом коде без объяснения почему.

### Task 1.4 — Голоса-повторы окном на ключ; `trace_id` вне текста (M17, m2)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, plugins
**Goal:** повторяющееся состояние — один голос на окно + счётчик; WARNING-константы старта не повторяются; ключ дросселя не зависит от `trace_id`.
**Files:** `router_module/core/router_manager.py:388-399` (образец `_SEND_ERROR_LOG_INTERVAL_SEC` → обобщить),
`channel_routing_module/core/channel_routing_manager.py` или `base_manager/mixins/observable_mixin.py` (новый `log_windowed(key, interval, level, msg, **ctx)`),
`shared_resources_module/queues/core/manager.py` (пара `Full()`/`drop_oldest`), `process_manager_module/process/process_manager_process.py`
(priority/liveness WARNING'и), `Plugins/control/robot_control/plugin.py:285`, `logger_module/core/sampling.py` (ключ по источнику+call-site — опционально, по бенчу).
**Steps:**
1. `log_windowed`: первый голос сразу, дальше — не чаще `interval` на ключ, в тексте — число подавленных; счётчик `windowed_suppressed` в readback. Окно — из политики (`observability.voices.default_window_sec`), не литерал.
2. Перевести на него: `Full()`/`drop_oldest` (один голос на окно + счётчик `queue_full_events`), `Failed to set priority` (один раз за процесс, INFO), `ready via liveness-fallback` (INFO, WARNING только если > `N` раз подряд).
3. `robot_control`: `trace_id` в `extra.context.trace_id`, текст постоянный; линт-страж: сообщение не содержит 32-hex.
4. Опционально (по бенчу, решение в задаче): ключ сэмплера `(уровень, источник, call-site)` до сборки записи — цена подавленной записи ≤ 1 мкс.
**Acceptance criteria:**
- [ ] Живьём: бут → 0 WARNING-констант (список из ревью m2 — по каждому контрольная строка INFO один раз); сценарий переполнения очереди (`gui` под нагрузкой) → ≤ 1 голос на окно при растущем `queue_full_events`.
- [ ] Пара инъекций: окно снято → шторм красный по числу; счётчик снят → «событие есть, счётчик 0» красный.
- [ ] `sampling_first_n` включён на стенде → `records_sampled_out > 0` при включённом дросселе (С-8 закрывается числом).
**Out of scope:** переписывание всех 226 точек — только перечисленные.

### Task 1.5 — Живой стенд Ф1 + ревью фазы
- [ ] Стенд без камеры и с камерой; `errors.log` непустой на первом, пустой на втором — пара; агентская сессия: `system_overview` называет отказ камеры в `anomalies`.
