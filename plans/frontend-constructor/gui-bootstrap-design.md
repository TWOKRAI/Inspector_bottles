# T4.1 — дизайн `GuiBootstrap` / `GuiAppSpec` / `GuiHostRuntime`

> **Статус: ЧЕРНОВИК (2026-09-24), ждёт ревью владельца.** Решения Р-A…Р-F (раздел 1) не утверждены — рекомендации автора, не принятые решения. Код T4.2–T4.4 не начинается до утверждения.


Часть плана [`plan.md`](plan.md), Ф4. Документ на ревью владельца **до кода**. Предпосылка
[gui-service Task 1.4](../2026-09-22_gui-service/phase-1-one-machine.md) (ред. 2): `GuiAppSpec` — контракт
**пакета вкладок**, который хост (`apps/pult/` или встроенный `GuiProcess`) загружает по имени.

Все ссылки `файл:строка` сняты на `3a5d738c` (ветка `feat/gui-service`) грепом и чтением. qex не
использовался (Ollama выключена). Ничего не запускалось: это чтение кода, а не замер.

Измерено, а не взято из плана: `app.py` — **1138** строк (план: «`run_gui` 60-808, ~955 LOC»).
Сейчас `run_gui` занимает `app.py:61-912` (852 строки), `_setup_bridge_callbacks` — `915-1042`,
`_setup_timers` — `1046-1138`. Вся композиционная поверхность — **1078 строк в трёх функциях**.

---

## 1. Решения, которые нужны от владельца

**Р-A. Список стадий расширяется и меняет порядок в одном месте.** План: `identity→theme→runtime→state→tabs→window→timers→show`.
Код устроен иначе. Окно создаётся **до** вкладок (`app.py:769` → `app.py:871`, вкладки кладутся в
`window.tab_widget`). Три крупных блока в плановом списке места не имеют: доменные сервисы
(`app.py:161-316, 400-415, 460-557`), авторизация с модальными диалогами (`app.py:559-644`) и `AppServices` с доменными
подписками (`app.py:646-766`).
- (а) Расширить список: `identity → theme → runtime → services → state → session → app_services → window → tabs → wiring → timers → show`.
  Состав стадий — в §3.
- (б) Оставить плановый список и уложить три блока внутрь `state`/`tabs` хуками.
- **Рекомендация: (а).** При (б) хук `state` наберёт ~600 строк, и сложность уедет в спеку, то есть
  случится ровно то, что запрещает приёмка T4.3. «Окно раньше вкладок» — не выбор, а факт кода. Его
  фиксирует характеризация T4.2.

**Р-B. Шина конвертов (`DataReceiverBridge`) нужна хосту Пульта раньше Блока В.** Это 120 строк Qt
(`multiprocess_prototype/frontend/bridge_impl.py`), доменных слов в ней нет. Через неё в виджеты
идут кадры, дельты стейта, хвост наблюдаемости и GUI-локальные метрики (`bridge_impl.py:81-96`). Вкладки
получают её напрямую: `RuntimeDeps.data_bridge` (`app.py:859`), читатель —
`widgets/tabs/observability/observability_tabs.py:195`. `apps/pult` прототип импортировать не может
(`.sentrux/rules.toml:128`).
- (а) Вынести шину новым файлом `frontend_module/bootstrap/envelope_bus.py` в рамках T4.3, то есть взять
  часть T3.1 вперёд. Прототипные импорты переписать на новый путь: `git mv`, без шима.
- (б) `RemoteGuiRuntime` держит свою шину на чистом Python и продублирует классификацию конвертов
  (`bridge_impl.py:81-96`).
- (в) Шину отдаёт пакет вкладок: хост получает её из `GuiAppSpec`.
- **Рекомендация: (а).** При (б) два классификатора разойдутся, при (в) рантайм хоста зависит от
  пакета. Цена (а): T3.1 стояла в конце Ф3 из-за G.2 («единый конверт», `plan.md:176`). Если G.2
  поменяет форму конверта, файл поменяется во фреймворке, а не в прототипе. Состояние G.2 на сегодня я
  не проверял (§9).

**Р-C. Где выравнивается форма ошибок `RemoteCommandSender`.** Отклонение (3) из итога Task 1.2
(`phase-1-one-machine.md:165-166`) таково. При разрыве `request_*` бросает `SocketConnectionLost`. При
отсутствии соединения `send_*` бросает `ConnectionError`. Встроенный `CommandSender` в обоих случаях
возвращает error-dict или молчит (`remote_command_sender.py:100-108`). Ключ корреляции у сокета
называется `request_id`, у `RouterManager.request` — `correlation_id`.
- (а) В самом `RemoteCommandSender`: `request_*` ловит разрыв и возвращает
  `{"success": False, "error": "connection lost", "request_id", "correlation_id"}`. `send_*` без соединения
  пишет в лог, дропает сообщение и считает дропы в счётчике `connection_state`.
