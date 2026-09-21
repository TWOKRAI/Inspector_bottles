# Phase 2 — Общий мир: лента и один энкодер

Часть плана [`plan.md`](plan.md). **Ред. 2 (2026-09-21)** — фаза переписана под автономную
форму (ред. 1 публиковала энкодер из плагина в топологии прототипа и читала его
source-плагином прототипа — оба отменены 2026-08-31; история в git).

Реализует принцип 5 [`vision.md`](vision.md): устройства не зовут друг друга, они делят
мир. В этой фазе мир — это лента: ПЧ задаёт скорость, лента крутит **один** энкодер, робот
отдаёт его регистром (как на железе), сцена читает его из мира. Второго Modbus-клиента
line→robot не появляется (решение 2026-08-13 в силе): `REG_ENC` — единственный источник
истины, вторая копия счётчика — тот же класс дефекта, что «два задания на одну деталь».

**Процессы стенда после фазы:** `robot` (хост `SimRobotHostPlugin`, владеет лентой и
энкодером) и `camera` (источник сцены → `mjpeg_sink`). Общий мир — `StateProxy` внутри
дерева симулятора, путь `sim.belt.*`.

---

### Task 2.0 — `ctx.state_proxy` у фреймворкового `GenericProcess` (carve-out из прототипа)

**Goal:** плагин в любом generic-приложении (`apps/line_sim`, `examples/minimal_app`)
получает рабочий `ctx.state_proxy`: `set` в одном процессе виден через `get`/`subscribe` в
другом. Прототип продолжает работать без изменений поведения.

**Контекст (факты разведки Ф1, [`phase-1`](phase-1-vertical-slice.md) §Разведка):**
`StateProxy` в процессе сегодня создаёт **прототипный** `GenericProcessApp`
(`multiprocess_prototype/generic_process_app.py:23`); фреймворковый `GenericProcess` его не
заводит (`process_module/generic/plugin_orchestrator.py:59`). Серверная половина — store с
непустым посевом у generic-приложения — закрыта Task 1.0 (ADR-APP-007). Эта задача —
клиентская половина. По правилу «запертое в прототипе выделяется, не копируется»
механизм переезжает во фреймворк, а `GenericProcessApp` становится его потребителем.

**Разведка (manager, 2026-09-21, HEAD `a0edf74a`; qex не использовался — Ollama лежит, всё ниже —
Grep/Read по дереву, номера строк сверены на этом SHA).**

*(1) Что `GenericProcessApp` делает сверх создания прокси — ничего.* Весь класс
(`multiprocess_prototype/generic_process_app.py:23-56`) — четыре действия: создаёт
`StateProxy(process_name=self.name, router=self.router_manager, server_target="ProcessManager",
logger=self.logger_manager)` (:37-42), зовёт `initialize()` (:43), регистрирует
`router_manager.register_message_handler("state.changed", proxy.on_state_changed)` (:46-47) —
всё это **до** `super()._init_custom_managers()` (:50); в `shutdown()` зовёт `proxy.shutdown()`
перед `super().shutdown()` (:52-56). Своих подписок и своей ветки `processes.<p>.health` у него
нет. Ветку здоровья и уровни телеметрии пишет **фреймворковый** heartbeat, и оба пути гейтятся
одним и тем же `getattr(self._services, "_state_proxy", None)`:
`_publish_telemetry_to_tree` (`process_module/heartbeat/process_heartbeat.py:1355-1357`) и
`_publish_health_to_tree` (там же, :1559-1561). Тот же приватный атрибут читают
`PluginOrchestrator.load_and_configure_managers` (`generic/plugin_orchestrator.py:60-62`, отсюда
`ctx.state_proxy`), копия контекста (`plugins/base.py:181-186`) и io-peek
(`generic/generic_process.py:336`). **Вывод:** carve-out — это ~20 строк создания/регистрации/
останова, а ветки `processes.<p>.health.*` и `processes.<p>.state.*` у generic-приложения
«включатся сами» побочным эффектом появления `_state_proxy` — это и есть механизм R7/K5, и это же
главный риск для прототипа (см. «Ловушки»).

