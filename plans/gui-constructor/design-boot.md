# Дизайн: сборка GUI — спека пакета, стадии, характеризация, hot-reload

Часть плана [`plan.md`](plan.md). Редакция T4.1 ([`gui-bootstrap-design.md`](../frontend-constructor/gui-bootstrap-design.md),
2026-09-24) под решение владельца [`constructor-layers.md`](../frontend-constructor/constructor-layers.md) и ревью CTO
[`2026-09-26_gui-constructor-layers-cto.md`](../../docs/reviews/2026-09-26_gui-constructor-layers-cto.md). Соседние файлы
дизайна: [`design-connection-context.md`](design-connection-context.md) (подключения, контекст виджета, шаблоны),
[`design-shell-layout.md`](design-shell-layout.md) (оболочка, раскладка, виджет, пакеты, Пульт).

**Откуда числа.** Ссылки `app.py:N` сняты в T4.1 на `3a5d738c` и **перепроверены 2026-09-26 на `e3f47c40`**
(`sed -n Np`): `app.py` — 1138 строк (`wc -l`), `grep -c "process\._" app.py` = 47, строки 91, 191, 339, 351, 436, 458,
769, 871, 1042, 1104, 1125 указывают туда же, куда в T4.1. Остальные ссылки перенесены из T4.1 без повторной сверки
и помечены «(T4.1)». Ничего не запускалось.

---

## 1. Что сохраняется из T4.1 и что развёрнуто

| Решение T4.1 | Статус в этом плане | Где |
|---|---|---|
| Р-A: список стадий расширен (12 стадий, окно раньше вкладок) | **сохраняется**, стадии `runtime`/`window`/`tabs` переименованы под новую форму | §3 |
| Р-B: шина конвертов во фреймворк новым файлом | сохраняется | `design-connection-context.md` §5 |
| Р-C: форма отказа `RemoteCommandSender` = error-dict | сохраняется | `design-connection-context.md` §5 |
| Р-D: тема — декларация пакета, выбор — prefs хоста | сохраняется | `design-connection-context.md` §5 |
| **Р-E: окно отдаёт пакет** | **развёрнуто владельцем 2026-09-26:** окна у оболочки, единица — виджет; переходный виджет `inspector.classic` | `design-shell-layout.md` §1, §5 |
| Р-F: hot-reload в `GuiBootstrap`, клиент вне дерева получает его бесплатно | сохраняется; зона чистки — список (находка CTO 10) | §5 |
| «Один рантайм на процесс» (`BootContext.runtime`) | **развёрнуто ревью CTO (находка 1):** реестр подключений с первого дня | `design-connection-context.md` §1 |

Р-A, Р-B, Р-C, Р-D, Р-F владелец **не оспорил, но явно не утверждал** (`constructor-layers.md:104`). План исходит из них;
подтверждение — открытый вопрос в [`plan.md`](plan.md), до старта Task 1.3.

---

## 2. `GuiAppSpec` — каталог виджетов пакета + раскладка по умолчанию

Было в T4.1: «контракт пакета вкладок» с хуками `build_window`/`tabs`. Стало: пакет отдаёт **каталог `WidgetSpec`**,
**раскладку по умолчанию** и хуки сборки прикладных сервисов. Окно не отдаёт никто, кроме оболочки.

Frozen-dataclass, **Qt-free по импортам** (Qt только в `TYPE_CHECKING`). Файл —
`frontend_module/bootstrap/interfaces.py`.

| Поле | Тип | Вид | Сегодня |
|---|---|---|---|
| `app_id`, `protocol_version` | `str`, `int` | декларация | нет; сверяется с `capabilities` бэкенда (добавляет gui-service 1.4) |
| `identity` | `AppIdentity` (`frontend_module/core/app_identity`) | декларация | `app.py:91` |
| `theme` | `ThemeSpec(dir: Path, default: str)` | декларация | `app.py:147-159` из манифеста (T4.1) → Р-D |
| `subscriptions` | `tuple[str, ...]` | декларация | захардкожены `process.py:131-148` (T4.1) |
| `telemetry_suffixes` | `tuple[str, ...] \| None` | декларация | дефолт фреймворка |
| `timers` | `tuple[TimerSpec(interval_ms, hook), ...]` | декларация + имя хука | fps-таймер `app.py:1062-1104` |
| **`widgets`** | `tuple[WidgetSpec, ...]` | декларация | вкладки `TabFactory` — регистрируются 1:1 (Task 1.5) |
| **`default_layout`** | `str` — путь к YAML раскладки внутри пакета | декларация | нет |
| **`ui_events`** | `tuple[UiEventSpec, ...]` | декларация | нет (Task 3.2) |
| `reload_prefixes` | `tuple[str, ...]` с завершающей точкой | декларация | неявно `process.py:385-392` (T4.1) → §5 |
| `hooks` | `GuiHooks` | хуки | тело `run_gui` |