- (б) В `RemoteGuiRuntime` — обёрткой над отправителем.
- (в) Научить вкладки ловить исключение.
- **Рекомендация: (а).** Класс заявлен как «тот же Protocol, что `CommandSender`», значит и форма
  отказа должна быть его. При (в) придётся править 29 файлов-потребителей (число из аудита 1.1).
  Решение меняет поведение, принятое в 1.2, поэтому оно здесь, а не в коде.

**Р-D. Кто выбирает активную тему.** Сегодня GUI читает с диска манифест бэкенда
(`app.py:147-159`, `_manifest.styles.active`). У Пульта диска бэкенда нет: критерий «GUI без диска»
из 1b.3.
- (а) Тема — декларация пакета (каталог тем и дефолт), выбор пользователя хранится в локальных prefs хоста.
- (б) Тему отдаёт бэкенд в `capabilities`.
- **Рекомендация: (а).** Тема — презентационный концерн. Ф2 T2.3 уже назвала её так
  (`app.py:152-154`). Бэкенду знать о ней незачем.

**Р-E. Кто рисует окно Пульта в фазе 1.** `apps/pult` не может взять `MainWindow` прототипа. При этом
phase-3 допускает «Пульт использует `main_window.py` прототипа как есть»
(`phase-3-multi-backend.md:22-24`), и это противоречит правилу хоста.
- (а) Окно строит пакет хуком `build_window`. Инспектор отдаёт свой `MainWindow`, Пульт в фазе 1 его
  показывает. `GuiHostWindow` (T4.6) остаётся в Блоке В, и он нужен Пульту только к 3.1 (N бэкендов
  в доках).
- (б) Выделить `GuiHostWindow` до 1.4.
- **Рекомендация: (а).** Так T4.6 не тянется под окно codemod, а противоречие в phase-3 снимается
  формулировкой «через пакет». Строку phase-3 поправит лид.

**Р-F. Hot-reload в Пульте.**
- (а) Цикл рестарта UI живёт в `GuiBootstrap`, и Пульт получает его бесплатно: соединение переживает
  рестарт, вкладки пересобираются.
- (б) В v1 Пульт перезапускается только целиком.
- **Рекомендация: (а).** Это тот же код, что у встроенного GUI. Отказ от него — вторая ветка поведения.

---

## 2. `GuiAppSpec` — контракт пакета вкладок

Frozen-dataclass, **Qt-free по импортам**. Хуки внутри ссылаются на Qt-код, но только по типам,
через `TYPE_CHECKING`. Файл — `frontend_module/bootstrap/interfaces.py`, так записано в 1.4
(`phase-1-one-machine.md:388`).

| Поле | Тип | Вид | Сегодня |
|---|---|---|---|
| `app_id` | `str` | декларация | нет; хост сверяет с `capabilities.app_id` (в `process_manager_module/process/*.py` грепом 0 — поле добавляет 1.4) |
| `protocol_version` | `int` | декларация | нет (то же) |
| `identity` | `AppIdentity` (уже есть, `frontend_module/core/app_identity`) | декларация | `app.py:91` |
| `theme` | `ThemeSpec(dir: Path, default: str)` | декларация | `app.py:147-159` из манифеста → Р-D |
| `subscriptions` | `tuple[str, ...]` | декларация | захардкожены `process.py:131-148` (`processes/system/devices/calibration.**`) |
| `telemetry_suffixes` | `tuple[str, ...] \| None` | декларация | `TelemetryViewModel(tracked_suffixes=…)` (`telemetry_view_model.py:84`); прототип не передаёт → дефолт фреймворка |
| `timers` | `tuple[TimerSpec(interval_ms, hook), ...]` | декларация + имя хука | fps-таймер `app.py:1062-1104` |
| `reload_namespace` | `str` (например `"multiprocess_prototype.frontend."`) | декларация | неявно `process.py:385-392` |
| `hooks` | `GuiHooks` — именованные функции по стадиям (§3) | хуки | тело `run_gui` |

`GuiHooks` — dataclass из **именованных** функций `(ctx: BootContext) -> None | T`: `build_services`,
`state_listeners`, `authenticate`, `build_app_services`, `build_window`, `tabs`, `wire_frames`. Лямбда
допустима только там, где тело сводится к одному вызову. Приёмка T4.3 считает их грепом в модуле спеки.
`BootContext` — изменяемый контейнер, который стадии наполняют по порядку: `app`, `runtime`, `bus`,
`view_model`, `bindings`, `services`, `window` и `extras: dict` для прикладного. Тот же «bag», что сегодня
держат локалы `run_gui` (`app.py:188-190`, «AppContext удалён»). Здесь он явный и одноразовый: живёт
одно воплощение UI.

