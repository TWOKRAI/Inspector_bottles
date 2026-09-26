# Ф1 — Разборка сборки GUI: стадии, реестр подключений, контекст виджета

Часть плана [`plan.md`](plan.md). Ветка `feat/gui-constructor-f1`. Бывшие T4.2–T4.5 frontend-constructor плюс то,
что ревью CTO потребовало до кода: реестр подключений (находка 1), веер кадров (2), легаси-дверь с закатом (9),
список зоны hot-reload (10), правила слоёв (условие 3). Дизайн — [`design-boot.md`](design-boot.md),
[`design-connection-context.md`](design-connection-context.md).

**Цель фазы:** встроенный GUI собирается `GuiBootstrap` из спеки пакета через реестр с одним подключением `local`;
нынешние вкладки — виджеты 1:1 с контекстом; **поведение для оператора не меняется** (характеризация равна до/после).

**Канон запуска (`.claude/CLAUDE.md` → «Task launch convention»), одинаков для всех задач фазы с механизмом:**
независимый `tester` один раз на механизм, **до** реализации, в `git worktree` на коммите до реализации, только по
acceptance criteria этого файла (запрещены: diff, файлы из FILES задачи, тесты автора) → его RED — спека исполнителю →
`developer`/`teamlead` (тесты на внутренние опасности — свои) → break-injection лида по каждому свойству с
предсказанием до прогона, по **обоим** наборам → живой стенд → `reviewer` синхронно (`run_in_background: false`),
находки — вход → наблюдаемый выход. Исполнители не коммитят в `main`, не пушат, не открывают PR — коммитит лид.
Лимит итераций исправления — 2, на третьей — эскалация `teamlead` → `cto`; лимит действует на любой глубине вложенности.

**Один писатель `app.py`:** задачи 1.2–1.5 и gui-service **1b.2b** правят `multiprocess_prototype/frontend/app.py` —
строгая очередь, не параллельно (записано в gui-service `plan.md`, Task 1b.2b).

---

### Task 1.0 — Правила слоёв для пакетов виджетов и эталонов (условие CTO 3)

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Handoff:** tester (RED, worktree на пред-коммите: пишет грепный контракт-тест и пробы-нарушения по acceptance ниже) →
  developer (правила `rules.toml`, `Services/STATUS.md`) → reviewer. Канон не пропускается: контракт-тест — код, и
  его пишет не автор правил.
- **Goal:** до первой строки кода конструктора границы, в которые он ляжет, стоят и **ловят** нарушение.
- **Design:** `design-shell-layout.md` §4 «Правила слоёв». Синтаксис sentrux — буквальные префиксы, исключений нет,
  поэтому `Services ↛ Qt кроме gui/` — контракт-тестом грепом, `examples ↛ Services/Plugins` — `[[boundaries]]`.
  **Module contract:** n/a.
- **Files:** 1. `.sentrux/rules.toml` (два `[[boundaries]]` рядом с `rules.toml:119-122`); 2. НОВЫЙ
  `Services/tests/test_no_qt_outside_gui.py` (или `scripts/` — где уже живут грепные контракт-тесты; выбрать по
  соседству и назвать в отчёте); 3. `Services/STATUS.md` — строка о правиле.
- **Acceptance:**
  - [ ] `sentrux check .` (CLI) — `✓ All rules pass`, число правил = прежнее + 2 (прежнее число назвать из вывода до правки).
  - [ ] RED-проба: временный файл `examples/_probe.py` с `import Services.line_sim` → `sentrux check .` называет
        нарушение `examples/* → Services/*`; файл удалён, проверка зелёная. Вывод обоих прогонов — в отчёте.
  - [ ] Контракт-тест: зелёный на дереве; временный `import PySide6` в `Services/line_sim/core/_probe.py` → красный с
        путём файла; тот же импорт в `Services/line_sim/gui/_probe.py` → зелёный; три автономных инструмента
        (`robot_comm/server/sim_robot.py`, `sim_monitor.py`, `hikvision_camera/sdk_app/main_window.py`) —
        разрешены поимённо, четвёртый вне `gui/` → красный.
  - [ ] Проба «ловит ли sentrux внешний `to = "PySide6/*"`»: временное правило + импорт → результат записан в
        отчёт одной строкой (ловит / не ловит). Если ловит — добавить правило на `Services/line_sim/core/*`.
- **Break-injection (лид):** убрать разрешение `*/gui/**` из теста → предсказание: красный только на пробе в `gui/`;
  убрать одно из трёх поимённых исключений → красный на этом файле.
- **Dependencies:** нет. Первая задача фазы.

---

