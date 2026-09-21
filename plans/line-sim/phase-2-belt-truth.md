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

**Статус: [DONE] 2026-09-21** — robot_comm 146 passed; инъекции J1–J3 + сырой режим 4/4; ревью: сырой режим тоже по реальному dt (скачок +18 % при первой команде снят), `perf_counter`, изоляция теста часов.
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

---

### Task 2.3 — Пульт ленты: одна командная поверхность, три клиента (новая, 2026-09-22)

**Решение владельца (2026-09-22):** веб-страница сима делается СЕЙЧАС, до Ф3; лентой управляют три
клиента — веб-страница, `backend_ctl` и прототип. Фаза 2 открыта заново ради этой задачи.
Пересечение с Ф6.1 ред. 3 («пульт командами через `backend_ctl`, GUI не пишется»): 2.3 закрывает
ленточную часть 6.1 и **отменяет** для ленты пункт «GUI не пишется» (решение владельца новее);
ручки потока/брака/паузы остаются за 6.1.

Задача режется на две (REDS > 10 в одной): **2.3a** — командная поверхность в `robot`,
**2.3b** — процесс `pult` с веб-страницей. 2.3b зависит от 2.3a.

#### Разведка (2026-09-22, qex недоступен — Ollama лежит; всё ниже сверено `grep`/чтением на `eb5995d2`)

1. **Команда плагина другому процессу с ответом.** `PluginContext` отдаёт `ctx.router_manager`
   (`multiprocess_framework/modules/process_module/plugins/base.py:103`) и `ctx.send_message`
   (`:139`). `ctx.io.send_command` (`process_module/io/process_io.py:58-73`) — fire-and-forget,
   возвращает `bool`, ответа не даёт. Синхронный запрос-ответ — `RouterManager.request(msg,
   timeout)` (`router_module/core/router_manager.py:1015`); с приёмного потока бросает
   `RouterReentrantRequestError` (`:56`, проверка `_assert_not_receive_thread` в теле `request`),
   до первого приёмного цикла возвращает `{"success": False, "error": "timeout", "reason":
   "no_receive_pump"}`. Неблокирующий вариант — `request_async(msg, on_response, timeout)` (`:1106`).
   **Готовый образец плагина-клиента:** `Plugins/hub/device_hub/client.py` — `DeviceHubClient(ctx,
   target_process=..., default_timeout=...)`: `build_command_message` + `router.request` +
   нормализация ответа PM-обёртки `{"success", "data": {"result"}}` → `{"status": "ok"|"error", ...}`
   (`:17-44`, `:73-120`). Контракт потока в его докстринге: только из worker-потока, не из
   приёмного цикла. Потоки `ThreadingHTTPServer` — не приёмный цикл, значит `request` из
   HTTP-обработчика законен.
2. **Регистрация и имена команд.** `ProcessModulePlugin.commands = {"<имя>": "<метод>"}`;
   `_auto_register_commands` (`plugins/base.py:1585-1611`) регистрирует имя **дословно** в
   `CommandManager` процесса (`ctx.command_manager.register_command(cmd_name, method)`), без
   префикса процесса или плагина. Живой образец: `"sim_robot.status": "cmd_status"`
   (`Plugins/sim/robot_host/plugin.py:84-86`). `backend_ctl` адресует пару «процесс + имя»:
   `drv.send_command("robot", "sim_robot.status")` (`backend_ctl/driver.py:657-667`; вызов в
   `apps/line_sim/tests/test_f1_task11_acceptance.py:307`, ответ разворачивается `_result` —
   `res["result"]`, `:78-82`). MCP-инструмент — `mcp__backend-ctl__send_command` с теми же
   `target`/`command`/`args`. Каталог команд виден без исходников через `introspect_handlers("robot")`.
3. **HTTP-сервер в плагине — прецедент есть.** `Plugins/sim/mjpeg_sink/plugin.py`: конструктор
   `ThreadingHTTPServer((host, port), handler_cls)` в `try/except OSError` — занятый порт ловится
   синхронно, потому что stdlib биндит в конструкторе (`:240-259`, докстринг `:17-31`);
   `serve_forever` в daemon-потоке (`:252`); обработчик — фабрика класса с замыканием на плагин
   (`_build_handler`, `:98-140`), `log_message` заглушён (`:107`); `shutdown()` → `server.shutdown()`
   (`:179-190`), открытые потоковые соединения переживают `shutdown` до дисконнекта (`:55-64`).
   Повторяем форму один в один.