**Загрузка по имени.** Строка `"<модуль>:<атрибут>"`, как класс процесса `gui` в `launch.py:216`
(`architecture.md:33`). Встроенный GUI получает её параметром процесса из `presentation.yaml`, Пульт —
из `apps/pult/config.yaml` (`gui_packs: {<app_id>: "..."}`). Загрузчик `bootstrap/pack_loader.py`
(Qt-free, 1.4) сверяет `app_id` и `protocol_version`. При несовпадении он называет обе версии и
вкладок не рисует. Entry points не заводим: пока приложений два.

**Лимит спеки: `app_spec.py` ≤ ~300 строк (T4.3).** Лимит держится **только если хуки лежат в
других модулях пакета**. Сегодня тело `run_gui` — это прикладная композиция поверх генерика, который
ещё в прототипе: `GuiStateBindings`, `RequestRunner`, `QtEventBus`, `TabFactory` ждут Ф3. До Ф3 хуки
остаются толстыми и живут в `multiprocess_prototype/frontend/boot/*.py`. `app_spec.py` только
перечисляет их. Это честная граница: сложность не исчезает, она переезжает из одной функции в
именованные модули и **уменьшается по мере Ф3**, когда генерик становится поведением стадий по
умолчанию.

---

## 3. Стадии и текущий boot-порядок (базовая линия характеризации T4.2)

### 3.1 Стадии (вариант Р-A(а))

| # | Стадия | Владелец | Строки `run_gui` сегодня |
|---|---|---|---|
| 0 | `diagnostics` — сторож модалок, stall-dump, qt-mcp probe | фреймворк (хост) | `70-84`, `132-144` |
| 1 | `identity` — `set_app_identity`, WheelGuard, UiEventTap | фреймворк + `spec.identity` | `91-118` |
| 2 | `theme` | фреймворк + `spec.theme` | `146-159` |
| 3 | `runtime` — отправитель, прокси, шина (из `GuiHostRuntime`) | фреймворк | `188-202`, `328` |
| 4 | `services` — реестры, топология, проверки старта, каталоги, адаптеры рецептов | хук `build_services` | `161-186`, `204-316`, `400-415`, `460-557` |
| 5 | `state` — VM, bindings, поллер; слушатели шины **по порядку** | фреймворк + хук `state_listeners` | `318-398`, `436`, `458` |
| 6 | `session` — auth, автологин, модальный `LoginDialog` | хук `authenticate` (может завершить процесс) | `559-644` |
| 7 | `app_services` — `build_app_services` + подписки доменной шины | хук `build_app_services` | `646-766` |
| 8 | `window` | хук `build_window` (Р-E) | `768-814` |
| 9 | `tabs` | хук `tabs` → `TabFactory` | `816-887` |
| 10 | `wiring` — кадры и маршрутизация дисплеев | хук `wire_frames` | `889-897` → `915-1042` |
| 11 | `timers` — `spec.timers` + фреймворковые safety/aboutToQuit | фреймворк | `899-900` → `1046-1138` |
| 12 | `show` — `topology_session.reset()` (хук), `show`, `exec` | фреймворк | `903-912` |

Перестановка по сравнению с кодом одна: построение объектов `services` (`161-186`) уезжает за
`runtime` (`188-202`). Оба блока ничего не подписывают, поэтому порядок подключения слушателей она не
меняет. Побочные эффекты `PluginManager.initialize()` (`app.py:184`) при переносе я не проверял (§9).

`state` стоит **раньше** `session`, и так должно остаться. `LoginDialog.exec()` (`app.py:640`) и
`StartupBlockingDialog.exec()` (`579`, `590`) крутят вложенный цикл событий. В нём доставляются
конверты, которые рабочий поток уже поставил в очередь (`bridge_impl.py:44`, AutoConnection → Queued).
Значит, слушатели должны быть подключены до первого модального окна. Это вывод из чтения кода, живьём
не наблюдался (§9).

### 3.2 Порядок подключения, который фиксирует характеризация T4.2