`GuiHooks` — только **именованные** функции `(ctx: BootContext) -> None | T`: `build_services`, `state_listeners`,
`authenticate`, `build_app_services`, `wire_frames`. Хуков `build_window` и `tabs` больше нет: окно строит оболочка
(стадия `shell`), виджеты создаёт применение раскладки (стадия `widgets`). Лямбда — только если тело — один вызов;
приёмка Task 1.4 считает их грепом.

`WidgetSpec` описан в `design-shell-layout.md` §3. Спека пакета — **данные плюс ссылки на функции**, её можно
импортировать без `QApplication`.

**Загрузка по имени** — строка `"<модуль>:<атрибут>"`, как класс процесса `gui` в `launch.py:216` (T4.1). Встроенный
GUI получает её параметром процесса из `presentation.yaml`, `apps/gui_client` — из своего конфига подключений.
Загрузчик `frontend_module/bootstrap/pack_loader.py` (Qt-free) сверяет `app_id`/`protocol_version`, при несовпадении
называет обе версии и виджетов пакета не создаёт. **Пакетов у одного клиента может быть несколько** (пакет
инспектора + пакет `sim.*` + общие виджеты фреймворка), каждый привязан к подключению (§3 стадия `widgets`).
Entry points не заводим — явный список.

**Лимит спеки: `app_spec.py` ≤ 300 строк** — держится, только если хуки лежат в `multiprocess_prototype/frontend/boot/*.py`.
До промоушена кита (frontend-constructor Ф3) хуки толстые; сложность переезжает из одной функции в именованные модули,
а не исчезает. Это граница, сказанная прямо (T4.1 §2).

---

## 3. Стадии и базовая линия характеризации

### 3.1 Стадии

| # | Стадия | Владелец | Строки `run_gui` сегодня |
|---|---|---|---|
| 0 | `diagnostics` — сторож модалок, stall-dump, qt-mcp probe | фреймворк | `70-84`, `132-144` (T4.1) |
| 1 | `identity` — `set_app_identity`, WheelGuard, UiEventTap | фреймворк + `spec.identity` | `91-118` |
| 2 | `theme` | фреймворк + `spec.theme` | `146-159` (T4.1) |
| 3 | **`connections`** — реестр подключений; для каждого — рантайм (отправитель, прокси, шина) | фреймворк | `188-202`, `328` (T4.1) |
| 4 | `services` — реестры, топология, проверки старта, каталоги, адаптеры рецептов | хук `build_services` | `161-186`, `204-316`, `400-415`, `460-557` (T4.1) |
| 5 | `state` — VM, bindings, поллер; слушатели шины **по порядку** | фреймворк + хук `state_listeners` | `318-398`, `436`, `458` |
| 6 | `session` — auth, автологин, модальный `LoginDialog` | хук `authenticate` (может завершить процесс) | `559-644` (T4.1) |
| 7 | `app_services` — `build_app_services` + подписки доменной шины | хук `build_app_services` | `646-766` (T4.1) |
| 8 | **`shell`** — окна оболочки, доки, замок, статус подключений (`design-shell-layout.md` §1) | фреймворк | `768-814` (сегодня `MainWindow()` на `769`) |
| 9 | **`widgets`** — применение раскладки: для каждого дока — `WidgetSpec.factory(ctx)` с контекстом (виджет, подключение) | фреймворк | `816-887` (сегодня `create_tabs` на `871`) |
| 10 | `wiring` — кадры и маршрутизация дисплеев | хук `wire_frames` | `889-897` → `915-1042` |
| 11 | `timers` — `spec.timers` + safety/aboutToQuit | фреймворк | `899-900` → `1046-1138` |
| 12 | `show` — `topology_session.reset()` (хук), `show`, `exec` | фреймворк | `903-912` (T4.1) |

Перестановка против кода одна: объекты `services` (`161-186`) уезжают за `connections` (`188-202`); оба блока ничего
не подписывают. Побочные эффекты `PluginManager.initialize()` (`app.py:184`) при переносе не проверены — пункт
характеризации Task 1.1.

`state` стоит **раньше** `session` и так остаётся: `LoginDialog.exec()` и `StartupBlockingDialog.exec()` крутят
вложенный цикл событий, в нём доставляются конверты, уже поставленные рабочим потоком в очередь
(`bridge_impl.py:44`, AutoConnection → Queued). Слушатели подключаются до первой модалки. **Вывод из чтения, живьём
не наблюдался** — Task 1.1 проверяет.