4. **Потокобезопасность записи `core.regs`.** Сегодня регистры пишут и читают **без замка**:
   `pymodbus` пишет в живой список со своего event-loop-потока (хук `binder` зовётся ДО применения
   записи, `Services/robot_comm/server/sim_robot.py:66-89`), тикер `sim-robot-motion` читает и
   мутирует тот же список (`:158-182`); докстринг модуля опирается на GIL (`:12-14`). Порядок
   держит протокол mailbox, а не замок: данные пишутся раньше, `VFD_FLAG` (0x1204) — последним
   (`Services/vfd_comm/core/client.py:66-91`), тикер применяет команду только при `FLAG == 1` и
   сам его гасит (`sim_core.py:342-370`). Запись плагина `core.write(addr, values)`
   (`sim_core.py:197-200`, поэлементно по возрастанию адреса) с тем же порядком «данные, потом
   флаг» — ровно та же дорога. Две оговорки, которых у Modbus-пути нет: (а) `attach()`
   (`sim_core.py:185-191`) копирует буфер и ПОТОМ подменяет ссылку — запись плагина между этими
   двумя строками теряется (окно — только первый запрос первого Modbus-клиента); (б)
   `BeltDrive` читает и пишет `_mm_s` из тикера, а новая `set_calibration` будет звать его с потока
   команды — гонка «прочитал прошлую команду / тикер применил новую / записал пересчёт по
   старой», нужен замок внутри `BeltDrive` (см. DESIGN 2.3a).

**Ещё два факта разведки, влияющих на дизайн:**
- Прототип зовёт `VfdClient.poll()` — это пульс `VFD_FLAG` **без** данных (`client.py:108-118`), а
  сим на каждом пульсе заново применяет то, что лежит в `CMD_RUN/DIR/FREQ` (`sim_core.py:351-356`).
  Значит опрос прототипа команду пульта не затирает — затирает только его явная команда
  (`run`/`stop`/`set_freq`). `stop()` прототипа пишет **только** `cmd_run=0`, `set_freq` — только
  `cmd_freq`: mailbox — общий набор регистров, команды частичные.
- Дефолтная калибровка `101.1311` мм/с — не константа, а `BeltDrive.from_enc_rate(7, 0.01)`:
  `7 × FACTOR_MM(0.144473) / 0.01` (`belt.py:88`, `registers.py:35`). До первой команды ПЧ лента
  в «сыром» режиме едет на этой скорости, а зеркало ПЧ (0x1210…) — нули.

---

### Task 2.3a — Командная поверхность ленты в процессе `robot`

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer (Sonnet, extended)
- **CHAIN:** `tester`(RED по приёмке, worktree на коммите до реализации) -> `developer`(GREEN + hazard-тесты) -> ведущий(инъекции) -> `reviewer`
- **Module contract:** public-api-change (`Services/robot_comm/server/belt.py`, `sim_core.py` —
  новые публичные члены; плагин — новые команды)

**TASK.** Процесс `robot` получает пять команд ленты; все, кроме `calibrate` и `status`, пишут
mailbox ПЧ в ядро тем же путём, что Modbus-запись инспектора, и применяются на ближайшем тике.

**DESIGN.**
1. `BeltDrive` (`Services/robot_comm/server/belt.py`):
   - `command()` запоминает последнюю команду в `self._last = (run, freq_hz_clamped, reverse)`.
   - Новое `set_calibration(mm_s_at_max_freq: float) -> None`: `ValueError` при `< 0`, NaN, inf.
     Под `self._lock` (новый `threading.Lock`, его же берёт `command()`): записать калибровку;
     если лента в «сыром» режиме (`_raw_rate is not None`) — выйти из него так, будто пришла
     команда `run=True, freq=freq_max_hz, reverse=False` (лента едет дальше, на новой скорости);
     иначе пересчитать `_mm_s` из `_last`. Порядок присваиваний: сначала `_mm_s`, потом
     `_raw_rate = None` — `advance()` без замка читает по одному атрибуту.
   - Свойства только для чтения: `mm_s_at_max_freq`, `freq_max_hz`, `state -> dict {run, freq_hz,
     reverse}`; в «сыром» режиме `state` = `{run: True, freq_hz: freq_max_hz, reverse: False}`.
   - `advance()` замок НЕ берёт (горячий путь тикера, одно чтение `_mm_s`).