*(2) `set` по пути вне посева (`sim.belt.*`) — проходит, сеять не надо.* Цепочка сервера:
`StateStoreManager.handle_state_set` (`state_store_module/manager/state_store_manager.py:181-218`)
→ `run_before_set` middleware → `TreeStore.set` (`core/tree_store.py:242-279`), который создаёт
промежуточные узлы (`_navigate(keys, create=True)`, :258; «как mkdir -p», :245). Единственный
middleware, который generic-оркестратор ставит без throttle-правил, — `TopologyGateMiddleware`
(`app_module/orchestrator.py:356-420`, флаг `FW_STATE_TOPOLOGY_GATE`), а он смотрит только на
`processes.<name>.*` и путь вне `processes` пропускает (`middleware/topology_gate.py:52`).
**Условие:** store должен существовать — гейт `_setup_state_store` (`app_module/orchestrator.py:368-372`)
не поднимает его при пустом `initial_state`; generic-дорога после Task 1.0 подаёт непустой
`{"processes": {...}}` (ADR-APP-007, `app_module/DECISIONS.md:169-224`). Приложение, вернувшее `{}`
явным хуком, store не получит — `set` уйдёт в PM без обработчика (fire-and-forget, `_send` не
узнает), `get` вернёт default после таймаута 5 с (`proxy/state_proxy.py:1449`). Живым прогоном
«`set sim.belt.encoder` → `state_get` видит» **не проверено** — это первый RED тестера.

*(3) Куда ADR — `process_module/DECISIONS.md` (новый `ADR-PM-049`; номер — последний на HEAD
`ADR-PM-048` на :3784, на других ветках не сверялся).* Код переезжает в `GenericProcess`
(`process_module`), и оба generic-приложения указывают именно его: `apps/line_sim/pipeline.yaml:38,50,62`,
`examples/minimal_app/pipeline.yaml:22,33`; он же дефолт `process_class`
(`generic/generic_process_config.py:72`). **Это отменяет прежнее решение** «`GenericProcessApp` —
строго в `app_module`» (`plans/2026-07-06_constructor-master/app-template-idea.md:69,77-81,201-202`).
Его довод — «`process_module` ссылается на state_store только под `TYPE_CHECKING`, перенос создал бы
новое runtime-ребро» — **устарел на HEAD**: runtime-импорты уже есть
(`process_module/managers/telemetry_reload.py:28`, `process_module/configs/observation_policy.py:80`),
а `state_store_module` не импортирует `process_module` (grep: 0), так что цикла не возникает. Вариант
`app_module` вдобавок требовал бы нового класса-процесса и правки `process_class` в YAML обоих
приложений. ADR обязан явно назвать отменяемое решение ссылкой на
`app-template-idea.md` §4; сам тот файл не правится (вне FILES). **Решение о месте — архитектурное и отменяет
унаследованное; до старта его подтверждает `cto`** (project-rules §7), см. ESCALATION в отчёте manager.

**Status line:** [PENDING] · **Level:** Senior (Opus) · **Assignee:** teamlead
**Module contract:** impl-only (публичный API `GenericProcess`/`PluginContext` не меняется;
`ctx.state_proxy` уже есть в контракте — `plugins/interfaces.py:260`).
**Handoff (CHAIN):** `tester`(RED, worktree на `a0edf74a`) → `teamlead`(GREEN + hazard-тесты) →
ведущий (break-injection + живой зонд) → `reviewer`(синхронно). Лимит — 2 итерации ревью, третья →
`cto`; лимит действует и при вложенном запуске.

**DESIGN:**
- `GenericProcess` (`generic/generic_process.py:52`) получает `_init_custom_managers()` с ровно тем
  телом, что сейчас в `GenericProcessApp._init_custom_managers` (:23-50): импорт `StateProxy`
  **внутри метода** (ленивый, как сейчас), `logger=self.logger_manager` (не `self` — Task Т.1,
  комментарий :29-36 переносится), `initialize()`, регистрация `state.changed` **до**
  `super()._init_custom_managers()` — оркестратор читает `_state_proxy` внутри этого super-вызова.
- Инъекция через конструктор (`ProcessModule.__init__(state_proxy=...)`, `core/process_module.py:109,133`)
  имеет приоритет: если `self.state_proxy is not None` — `self._state_proxy = self.state_proxy`, свой
  не создаётся и `state.changed` здесь **не** регистрируется (его зарегистрирует шаг 10
  `_init_state_proxy`, :720-739). Иначе — создать свой и **не** присваивать `self.state_proxy`, чтобы
  шаг 10 не сделал второй регистрации (`ExactMatchStrategy.register_handler` на дубликат — WARNING и
  `False`, `dispatch_module/strategies/exact_match.py:33-38`).
