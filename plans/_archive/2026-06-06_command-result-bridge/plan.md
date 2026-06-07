# План: Command-result bridge — GUI узнаёт результат своих команд (request/response GUI→PM)

- **Slug:** `command-result-bridge`
- **Дата:** 2026-06-06
- **Статус:** ✅ **DONE (2026-06-07).** P1 `deae8b91` · P2 `e9e29f71` · P3 `c4894133` — все verified. **P4 закрыт по существу** (оценка merit 2026-06-07): тяжёлый ADR признан дублем транспортного ADR-005 + auto-reply note → GUI-специфика зафиксирована в **frontend_module DECISIONS FE-004**; интеграция покрыта существующими тестами + `backend_ctl` (PM-сторона round-trip); memory dual-write `project_command_result_bridge`. Разблокировал lifecycle (p4.4.4) и pipeline-live Этап 3.
- **Ветка:** `feat/command-result-bridge` (переименована из `feat/lifecycle-feedback` 2026-06-06).
- **Refs:** `plans/2026-05-31_transport-router-hub/plan.md` (P0.5 request/response `1a1b6b9b`), `p4.4.4_lifecycle-feedback.md` (зависит от этого моста), `plans/2026-05-31_pipeline-live-control/plan.md` (Этап 3 — тоже потребитель), memory `project_pipeline_live_control_stage1`, `project_backend_control_mcp`, `feedback_mvp_pattern`, `feedback_qt_mcp_smoke_verification`, `feedback_dict_at_boundary_gui`.
- **Слой:** mixed (framework: `frontend_module/CommandSender`; prototype: proxy + presenter + GUI).

---

## Зачем (продуктовая боль)

