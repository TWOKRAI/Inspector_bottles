# Ф2 — Минимальная оболочка, `inspector.classic`, эталон `examples/minimal_gui`

Часть плана [`plan.md`](plan.md). Ветка `feat/gui-constructor-f2`. Бывший T4.6 frontend-constructor (вынут из Блока В
решением владельца 2026-09-26: «раньше, к 1.4, в минимуме: доки, раскладка, замок») плюс бывшая Ф5 того же плана
(`minimal_gui`) в новой форме. Дизайн — [`design-shell-layout.md`](design-shell-layout.md).

**Цель фазы:** окна принадлежат оболочке фреймворка; встроенный GUI = оболочка + `inspector.classic`; клиент вне
дерева `apps/gui_client` (gui-service 1.4) — та же оболочка; второй потребитель оболочки — `examples/minimal_gui` —
собирается без прототипа, `Services` и `Plugins` и проходит headless CI против `examples/minimal_app` по сокету.
Это **приёмка gui-service 1.4 со стороны фреймворка** (`constructor-layers.md:76-77`).

Канон запуска задач — как в [`phase-1-boot-split.md`](phase-1-boot-split.md) (шапка): tester до кода в worktree →
исполнитель → инъекции лида с предсказаниями → стенд → reviewer синхронно; исполнители не коммитят и не пушат;
2 итерации → эскалация.

**Порядок внутри фазы:** 2.1 → 2.2 → **gui-service 1.4** (владелец — gui-service; `RemoteGuiRuntime` +
`apps/gui_client`) → 2.4. Task 2.3 — параллельно с 2.1/2.2 (другие файлы).

---

### Task 2.1 — Оболочка `frontend_module/host/`: окна, доки, раскладка, замок

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree на коммите конца Ф1) → teamlead → reviewer
- **Goal:** стадия `shell` строит `GuiHostWindow` фреймворка; стадия `widgets` создаёт доки по YAML раскладки;
  правки пользователя сохраняются блобом; замок переживает восстановление; док переносится в другое окно меню.
- **Design:** `design-shell-layout.md` §1–§2. Путь **вне** Gen-1 `windows/` (находка CTO 4). Нативные
  `QMainWindow` + `QDockWidget`, без ADS. Разбор YAML — Qt-free (`host/layout_model.py`). **Module contract:** new-full
  (`frontend_module/host/`: README, STATUS, тесты).
- **Files:** 1. НОВЫЙ `frontend_module/host/window.py`; 2. НОВЫЙ `…/host/layout_model.py` (Qt-free: схема YAML,
  валидация, хеш набора `objectName`); 3. НОВЫЙ `…/host/layout.py` (применение/сохранение, блоб); 4. НОВЫЙ
  `…/host/lock.py`; 5. `frontend_module/bootstrap/bootstrap.py` (стадии `shell`/`widgets`); 6. НОВЫЙ
  `…/host/tests/test_host_layout.py` (pytest-qt offscreen).
- **Acceptance:**
  - [ ] YAML с двумя окнами и тремя доками → созданы 2 `QMainWindow` и 3 `QDockWidget` с `objectName`
        `window.<id>` / `dock.<widget_id>`; док с `tab_with` — во вкладке соседа (`tabifiedDockWidgets` не пуст).
  - [ ] Round-trip блоба: сдвинуть док, закрыть, открыть → положение восстановлено (область и `isFloating`).
  - [ ] **Замок переживает `restoreState`:** блоб, где запертый док был плавающим и скрытым, применён → док видим,
        пристыкован, `features()` без `DockWidgetClosable`/`DockWidgetFloatable`/`DockWidgetMovable`.
  - [ ] Хеш набора `objectName` не совпал (в YAML добавлен док) → блоб не применён, раскладка по YAML, в логе одна
        строка с причиной.
  - [ ] «Переместить в окно ▸ aux» → `dock.parent()` = окно `aux`, в исходном окне `dockWidgetArea` =
        `NoDockWidgetArea` (проба CTO как тест).
  - [ ] Статус подключений: фейковое подключение переходит `CONNECTED → DISCONNECTED` → индикатор в строке статуса
        меняет текст ≤ 1 с; `close_guards` возвращает `False` → окно не закрыто.
  - [ ] Предметных слов нет: `grep -riE "bottle|defect|inspection|Inspector_bottles" frontend_module/host --include='*.py'`
        вне тестов → 0; `grep -l PySide6 frontend_module/host/layout_model.py` → пусто.