- Нет `router_manager` → прокси не создаётся (`_state_proxy` остаётся `None`, heartbeat молчит как
  сейчас). Сознательно без опции «выключить прокси»: YAGNI, хук не нужен ни одному приложению сегодня.
- `GenericProcess.shutdown()`: `self._state_proxy.shutdown()` (если есть) → `super().shutdown()`.
- `GenericProcessApp` остаётся **пустым подклассом** (`pass` + докстринг «исторический адрес,
  116 ссылок `process_class` в YAML прототипа, поведение — у `GenericProcess`»): переименование 116
  ссылок — вне задачи.
- `generic/generic_process.py:333-336` (комментарий «прототип хранит…» и двойной `getattr`) и
  `plugin_orchestrator.py:59` (комментарий «устанавливается подклассами») — поправить текст под новую
  правду; логику io-peek не трогать.

**FILES (6):**
1. `multiprocess_framework/modules/process_module/generic/generic_process.py`
2. `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py` (только комментарий :59)
3. `multiprocess_prototype/generic_process_app.py`
4. `multiprocess_framework/modules/process_module/DECISIONS.md` (+ `python -m scripts.sync`)
5. `multiprocess_framework/modules/process_module/tests/test_generic_process_state_proxy.py` (новый, hazard-тесты автора)
6. `multiprocess_framework/modules/process_module/tests/test_logger_slot_wiring_order.py` (докстринг :8 называет `GenericProcessApp`)

Файлы тестера (свои, в его worktree): `multiprocess_framework/modules/process_module/tests/test_generic_process_state_proxy_acceptance.py`
(один процесс, настоящий `RouterManager`, без спавна), `apps/line_sim/tests/test_state_proxy_live.py` и
приложение-фикстура `apps/line_sim/tests/fixtures/state_proxy_app/` (два процесса на голом `GenericProcess`,
плагин-писатель в A и плагин-читатель в B; живёт в `apps/`, потому что тесту нужен `app_module.run_app`,
а `multiprocess_framework/*` импортировать `app_module` не может — `.sentrux/rules.toml:110-113`). Нужен файл вне списка → стоп и вопрос ведущему.
`README.md`/`STATUS.md` `process_module` и `app_module/DECISIONS.md` (ссылка «клиентская половина —
Task 2.0», :222-224) — строкой в отчёт, не правкой.

**REDS (предсказание тестера на `a0edf74a`, ≤ 10):**
- `…_acceptance.py::test_bare_generic_process_plugin_sees_state_proxy`
- `…_acceptance.py::test_shutdown_unsubscribes_all`
- `apps/line_sim/tests/test_state_proxy_live.py::test_set_in_robot_visible_in_camera_get`
- `apps/line_sim/tests/test_state_proxy_live.py::test_subscribe_glob_receives_event_once`
- `apps/line_sim/tests/test_state_proxy_live.py::test_heartbeat_pushes_camera_fps_to_tree`

**Steps:**
1. `tester` в worktree на `a0edf74a` пишет три файла выше по Acceptance → красный прогон, число
   красных сверено с REDS (расхождение — находка, записать).
2. `teamlead`: baseline до правки — `python scripts/run_framework_tests.py` и
   `pytest multiprocess_prototype -q` (числа в отчёт); затем перенос по DESIGN.
3. `teamlead`: hazard-тесты (`test_generic_process_state_proxy.py`, см. «Ловушки»), ADR-PM-049,
   `python -m scripts.sync`, `python scripts/validate.py`.
4. Прогоны радиуса: `process_module/tests`, `app_module/tests`, `apps/line_sim/tests`,
   `examples/minimal_app/tests`, тесты тестера; `ruff check -q`; `sentrux check .` (CLI).
5. Ведущий: break-injection (матрица ниже) и живой зонд `--app line_sim` + прототип без аргументов.
6. `reviewer` синхронно, на фиксированном SHA.