2. `RobotSimCore` (`sim_core.py`): публичное свойство `belt -> BeltDrive` и метод
   `command_vfd(*, run: bool | None = None, freq_hz: float | None = None, reverse: bool | None = None)`:
   пишет только переданные поля (`CMD_RUN` 0x1200, `CMD_DIR` 0x1201, `CMD_FREQ` 0x1202 =
   `round(freq_hz * _VFD_FREQ_SCALE)`) через `self.write`, затем ОТДЕЛЬНЫМ последним вызовом
   `self.write(_REG_VFD_FLAG, [1])`. Частичность — как у `VfdClient`: `stop` пишет только RUN.
   Адреса не дублировать в плагине — плагин знает только `command_vfd`.
3. `SimRobotHostPlugin` (`Plugins/sim/robot_host/plugin.py`), новые команды в `commands`:
   | Команда | args | Что пишет | Ответ |
   |---|---|---|---|
   | `belt.run` | `freq_hz: float` (обяз.), `reverse: bool = False` | `command_vfd(run=True, freq_hz, reverse)`; снимает jog | статус |
   | `belt.stop` | — | `command_vfd(run=False)`; снимает jog | статус |
   | `belt.jog` | `direction: +1\|-1` (обяз.), `freq_hz: float = jog_freq_hz` | `command_vfd(run=True, freq_hz, reverse=direction<0)`; продлевает дедлайн `now + jog_timeout_ms` | статус |
   | `belt.calibrate` | `mm_s_at_max_freq: float` (обяз.) | `core.belt.set_calibration(...)`; mailbox не трогает | статус |
   | `belt.status` | — | ничего | статус |
   Статус: `{ok: True, run, freq_hz, reverse, mm_s, encoder, jogging, mm_s_at_max_freq}`;
   `run/freq_hz/reverse` — из `core.belt.state` (ЭФФЕКТИВНОЕ состояние, кто бы ни писал mailbox),
   `mm_s` — `core.belt_mm_s`, `encoder` — `core.encoder`. Команда пишет mailbox и возвращает
   статус сразу — он может ещё не отражать команду (применение на следующем тике, ≤ ~12 мс);
   клиенты опрашивают `belt.status`. Ошибки — `{ok: False, error: "<код>: <текст>"}`, без
   исключения наружу: `bad_args` (нет поля, не число, `freq_hz ∉ [0, freq_max_hz]`, `direction ∉
   {1, -1}`, калибровка `< 0`/NaN), `server_not_running` (`self._server is None`).
   Валидация частоты — как `VfdClient._validate_freq` (`client.py:140-145`): вне диапазона —
   отказ, не клэмп.
4. Dead-man jog. Поля плагина `_jog_deadline: float | None`, `_jog_regs: tuple` (что записал
   jog) под `self._lock`. Проверка — в `_publish_loop` на каждом тике (`publish_ms`, 50 мс), НЕ
   отдельным потоком: если `_jog_deadline` прошёл → `command_vfd(run=False)` **только если**
   mailbox всё ещё равен `_jog_regs` (`core.read(0x1200, 3)`; адрес — через константу ядра,
   экспортируй кортеж `VFD_CMD_ADDR` рядом с `command_vfd` или метод `vfd_mailbox()`); иначе
   jog считается перебитым другим писателем — снять флаг jog, ленту НЕ трогать. `belt.run`/
   `belt.stop` снимают jog безусловно. Конфиг: `jog_timeout_ms` (дефолт 500), `jog_freq_hz`
   (дефолт 10.0).