Шина конвертов (`process._bridge`):
1. `set_state_callback` ← `GuiStateBindings` (первичный) — внутри конструктора, `app.py:339-347`
2. `add_state_listener(telemetry_view_model.on_state_delta)` — `app.py:351`
3. `add_state_listener(_forward_state_delta_to_topology)` — `app.py:436`
4. `add_state_listener(_obs_tail_activator.on_state_delta)` — `app.py:458`
5. `tabs.bind_live_source(bridge)` — вкладка наблюдаемости при `create_tabs` (`observability_tabs.py:195-197`, после `app.py:871`); каким членом шины (колбэк или Qt-сигнал `observability_received`, `bridge_impl.py:30`) — не проверял, см. §9
6. `set_frame_callback(_on_frame_received)` — `app.py:1042`

Доменная шина (`QtEventBus`, вызывает обработчики в порядке регистрации, `app.py:713-717`):
- `TopologyReplaced`: `topology_bridge.on_topology_changed` (`679`) → `session.mark_edited` (`697`) →
  подписчики вкладок (`PipelinePresenter.__init__`, внутри `create_tabs`, `871`)
- `RecipeActivated`: `session.mark_activated` (`698`) → подписчики вкладок (`871`) → `_rebuild_displays` (`999`)
- `PluginConfigChanged`: live-запись (`766`) → подписчики вкладок, если есть
- `DisplaysChanged`: подписчики вкладок (`871`) → `_rebuild_displays` (`1000`)

Таймеры и выход: `fps_timer.start` (`1104`) → `safety_timer.start` (`1121`) → `aboutToQuit`:
флаг остановки (`1124`) → `aboutToQuit`: `telemetry_poller.stop` (`1134`).

Модальные точки: `StartupBlockingDialog` (`579`/`590`, затем `sys.exit(1)`) → `LoginDialog` (`640`). Обе
стоят после шагов 1–4 шины и до окна.

Приёмка T4.2 — снимок этой последовательности **до** разборки и сравнение **после**. Шина и
`event_bus` инжектируются, поэтому шпион на них законен: здесь имена методов (`add_state_listener`,
`subscribe`) и есть контракт.

---

## 4. `GuiHostRuntime` — Protocol и две реализации

### 4.1 Сырьё: обращения `app.py` к процессу (греп на `3a5d738c`)

**53 обращения к приватным атрибутам `process`**: 47 через точку (`grep -c "process\._"`) и 6 строкой
в `getattr`/`setattr` (`app.py:111,114,117,328,1125` ×2). Атрибутов 14:

| Атрибут | Раз | Вид | Строки |
|---|--:|---|---|
| `_log_warning` / `_log_info` / `_log_error` / `_log_debug` | 17 / 11 / 1 / 1 | вызов | повсюду |
| `_bridge` | 10 | чтение | `340,351,436,458,859,1042,1076,1082,1089,1097` |
| `_record_metric` | 1 | вызов | `316` |
| `_stall_dump_fp` | 1 | **присвоение** | `84` |
| `_ui_event_tap` | 2 | **присвоение** + getattr | `110`, `114` |
| `_ui_tap_commands_registered` | 2 | getattr + **присвоение** | `111-112` |
| `_ui_command_sender` | 2 | **присвоение** + getattr | `193`, `117` |
| `_gui_state_proxy` | 1 | getattr | `328` |
| `_restart_ui` | 2 | **присвоение** + getattr | `831`, `1125` |
| `_stop_requested` | 1 | **setattr** | `1125` |
| `_window` | 1 | **присвоение** | `903`; читателей во всём дереве 0 (греп по `multiprocess_prototype`, `multiprocess_framework`, `backend_ctl`) |

Публичные обращения: `process.name` ×2 (`389`, `457`), `report_error` ×4 (`310,586,620,667`),
`should_stop` ×1 (`1111`). Сам `process` утекает в конструкторы дважды: `CommandSender(process)` (`191`) и
`register_ui_tap_commands(process, …)` (`112`). Второму нужен `command_manager` процесса
(`frontend_module/debug/tap_commands.py:50`).

### 4.2 Protocol (Qt-free, `frontend_module/bootstrap/runtime.py`)

```python
class GuiHostRuntime(Protocol):
    name: str
    logger: GuiLogger                    # .debug/.info/.warning/.error(msg, module=)
    command_sender: CommandSender        # RemoteCommandSender — наследник
    state_proxy: GuiStateProxy | None    # .cache, ensure_/release_subscription
    bus: EnvelopeBus                     # dispatch, set_state_callback, add/remove_state_listener,
                                         # set_frame_callback, set_observability_callback (Р-B)
    capabilities: RuntimeCaps            # supports_ui_tap, connection-aware, app_id/protocol_version
    def report_error(self, exc: BaseException, *, context: str, module: str, **fields) -> None: ...
    def record_metric(self, name: str, value: float = 1) -> None: ...
    def install_ui_tap(self, tap: object, sender_getter: Callable[[], object]) -> None: ...
    def should_stop(self) -> bool: ...
    def request_ui_restart(self) -> None: ...
    def ui_restart_requested(self) -> bool: ...
    def on_ui_exit(self) -> None: ...     # то, что сегодня делает aboutToQuit-лямбда 1125
    def connection_state(self) -> ConnectionState: ...
    def add_connection_listener(self, cb: Callable[[ConnectionState], None]) -> None: ...
```