**Что меняет реестр подключений в стадиях.** Стадии 3, 5, 9, 10 работают «на подключение»: у встроенного GUI одно
подключение `local` (`InProcessRuntime`), у `apps/gui_client` — N (`RemoteGuiRuntime` каждое). Стадии 6–7 пока
остаются у пакета инспектора и получают его подключение явно (`ctx.connection(spec.app_id)`), а не «единственный
рантайм». Правка стадий — Task 1.3–1.4, до оболочки, чтобы Ф2–Ф3 не переписывали стадии (находка CTO 1).

### 3.2 Порядок подключения, который фиксирует характеризация (Task 1.1)

Шина конвертов (`process._bridge`):
1. `set_state_callback` ← `GuiStateBindings` (первичный) — в конструкторе, `app.py:339-347`
2. `add_state_listener(telemetry_view_model.on_state_delta)` — `app.py:351`
3. `add_state_listener(_forward_state_delta_to_topology)` — `app.py:436`
4. `add_state_listener(_obs_tail_activator.on_state_delta)` — `app.py:458`
5. `tabs.bind_live_source(bridge)` — вкладка наблюдаемости внутри `create_tabs` (`app.py:871`); колбэк или
   Qt-сигнал `observability_received` (`bridge_impl.py:30`) — не проверено (T4.1 §9), выясняет Task 1.1
6. `set_frame_callback(_on_frame_received)` — `app.py:1042`

Доменная шина (`QtEventBus`, обработчики в порядке регистрации, `app.py:713-717`, T4.1):
- `TopologyReplaced`: `topology_bridge.on_topology_changed` (`679`) → `session.mark_edited` (`697`) → подписчики вкладок (`871`)
- `RecipeActivated`: `session.mark_activated` (`698`) → подписчики вкладок (`871`) → `_rebuild_displays` (`999`)
- `PluginConfigChanged`: live-запись (`766`) → подписчики вкладок, если есть
- `DisplaysChanged`: подписчики вкладок (`871`) → `_rebuild_displays` (`1000`)

Таймеры и выход: `fps_timer.start` (`1104`) → `safety_timer.start` (`1121`) → `aboutToQuit`: флаг остановки (`1125`)
→ `aboutToQuit`: `telemetry_poller.stop` (`1134`).

Модальные точки: `StartupBlockingDialog` (`579`/`590`, затем `sys.exit(1)`) → `LoginDialog` (`640`); обе после
шагов 1–4 шины и до окна.

**Приёмка характеризации** — снимок этой последовательности до разборки и **равенство списков** после. Шина и
`event_bus` инжектируются, шпион на них законен: здесь имена `add_state_listener` / `subscribe` и есть контракт.
Break-injection: переставить `436` и `458` — тест обязан упасть.

**Что характеризация добавляет к T4.1 (новое):**
- инвентарь **Qt-сигнальных** потребителей шины (`frame_received`/`state_updated`/`observability_received`,
  `bridge_impl.py:25-30`) — от него зависит, Qt-free ли Protocol шины (T4.1 §9; `design-connection-context.md` §2);
- инвентарь **подписчиков кадров**: сегодня `set_frame_callback` хранит один `_frame_cb`
  (`bridge_impl.py:34,48`, перепроверено) — сколько дисплеев сидит за ним и как они разбирают `sender`;
- число полей, которые вкладки реально берут из `RuntimeDeps` (CTO: 13 прикладных + 25 `FrameworkRuntime` = 38) —
  база для легаси-двери `ctx.legacy_deps` (`design-connection-context.md` §3.6).

---

## 4. `BootContext` и жизнь воплощения UI

`BootContext` — изменяемый контейнер одного воплощения UI: `app`, `connections` (реестр), `shell`, `view_model`,
`bindings`, `services`, `extras: dict`. Тот же «bag», что сегодня держат локалы `run_gui` (T4.1: `app.py:188-190`,
«AppContext удалён»), только явный. Члена `runtime` **нет** — вместо него `ctx.connection(name)` (реестр).

Всё, что воплощение подключает к долгоживущим объектам (шина подключения, прокси, `app`, оболочка), идёт через
`BootContext.attach(target, handle)`; на выходе из воплощения снимается в **обратном** порядке. Это закрывает
гипотезу утечки слушателей (§5 находка 2) и заранее — подписки `ensure_subscription`, которые у клиента вне дерева
живут на бэкенде.

---

## 5. Контракт hot-reload

Сегодня (`process.py:308-326`, `376-405`, T4.1; строки `325`, `376`, `392`, `401` перепроверены) после `_restart_ui`
удаляются модули с префиксом `multiprocess_prototype.frontend`, кроме `…frontend.process` и `…frontend.bridge`, затем
`importlib.reload(app)` и повторный `run_gui`.