5. Начальная калибровка: параметр плагина `belt_mm_s_at_max_freq` в `apps/line_sim/pipeline.yaml`
   (`101.1311` — равен сегодняшнему дефолту, поведение стенда не меняется). В `_start_server`
   после создания сервера: если ключ задан — `server.core.belt.set_calibration(v)` **и** стартовая
   команда `command_vfd(run=True, freq_hz=freq_max_hz, reverse=False)` через mailbox (решение
   ведущего 2026-09-22): лента едет с первого тика, как сегодня, но зеркало ПЧ, `belt.status` и
   скорость согласованы с самого старта — «run=True при нулевом зеркале» не бывает. Нет ключа —
   «сырой» режим как сегодня. Живой тест: сразу после старта `belt.status` = run/50 Гц/101.13 и
   зеркало ПЧ (`0x1210…`) показывает тот же run.
6. **Арбитраж.** Один mailbox, два мастера (Modbus-клиент прототипа и команды `belt.*`) — побеждает
   последний записавший, как у реального ПЧ с двумя мастерами. Замков и приоритетов не вводим.
   `belt.status` всегда показывает эффективное состояние ленты, а не последнюю команду
   конкретного клиента.

**FILES.**
1. `Services/robot_comm/server/belt.py`
2. `Services/robot_comm/server/sim_core.py`
3. `Services/robot_comm/tests/test_belt_drive.py` (автор: hazard-тесты замка и порядка)
4. `Plugins/sim/robot_host/plugin.py`
5. НОВЫЙ `Plugins/sim/robot_host/tests/test_belt_commands.py`
6. `Plugins/sim/robot_host/README.md` (+ `STATUS.md` одной строкой — седьмой файл, docs)
7. `apps/line_sim/pipeline.yaml` (ключи `belt_mm_s_at_max_freq`, `jog_timeout_ms`, `jog_freq_hz`)

**REDS** (слепые, из приёмки; `tester` пишет их в worktree на `eb5995d2`-или-позже, до реализации;
плагин в тестах — через `configure/start` с фейковым `ctx` и настоящим `RobotSimCore`, либо
`SimRobotServer` на свободном порту):
1. `Services/robot_comm/tests/test_belt_calibration.py::test_set_calibration_rescales_running_belt` —
   `command(True, 25)`, затем `set_calibration(200.0)` → `mm_s == 100.0`.
2. `…::test_set_calibration_leaves_raw_mode_at_max_freq` — `from_enc_rate(7, 0.01)`,
   `set_calibration(200.0)` → `mm_s == 200.0`, `state == {run: True, freq_hz: 50.0, reverse: False}`.
3. `…::test_set_calibration_rejects_negative_and_nan` — `-1.0` и `float("nan")` → `ValueError`,
   калибровка прежняя.
4. `Plugins/sim/robot_host/tests/test_belt_commands.py::test_run_25hz_default_calibration` —
   `belt.run {freq_hz: 25}` + один `core.tick()` → `belt.status.mm_s == pytest.approx(50.5656, abs=0.5)`,
   `run is True`, `freq_hz == 25.0`.
5. `…::test_command_goes_through_mailbox` — после `belt.run {freq_hz: 25, reverse: true}` и ДО тика:
   `core.read(0x1200, 3) == [1, 1, 2500]`, `core.read(0x1204, 1) == [1]`; после тика `0x1204 == 0`,
   зеркало `0x1210 == 1`, `0x1211 == 2500`.
6. `…::test_stop_writes_only_run` — `belt.run {freq_hz: 30}`, тик, `belt.stop`, тик → `mm_s == 0.0`,
   `core.read(0x1202, 1) == [3000]` (частота не тронута).
7. `…::test_calibrate_200_then_run_50` — `belt.calibrate {mm_s_at_max_freq: 200}`, `belt.run
   {freq_hz: 50}`, тик → `mm_s == 200.0`, `mm_s_at_max_freq == 200.0`.
8. `…::test_jog_without_refresh_stops_in_window` — `belt.jog {direction: -1, freq_hz: 10}` при
   `jog_timeout_ms=500`, реальный паблишер (`publish_ms=50`) и реальный тикер: `mm_s < 0` сразу
   после тика; остановка (`mm_s == 0.0`) наступает в окне `[0.5, 1.0]` с от команды; с
   подкачкой `belt.jog` каждые 200 мс лента едет ≥ 1.5 с.