- **Break-injection (лид):** применять замок **до** `restoreState` → предсказание: падает только тест «замок
  переживает»; убрать проверку хеша → падает тест «блоб не применён».
- **Dependencies:** Ф1 целиком (1.4 — стадии, 1.5 — `WidgetSpec`/контекст).

---

### Task 2.2 — `inspector.classic`: центральная часть `MainWindow` как виджет в оболочке

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree на коммите после 2.1) → teamlead → reviewer
- **Goal:** встроенный GUI = `GuiHostWindow` + один запертый док `inspector.classic` (header / банер / центральная
  панель / tab-host) + раскладка инспектора по умолчанию. Для оператора выглядит как сегодня.
- **Design:** `design-shell-layout.md` §1 (что уходит в оболочку), §5; `design-connection-context.md` §3.6
  (`legacy_deps`). Статус-бар, F11, геометрия, QSettings — у оболочки; метрики FPS/Latency/Frames — `add_status_widget`
  из пакета; RS-4 — `close_guards`. Миграция геометрии `INNOTECH/Inspector` — один раз (§2.4). **Module contract:**
  impl-only.
- **Files:** 1. `multiprocess_prototype/frontend/windows/main_window.py` → центральный виджет (класс-наследник
  `QWidget`, не `QMainWindow`); 2. НОВЫЙ `multiprocess_prototype/frontend/layouts/default.yaml`; 3.
  `multiprocess_prototype/frontend/app_spec.py` (`WidgetSpec("inspector.classic", legacy=True, …)`, `default_layout`);
  4. `multiprocess_prototype/frontend/boot/*` (статус-виджеты, `close_guards`); 5. тесты окна прототипа, завязанные на
  `QMainWindow` (правка ожиданий — поимённо в отчёте).
- **Acceptance:**
  - [ ] `inspector.classic` — не `QMainWindow` (`isinstance` ассерт); в процессе ровно один `QMainWindow` верхнего уровня.
  - [ ] Набор вкладок и их порядок внутри `classic` == до задачи (тест 1.5 зелёный).
  - [ ] Закрытие окна с несохранённой топологией → вопрос RS-4 (через `close_guards`), «Отмена» → окно открыто.
  - [ ] Строка статуса показывает FPS/Latency/Frames (5 биндингов `system.*` живы — тест на фейковом состоянии).
  - [ ] Первый запуск на prefs с ключом `INNOTECH/Inspector` → геометрия главного окна взята оттуда; второй запуск —
        из ключа `AppIdentity`; старый ключ не перезаписан.
  - [ ] Характеризация 1.1, sunset `legacy_deps` = 1, сьюты ≥ baseline; qt-smoke и hot-reload ×2.
- **Break-injection (лид):** оставить `classic` наследником `QMainWindow` → предсказание: падает `isinstance`-тест
  и тест «один `QMainWindow`»; убрать регистрацию `close_guards` → падает тест RS-4.
- **Dependencies:** 2.1.

---

### Task 2.3 — `examples/minimal_app`, шаги 1–2: счётчик в состоянии, команда с ответом

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** эталон бэкенда даёт то, что тянет `minimal_gui`: `ticker` пишет счётчик в дерево состояния (шаг 1);
  команда с ответом — `reset` и `set_interval{sec}` (шаг 2; связь с gui-service 1b.2c — «команда туда и обратно»).
- **Design:** `constructor-layers.md` → таблица шагов. Дальше двух шагов не расти: 3–4 — Ф3, по вытягиванию.
  **Module contract:** impl-only (эталон; публичного API не меняет).
- **Files:** 1. `examples/minimal_app/plugins/tick_source/plugin.py`; 2. `examples/minimal_app/pipeline.yaml` (если
  нужен путь состояния); 3. `examples/minimal_app/tests/test_ci_smoke.py`; 4. `examples/minimal_app/README.md`.
- **Acceptance:**
  - [ ] Путь состояния `ticker.count` (точное имя — в README): через `BackendHarness` + `state_get` за 5 с при
        интервале 1 с — не меньше 3 разных возрастающих значений.
  - [ ] `send_command(ticker, reset)` → ответ `{"success": true}` ≤ 2 с, следующее значение `ticker.count` ≤ 1.
  - [ ] `set_interval{sec: 0.2}` → за 2 с не меньше 6 новых значений; `set_interval{sec: -1}` → ответ
        `{"success": false, "error": …}` с текстом про диапазон, интервал не изменился.
  - [ ] Smoke по-прежнему ≤ 10 с (сегодня 2.4–2.8 с по записи и ревью CTO); `grep -rnE "^\s*(from|import)\s+(multiprocess_prototype|Services|Plugins)" examples --include='*.py'` → 0.