**Acceptance criteria** (измеримы тестером вслепую, литералы):
- [ ] Плагин в процессе на голом `GenericProcess` (`process_class:
      multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess`) видит
      `ctx.state_proxy is not None` и в `configure_managers(ctx)`, и в `configure(ctx)` — у
      `examples/minimal_app` и `apps/line_sim`.
- [ ] Двухпроцессная фикстура: `set("sim.belt.encoder", {"value": 42})` в A → `get("sim.belt.encoder")`
      в B возвращает `{"value": 42}` не позже 2.0 с; `subscribe("sim.belt.*", cb)` в B, оформленная
      **до** `set`, получает событие с путём `sim.belt.encoder` не позже 2.0 с. Путь нигде не посеян
      (посев — дефолтный, только `processes`).
- [ ] `backend_ctl` той же фикстуры: `state_get("sim.belt.encoder")` → `{"value": 42}`.
- [ ] Один `set` в A → колбэк подписки в B вызван **ровно 1 раз** за 2.0 с (не 0 и не 2).
- [ ] Останов процесса шлёт `state.unsubscribe_all` с `subscriber == <имя процесса>` (ровно 1 сообщение).
- [ ] Зонд `backend_ctl.probes.probe_observability_consumer_acceptance --app line_sim`:
      **R7 = PASS** (снимок `count>0` и ≥1 точка истории `processes.camera.state.fps` за ≤ 12 с);
      **K5 = PASS** (контроль ≥1 дельта `processes.camera.state.{fps,latency_ms}` за 12 с; OFF — 0;
      ON — ≥1). Механизм: появление `_state_proxy` снимает ранний выход `process_heartbeat.py:1355-1357`.
      **Оговорка K5 (не проверено):** контроль гасится, если `fps` и `latency_ms` камеры сима
      стабильны — `TreeStore.set` не даёт дельты на неизменное значение (так строка сама пишет
      о NOT_REACHED). NOT_REACHED с `контроль=0` при наличии `processes.camera.state.fps` в дереве —
      не PASS и не молчаливое принятие: ведущий снимает значения `latency_ms` за 12 с и решает, дефект
      это оси или зонда, с записью в отчёт.
      Прочие строки сима — не хуже прогона после 1.5/1.6 (PASS 37 / FAIL 2 / PARTIAL 4 / NOT_REACHED 6 /
      UNVERIFIED 1 / N/A 2 → ожидаемо PASS 39, PARTIAL 3, NOT_REACHED 5; T1 остаётся FAIL — Task 5.1).
- [ ] Прототип: тот же зонд без аргументов — 51 строка, PASS 41 / FAIL 1 / PARTIAL 3 / NOT_REACHED 5 /
      UNVERIFIED 1, вердикты по id совпадают с baseline; `pytest multiprocess_prototype` и
      `python scripts/run_framework_tests.py` — не ниже baseline шага 2 (числа в отчёт).
- [ ] В `multiprocess_prototype/generic_process_app.py` нет `StateProxy(`, `register_message_handler`
      и `shutdown` (grep: 0).
- [ ] `sentrux check .` (CLI) — все правила зелёные; `python scripts/validate.py` — зелёный.

**Break-injection (ведущий; предсказание записать ДО прогона):**
| # | Инъекция | Должны умереть |
|---|---|---|
| I1 | удалить создание прокси в `GenericProcess` | все REDS тестера, R7/K5 зонда |
| I2 | создавать прокси **после** `super()._init_custom_managers()` | `test_bare_generic_process_plugin_sees_state_proxy` (ctx без прокси), set/get фикстуры |
| I3 | не регистрировать `state.changed` | `test_subscribe_glob_receives_event`; `get` из кэша — нет, IPC-фолбэк проходит (ожидаемо зелёный — зафиксировать) |
| I4 | регистрировать и в `_init_custom_managers`, и присвоить `self.state_proxy` | только hazard-тест автора на реестр dispatcher'а: наблюдаемого эффекта нет (первый выигрывает, `_warn_log` стратегии по умолчанию — no-op, `dispatch_module/strategies/base_strategy.py:33`) — тестер это поймать не может, и это ожидаемо |
| I5 | убрать `proxy.shutdown()` из `GenericProcess.shutdown` | `test_shutdown_unsubscribes_all` |
| I6 | `logger=self` вместо `self.logger_manager` | hazard-тест автора на слот логгера (см. Т.1) |