### Task 1.1 — Характеризация boot-порядка и инвентари (бывш. T4.2, первая половина)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** tester
- **Handoff:** tester (характеризационные тесты = спека для 1.2–1.5) → reviewer
- **Goal:** зафиксировать **текущее** поведение сборки до разборки: порядок §3.2, модалки, таймеры, утечку
  слушателей при рестарте, потребителей шины и кадров.
- **Design:** `design-boot.md` §3.2, §5. Шпион на инжектируемых шине и `event_bus` законен (имена методов — контракт).
  **Module contract:** n/a (тесты + отчёт).
- **Files:** 1. НОВЫЙ `multiprocess_prototype/frontend/tests/characterization/test_boot_order.py`;
  2. НОВЫЙ `…/characterization/test_ui_restart_listeners.py`; 3. НОВЫЙ `…/characterization/conftest.py` (фейковый
  процесс/шина); 4. НОВЫЙ `plans/gui-constructor/inventory-f1.md` — таблицы: замер времени сегодняшнего `create_tabs`
  (`app.py:871`) и применения дисплеев (якорь литералов Task 1.5), Qt-сигнальные потребители шины,
  подписчики `_frame_cb`, поля `RuntimeDeps`, которые реально читают вкладки (число и список), baseline сьют.
- **Acceptance:**
  - [ ] Тест порядка: список событий шины (`set_state_callback`, 3× `add_state_listener` в порядке 351/436/458,
        `bind_live_source`, `set_frame_callback`), доменной шины по типам событий, старта таймеров и `aboutToQuit` —
        записан литералом в тесте (не выведен из кода), зелёный на текущем `app.py`.
  - [ ] Тест утечки: два рестарта UI → `len(bus._state_listeners)` записан литералом того, что **наблюдается**
        (гипотеза автора T4.1: 3 → 6 → 9; если иначе — это находка, записать).
  - [ ] Модалки: `StartupBlockingDialog`/`LoginDialog` стоят после шагов 1–4 шины и до окна — ассерт по порядку.
  - [ ] `inventory-f1.md` отвечает на три вопроса числом со ссылкой на команду: сколько потребителей подписаны на
        Qt-сигналы шины и какие; сколько дисплеев за одним `_frame_cb`; сколько из 38 полей `RuntimeDeps` читают вкладки.
  - [ ] Якорь для Task 1.5: время `create_tabs` (`app.py:871`) и применения дисплеев на текущем `app.py` — медиана
        из 5 запусков offscreen, мс, команда и вывод в `inventory-f1.md`.
  - [ ] Baseline сьют переснят: `multiprocess_prototype/frontend` и `frontend_module` offscreen — passed/failed числом.
- **Break-injection (лид):** переставить `app.py:436` и `app.py:458` → предсказание: падает только тест порядка;
  добавить `remove_state_listener` в выход воплощения → тест утечки падает (он фиксирует текущее).
- **Dependencies:** нет (параллельно 1.0).

---

### Task 1.2 — Механическая разборка `run_gui` на стадии-функции (бывш. T4.2 + T4.5)

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Handoff:** teamlead (REDS = характеризация 1.1, зелёная до и после каждой стадии) → reviewer
- **Goal:** 1078 строк композиции (`run_gui` + `_setup_bridge_callbacks` + `_setup_timers`, T4.1) разложены на
  функции стадий `design-boot.md` §3.1 в `multiprocess_prototype/frontend/boot/`; вложенные колбэки и таймеры —
  стадии `wiring`/`timers`. Логика не меняется, `process._*` пока остаются.
- **Design:** `design-boot.md` §3.1 — порядок стадий; перестановка одна (`services` за `connections`). Каждая стадия —
  отдельный коммит + qt-smoke. **Module contract:** impl-only.
- **Files:** 1. `multiprocess_prototype/frontend/app.py`; 2–6. НОВЫЕ `multiprocess_prototype/frontend/boot/{__init__,
  diagnostics_identity_theme,services,state_session,app_services,wiring_timers}.py` (группировка — на усмотрение
  исполнителя, ≤ 6 файлов).
- **Acceptance:**
  - [ ] Характеризация Task 1.1 зелёная без правки её литералов.
  - [ ] `run_gui` — только последовательный вызов функций стадий; `wc -l app.py` уменьшился, число строк до/после — в отчёте.
  - [ ] Сьюты ≥ baseline 1.1, 0 failed.
  - [ ] qt-smoke: окно поднимается, «Перезапустить интерфейс» дважды — окно и вкладки на месте.
- **Break-injection (лид):** перенести стадию `state` после `session` → предсказание: падает тест модалок/порядка 1.1.
- **Dependencies:** 1.1.

---