- **Break-injection (лид):** команда `reset` без ответа (return None) → предсказание: падает тест ответа, тест
  значения после сброса — тоже (ждёт ответа); `set_interval` принимает отрицательное значение → падает только тест
  отказа; счётчик пишется в состояние константой → падает только тест «3 возрастающих значения».
- **Dependencies:** нет (параллельно 2.1/2.2).

---

### Task 2.4 — `examples/minimal_gui` + headless CI smoke против `minimal_app` по сокету

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree на коммите после gui-service 1.4) → developer → reviewer
- **Goal:** «сделай свой GUI» исполняемой документацией: несколько строк `run.py`, `layout.yaml`, один локальный
  пакет с одним виджетом (счётчик `minimal_app`) + один общий виджет фреймворка — всё грузится одинаково.
- **Design:** `constructor-layers.md` → «Приёмка `examples/minimal_gui`»; `design-shell-layout.md` §2–§4. Клиент —
  тот же, что `apps/gui_client`: `GuiBootstrap` + `RemoteGuiRuntime` + оболочка; своего кода рантайма в эталоне нет.
  **Module contract:** new-full (эталон: README как туториал, тесты).
- **Files:** 1. НОВЫЙ `examples/minimal_gui/run.py`; 2. НОВЫЙ `…/layout.yaml`; 3. НОВЫЙ `…/pack/{__init__,widgets}.py`
  (`APP_SPEC` + виджет счётчика: число + кнопка «Сброс»); 4. НОВЫЙ `…/README.md` (стиль `minimal_app/README.md`);
  5. НОВЫЙ `…/tests/test_gui_smoke.py`; 6. CI-конфиг job рядом с examples-smoke (путь — где живёт нынешний
  examples-smoke; назвать в отчёте).
- **Acceptance:**
  - [ ] `grep -rnE "^\s*(from|import)\s+(multiprocess_prototype|Services|Plugins)" examples/minimal_gui --include='*.py'` → 0;
        `sentrux check .` зелёный (правила Task 1.0).
  - [ ] CI smoke (`QT_QPA_PLATFORM=offscreen`): `BackendHarness` поднимает `minimal_app` с `BACKEND_CTL=1`,
        клиент подключается по сокету; виджет счётчика показывает не меньше 3 разных возрастающих значений за 5 с.
  - [ ] Кнопка «Сброс» (программный клик) → ответ бэкенда доходит до виджета ≤ 2 с, значение ≤ 1.
  - [ ] Общий виджет фреймворка (`fw.processes` или телеметрия — выбрать один и назвать) показывает `ticker` и
        `console_sink` — загружен тем же загрузчиком по строке, что локальный пакет.
  - [ ] `wc -l` прикладного кода эталона (`run.py` + `pack/`) ≤ 150; `run.py` ≤ 15 строк.
  - [ ] Остановка `minimal_app` посреди smoke → индикатор «отключён» ≤ 5 с, процесс клиента жив; smoke целиком ≤ 60 с.
  - [ ] README воспроизведён по шагам reviewer'ом (вывод команд — в отчёте ревью).
- **Break-injection (лид):** импорт `Services.line_sim` в `pack/widgets.py` → предсказание: красные sentrux и
  грепный тест; виджет подписан на неверный путь состояния → падает только тест «3 значения»; фабрика виджета зовёт
  `frames.subscribe` синхронно-блокирующе — **не ловится** этим эталоном (кадров нет), ловит 1.5 — записать как
  известную слепую зону эталона.
- **Dependencies:** 2.1, 2.3; gui-service **1.4** (`RemoteGuiRuntime`, `apps/gui_client`).

---

## Что gui-service 1.4 получает от этой фазы (для синхронизации)

| gui-service 1.4 ждёт | Откуда |
|---|---|
| стадии, реестр, `GuiBootstrap`, загрузчик пакетов | Ф1 (1.3, 1.4) |
| контекст виджета, вкладки виджетами | Ф1 (1.5) |
| оболочка с доками, раскладкой, замком, статусом подключения | 2.1 |
| пакет инспектора с `inspector.classic` без `QMainWindow` | 2.2 |
| `apps/gui_client` = оболочка + конфиг подключений + `RemoteGuiRuntime` | **сама gui-service 1.4** |

`examples/minimal_gui` (2.4) — второй потребитель оболочки и загрузчика рядом с инспектором; пока он не собирается
без прототипа, общее ещё сидит в прототипе — это счётчик долга (`constructor-layers.md:78`).