`_stall_dump_fp` и `_window` в Protocol **не входят**. Первый — ссылка от GC, её держит `BootContext`.
Второй пишется, но нигде не читается, и в T4.4 он просто удаляется. `subscriptions` тоже не член: их
применяет конструктор рантайма (§4.4).

### 4.3 Как каждая реализация выполняет каждый член

| Член | `InProcessRuntime` (T4.4, `GuiProcess` в дереве) | `RemoteGuiRuntime` (1.4, Пульт по сокету) |
|---|---|---|
| `name` | `process.name` | имя клиента из конфига хоста (идёт в `sender` и `_fence.sender`, `remote_command_sender.py:120-127`) |
| `logger` | адаптер к `process._log_*` — строит **сам `GuiProcess`** (свои приватные трогает только владелец) | `get_std_logger` в `--log-dir` (1.4, Step 3) |
| `report_error` / `record_metric` | `process.report_error` / `_record_metric` | в лог; метрики — в локальный счётчик для статус-бара (на бэкенд не уходят) |
| `command_sender` | `CommandSender(process)` | `RemoteCommandSender(client, name=…)`; форма отказа — Р-C |
| `state_proxy` | `process._gui_state_proxy` (`process.py:80-87`) | `RemoteStateProxy(client, dispatch=qt_invoker)`; колбэки уже маршалятся через `dispatch` (`remote_state_proxy.py:123-125`) |
| `bus` | `process._bridge`: рабочий поток `data_receiver` кладёт в неё и данные, и дельты (`process.py:182,269`) | свой экземпляр шины (Р-B). Питают её: колбэк `RemoteStateProxy` → `state_delta_message(d)`, `RemoteFrameSource` (1.3) → `{"data_type": "frame_ready", "frame", "sender", "data": {"capture_ts", …}}`, push `observability.record` |
| `install_ui_tap` | `register_ui_tap_commands(process, …)` ровно один раз за жизнь процесса (сегодня этот флаг держит `_ui_tap_commands_registered`) | no-op, `capabilities.supports_ui_tap = False`: у Пульта нет `CommandManager`, `backend_ctl` в его UI не заглядывает (§9) |
| `should_stop` | `process.should_stop()` | флаг закрытия хоста |
| `request_ui_restart` / `ui_restart_requested` | флаг `_restart_ui` **внутри** `InProcessRuntime` | тот же флаг, соединение не трогается (Р-F) |
| `on_ui_exit` | без рестарта: `_stop_requested = True`, а после цикла `_request_system_shutdown()` (`process.py:329-330`) — **закрытие окна гасит всю систему** | без рестарта: закрыть клиента. **Бэкенд не гасится** (приёмка 1.4: `kill -9` Пульта бэкенд не замечает) |
| `connection_state` / listener | всегда `CONNECTED`, слушатель не вызывается | `CONNECTING/CONNECTED/DISCONNECTED` от реконнект-контроллера |
| применение `spec.subscriptions` | в `_init_application_threads` — **то же место**, что сегодня (`process.py:130-148`); список передаётся параметром процесса | в `connect()`, до стадии `state`; повторяется в `on_reconnected` |

Мерило Protocol — **один контрактный набор тестов**, параметризованный двумя реализациями.
`InProcessRuntime` проверяется на фейковом процессе, `RemoteGuiRuntime` — на in-process
`SocketChannel(port=0)`, как в тестах 1.2. На каждую строку таблицы нужен свой тест. Если строка
проходит только у одной реализации, она обязана значиться в `capabilities`, иначе считается дефектом
Protocol.

### 4.4 Жизнь `RemoteGuiRuntime`: реконнект, и что видит вкладка

Клиент сам не переподключается (`socket_client.py:45-55`). Порядок реконнекта задан там же, и
контроллер рантайма выполняет его буквально: `close → connect → refresh_fence → on_reconnected`.
Пауза растёт экспоненциально с потолком. Числа выбирает 1.4 под свою приёмку: «отключён» за ≤ 5 с,
переподключение за ≤ 15 с.

Когда бэкенд отваливается, вкладка видит следующее:
- **Команды:** `request_*` возвращает error-dict `connection lost` (при Р-C(а)), `send_*` дропается со
  счётчиком. Вкладка ведёт себя как при таймауте на очередях — новой ветки в ней нет.