### Task 1.3 — Реестр подключений + `GuiHostRuntime` + `InProcessRuntime` (бывш. T4.4, находка CTO 1)

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree на коммите после 1.2) → teamlead → reviewer
- **Goal:** стадии получают рантайм из `ConnectionRegistry` (одно подключение `local`), `app.py` не трогает
  `process._*`; шина конвертов переезжает во фреймворк (Р-B).
- **Design:** `design-connection-context.md` §1, §2, §5 (Р-B). Флаги рестарта/остановки — у процесса, не у
  подключения. **Module contract:** new-full (`frontend_module/bootstrap/`: README, interfaces, contract tests).
- **Files:** 1. НОВЫЙ `frontend_module/bootstrap/runtime.py` (Protocol); 2. НОВЫЙ `…/bootstrap/connections.py`;
  3. НОВЫЙ `…/bootstrap/runtime_inprocess.py`; 4. `…/bootstrap/envelope_bus.py` (`git mv` из
  `multiprocess_prototype/frontend/bridge_impl.py` + импорт-сайты); 5. `multiprocess_prototype/frontend/process.py`;
  6. `multiprocess_prototype/frontend/app.py` + `boot/*`. README/STATUS пакета `bootstrap/` — сверх лимита, это
  контракт модуля.
- **Acceptance:**
  - [ ] `grep -c "process\._" multiprocess_prototype/frontend/app.py` = 0 (было 47);
        `grep -cE "getattr\(process|setattr\(process" multiprocess_prototype/frontend/app.py` = 0; `process._window` удалён.
  - [ ] `ConnectionRegistry`: дубликат имени → `ValueError` с именем; неизвестное имя → `KeyError` с перечнем
        известных; `close_all` при исключении в первом закрывает второй (счётчик закрытий = 2).
  - [ ] Контракт-набор `GuiHostRuntime` параметризован **двумя** `InProcessRuntime` на двух фейковых процессах: команда
        через подключение A приходит только в процесс A (спай B = 0 вызовов).
  - [ ] `grep -l PySide6 frontend_module/bootstrap/{runtime,connections,runtime_inprocess}.py` → пусто.
  - [ ] Характеризация 1.1 зелёная; `ui_tap_ping` зелёный живьём (`backend_ctl`), подписки применяются в том же
        месте (VM получает непустой `initial_cache` на фейковом прокси с кэшем).
- **Break-injection (лид):** вернуть «единственный рантайм» (реестр отдаёт первое подключение на любое имя) →
  предсказание: падает тест «команда только в A»; убрать `try` в `close_all` → падает тест счётчика закрытий.
- **Dependencies:** 1.2. Сьюта Р-C/`RemoteGuiRuntime` — gui-service 1.4 подключает свою реализацию к тому же набору.

---

### Task 1.4 — `GuiBootstrap` + спека пакета + загрузчик + зона hot-reload списком (бывш. T4.3, находка CTO 10)

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree на коммите после 1.3) → teamlead → reviewer
- **Goal:** `run_gui` заменён `GuiBootstrap.run_forever(registry, pack_refs)`; инспектор отдаёт `APP_SPEC`
  (каталог виджетов + раскладка по умолчанию + хуки); пакет грузится по строке; утечка слушателей закрыта.
- **Design:** `design-boot.md` §2, §4, §5. На этом шаге оболочки ещё нет: стадия `shell` строит нынешний
  `MainWindow`, стадия `widgets` — вкладки через `TabFactory` (виджетами они станут в 1.5). **Module contract:**
  public-api-change (`frontend_module/bootstrap/interfaces.py`).
- **Files:** 1. НОВЫЙ `frontend_module/bootstrap/interfaces.py`; 2. НОВЫЙ `…/bootstrap/bootstrap.py`; 3. НОВЫЙ
  `…/bootstrap/pack_loader.py`; 4. НОВЫЙ `multiprocess_prototype/frontend/app_spec.py`; 5.
  `multiprocess_prototype/frontend/process.py` (цикл рестарта уходит в `GuiBootstrap`); 6. `presentation.yaml`
  (строка пакета параметром процесса).
- **Acceptance:**
  - [ ] `wc -l multiprocess_prototype/frontend/app_spec.py` ≤ 300; `grep -c "lambda" app_spec.py` = 0; `run_gui` удалён.
  - [ ] `pack_loader`: `"mod:attr"` загружается; несовпадение `protocol_version` → ошибка с **обеими** версиями в тексте;
        неизвестный `app_id` → «нет пакета для приложения <id>».
  - [ ] Зона чистки = объединение `reload_prefixes` загруженных пакетов: тест с двумя фейковыми пакетами
        (`pkg_a.`, `pkg_b.`) — после рестарта оба перезагружены (новые объекты модулей), модуль `pkg_ab_other`
        (префикс без точки) — **не** тронут; `multiprocess_framework.*` — не тронут.
  - [ ] Утечка: после двух рестартов число слушателей шины = после старта (литерал из 1.1 для старта); литерал
        характеризации меняется **отдельным коммитом** с записью «поведение изменено намеренно».
  - [ ] Характеризация порядка 1.1 зелёная; сьюты ≥ baseline; qt-smoke hot-reload ×2.
  - [ ] README `frontend_module/bootstrap` и README прототипа — абзац «что перезагружается кнопкой, что нет».
