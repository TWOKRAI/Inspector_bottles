# Дизайн: подключения, контекст виджета, шаблоны общения

Часть плана [`plan.md`](plan.md). Редакция §4 и решений Р-B/Р-C/Р-D из T4.1
([`gui-bootstrap-design.md`](../frontend-constructor/gui-bootstrap-design.md)). Соседи:
[`design-boot.md`](design-boot.md), [`design-shell-layout.md`](design-shell-layout.md).
Ссылки «(T4.1)» перенесены без повторной сверки; остальные перепроверены 2026-09-26 на `e3f47c40`.

---

## 1. Реестр подключений — с первого дня (находка CTO 1)

Запись владельца говорила «`GuiHostRuntime` почти без изменений; их может быть N». CTO: Protocol T4.1 держит один
`command_sender`, один `state_proxy`, одну шину, а `BootContext` — один `runtime`; раскладка же даёт доку `conn`,
виджету — `backend_role`. Значит, «N» — это правка стадий `runtime`/`state`, а не «добавить в Ф3».

**Решение плана:** рантайм = **одно подключение**. Бутстрап держит `ConnectionRegistry`:

```python
class ConnectionRegistry:                   # Qt-free, frontend_module/bootstrap/connections.py
    def add(self, name: str, runtime: GuiHostRuntime) -> None: ...   # имя уникально, иначе ValueError
    def get(self, name: str) -> GuiHostRuntime: ...                   # KeyError с перечнем известных имён
    def names(self) -> tuple[str, ...]: ...                           # порядок добавления
    def for_app(self, app_id: str) -> tuple[str, ...]: ...            # подключения, чей capabilities.app_id == app_id
    def close_all(self) -> None: ...                                  # обратный порядок; ошибка одного не мешает остальным
```

- Встроенный GUI: одно подключение `local` → `InProcessRuntime`. Поведение не меняется.
- `apps/gui_client`: N подключений из конфига → `RemoteGuiRuntime` каждое (gui-service 1.4 — одно, 3.1 — N).
- Контекст виджета разрешается **парой (виджет, подключение)**: раскладка указывает у дока `connection:`; если не
  указано — подключение, чей `app_id` совпадает с `app_id` пакета виджета; если таких ноль или больше одного —
  ошибка применения раскладки с именами, а не «первый попавшийся».
- **Одна реализация, но через реестр:** Task 1.3 вводит реестр при единственном `local`. Контракт-тест реестра
  параметризован **двумя** подключениями одного типа (два фейковых процесса) — иначе «N» опять останется записью.

## 2. `GuiHostRuntime` — Protocol одного подключения

Состав — T4.1 §4.2 без изменений по членам (Qt-free, `frontend_module/bootstrap/runtime.py`):

```python
class GuiHostRuntime(Protocol):
    name: str                            # имя подключения в реестре
    logger: GuiLogger
    command_sender: CommandSender        # RemoteCommandSender — наследник
    state_proxy: GuiStateProxy | None
    bus: EnvelopeBus                     # dispatch, set_state_callback, add/remove_state_listener,
                                         # set_frame_callback, set_observability_callback (Р-B)
    capabilities: RuntimeCaps            # supports_ui_tap, app_id, protocol_version
    def report_error(self, exc: BaseException, *, context: str, module: str, **fields) -> None: ...
    def record_metric(self, name: str, value: float = 1) -> None: ...
    def install_ui_tap(self, tap: object, sender_getter: Callable[[], object]) -> None: ...
    def should_stop(self) -> bool: ...
    def request_ui_restart(self) -> None: ...
    def ui_restart_requested(self) -> bool: ...
    def on_ui_exit(self) -> None: ...
    def connection_state(self) -> ConnectionState: ...
    def add_connection_listener(self, cb: Callable[[ConnectionState], None]) -> None: ...
```

Сырьё Protocol — **53 обращения** `app.py` к приватным атрибутам `process` (T4.1 §4.1: 47 через точку — перепроверено
`grep -c "process\._"` = 47 — и 6 строкой в `getattr`/`setattr`; `grep -cE "getattr\(process|setattr\(process"` = **5** строк,
в строке 1125 их два — ревью CTO плана 2026-09-26), 14 атрибутов. `_stall_dump_fp` (ссылка от GC) держит
`BootContext`; `_window` (пишется, читателей 0) удаляется.

**Флаги рестарта и `should_stop` — у процесса, а не у подключения.** При N подключениях «перезапустить интерфейс»
и «закрыть приложение» — одно событие хоста. Поэтому `request_ui_restart`/`ui_restart_requested`/`should_stop`/
`on_ui_exit` у `InProcessRuntime` делегируют процессу, у `RemoteGuiRuntime` — одному объекту хоста `GuiClientHost`,
общему для всех подключений. Правка против T4.1, где рантайм был один.