9. `…::test_modbus_write_overrides_jog` — `belt.jog {direction: 1}`, затем прямая запись
   `core.write(0x1200, [1, 0, 4000]); core.write(0x1204, [1])` (как Modbus-мастер), ждать 1.0 с →
   лента едет, `mm_s == pytest.approx(80.905, abs=0.5)`, `jogging is False`.
10. `…::test_bad_args_and_no_server` — `belt.run {freq_hz: 60}` → `ok False`, `error` начинается с
    `bad_args`; `belt.jog {direction: 0}` → `bad_args`; сервер не поднят (`auto_start: false`) →
    `belt.status` → `server_not_running`.

**ACCEPTANCE** (живой стенд `apps/line_sim`, `backend_ctl` на 8766):
- [ ] `send_command("robot", "belt.run", {"freq_hz": 25})` → через ≥ 0.2 с `send_command("robot",
      "belt.status")["result"]["mm_s"]` = **50.57 ± 0.5**; `state_get("sim.belt.encoder")` растёт;
      `introspect_telemetry("robot")` → уровень `belt_mm_s` ≈ 50.57.
- [ ] `belt.calibrate {mm_s_at_max_freq: 200}` → `belt.run {freq_hz: 50}` → `mm_s == 200.0`;
      `belt.calibrate {101.1311}` возвращает стенд в исходное.
- [ ] `belt.jog {direction: 1}` один раз, без подкачки → `mm_s == 0.0` спустя **0.5–1.0 с**
      (два снятия `belt.status`: на 0.3 с ещё едет, на 1.2 с стоит).
- [ ] Путь прототипа: `belt.run {25}`, затем «стоп» боевым `VfdClient.stop()` (`gd20_bridge`,
      `127.0.0.1:5021`) → `belt.status`: `run False`, `mm_s 0.0`. Затем `VfdClient.poll()` не
      запускает ленту (частота 25 Гц лежит, `run` 0).
- [ ] `introspect_handlers("robot")` перечисляет все пять `belt.*` и прежний `sim_robot.status`.
- [ ] Регресс: `Services/robot_comm/tests` и `Plugins/sim/robot_host/tests` зелёные; стенд без
      команд ведёт себя как до задачи (лента 101.13 мм/с с момента старта).

**Hazard-тесты автора (в `test_belt_drive.py` / hazard-файл плагина):**
- гонка `set_calibration` ↔ `command` из двух потоков (10⁴ итераций): итоговый `mm_s` равен
  пересчёту по последней применённой команде — без замка тест обязан падать хотя бы иногда;
  если не ловится стабильно — принудить переключение (`sys.setswitchinterval(1e-6)`) и сказать это;
- `advance()` не берёт замок (замер: в тике нет `acquire` — проверять эффектом: тикер не встаёт,
  пока другой поток держит замок `BeltDrive` 0.2 с);
- порядок «данные → флаг»: подменить `core.write` шпионом по адресам И проверить эффект — тикер,
  прерывающий `command_vfd` между записями (ручной `tick()` после первой записи), не применяет
  полкоманды: `FLAG` ещё 0;
- тест, который может зависнуть (ожидание остановки jog), — вызов в daemon-потоке с `join`-дедлайном.

**Break-injection (ведущий; ожидание записано ДО прогона):**
| # | Инъекция | Должны упасть |
|---|---|---|
| A1 | `command_vfd` пишет FLAG первым | 5, hazard «порядок» |
| A2 | `set_calibration` не пересчитывает `_mm_s` | 1, 2, 7 |
| A3 | убрать замок в `BeltDrive` | hazard гонки (с оговоркой о стабильности) |
| A4 | watchdog jog выключен | 8 |
| A5 | watchdog стопит без сравнения mailbox | 9 |
| A6 | `belt.stop` пишет `run=0, freq=0` | 6 |
| A7 | клэмп вместо отказа `freq_hz > 50` | 10 |
| A8 | статус из последней команды плагина, а не из `belt.state` | 9, приёмка «путь прототипа» |
| A9 | `advance()` берёт замок | hazard «тикер не встаёт» |