Находки T4.1, сохраняются:
1. **Префикс без точки** (`process.py:392`): `"…frontend.bridge_impl".startswith("…frontend.bridge")` истинно —
   `DataReceiverBridge` переживает рестарт случайно.
2. **Слушатели шины, по всей видимости, текут между воплощениями.** `add_state_listener` дедуплицирует по
   идентичности (`bridge_impl.py:55-63`), каждое воплощение добавляет три новых callable (`351`, `436`, `458`),
   `remove_state_listener` в `app.py` не вызывается (T4.1: греп 0). **Гипотеза, не воспроизведение**; Task 1.1
   считает `len(bus._state_listeners)` после двух рестартов, ожидание автора 3 → 6 → 9.

Находка CTO 10, новая: зона чистки — только прототип. Пакеты в `Services/*/gui/` и общие виджеты фреймворка кнопкой
«Перезапустить интерфейс» не перезагрузятся.

**Контракт:**
- Цикл рестарта переезжает из `GuiProcess.run` в `GuiBootstrap.run_forever(connections, pack_refs)`. Реестр
  подключений создаётся один раз и рестарт переживает; стадии 0–12 выполняются заново.
- **Зона чистки — объединение `spec.reload_prefixes` всех загруженных пакетов** (каждый префикс с завершающей
  точкой), минус `runtime.keep_modules` каждого подключения. Пакет `sim.*` из `Services/line_sim/gui/` отдаёт
  `("Services.line_sim.gui.",)` и перезагружается кнопкой; корень `Services.line_sim` — нет (он Qt-free и может
  держать состояние бэкенд-клиента).
- Фреймворк **не перезагружается никогда** — ни `frontend_module`, ни виджеты кита. DX-регресс, сказанный прямо:
  правка оболочки, стадий, шины, реестра или промоутнутых виджетов требует полного рестарта GUI. Записать в README
  `frontend_module/bootstrap` и в README прототипа (Task 1.4).
- Утечка (находка 2): характеризация Task 1.1 **фиксирует текущее** (3 → 6); Task 1.4 меняет ожидание на «3 → 3»
  отдельным коммитом с записью, что поведение изменено намеренно.

---

## 6. Риски сборки и чем их мерить

| Риск | Чем мерить |
|---|---|
| Разборка `run_gui` тихо меняет порядок | Task 1.1: снимок §3.2 до и после — равенство списков; инъекция «переставить 436/458» роняет тест |
| Утечка слушателей при рестарте UI | Task 1.1 фиксирует текущее; Task 1.4 — «после рестарта столько же, сколько после старта» |
| Сложность мигрирует в спеку | Task 1.4: `wc -l app_spec.py` ≤ 300; `grep -c "lambda" app_spec.py` = 0; `run_gui` удалён |
| Приватные атрибуты остаются | Task 1.3: `grep -c "process\._" multiprocess_prototype/frontend/app.py` = 0 (сегодня 47); `grep -cE "getattr\(process\|setattr\(process"` = 0 (T4.1: 6) |
| Реестр на одну реализацию подогнан под «один рантайм» | Task 1.3: контракт-набор параметризован **двумя** подключениями одного типа (два фейковых процесса); `RemoteGuiRuntime` подключается к тому же набору в gui-service 1.4 |
| Qt протекает в ядро | `grep -l PySide6 frontend_module/bootstrap/{interfaces,runtime,runtime_inprocess,connections,pack_loader,context}.py` → пусто. Импорт-проверка `assert "PySide6" not in sys.modules` сегодня упала бы у всех (`frontend_module/__init__.py` тянет `components`/`widgets`, T4.1 §7) — в приёмку не ставить до расщепления Р-4 |
| Hot-reload умер | qt-smoke: «Перезапустить интерфейс» дважды → окно и виджеты на месте, число слушателей стабильно |
| Регресс сьюты | pytest-qt `multiprocess_prototype/frontend` ≥ 2470 passed / 0 failed, `frontend_module` ≥ 574 (baseline аудита gui-service 1.1, T4.1 §8). **Числа июльско-сентябрьские — Task 1.1 переснимает baseline первым шагом** |

## 7. Открыто по сборке

- Порядок §3.2 реконструирован из исходника; подписчики внутри конструкторов вкладок не пройдены — даст только
  живой снимок Task 1.1.
- Что происходит с сигналами рабочего потока `data_receiver` **до** создания `QApplication` (`process.py:158-163`,
  T4.1) — не знаю; вопрос характеризации.
- G.2 «единый конверт» — влит ли, не проверял; от него зависит цена Р-B.
- Разные QSettings-namespace (`main_window.py:266` — `INNOTECH/Inspector`, перепроверено; `app.py:91` —
  `Inspector/Inspector Bottles`) — последствия для сохранённой геометрии при переходе на оболочку не оценены
  (`design-shell-layout.md` §2.4).