**Edge cases:**
- `router_manager is None` (частичная сборка/тестовый стенд) → `_state_proxy is None`, исключения нет.
- Прокси, переданный конструктором, — используется он, второй не создаётся, handler один.
- Приложение с явным `state_bootstrap` → `{}`: store нет, прокси есть. Поведение фиксируется тестом
  автора как **текущее** (heartbeat шлёт merge в PM без обработчика), не чинится — строка в отчёт.
- Процесс без плагинов (`config.plugins` пуст): прокси всё равно создаётся — heartbeat пишет здоровье.
- `GenericProcessApp` в прототипе: тот же объект поведения, 116 YAML-ссылок продолжают резолвиться.

**Ловушки для автора (hazard-тесты):**
- **Порядок.** `_state_proxy` обязан существовать до `PluginOrchestrator.load_and_configure_managers`
  (`plugin_orchestrator.py:60`), а `logger_manager` — до создания прокси (шаг 3 `_init_managers`
  раньше шага 6, `core/process_module.py:227-236`); пиновка — расширить
  `test_logger_slot_wiring_order.py` (`_CONSUMERS`, :45), а не новый механизм.
- **Регистрация на живом приёмнике.** Handler ставится на шаге 6, до старта `message_processor`
  (шаг 7) — окна, где `state.changed` приходит без обработчика, быть не должно; не переносить в шаг 10.
- **Двойная регистрация** (см. DESIGN): первый выигрывает **молча** (`_warn_log` по умолчанию no-op) —
  тест автора читает реестр обработчиков dispatcher'а по ключу `state.changed`, не лог.
- **Реентерабельность.** `get`/`subscribe(sync=True)` из обработчика на приёмном потоке роутера
  бросает `RouterReentrantRequestError` (`proxy/state_proxy.py:1506`) — это контракт, не глотать;
  в докстринге `GenericProcess` назвать, что плагин не зовёт синхронный `get` из message-handler.
- **Прототип получает прокси по новой дороге.** Процессы прототипа, у которых `process_class` не задан
  (дефолт — `GenericProcess`, `generic_process_config.py:72`), сейчас без прокси и начнут публиковать
  здоровье/телеметрию в дерево. Есть ли такие — **не проверено** (grep YAML дал 116 `GenericProcessApp`,
  5 `GenericProcess` только в `apps/`/`examples/`; сборка топологии кодом не просматривалась). Сверить
  `system_overview` прототипа до/после; новые ветки `processes.<p>.*` — находка, не норма.
- **Порядок останова.** `proxy.shutdown()` шлёт `state.unsubscribe_all` через роутер — вызывать до
  `super().shutdown()`, пока роутер жив.

**Out of scope:** пути состояния симулятора (`sim.belt.*` в коде плагинов — Task 2.2); уровни плагинов
сима (T1 — Task 5.1); переименование 116 ссылок `GenericProcessApp`; поведение приложения без store
(явный `{}`); правка `app-template-idea.md`, `app_module/DECISIONS.md`, README/STATUS модулей.
**Dependencies:** Task 1.0, Task 1.5 (гейт телеметрии активен — без него R7/K5 не измеримы).

---

### Task 2.1 — Модель ленты `BeltDrive`: команда ПЧ → скорость → энкодер

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** живая команда ПЧ (та же, что инспектор шлёт на железо через мост
`vfd_belt → robot_main`) меняет **фактическую** скорость приращения энкодера. Лента —
отдельный класс; ядро робота ей пользуется, а не содержит её внутри.

**Контекст:** `RobotSimCore._handle_vfd` уже эмулирует зеркало ПЧ (mailbox `0x1200` /
зеркало `0x1210`, обновление только по пульсу `VFD_FLAG` — как в боевой Lua), но
`_enc_rate` — константа из `__init__`: «инспектор притормозил конвейер» в симе сегодня не
происходит. Ред. 1 предлагала дописать формулу прямо в `_handle_vfd` — отвергнуто:
конвейер — самостоятельное устройство каталога ([`vision.md`](vision.md) §Каталог), и
когда появится ПЧ без моста (`Services/vfd_comm/protocols/gd20_direct.yaml`), той же лентой
должен уметь управлять другой хост. Поэтому: класс ленты + внедрение через конструктор.