**OUT OF SCOPE:** рампа разгона/торможения; ручка `freq_max_hz`; учёт «кто последний писал»
(поле `source` в статусе — если понадобится оператору, отдельная строка); перенос `BeltDrive` в
`Services/line_sim` (ponytail-метка в `belt.py` остаётся); закрытие окна `attach()`.

**TRAPS.**
- Команды исполняются на потоке диспетчера команд процесса `robot` — ни `sleep`, ни
  `router.request` внутри `cmd_belt_*` (последнее — `RouterReentrantRequestError`, если это
  приёмный поток; автор проверяет, какой поток, и пишет в README числом/именем).
- `freq_hz` в регистре — `round(freq × 100)` в `uint16`; 50 Гц = 5000, переполнения нет, но
  отрицательная частота до валидации дала бы `& 0xFFFF` мусор — валидация раньше записи.
- `_publish_once` возвращается рано при `self._server is None` — watchdog jog ставить ДО этой
  проверки не нужно (без сервера нет и ленты), но и после неё jog-состояние не должно зависнуть:
  `belt.status` при `server_not_running` отдаёт ошибку, а не `jogging: True`.
- Два потока пишут `_jog_deadline` (команда и паблишер) — под `self._lock`.

**HANDOFF IN:** Task 2.1/2.1b/2.2 закрыты; стенд живёт на 8766/5021/8091.

---

### Task 2.3b — Веб-пульт ленты: процесс `pult`, страница на 127.0.0.1:8092

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer (Sonnet, extended)
- **CHAIN:** `tester`(RED по приёмке, worktree на коммите 2.3a) -> `developer`(GREEN) -> ведущий(инъекции, живой стенд) -> `reviewer`
- **Module contract:** new-lite (`Plugins/sim/pult_web/plugin.py`)
- **Зависит от:** 2.3a.

**TASK.** Новый процесс `pult` в `apps/line_sim` с side-effect плагином `PultWebPlugin`: stdlib
`http.server`, страница с MJPEG-картинкой и ручками ленты. Каждая ручка — те же команды `belt.*`
процессу `robot` по IPC фреймворка; своей логики ленты у пульта нет.

**DESIGN.**
1. Форма сервера — копия `MjpegSinkPlugin` (`Plugins/sim/mjpeg_sink/plugin.py:98-265`):
   `ThreadingHTTPServer` в `try/except OSError` → `_fail` + `ctx.health.report_error`, процесс
   живёт; `serve_forever` в daemon-потоке; `shutdown()` симметрично. Конфиг: `host` 127.0.0.1,
   `port` 8092, `mjpeg_url` `http://127.0.0.1:8091/`, `robot_process` `robot`, `timeout_s` 1.0.
2. IPC — `Plugins.hub.device_hub.client.DeviceHubClient(ctx, target_process=robot_process,
   default_timeout=timeout_s)`, вызов `client.request("belt.run", {...})` из потока
   HTTP-обработчика (не приёмный поток — законно, разведка п.1). Новый клиент не писать. Первым
   делом автор снимает **живой** ответ `robot` на `belt.status` через `DeviceHubClient` и
   пиннит форму в тесте: нормализация `_normalize_response` возвращает сырой dict, если в нём
   есть ключ `status` (`client.py:28-29`) — у ответа `belt.*` такого ключа быть не должно.
3. HTTP API (JSON, `Content-Type: application/json`):
   | Метод, путь | Тело | Команда |
   |---|---|---|
   | `GET /` | — | страница |
   | `GET /api/status` | — | `belt.status` |
   | `POST /api/run` | `{freq_hz, reverse}` | `belt.run` |
   | `POST /api/stop` | `{}` | `belt.stop` |
   | `POST /api/jog` | `{direction, freq_hz?}` | `belt.jog` |
   | `POST /api/calibrate` | `{mm_s_at_max_freq}` | `belt.calibrate` |
   Ответ — результат команды как есть. Кривой JSON тела → 400 `{ok: false, error: "bad_json"}`;
   неизвестный путь → 404; ответ `robot` не пришёл (`status == "error"` от клиента) → 504
   `{ok: false, error: "<сообщение клиента>"}`. Тело не больше 4 КБ (`Content-Length` > 4096 → 413).