- **Стейт:** последние значения в VM и bindings остаются, то есть устаревают без пометки. В статус-баре
  шелла висит «отключён» (слушатель `connection_state`). Поповиджетной пометки «устарело» в v1 нет — это
  ограничение, записать в README Пульта.
- **Кадры:** дисплеи замирают на последнем кадре. `RemoteFrameSource` переподписывается durable-путём
  (1.3).
- **После реконнекта:** `on_reconnected` переподписывает паттерны (`remote_state_proxy.py:174-237`). Бэкенд
  отдаёт стартовый replay, дельты через шину догоняют bindings. Команды сначала получают свежий fence.
- **Запрещено:** модальный диалог при разрыве. Он заблокирует safety-таймер, как объяснено в
  `app.py:1112-1117`.

---

## 5. Контракт hot-reload

Сегодня (`process.py:308-326`, `376-405`) после `_restart_ui` удаляются все модули с префиксом
`multiprocess_prototype.frontend`, кроме `…frontend.process` и `…frontend.bridge`. Затем
`importlib.reload(app)`, и `run_gui` запускается снова.

Две находки при чтении:
1. **Префикс сравнивается без точки.** `"…frontend.bridge_impl".startswith("…frontend.bridge")` истинно, и
   `DataReceiverBridge` переживает рестарт **случайно**, хотя это и нужно: экземпляр держит процесс.
   Точно так же уцелел бы любой будущий модуль `frontend.processing*`.
2. **Слушатели шины, по всей видимости, текут между воплощениями UI.** Шина живёт дольше UI.
   `add_state_listener` дедуплицирует только по идентичности (`bridge_impl.py:55-63`), а каждое
   воплощение добавляет три **новых** callable (`app.py:351,436,458`). `remove_state_listener` в `app.py`
   не вызывается ни разу (греп: 0). После N рестартов старые VM, `TopologyBridge` и
   `ObservabilityTailActivator` остаются живыми слушателями. **Это гипотеза по чтению, не
   воспроизведение.** Проверка в T4.2: сделать два рестарта и посчитать `len(bus._state_listeners)`.
   Ожидаю 3 → 6 → 9.

**Контракт (T4.3/T4.4):**
- Цикл рестарта переезжает из `GuiProcess.run` в `GuiBootstrap.run_forever(runtime, pack_ref)`. Рантайм
  создаётся один раз и рестарт переживает. Стадии 1–12 выполняются заново на каждое воплощение.
- Всё, что воплощение подключает к долгоживущим объектам (шина, прокси, `app`), идёт через
  `BootContext.attach(...)`. На выходе из воплощения это снимается в обратном порядке. Так закрывается
  находка 2, а в тесте её заменяет ассерт «после рестарта столько же слушателей, сколько после старта».
  То же касается подписок `ensure_subscription` в bindings. У Пульта они живут на бэкенде, и течь там
  дороже.
- Зона чистки — `spec.reload_namespace`, строка с завершающей точкой, минус `runtime.keep_modules`
  (in-process: модуль процесса и модуль шины). После чистки пакет заново разрешается загрузчиком по
  той же строке.
- Фреймворк **не перезагружается никогда**.

**DX-регресс, сказанный прямо.** После T4.3 сам `GuiBootstrap` и стадии по умолчанию живут во
фреймворке. Правка порядка стадий, шины (Р-B) или рантайма требует полного рестарта GUI, а не кнопки
«Перезапустить интерфейс». Сегодня почти вся композиция в `app.py` перезагружается кнопкой. После Ф3
то же коснётся промоутнутых виджетов и форм (`plan.md:186`). Горячей остаётся только прикладная часть:
хуки, вкладки, `app_spec.py`. Записать в README прототипа и в README `frontend_module/bootstrap`.

---

## 6. `GuiHostWindow` (T4.6) — что шелл, что прикладное

Разбор `windows/main_window.py` (766 строк):

| Генерик → `GuiHostWindow` | Прикладное → остаётся в прототипе |
|---|---|
| Каркас: header / банер / центральная панель / tab-host / статус-бар (`126-174`, `201-205`, `228-233`) | `AppHeaderWidget`, `ErrorBannerWidget` прототипа (`20-21`) → шелл принимает фабрики |
| Кнопка «Скрыть» и drag-высота вкладок, `HideToggleButton` целиком (`45-113`, `442-582`) | Геометрия в `QSettings("INNOTECH", "Inspector")` (`266`) → ключ из `AppIdentity` (сегодня **другой** namespace, чем `AppIdentity(org="Inspector")` в `app.py:91`) |
| F11/Esc полноэкранный режим (`262-263`, `380-405`) | RS-4: индикаторы топологии, `set_topology_session`, `confirm_discard_topology_changes` (`207-226`, `300-346`, `639-664`) → шелл даёт **хук закрытия** `close_guards: list[Callable[[str], bool]]` |
| Undo/Redo-шорткаты на `UndoRedoController` (`409-440`) | Статус-бар FPS/Latency/Frames и 5 биндингов `system.*` (`595-626`) |
| Слот центральной панели `set_image_panel` (`367-376`) | Аккумуляторы кадров и трассы (`673-766`) — метрики дисплея, уходят к `wire_frames`/`timers` пакета |
| Сохранение и восстановление геометрии (`271-285`) | Dirty-метка Settings (`634-637`) |