**Открытый вопрос T4.1 §9, остаётся:** если потребители подписаны на **Qt-сигналы** шины, а не на колбэки, член `bus`
не может быть Qt-free. Решает инвентарь Task 1.1: либо потребители переводятся на колбэки (тогда `bus` в Protocol),
либо шина признаётся Qt-типом и уезжает из Protocol в `BootContext`, а контекст виджета получает её через адаптер.

### 2.1 Как реализации выполняют члены

Таблица T4.1 §4.3 остаётся мерилом. Коротко по отличиям:

| Член | `InProcessRuntime` (Task 1.3, `GuiProcess` в дереве) | `RemoteGuiRuntime` (gui-service 1.4) |
|---|---|---|
| `logger` | адаптер к `process._log_*`, строит сам `GuiProcess` | `get_std_logger` в `--log-dir` |
| `command_sender` | `CommandSender(process)` (`app.py:191`) | `RemoteCommandSender(client, name=…)`, форма отказа — Р-C |
| `state_proxy` | `process._gui_state_proxy` | `RemoteStateProxy(client, dispatch=qt_invoker)` |
| `bus` | `process._bridge` (рабочий поток `data_receiver`) | свой экземпляр шины, питают прокси, `RemoteFrameSource`, push наблюдаемости |
| `install_ui_tap` | `register_ui_tap_commands(process, …)` один раз за жизнь процесса | no-op, `supports_ui_tap = False` |
| `on_ui_exit` | закрытие окна гасит всю систему (`process.py:329-330`, T4.1) | закрыть клиента; **бэкенд не гасится** |
| `connection_state` | всегда `CONNECTED` | `CONNECTING/CONNECTED/DISCONNECTED` от реконнект-контроллера |
| `spec.subscriptions` | в `_init_application_threads`, то же место, что сегодня | в `connect()`, до стадии `state`; повтор в `on_reconnected` |

Реконнект `RemoteGuiRuntime` — T4.1 §4.4 без изменений: `close → connect → refresh_fence → on_reconnected`,
экспоненциальная пауза с потолком; «отключён» ≤ 5 с, переподключение ≤ 15 с (числа gui-service 1.4). Модальный
диалог при разрыве запрещён. Пометки «устарело» у виджетов в v1 нет — индикатор в статусе оболочки; решение автора
T4.1, владельцем не подтверждено.

## 3. `WidgetContext` — одна дверь виджета

Фабрика виджета получает только контекст (`WidgetSpec.factory(ctx) -> QWidget`). Виджет не импортирует другие
виджеты и не знает окон. Контекст — узкий фасад над **одним** подключением плюс шина интерфейса:

```python
class WidgetContext(Protocol):          # Qt-free по импортам, frontend_module/bootstrap/context.py
    widget_id: str                      # экземпляр в раскладке (objectName дока)
    params: Mapping[str, Any]           # параметры экземпляра из раскладки
    connection: str                     # имя подключения из реестра
    state: StateChannel                 # subscribe(glob, cb) -> Handle; get(path)
    commands: CommandChannel            # request(target, command, data, timeout) -> Reply; send(...)
    frames: FrameChannel                # subscribe(source, cb) -> Handle — неблокирующий
    files: FileChannel                  # fetch(ref, on_done) -> Cancel — неблокирующий; заглушка до dataset-annotation 2.1 (§3.4)
    ui_bus: UiBus                       # publish(event, payload); subscribe(event, cb) -> Handle
    connection_state: ConnectionView    # текущее + подписка
    legacy_deps: object                 # ТОЛЬКО inspector.classic (§3.6)
```

Все `Handle` снимаются контекстом при уничтожении виджета и при рестарте воплощения (через `BootContext.attach`).

### 3.1 Состояние (канал «факт о системе»)

`state.subscribe(glob, cb)` поверх `GuiStateBindings` подключения: glob-синтаксис тот же, что у `StateProxy`;
колбэк — в GUI-потоке. Первое значение из кэша прокси приходит синхронно при подписке, если оно есть (чтобы виджет,
созданный после старта, не ждал дельты). Два виджета на один glob = одна подписка `ensure_subscription` у прокси
(счётчик ссылок), отписка последнего снимает её.

### 3.2 Команды (канал «действие»)