4. Страница — одна строка-константа в `plugin.py` (без шаблонизатора и без файла): `<img
   src=mjpeg_url>`, ползунок частоты 0–50 Гц (шаг 0.5) + поле, кнопки «Пуск»/«Стоп», переключатель
   направления, две кнопки jog (◀ / ▶), поле калибровки + «Применить», живые `encoder`, `mm_s`,
   `run`, `freq_hz`, `reverse`, `jogging`, `mm_s_at_max_freq`. Jog: `pointerdown` → `POST /api/jog`
   сразу и каждые 200 мс; `pointerup`, `pointercancel`, `pointerleave`, `blur` окна,
   `visibilitychange` → остановить таймер и `POST /api/stop`. Живые значения — опрос
   `GET /api/status` каждые 250 мс (одна дорога; подписка на `sim.belt.**` не нужна — статус уже
   несёт энкодер и скорость). Нет ответа → надпись «robot не отвечает», ручки не блокируются.
5. Процесс `pult` в `apps/line_sim/pipeline.yaml` по форме `mjpeg` (GenericProcess, один плагин);
   `wires` не нужны (портов данных нет). Прототип не меняется: он рулит лентой своим мостом ПЧ
   (`multiprocess_prototype/recipes/letter_robot_sim.yaml`), арбитраж — DESIGN 2.3a п.6.

**FILES.**
1. НОВЫЙ `Plugins/sim/pult_web/plugin.py` (+ пустой `__init__.py`)
2. НОВЫЙ `Plugins/sim/pult_web/README.md`
3. НОВЫЙ `Plugins/sim/pult_web/STATUS.md`
4. НОВЫЙ `Plugins/sim/pult_web/tests/test_pult_web.py` (+ пустой `tests/__init__.py`)
5. `apps/line_sim/pipeline.yaml` — процесс `pult`
6. `apps/line_sim/README.md` — порт 8092, три клиента ленты, арбитраж

**REDS** (слепые; HTTP проверяется настоящим `urllib` против поднятого плагина на свободном порту,
`robot` подменён фейковым `DeviceHubClient`-двойником, который записывает вызовы и отвечает
заданным dict; плюс один тест с настоящими объектами — см. ниже):
1. `Plugins/sim/pult_web/tests/test_pult_web.py::test_index_has_controls_and_mjpeg` — `GET /` → 200,
   `text/html`, в теле `src="http://127.0.0.1:8091/"`, `id` ползунка, кнопок пуск/стоп/jog и поля калибровки.
2. `…::test_run_forwards_same_command` — `POST /api/run {"freq_hz": 25, "reverse": true}` → двойник
   получил ровно `("belt.run", {"freq_hz": 25, "reverse": True})`, HTTP 200, тело = ответ двойника.
3. `…::test_jog_stop_calibrate_status_map` — `/api/jog`, `/api/stop`, `/api/calibrate`, `GET
   /api/status` → команды `belt.jog`, `belt.stop`, `belt.calibrate`, `belt.status` с телами как пришли.
4. `…::test_bad_json_400_unknown_404_oversize_413` — три отказа, двойник не вызван ни разу.
5. `…::test_robot_timeout_504` — двойник отвечает `{"status": "error", "message": "timeout"}` → 504,
   `ok false`.
6. `…::test_port_busy_degrades_not_crashes` — порт занят заранее → `start()` без исключения,
   состояние `error`, `health.report_error` вызван один раз.
7. `…::test_page_jog_is_dead_man` — в тексте страницы есть обработчики `pointerup`, `pointercancel`,
   `blur` и `visibilitychange`, каждый ведёт к `/api/stop`, и интервал подкачки 200 мс (проверка
   текста — слабая, см. «Открыто»).
8. `apps/line_sim/tests/test_f2_task23_live.py::test_pult_drives_belt_end_to_end` — живой стенд
   во временных портах (форма фикстуры — `apps/line_sim/tests/test_f2_task22_live.py`): `POST
   /api/run {25}` → `backend_ctl send_command("robot","belt.status")` `mm_s` 50.57 ± 0.5;
   `POST /api/stop` → 0.0. Это тест «настоящие объекты», не двойник.