Шелл — `frontend_module/windows/host_window.py` (Qt). В нём нет ни одного импорта прототипа и ни
одного `system.*`-пути. Метрики статус-бара пакет добавляет через `add_status_widget`.
Существующий шаблон `windows/` фреймворка — Gen-1, он заморожен (`plan.md:52`) и не
переиспользуется. При Р-E(а) T4.6 остаётся в Блоке В, а Пульту фазы 1 окно отдаёт пакет.

---

## 7. Раскладка: Qt-free ядро или Qt-пакет (Р-4 rework)

| Тип | Файл | Сторона Р-4 | Когда | Окно codemod |
|---|---|---|---|---|
| `GuiAppSpec`, `GuiHooks`, `ThemeSpec`, `TimerSpec` | `frontend_module/bootstrap/interfaces.py` | **ядро** (Qt только в `TYPE_CHECKING`) | T4.3 | не нужно (новый файл) |
| `GuiHostRuntime`, `EnvelopeBus`, `ConnectionState`, `RuntimeCaps` (Protocol) | `bootstrap/runtime.py` | **ядро** | T4.3 | не нужно |
| `InProcessRuntime` | `bootstrap/runtime_inprocess.py` | **ядро** (получает коллабораторов готовыми, `ProcessModule` не импортирует) | T4.4 | не нужно |
| `RemoteGuiRuntime` + реконнект-контроллер | `bootstrap/remote_runtime.py` | **ядро** (`dispatch` приходит извне) | gui-service 1.4 | не нужно |
| `pack_loader` | `bootstrap/pack_loader.py` | **ядро** | 1.4 | не нужно |
| `BootContext`, `GuiBootstrap`, стадии по умолчанию, `qt_invoker` | `bootstrap/bootstrap.py` | **Qt-пакет** | T4.3 | не нужно |
| `EnvelopeBus`-реализация (`DataReceiverBridge`) | `bootstrap/envelope_bus.py` | **Qt-пакет** | T4.3 при Р-B(а) | не нужно (`git mv` одного файла + импорт-сайты) |
| `GuiHostWindow` | `windows/host_window.py` | Qt-пакет | T4.6, Блок В | не требуется, но задача в Блоке В |
| `APP_SPEC` инспектора, хуки `boot/*.py` | `multiprocess_prototype/frontend/app_spec.py`, `frontend/boot/` | прототип (Qt) | T4.2 (хуки как стадии-функции), T4.3 (спека) | не нужно |

T4.2, T4.3 и T4.4 обходятся **без окна codemod**: это новые файлы во фреймворке и правки на месте в
прототипе (`app.py`, `process.py`). Колонку «Qt» проверяет греп `PySide6` по файлу (§8).

Честная оговорка: `frontend_module/__init__.py` импортирует `components`/`widgets`
(`phase-1-one-machine.md:169-171`). Поэтому **импорт** любого Qt-free файла через пакет всё равно
поднимает PySide6. До расщепления Р-4 Qt-free-ность проверяется только грепом файла. Проверка
`import …; assert "PySide6" not in sys.modules` сегодня упала бы у всех, и в приёмку её не ставить.

---

## 8. Риски и что должна мерить приёмка T4.2–T4.4