`commands.request(...)` возвращает `Reply(ok, data, error)`; ошибка бэкенда и разрыв соединения приходят **одной
формой** (Р-C). Для правки поля регистра — связь с gui-service 1b.2c: отказ бэкенда откатывает поле и показывает
текст; контекст отдаёт это виджету как `Reply(ok=False, error=...)`, откат делает движок форм. Блокирующий
`request` в GUI-потоке запрещён: вызов через `RequestRunner` (как сегодня у вкладок), результат — колбэком.

### 3.3 Кадры — веер и неблокирующая подписка (находка CTO 2)

Сегодня: `set_frame_callback` хранит **один** `_frame_cb` (`bridge_impl.py:34,48`, перепроверено);
`RemoteFrameSource.subscribe(senders, on_frame, timeout=5.0)` блокирует до ответа хоста, один запрос на вызов
(`remote_frame_source.py:228-232`, перепроверено). Если каждый виджет зовёт `ctx.frames.subscribe(camera, view.show)`
из фабрики, это N подписок на хосте и N блокировок GUI-потока при применении раскладки.

**Контракт:** на подключение — один `FrameHub`:
- первая подписка на источник порождает **одну** подписку вверх (in-process — регистрация в шине, remote —
  `RemoteFrameSource.subscribe`); следующие — только локальный веер; последняя отписка снимает верхнюю;
- вызов `subscribe` возвращается **сразу**; верхняя подписка выполняется вне GUI-потока, кадры доставляются в
  GUI-поток; ошибка верхней подписки приходит в `connection_state`/колбэк ошибки, не исключением в фабрику;
- медленный потребитель не тормозит остальных: веер отдаёт **последний** кадр, старые выбрасываются.

**Приёмка (литералы, в Task 1.5 и 2.4):** 5 виджетов на один источник → 1 верхняя подписка (in-process — счётчик на
фейковой шине; remote — `introspect_router_stats`/счётчик подписчиков на хосте = 1 на клиента); `subscribe` при
верхнем источнике, отвечающем через 2 с, возвращается в GUI-поток **≤ 50 мс**; применение раскладки с 5 дисплеями
не держит GUI-поток дольше 200 мс подряд (сторож модалок / stall-dump). **50 мс / 200 мс — временные:** якорь —
замер Task 1.1 (сегодняшнее время `create_tabs`, `app.py:871`, и применения дисплеев); Task 1.5 ссылается на это
число и при расхождении правит литерал 200 мс записью. «≤ 50 мс при верхнем ответе через 2 с» остаётся как есть.

### 3.4 Файлы по id — зарезервировано

Четвёртый канал — не состояние и не живые кадры: снимки датасета, спрайты слоёв.

**Канал файлов (согласовано 2026-09-26; одинаковый текст в `gui-constructor/design-connection-context.md` §3.4 и `dataset-annotation/phase-2-annotation-widget.md` Task 2.1).** Ссылка: `ref = {provider, name, id, variant}`, `variant ∈ {"thumb", "full"}`. Два слоя: (1) `RemoteFileSource.fetch(ref) -> tuple[bytes | None, str | None]` — во фреймворке (`frontend_module/bridge/remote_file_source.py`), без Qt, вызывается в потоке пула; (2) `FileChannel.fetch(ref, on_done) -> Cancel` — член контекста виджета `ctx.files`, неблокирующий; `on_done(FileResult(ok, data, mime, error))` вызывается в GUI-потоке; `Cancel` — вызываемое без аргументов. Подключение виджета — поле `ctx.connection: str`, каналы лежат прямо на `ctx`; метода `ctx.connection(name)` нет (это `BootContext`). Заглушка gui-constructor 1.5 возвращает `FileResult(ok=False, data=None, mime=None, error="files channel not implemented")`; реализацию делает dataset-annotation 2.1. Qt-обёртка `qt_files.py` адаптера `AnnotationPorts` уходит вместе с адаптером в sunset 2.5b.

### 3.5 Шина интерфейса (канал «контекст интерфейса»)

Выбранный дефект, выбранный слой, «вынести на Пульт» — не факт о системе и не действие на бэкенде. События
**объявлены в пакете** (`GuiAppSpec.ui_events`: имя с префиксом пакета, схема payload как `dict` ключей и типов).
Публикация необъявленного события — ошибка (в dev — исключение, в проде — лог + счётчик). Шина — в процессе
клиента, общая для всех подключений; payload — `dict` (Dict at Boundary и здесь, чтобы события можно было писать
в запись сессии). Прямая ссылка виджета на виджет запрещена. Реализация — Task 3.2, когда приходит второй пакет
(`sim.*`): до этого `QtEventBus` прототипа живёт как есть (`constructor-layers.md:105`).

### 3.6 Легаси-дверь `ctx.legacy_deps` и её закат (находки CTO g, 9)