Масштаб «Гц → мм/с» реального стенда в коде не найден — остаётся конфигурируемым
параметром (владелец: «точность мира — примерная, достаточно»). Это калибровочная ручка,
а не константа.

**Files:**
- НОВЫЙ `Services/robot_comm/server/belt.py` — `BeltDrive`
  (`# ponytail:` лежит рядом с единственным потребителем; переезжает в `Services/line_sim`,
  когда лентой начнёт управлять второй хост)
- `Services/robot_comm/server/sim_core.py` — `RobotSimCore.__init__(…, belt: BeltDrive |
  None = None)`, `_handle_vfd`, `tick`
- `Services/robot_comm/server/__main__.py` — `--belt-mm-s` строит `BeltDrive`
- `Services/robot_comm/tests/test_belt_drive.py` — тесты автора (hazard)
- `Services/robot_comm/tests/test_sim_register_map_contract.py` — контракт карты регистров
- `Services/robot_comm/server/README.md`, `STATUS.md`

**Steps:**
1. Выяснить по `Services/vfd_comm` (карта `gd20_bridge.yaml`, scale регистра частоты), в
   каких единицах приходит `regs[_REG_VFD_CMD_FREQ]`; зафиксировать масштаб в docstring.
2. `BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)`:
   `command(run: bool, freq_hz: float, reverse: bool = False)`;
   `advance(dt_s: float) -> int` — приращение энкодера в отсчётах за `dt_s`;
   свойство `mm_s`. **Дробный остаток копится между вызовами** — средняя скорость точна
   при любом `dt_s`. Нынешняя формула `max(1, round(...))` так не умеет: она округляет на
   каждом тике и не даёт ленте ехать медленнее одного отсчёта за тик — на малой частоте
   это тихая ложь о скорости.
   `BeltDrive.from_enc_rate(enc_rate, tick_s)` — лента с постоянной скоростью,
   эквивалентной старому параметру.
3. `RobotSimCore`: `belt=None` → `BeltDrive.from_enc_rate(enc_rate, TICK_INTERVAL_S)`
   (поведение до первой команды ПЧ не меняется); `tick()` зовёт `belt.advance(dt)`;
   `_handle_vfd` при пульсе `VFD_FLAG` зовёт `belt.command(run, freq_hz, reverse)`.
   Скорость меняется **только в момент пульса** — это ограничение прошивки, воспроизведено
   намеренно; слово «плавно» нигде не писать.
4. Контракт-тест карты регистров (принцип 3 видения): адреса mailbox ПЧ, которыми
   пользуется `sim_core`, совпадают с адресами из `gd20_bridge.yaml`, откуда их читает
   драйвер. Сегодня это две копии (`sim_core.py:71-76` и yaml) — тест делает расхождение
   красным.
5. Hazard-тест автора: единственный писатель скорости — `tick()` на ticker-потоке;
   проверять синхронно, прямым вызовом `tick()`, без `time.sleep`.

**Acceptance criteria:**
- [ ] `BeltDrive(100.0, 50.0)`; `command(run=True, freq_hz=25.0)`; сумма `advance(0.01)`
      за 1000 вызовов равна **3461** ±1 отсчёт (половина частоты → 50 мм/с →
      500 мм за 10 с; 500 / 0.144473 = 3460.85). В тесте — литерал, а
      `FACTOR_MM == 0.144473` проверяется отдельным assert.
- [ ] `command(run=False, …)` → сумма `advance` равна 0.
- [ ] Малая скорость: `command(run=True, freq_hz=0.5)` (1 мм/с) → за 1000 вызовов
      `advance(0.01)` сумма равна **69** ±1 (10 мм / 0.144473 = 69.2), а **не** 1000
      (старый пол «не меньше отсчёта за тик»).
- [ ] `RobotSimCore(enc_rate=7)` без единой команды ПЧ: энкодер за N тиков растёт так же,
      как до задачи — существующие `test_sim_e2e.py` зелёные без правок.
- [ ] После записи команды ПЧ (run=1, freq, `vfd_flag=1`) и `tick()` скорость ленты
      соответствует команде; конструкторный `enc_rate` больше не действует.
- [ ] Сдвиг любого адреса mailbox в `sim_core.py` на 1 → контракт-тест карты красный.
- [ ] `pytest Services/robot_comm -q` — 0 failed, passed не ниже baseline 127.