**ACCEPTANCE** (живой стенд + браузер владельца):
- [ ] `http://127.0.0.1:8092/` открывается, картинка из 8091 идёт, энкодер на странице растёт.
- [ ] Ползунок 25 Гц + «Пуск» → на странице `mm_s` 50.57 ± 0.5; тот же `belt.status` через
      `backend_ctl` показывает то же.
- [ ] Удержание ▶ 2 с → лента едет всё время удержания; отпускание → `mm_s == 0.0` за ≤ 0.3 с
      (явный `stop`); закрытие вкладки при зажатой кнопке → стоп за 0.5–1.0 с (dead-man 2.3a).
- [ ] Калибровка 200 → «Пуск» 50 Гц → `mm_s` 200.0.
- [ ] Прототип подал «стоп» своим мостом → страница за ≤ 0.5 с показывает `run false`, `mm_s 0.0`.
- [ ] Процесс `robot` остановлен (`backend_ctl`) → страница показывает «robot не отвечает», процесс
      `pult` жив, в `errors.log` `pult` нет трассы на каждый опрос (ошибка IPC — `throttle` у клиента).
- [ ] `Plugins/sim/pult_web` не импортирует `Plugins.sim.robot_host` и `multiprocess_prototype`;
      `sentrux check .` зелёный.

**Hazard-тесты автора:**
- параллельные запросы (`ThreadingHTTPServer`, 20 одновременных `POST /api/jog`) — каждый дошёл
  двойнику ровно один раз, сервер отвечает;
- `shutdown()` при открытом MJPEG-соединении в браузере не висит (join с дедлайном);
- медленный `robot` (двойник спит 2 с при `timeout_s` 1.0) не блокирует `GET /` соседнего клиента.

**Break-injection (ведущий):**
| # | Инъекция | Должны упасть |
|---|---|---|
| B1 | `/api/run` зовёт `belt.jog` | 2 |
| B2 | убрать `pointerup`→stop со страницы | 7 |
| B3 | 504 заменить на 200 с телом ошибки | 5 |
| B4 | `ThreadingHTTPServer` без `try/except OSError` | 6 |
| B5 | не проверять `Content-Length` | 4 |
| B6 | пульт шлёт в процесс `camera` | 8 (живой) |

**OUT OF SCOPE:** авторизация и доступ не с `127.0.0.1`; ручки потока/брака/паузы (Ф6.1, после
Ф3); журнал обмена (Ф6.2); WebSocket/SSE вместо опроса; подписка на дерево `sim.belt.**` в пульте;
стили сверх читаемости.

**TRAPS.**
- `DeviceHubClient.request` при отказе IPC зовёт `health.report_error(..., throttle=30.0)` — на
  опросе каждые 250 мс без `throttle` было бы 4 трассы в секунду; проверить, что throttle доходит.
- `request` до первого приёмного цикла процесса `pult` отдаёт `no_receive_pump` через грейс — первые
  запросы страницы сразу после старта могут получить 504; это не баг, но в README.
- `do_POST` читает ровно `Content-Length` байт, не `rfile.read()` до EOF (зависнет на keep-alive).

---

**Открыто по 2.3 (manager, 2026-09-22):**
- На каком потоке исполняются команды `CommandManager` процесса `robot` — не сверено (дошёл до
  `_auto_register_commands`, не до диспетчера); DESIGN держится правила «в обработчике не блокировать»
  при любом ответе, но README 2.3a должен назвать поток.
- Форма ответа `router.request` для прямой команды процессу (`result` сверху или `data.result`) не
  снята живьём — `DeviceHubClient` покрывает обе формы по коду; первый шаг 2.3b — живой снимок.
- RED 7 в 2.3b проверяет текст страницы, а не поведение браузера; настоящая проверка dead-man
  страницы — ручная приёмка владельцем (удержание/закрытие вкладки) или Playwright, которого в
  `enabled.yaml` может не быть.
- Окно гонки `attach()` (запись плагина до первого Modbus-клиента теряется в момент подключения)
  не закрывается: вероятность — одно окно в жизни процесса; симптом — команда пульта «не
  сработала» в миг подключения прототипа, лечится повтором.