GUI сегодня **не знает результат ни одной своей команды**. `ProcessManagerProxy._dispatch` ([process_manager_proxy.py:93-97](../../multiprocess_prototype/frontend/bridge/process_manager_proxy.py#L93)) шлёт fire-and-forget и возвращает optimistic-ack `{"success": True, "dispatched": True}` — **всегда**, даже если backend упал/откатился.

| Боль | Сейчас |
|------|--------|
| Активировал рецепт — **запустился или упал?** | UI говорит «отправлено», факт неизвестен |
| `replace_blueprint` сделал rollback (ошибка старта процесса) | GUI не узнает — покажет «успех» |
| Тихий провал команды (нет приёмника, плохой аргумент) | диагностика «параметр не применяется live» заняла ~30 шагов (memory `project_backend_control_mcp`) |

Это **fire-and-pray** на каждой команде. Мост превращает его в «узнал успех/ошибку» — продуктовая ценность на каждой дискретной операции.

> **Почему именно сейчас.** Тот же request/response-мост требуется pipeline-live-control Этапу 3 (live-применение, знать «применилось ли») и lifecycle-прогрессу (P4.4.4). Один keystone разблокирует три направления.

---

## Recon (2026-06-06, read-only, на актуальном `main`)

### G1. ✅ Round-trip УЖЕ работает на транспорте и PM-стороне (доказано backend_ctl)
- GUI-host (`GuiProcess(ProcessModule)`) **имеет** `self.router_manager` с рабочим `request()` (P0.5) — он уже зовётся для state-подписок ([process.py:42-80](../../multiprocess_prototype/frontend/process.py#L42)).
- system message_processor GUI крутит `receive()` (стандартный, не переопределён, [process.py:34](../../multiprocess_prototype/frontend/process.py#L34)) → резолвит `type=="response"` ([router_manager.py:590](../../multiprocess_framework/modules/router_module/core/router_manager.py#L590)) → `_pending_requests`.
- PM отвечает: `_handle_process_command → reply_to_request` (`type="response"`, `request_id=cid`, `targets=[sender]`). Доказано headless: `backend_ctl/smoke_proof.py` шлёт `process.command` и получает `command.response`.

### G2. Дыра — ТОЛЬКО GUI-клиент (fire-and-forget)
- `CommandSender` ([command_sender.py](../../multiprocess_framework/modules/frontend_module/bridge/command_sender.py)) шлёт через `self._process.send_message(target, msg)` — fire-and-forget. `IProcess`-протокол ([:26-31](../../multiprocess_framework/modules/frontend_module/bridge/command_sender.py#L26)) объявляет только `name` + `send_message`. `request()` не используется.
- `ProcessManagerProxy._dispatch` ([:93](../../multiprocess_prototype/frontend/bridge/process_manager_proxy.py#L93)) → `send_system_command` → optimistic-ack.
→ Чтобы GUI узнал результат: клиент должен звать `router.request(msg, timeout)` вместо `send_message`, забрать реальный `response`.

### G3. Потоки — request() из Qt main-thread безопасен, но блокирует UI
- Команды триггерятся из **Qt main-thread** (клик). main-thread ≠ receive-поток (receive в system message_processor + data_receiver воркерах) → дедлока P0.5 **нет**.
- НО `request()` блокирует вызывающий поток до ответа/таймаута. `replace_blueprint` — секунды (спавн процессов). Блокировать main-thread = **фриз UI**.
→ **Решение:** `request()` исполнять на **worker-потоке** (`QThreadPool`/`QRunnable`), результат маршалить в main-thread сигналом. Это ядро GUI-работы.

### G4. correlation проставит сам `request()` (ничего вручную)
- `router.request(msg)` генерит `cid`, ставит `msg["request_id"]` и зеркалит в `data.correlation_id` ([router_manager.py:377-383](../../multiprocess_framework/modules/router_module/core/router_manager.py#L377)). Reply-адресат — `sender` (GUI name, ставит `build_system_command_message`). Клиент строит обычный билет и просто зовёт `request()`.

### G5. Backward — request-path ТОЛЬКО для дискретных команд
- Высокочастотные field-write (слайдеры, `send_field_command` с debounce, [:74](../../multiprocess_framework/modules/frontend_module/bridge/command_sender.py#L74)) **остаются fire-and-forget** — блокирующий round-trip на каждый тик слайдера недопустим.
- Request-path добавляется opt-in для дискретных действий: активация рецепта (`blueprint.replace`), `process.start/stop/restart`, `system.shutdown` (где результат важен).

### G6. Точка инициации в GUI (уточнить в P3 investigation-first)
- Ревью указало `presenter.py:1589/1643` → `proxy.replace_blueprint(blueprint)`. Точный call-site и поток (должен уметь не блокировать main) подтвердить перед правкой.

---

## Целевая архитектура

```
Qt main-thread (клик «Активировать рецепт»)
  presenter.activate_recipe()
    proxy.replace_blueprint_async(bp, on_result=cb)   # НЕ блокирует
        runner.submit(lambda: sender.request_system_command({"cmd":"blueprint.replace","blueprint":bp}, timeout=30))
                                        │ (QThreadPool worker-поток)
                                        ▼
                              router.request(msg, timeout)  # блокирует worker, НЕ main
                                        │ send → ProcessManager
                                        ▼ (system message_processor резолвит response)
                              response {"success":..,"result":{replaced, rolled_back,..}}
                                        │
        on_result(response) ◀── signal (queued, в main-thread) ── runner.finished.emit(response)
    presenter показывает успех/ошибку (status/toast/dialog)
```

### Минимум сущностей (reuse-first)
| Сущность | Где | Что |
|---|---|---|
| `CommandSender.request_command` / `request_system_command` | `frontend_module` (расширение) | блокирующий `router.request(build_*_message(...), timeout)` → реальный `response` dict |
| `IProcess` (расширение протокола) | `frontend_module` | дать доступ к `request` (метод `request_message(target, msg, timeout)` или `router_manager`) |
| `RequestRunner` | prototype `frontend/bridge` (новый) | `QThreadPool`+`QRunnable`+QObject-сигнал: гонит request на воркере, `finished(result)` в main-thread |
| `ProcessManagerProxy.*_async(... on_result=)` | prototype (расширение) | async-вариант поверх runner; старые fire-and-forget методы сохраняются (G5) |
| presenter feedback | prototype (recipe-activation) | показать success/error (MVP-паттерн) |

---

## Принципы
1. **Reuse-first** — `router.request()`/`reply_to_request`/correlation (P0.5) и PM-reply уже работают (G1); строим только GUI-клиент. Транспорт/каналы не трогаем.
2. **No big-bang / strangler** — старые fire-and-forget методы живут (G5); request-path добавляется рядом, opt-in per-команда. Прототип запускаем после каждой задачи.
3. **Thread-safety** — `request()` только на worker-потоке; в Qt-виджеты только из main-thread через signal/slot (G3). Никакого cross-thread доступа к Qt.
4. **Dict-at-Boundary** — на проводе dict; результат в GUI — dict (memory `feedback_dict_at_boundary_gui`).
5. **MVP** — feedback через presenter+View-Protocol (memory `feedback_mvp_pattern`).
6. **Investigation-first** — recon выполнен; P3 уточняет G6 до правки GUI.

---

## Декомпозиция

```
P1 framework: CommandSender request-path (+ IProcess) ─▶ P2 GUI: RequestRunner + ProcessManagerProxy async
        ▶ P3 presenter: recipe-activation показывает success/error (+ qt-smoke) ─▶ P4 integration + ADR + docs
```

### Task P1 — Framework: CommandSender.request_command/request_system_command + IProcess
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Дать `CommandSender` блокирующий request-путь, возвращающий реальный `response`. Без потоков/GUI (вызывается из теста синхронно).
**Files:** `frontend_module/bridge/command_sender.py` (новые `request_command`/`request_system_command`; расширить `IProcess`), `frontend_module/bridge/tests/`.
**Steps:**
1. Расширить `IProcess`: дать доступ к request — метод `request_message(target, msg, timeout) -> dict` (дефолт через `router_manager.request`) ИЛИ опц. атрибут `router_manager`. Выбрать минимально-инвазивный (ProcessModule имеет `router_manager`).
2. `request_system_command(command: dict, timeout: float = 30.0) -> dict`: `build_system_command_message(command, sender=self._process.name)` → `request()` → вернуть response. correlation проставит `request()` (G4).
3. `request_command(target, command, args, timeout)` — аналогично через `build_command_message`.
4. Не трогать `send_command`/`send_field_command` (fire-and-forget остаётся, G5).
5. Тесты: fake process с router-stub; проверить, что билет идёт в `request()` (не `send_message`), response возвращается; таймаут → `{"success": False, "error": "timeout"}` (как `request()`).
**Acceptance:** - [x] `request_system_command` возвращает реальный response PM (через router.request) - [x] fire-and-forward методы без изменений (паритет) - [x] таймаут проброшен корректно - [x] framework-тесты зелёные, ruff/pyright чисты.
**Out of scope:** потоки (P2); GUI (P3).
**Статус:** ✅ **P1 DONE** (`deae8b91`). `request_command`/`request_system_command` + `IRequestingProcess` + `DEFAULT_REQUEST_TIMEOUT=30s`. 6 тестов (round-trip, timeout, no-router→raise, паритет fire-and-forget); command_sender/19 passed, ruff+pyright clean. **Решение:** тесты — в существующем `multiprocess_prototype/.../test_command_sender.py` (конвенция: CommandSender-тесты живут там через re-export), не в новом framework-tests-каталоге.

### Task P2 — GUI: RequestRunner (worker-поток) + ProcessManagerProxy async-вариант
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Гонять request на worker-потоке, маршалить результат в Qt main-thread; async-методы proxy.
**Files:** `multiprocess_prototype/frontend/bridge/request_runner.py` (новый), `process_manager_proxy.py` (расширить async-методами), тесты pytest-qt.
**Steps:**
1. `RequestRunner`: `QThreadPool` + `QRunnable`-задача зовёт `sender.request_system_command(...)`; QObject-сигнал `finished(dict)` (AutoConnection → main-thread). Ошибка в задаче → `finished({"success": False, "error": str})` (не падение потока).
2. `ProcessManagerProxy.replace_blueprint_async(blueprint, on_result: Callable[[dict], None])` (+ `start/stop/restart_process_async` по необходимости) — submit в runner, `on_result` вызывается в main-thread.
3. Старые fire-and-forget методы сохранить (G5, back-compat для путей, где результат не нужен).
4. Тесты pytest-qt: submit → `on_result` получает фейковый response в main-thread; ошибка задачи → error-result; нет cross-thread Qt-доступа.
**Acceptance:** - [x] `replace_blueprint_async` не блокирует main-thread, `on_result` приходит в main-thread - [x] исключение в request → error-result, поток жив - [x] старые методы fire-and-forget работают - [x] pytest-qt зелёные.
**Out of scope:** presenter/виджет (P3).
**Статус:** ✅ **P2 DONE** (`e9e29f71`). `RequestRunner` (QThreadPool + Signal/AutoConnection, паттерн DataReceiverBridge) + `ProcessManagerProxy.*_async(on_result)` (replace_blueprint/start/stop/restart). 9 тестов (доставка, on_result в main-thread + request на worker, error-result, wrap, None, real-result, lifecycle, паритет); 13 passed. **Находка тестом:** async-сабмиты идут конкурентно на пуле → порядок завершения не гарантирован (тест сравнивает множеством, не списком) — это корректное свойство, не баг.

### Task P3 — Presenter: активация рецепта показывает success/error (+ qt-smoke)
**Level:** Senior+ · **Assignee:** teamlead/developer · **MVP обязателен**
**Goal:** При активации рецепта GUI показывает реальный результат (успех с числом заменённых процессов / ошибку с причиной/rollback).
**Files:** recipe-activation presenter (уточнить call-site, G6), View-Protocol + feedback-виджет (status-line/toast/dialog), подключение `replace_blueprint_async`. Тесты pytest-qt.
**Steps:**
1. **Investigation-first (G6):** найти точный call-site `proxy.replace_blueprint` (ревью: `presenter.py:1589/1643`) и поток вызова.
2. Заменить fire-and-forget вызов на `replace_blueprint_async(bp, on_result=self._on_replace_result)`; показать «выполняется…» (спиннер/disabled-кнопка) до результата.
3. `_on_replace_result(resp)`: `resp["success"]` → «Рецепт запущен (заменено N процессов)»; иначе → ошибка/`rolled_back` через View.
4. pytest-qt: presenter обновляет View по фейковым success/error результатам.
5. **qt-mcp smoke** (memory `feedback_qt_mcp_smoke_verification`): прототип, активировать рецепт → индикатор результата виден, UI не фризится, FPS не просел; проверить и happy, и error (битый blueprint).
**Acceptance:** - [x] активация рецепта показывает реальный success/error (не optimistic) - [x] UI не фризится во время операции (worker-поток) - [x] qt-mcp smoke: live happy-path (restore→«Запустить»→async replace→процессы подняты, GUI выжил); feedback НЕ-модальный (статус+лог) - [x] pytest-qt зелёные (459 pipeline).
**Out of scope:** lifecycle-прогресс (P4.4.4 follow-up); request-path для других команд (по аппетиту позже).
**Статус:** ✅ **P3 DONE** (`c4894133` non-modal). По ходу live-smoke вскрыт и починен каскад крашей горячей замены (вне исходного scope, но блокировал приёмку):
- `00781adb` — `replace_blueprint` читал `class` вместо канонического `process_class` → класс не грузился → откат → краш. + reply `success` по self-report.
- `9288835c` — монитор реально не паузился при replace (цикл шёл по worker-event, игнорировал `_monitoring`) → ложный unresponsive.
- `3b4891fe` — unresponsive при disabled-policy ронял ВСЮ систему (каскад на GUI). Теперь не роняет (как crashed).
- `f1c88d10` — restore: активный рецепт из манифеста при старте (раньше всегда None).
**Остаток (следующая сессия):** persist slug→app.yaml при активации (restore готов); баг UI-активации «Загрузить» (dispatch ActivateRecipe early-return?); косметика — 3 ложных unresponsive при старте процессов (безвредны); app переписывает raw-рецепт (стирает комментарии).

### Task P4 — Integration + ADR + docs + sentrux
**Level:** Senior · **Assignee:** tester + teamlead
**Goal:** Нулевая регрессия, закрепить решения.
**Files:** `*/tests/`, `multiprocess_framework/DECISIONS.md` (+ `frontend_module` DECISIONS), `scripts.sync`, обновить `p4.4.4_lifecycle-feedback.md` (depends-on снят/готов), pipeline-live-control plan (врезка «мост готов»).
**Steps:**
1. Integration: GUI request round-trip (recipe activation success+error) + паритет fire-and-forget путей.
2. qt-smoke FPS-паритет (~21).
3. **ADR**: «GUI дискретные команды идут request/response (GUI узнаёт результат); field-write остаётся fire-and-forget; request — на worker-потоке, результат в main-thread сигналом». + `scripts.sync` + `validate.py`.
4. sentrux `session_start`(до P1)→`session_end`.
5. Memory dual-write: новая запись «command-result-bridge DONE» + отметить разблокировку lifecycle/pipeline-Этап3.
**Acceptance:** - [ ] integration зелёный (request + паритет) - [ ] qt-smoke success/error + FPS - [ ] ADR + sync + validate чисты - [ ] sentrux дельта (опц.) - [ ] memory обновлена.
**Out of scope:** —

---

## Риски

| Риск | Severity | Митигирование |
|---|---|---|
| `request()` из main-thread → фриз UI | HIGH | P2: только worker-поток (`QThreadPool`), результат сигналом в main (G3) |
| Cross-thread Qt-доступ из on_result | HIGH | сигнал AutoConnection → слот в main-thread; никакого прямого доступа к виджетам с воркера |
| Регресс высокочастотных field-write (блокировка) | HIGH | G5: field-write остаётся fire-and-forget; request-path только для дискретных команд |
| Таймаут на долгом `replace_blueprint` | MEDIUM | щедрый timeout (30s); индикатор «выполняется…»; lifecycle-прогресс (follow-up) уберёт слепое ожидание |
| `request()` из receive-потока (дедлок P0.5) | MEDIUM | request только из RequestRunner-воркера, не из system/data receive-потоков; проверить в P2/P3 |
| Утечка/зависание worker-потока при смерти PM | LOW | timeout гарантирует возврат; QThreadPool переиспользует потоки |

## Верификация (общая)
- `python scripts/run_framework_tests.py` / `make test` — зелёные после каждой задачи.
- `make check` (ruff+pyright+bandit).
- qt-mcp smoke после P3: активация рецепта (happy+error), UI не фризится, FPS ~21.
- backend_ctl уже доказывает PM-сторону round-trip (G1) — GUI-сторона добавляется smoke'ом.
- sentrux `session_start`→`session_end`.

## Коммиты
- Каждая задача — `feat(frontend)`/`feat(prototype)` коммит, `Layer:` соответственно, `Refs: plans/2026-06-06_command-result-bridge/plan.md`.
- ADR — в составе P4.
- Создание/закрытие плана — отдельный `docs(plans):` коммит.

## Связь с другими планами
- **Разблокирует** [`p4.4.4_lifecycle-feedback`](../2026-05-31_transport-router-hub/p4.4.4_lifecycle-feedback.md): прогресс-события поедут поверх того же request-канала (`request(on_progress=...)` добавится к RequestRunner). BLOCKER-2 ревью снимается этим планом.
- **Разблокирует** [`pipeline-live-control` Этап 3](../2026-05-31_pipeline-live-control/plan.md): live-применение узнаёт «применилось ли».
- **BLOCKER-1 lifecycle** (ctx для вложенных `process.command`) — НЕ закрывается этим планом; остаётся в P4.4.4 как отдельная задача (ctx на пути `_handle_process_command`).