| Риск | Чем мерить |
|---|---|
| Разборка `run_gui` тихо меняет порядок | T4.2: снимок последовательности §3.2 (шина, доменная шина по типу события, старт таймеров, `aboutToQuit`, позиция модалок) до и после — **равенство списков**. Break-injection: переставить `436` и `458` местами — тест обязан упасть |
| Утечка слушателей при рестарте UI (§5, находка 2) | T4.2: тест характеризации **фиксирует текущее** (3 → 6), T4.3/4.4 меняют ожидание на «3 → 3» отдельным коммитом с явной записью, что поведение изменено намеренно |
| Сложность мигрирует в спеку | T4.3: `wc -l app_spec.py` ≤ 300; `grep -c "lambda" app_spec.py` = 0; `run_gui` удалён |
| Приватные атрибуты остаются | T4.4: `grep -c "process\._" app.py` = 0 (сегодня 47), `grep -c "getattr(process\|setattr(process" app.py` = 0 (сегодня 6), `process._window` удалён |
| Protocol подогнан под одну реализацию | Контрактный набор §4.3 зелёный на **обеих** реализациях. До 1.4 `RemoteGuiRuntime` нет, и T4.4 закрывается на одной. Строки таблицы §4.3 — acceptance 1.4, не T4.4 |
| Qt протекает в ядро | `grep -l PySide6 bootstrap/{interfaces,runtime,runtime_inprocess,remote_runtime,pack_loader}.py` → пусто |
| ui_event_tap сломан | T4.4: `ui_tap_ping` зелёный живьём (acceptance плана) — только для `InProcessRuntime` |
| Подписки применяются позже, чем сегодня | T4.4: VM получает непустой `initial_cache` на том же стенде, что до правки (тест: фейковый прокси с кэшем → VM видит его в стадии `state`) |
| Регресс набора | pytest-qt `multiprocess_prototype/frontend` ≥ 2470 passed / 0 failed, `frontend_module` ≥ 574 (baseline аудита 1.1, `phase-1-one-machine.md:12`) |
| Hot-reload умер | qt-smoke: «Перезапустить интерфейс» дважды → окно и вкладки на месте, число слушателей стабильно |

---

## 9. Что осталось открытым и что в этом документе ненадёжно

- **Ничего не запускалось.** Все номера строк и числа — греп и чтение на `3a5d738c`. Порядок §3.2
  реконструирован из исходника, а не записан живым шпионом. Там, где подписка происходит внутри
  конструкторов вкладок (`PipelinePresenter`, наблюдаемость), я сослался на `create_tabs`, но внутрь
  каждой вкладки не заходил. Полный список подписчиков вкладок по типам событий даст только живой
  снимок T4.2.
- **Утечка слушателей (§5)** — гипотеза по чтению `bridge_impl.py:55-63` и `app.py`. Воспроизведения нет.
- **Вложенный цикл модалок доставляет конверты (§3.1)** — вывод из того, что соединение
  `AutoConnection` становится `Queued` из рабочего потока. Не проверено. Что происходит с сигналами,
  которые рабочий поток `data_receiver` испускает **до** создания `QApplication` (`process.py:158-163`
  стартует рабочий поток раньше `run_gui`), я не знаю. Это вопрос для характеризации.
- **Qt-free-ность `EnvelopeBus`** под вопросом: если вкладки (как минимум наблюдаемость,
  `observability_tabs.py:197`) подписываются на **Qt-сигналы** шины (`frame_received`/`state_updated`/
  `observability_received`, `bridge_impl.py:25-30`), а не на колбэки, то Protocol шины придётся либо
  описывать без сигналов и переводить таких потребителей на колбэки, либо признать шину Qt-типом и вынести
  член `bus` из Qt-free Protocol в `BootContext`. Инвентарь потребителей сигналов — первый шаг T4.3.
- **G.2 «единый конверт»** — не проверял, влит ли он. От этого зависит цена Р-B(а).
- **Побочные эффекты `PluginManager.initialize()`** при переносе за стадию `runtime` не проверены.
- **`app_id` / `protocol_version`** в `capabilities` сегодня отсутствуют (греп 0 по
  `process_manager_module/process/*.py`). Где именно их задаёт приложение, решает 1.4.
- **Удалённый ui_tap:** у Пульта нет `CommandManager`, поэтому `backend_ctl` не видит жестов его UI.
  Отладочная плоскость для Пульта в дизайне не решена, помечена флагом `capabilities`.
- **Пометка «устарело» у виджетов при разрыве** в v1 не предусмотрена. Решение «достаточно индикатора в
  статус-баре» — моё, владелец его не подтверждал.
- **Противоречие в `phase-3-multi-backend.md:22-24`** («Пульт использует `main_window.py` прототипа как
  есть» против `apps/* ↛ multiprocess_prototype/*`). Р-E предлагает снятие, но правка phase-3 — за лидом.
- **Разные QSettings-namespace** (`main_window.py:266` — `INNOTECH/Inspector`, `app.py:91` —
  `Inspector/Inspector Bottles`) — наблюдение. Последствия для сохранённой геометрии при переходе
  шелла на `AppIdentity` не оценены.
- Ф3 не начата, поэтому до неё хуки `boot/*.py` будут толстыми. Лимит «≤ 300 строк спеки» выполним, но
  «сложность не мигрирует» до Ф3 выполняется только формально: она переезжает в именованные модули
  прототипа.