- **Break-injection (лид):** вернуть сравнение префикса без точки → предсказание: падает тест `pkg_ab_other`;
  убрать снятие `attach` в обратном порядке → падает тест утечки.
- **Dependencies:** 1.3.

---

### Task 1.5 — `WidgetContext`, вкладки виджетами 1:1, легаси-дверь, веер кадров (находки CTO 2, 9)

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree на коммите после 1.4) → teamlead → reviewer
- **Goal:** каждая вкладка `TabFactory` зарегистрирована как `WidgetSpec` и создаётся фабрикой с контекстом;
  каналы state/commands/frames/files/ui_bus существуют; кадры идут через `FrameHub`; `ctx.legacy_deps` — одна дверь
  с sunset-тестом.
- **Design:** `design-connection-context.md` §3, §4 (шаблоны — текстом в README); `design-shell-layout.md` §3.
  `files` — заглушка с текстом; `ui_bus` — тонкий адаптер к нынешнему `QtEventBus` без контрактов (контракты — 3.2).
  **Module contract:** public-api-change (`bootstrap/context.py` — новый публичный Protocol).
- **Files:** 1. НОВЫЙ `frontend_module/bootstrap/context.py`; 2. НОВЫЙ `…/bootstrap/frame_hub.py`;
  3. `multiprocess_prototype/frontend/app_spec.py` (каталог `WidgetSpec` вкладок); 4.
  `multiprocess_prototype/frontend/tab_factory.py` (фабрики-обёртки); 5. НОВЫЙ
  `multiprocess_prototype/frontend/tests/test_legacy_deps_sunset.py`; 6. `…/bootstrap/README.md`.
- **Acceptance:**
  - [ ] Набор вкладок встроенного GUI == до задачи (множество имён, тест).
  - [ ] **Веер:** 5 подписчиков на один источник → 1 верхняя подписка (счётчик на фейковой шине); отписка четырёх →
        верхняя жива; пятой → снята.
  - [ ] **Неблокирующая подписка:** фейковый верхний источник отвечает через 2 с → `frames.subscribe` возвращается
        в GUI-поток ≤ 50 мс (тест в daemon-потоке с дедлайном; зависание = провал, не таймаут сьюты).
  - [ ] Применение раскладки с 5 дисплеями не держит GUI-поток дольше 200 мс подряд — литерал временный: сверяется с
        якорем Task 1.1 (`inventory-f1.md`, время `create_tabs`); при расхождении литерал правится отдельной записью.
  - [ ] Медленный потребитель (колбэк спит 100 мс) не снижает число кадров у быстрого соседа ниже 0.8 × потока.
  - [ ] Sunset: `grep -rn "legacy_deps" multiprocess_prototype --include='*.py'` вне `tests/` = **1**; второй
        `WidgetSpec(legacy=True)` → ошибка загрузки пакета с именами обоих.
  - [ ] `ctx.files.fetch({"provider": "p", "name": "n", "id": "x", "variant": "full"}, on_done)` возвращает `Cancel`
        сразу; `on_done` в GUI-потоке получает `FileResult(ok=False, data=None, mime=None,
        error="files channel not implemented")`; `variant` вне `{"thumb", "full"}` → ошибка с допустимыми значениями
        (форма — общий текст `design-connection-context.md` §3.4 / dataset-annotation Task 2.1).
  - [ ] `grep -l PySide6 frontend_module/bootstrap/{context,frame_hub}.py` → пусто.
- **Break-injection (лид):** `FrameHub` делает верхнюю подписку на каждого подписчика → предсказание: падает тест
  веера (5 ≠ 1); верхняя подписка в GUI-потоке → падает тест 50 мс; убрать ограничение `legacy=True` одним
  экземпляром → падает sunset-тест.
- **Dependencies:** 1.4. Живой стенд: встроенный GUI на синтетическом источнике, `introspect_router_stats` —
  число подписчиков кадров GUI-процесса то же, что до задачи.

---

## Приёмка фазы

Лид: характеризация 1.1 зелёная на конце фазы; инъекции 1.0–1.5 записаны в этот файл (таблица «предсказано /
упало»); живой стенд встроенного GUI — вкладки, дисплеи, hot-reload ×2, `ui_tap_ping`. CTO — приёмка фазы (один раз).