**Out of scope:** разгон/торможение по рампе; публикация энкодера наружу (Task 2.2).
**Edge cases:** `freq_max_hz <= 0` → скорость 0 и предупреждение в лог, не исключение;
`freq_hz` вне `[0, freq_max_hz]` → clamp; `reverse=True` → отрицательное приращение
(энкодер квадратурный), знак покрыт тестом.
**Dependencies:** нет. **Module contract:** new-lite (`belt.py`).

---

### Task 2.1b — Лента по реальному времени: `tick(dt_s)` с измеренным dt

**Level:** Middle (Sonnet) · **Assignee:** developer · **Module contract:** impl-only
**Основание:** ревью 2.1 — тикер `SimRobotServer._ticker` делает `tick()` + `sleep(0.01)`, реальный
период 11.96 мс (macOS), а лента считает dt = 0.01 → по часам едет на ≈16 % медленнее команды.
**DESIGN:** `RobotSimCore.tick(dt_s: float | None = None)`, None → `TICK_INTERVAL_S` (все прямые
вызовы и тесты не меняются); `_ticker` меряет `time.monotonic()` между тиками и передаёт dt,
ограниченный сверху `_MAX_TICK_DT_S = 0.1` (`# ponytail:` — пауза процесса не превращается в прыжок
ленты). Сырой режим `from_enc_rate` остаётся «enc_rate за тик» (легаси-смысл параметра).
**FILES:** `Services/robot_comm/server/sim_core.py`, `sim_robot.py`, `tests/test_belt_drive.py`, `server/README.md`.
**Acceptance:** `tick(0.02)` ×500 == `tick(0.01)` ×1000 == 3461±1 при 25 Гц; живой `SimRobotServer` с
лентой 100 мм/с и командой 50 Гц за 2.0 с по часам даёт 1384 ±3 % отсчётов (200 мм / 0.144473; сегодня ≈1160, −16 %);
`pytest Services/robot_comm -q` — 0 failed. **Dependencies:** 2.1.

---

### Task 2.2 — Энкодер в общем мире: робот публикует, сцена едет

**Решение ведущего по чтению мира (2026-09-21, по разведке `state_proxy.py:288-345,1307-1337`):**
кэш `StateProxy` наполняют только дельты подписки, и кладёт он листья; без подписки `get` — всегда
синхронный IPC (до 5 с), из приёмного потока — `RouterReentrantRequestError`. Поэтому шаг 2 ниже
меняется: `SceneSourcePlugin` в `configure` делает `subscribe("sim.belt.**", cb, sync=False)`, колбэк
складывает последнее значение (и цельный dict дельты создания, и полистовые дельты
`sim.belt.encoder.value`/`.t`) в поле плагина; `produce()` читает поле — ни одного IPC на кадр.
Прежняя формулировка «без колбэков» исходила из дешёвого `get`, которого нет.


**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** процесс `robot` публикует энкодер в мир симулятора; процесс `camera` рисует
**один** тестовый спрайт, положение которого считается из этого значения. Видимое
доказательство: остановил ленту командой ПЧ — спрайт в MJPEG-потоке замер.

**Files:**
- `Plugins/sim/robot_host/plugin.py` — throttled-паблишер энкодера
- НОВЫЙ `Plugins/sim/scene_source/{__init__.py, plugin.py, README.md, STATUS.md, tests/}` —
  `SceneSourcePlugin`: source-плагин **внутри симулятора** (образец формы —
  `Plugins/sources/synthetic_frame_source`). В этой задаче — фон + один спрайт-заглушка;
  движок слоёв подключается в Ф3.4
- `apps/line_sim/pipeline.yaml` — процесс `camera`: `scene_source` → `mjpeg_sink`
  (заменяет заглушку `camera_service/simulator` из Task 1.2); параметр `seed` стенда
- `apps/line_sim/README.md` — путь мира `sim.belt.encoder`