`inspector.classic` (центральная часть `MainWindow`, `design-shell-layout.md` §5) требует всех 38 зависимостей
`RuntimeDeps` (CTO: 13 прикладных + 25 `FrameworkRuntime`). Дверь — 5 каналов. Чтобы не задержать gui-service 1.4,
`classic` получает `ctx.legacy_deps` = нынешний `RuntimeDeps`. Правила:
- член называется `legacy_deps` и есть **только** в контексте, созданном для `WidgetSpec` с флагом `legacy=True`;
- sunset-тест в `multiprocess_prototype/frontend/tests/`: число вхождений `ctx.legacy_deps` в прод-коде
  прототипа — **ровно 1** (`grep -rn "legacy_deps" multiprocess_prototype --include='*.py'` без `tests/`); рост —
  красный тест; уменьшение до 0 — отдельный коммит, меняющий литерал (Ф5);
- второй `WidgetSpec` с `legacy=True` — ошибка загрузки пакета.

## 4. Шаблоны поверх каналов

### 4.1 Сохранение командой с ревизией (холсты-редакторы)

Образец — `recipe.*` (gui-service 1b.1): черновик, undo и документ живут в GUI; сохранение — команда
`<svc>.commit{doc, base_rev}` → `{ok, rev}` или `{ok: false, error: "conflict", rev}`. Блокировок нет (падение
клиента не должно ничего вешать на бэкенде). Второй потребитель — редактор слоёв `sim.*` (Ф3) — поэтому клиентский
помощник черновика с ревизией уходит во фреймворк в Task 3.4 по правилу двух потребителей; до этого — только
описание шаблона.

### 4.2 Долгая задача

Не новый механизм, а оформленный шаблон: `<svc>.start{...}` → `{ok, job_id}`; прогресс и итог — в дереве состояния
`<svc>.jobs.<job_id>.{state, progress, message}`; `<svc>.cancel{job_id}`. Тот же набор доступен через
`backend_ctl`. Кода в этом плане нет — потребители (генерация датасета, обучение) в плане разметки; обучение может
уехать в облако, локальный UI обучения драйвером конструктора **не является** (решение владельца 2026-09-26).
Шаблон попадает в README контекста (Task 1.5) как текст.

## 5. Решения T4.1, которые остаются в силе

**Р-B — шина конвертов во фреймворк новым файлом** `frontend_module/bootstrap/envelope_bus.py` (сегодня
`multiprocess_prototype/frontend/bridge_impl.py`, 120 строк Qt, доменных слов нет; T4.1). `git mv` + импорт-сайты, без
шима. Причина: клиент вне дерева прототип импортировать не может (`apps/* ↛ multiprocess_prototype/*`,
`.sentrux/rules.toml:128-131` — ссылка gui-service на `:128` дрейфнула, находка CTO 8). Цена: если G.2 («единый
конверт») поменяет форму, файл меняется во фреймворке. Когда: Task 1.3 (нужна реестру).

**Р-C — форма отказа `RemoteCommandSender`:** `request_*` при разрыве возвращает
`{"success": False, "error": "connection lost", "request_id", "correlation_id"}`; `send_*` без соединения — лог, дроп,
счётчик дропов. Вкладки не ловят исключений (иначе 29 файлов-потребителей, аудит gui-service 1.1). Исполняет
gui-service 1.4 (класс его), мерило — контракт-набор §2.1.

**Р-D — тема** — декларация пакета (`ThemeSpec`), выбор пользователя — prefs клиента. Бэкенд о теме не знает;
у клиента вне дерева диска бэкенда нет (критерий «GUI без диска», gui-service 1b.3).

## 6. Открыто и ненадёжно

- Qt-free-ность `bus` — зависит от инвентаря сигнальных потребителей (Task 1.1). Если шина — Qt-тип, Protocol
  теряет член, и контракт-набор надо переписать; риск назван, не снят.
- Числа §3.3 (50 мс, 200 мс) — мои, временные до замера Task 1.1, не замерены на стенде. Веер живьём не мерился
  ни CTO, ни мной (qt-mcp не подключался, стенд не поднимался).
- Слияние подписок состояния по счётчику ссылок (§3.1) — предположение, что `GuiStateBindings` его допускает; не
  проверено чтением `GuiStateBindings`.
- Удалённый ui_tap: у клиента вне дерева нет `CommandManager`, `backend_ctl` не видит жестов его UI — отладочная
  плоскость не решена (T4.1 §9).
- Канал файлов: форма и транспорт — из плана разметки, сверены по его сообщению лиду, а не чтением его файлов
  целиком; если его `FileResult`/`ref` поменяются при постановке, этот раздел правится вслед.