**Steps:**
1. Паблишер в `SimRobotHostPlugin`: каждые `publish_ms` (дефолт 50) —
   `ctx.state_proxy.set("sim.belt.encoder", {"value": core.encoder, "mm_s": belt.mm_s,
   "t": time.monotonic()})`. Без `state_proxy` (Task 2.0 не влита) — плагин живёт,
   `status` сообщает `world: unavailable`.
   Это **состояние мира** — его потребляет сцена. **Наблюдение** идёт отдельной дорогой:
   на том же такте `publish_metric("encoder", …)`, `publish_metric("belt_mm_s", …)`,
   `publish_metric("writes_seen", …)` — уровни с именем (раздел «Наблюдаемость» плана).
   Заодно закрывается замечание ревью Ф1: сегодня `record_metric` зовётся только из
   `cmd_status`/`shutdown`, и без опроса статуса числа не текут.
2. `SceneSourcePlugin.produce()`: читает `ctx.state_proxy.get("sim.belt.encoder",
   default=…)` на каждом кадре (без колбэков — меньше связности), хранит последнее
   значение. Мир пуст (процесс `robot` ещё не поднялся) → кадр с объектом в исходной
   позиции, без исключения.
3. Позиция спрайта: `x_px = (encoder − spawn_encoder) × FACTOR_MM × px_per_mm`;
   `FACTOR_MM` — импортом из `Services.robot_comm.core.registers`, не копией числа.
4. Hazard-тест автора: гонка старта процессов; дыра в публикации (значение старше
   `stale_ms`) — сцена замирает и пишет предупреждение, а не экстраполирует.

**Acceptance criteria** (сим поднят, `backend_ctl` на 8766):
- [ ] `state_get("sim.belt.encoder")` — два снятия с интервалом 1 с, второе `value`
      строго больше первого.
- [ ] Команда «стоп» ПЧ боевым клиентом (`Services/vfd_comm`, протокол `gd20_bridge`, на
      `127.0.0.1:5021`; если его API этого не позволяет — сырой записью mailbox-регистров
      pymodbus-клиентом, с пометкой в отчёте) → два снятия подряд равны. Команда «пуск» с
      `freq_hz > 0` → рост возобновился.
- [ ] Кадры из `http://127.0.0.1:8091/`: центр масс спрайта смещается монотонно, пока
      энкодер растёт, и неподвижен (±1 px), пока лента стоит.
- [ ] Поднят только процесс `camera` (без `robot`) → поток отдаёт кадры, исключений в
      `errors.log` нет.
- [ ] `introspect_telemetry` (порт 8766) → в `levels` процесса `robot` есть `belt_mm_s` и
      `encoder` писателя `sim_robot_host`; после команды «стоп» ПЧ `belt_mm_s == 0`.
      Опрашивать `sim_robot.status` для этого не требуется. (Если уровни не читаются у
      generic-приложения — разрыв ловит Task 1.4; здесь критерий остаётся красным, а не
      переписывается.)
- [ ] В `Plugins/sim/scene_source` нет импортов `Plugins.sim.robot_host` и
      `multiprocess_prototype` (принцип 5: модели не знают друг друга).

**Входящие хвосты из 2.0/2.1 (2026-09-21, решить в спеке до старта):**
- `StateProxy` кладёт dict-значение в кэш листьями (`sim.belt.encoder.value`), поэтому
  `get("sim.belt.encoder")` кэш не находит и **всегда** уходит в синхронный IPC
  (`state_proxy.py:302,1320-1337`); из приёмного потока это `RouterReentrantRequestError` (:1506).
  Сцена читает энкодер на каждом кадре → либо читать лист `sim.belt.encoder.value`, либо
  подписка + последнее значение, либо сборка поддерева из кэша в `state_store_module` (отдельная задача).
- Реальный период тикера `SimRobotServer` ≈ 11.96 мс против dt ядра 0.01 с (замер ревью 2.1,
  macOS) → лента по часам едет на ≈16 % медленнее команды. Для «спрайт едет со скоростью ленты» —
  `tick(dt)` с измеренным dt или признать погрешность числом в README.

**Out of scope:** несколько объектов, спавн/деспавн, реальные спрайты (Ф3).
**Edge cases:** переполнение энкодера (32-бит signed, `RegDW(signed=True)`) — в README
числом: сколько часов прогона на типичной скорости до переполнения; v1 на более длинные
прогоны не рассчитан, и это сказано явно.
**Dependencies:** Task 1.2 (`mjpeg_sink`), Task 2.0, Task 2.1.
**Module contract:** new-lite (`Plugins/sim/scene_source/plugin.py`).
