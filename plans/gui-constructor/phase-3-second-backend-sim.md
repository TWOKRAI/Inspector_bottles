# Ф3 — Второй бэкенд: подключения N, шина интерфейса, пакет `sim.*` с редактором слоёв

Часть плана [`plan.md`](plan.md). Ветка `feat/gui-constructor-f3`. Второй потребитель контракта виджета и шины —
симулятор (`constructor-layers.md` → «Следующие потребители»). Идёт **вместе** с gui-service Ф3 (3.1, 3.2) — таблица
разграничения ниже.

**Цель фазы:** клиент держит два подключения (инспектор 8765, `line_sim` 8766); вкладка симулятора — пакет `sim.*`
из `Services/line_sim/gui/` поверх второго подключения, со сценой, пультом ленты и редактором слоёв; виджеты разных
пакетов общаются через объявленные события шины интерфейса; отвал одного бэкенда не трогает второй.

Канон запуска — шапка [`phase-1-boot-split.md`](phase-1-boot-split.md).

## Разграничение с gui-service Ф3 и планом редактора слоёв

| Что | Владелец | Задача |
|---|---|---|
| Реестр на N подключений в оболочке, `connections:` в раскладке, статус на подключение, изоляция отказов | **этот план** | 3.1 |
| Хранилище подключений клиента (`apps/gui_client/connections.py`: имя, host, port, `token_env`), N `RemoteGuiRuntime` в реестр | gui-service | 3.1 (переписана: докинг — у оболочки) |
| Штатные виджеты фреймворка против симулятора, таблица «работает / почему нет» | gui-service | 3.2 |
| Шина интерфейса с объявленными событиями | этот план | 3.2 |
| Пакет `sim.*`: скелет, сцена, пульт ленты | этот план | 3.3 |
| Помощник «черновик + ревизия» во фреймворке (второй потребитель после `recipe.*`) | этот план | 3.4 |
| Команды слоёв на бэкенде `line_sim` + виджеты редактора слоёв (список, свойства, канва) | план [`line-sim-layer-editor`](../line-sim-layer-editor/plan.md) | его Task 1.2–1.3 (переписаны под пакет) |
| `minimal_app` шаги 3–4 | этот план | 3.5 (по вытягиванию) |

---

### Task 3.1 — N подключений в оболочке: раскладка по подключениям, изоляция отказов

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree на коммите конца Ф2) → developer → reviewer
- **Goal:** реестр с первого дня (Ф1) получает второго реального жильца: раскладка объявляет `connections:`, док —
  `connection:`; у каждого подключения свой индикатор; падение/разрыв одного не трогает другие.
- **Design:** `design-connection-context.md` §1 (правило разрешения пары виджет–подключение, ошибка при 0 или >1
  кандидате). Кода докинга не писать — он в 2.1. **Module contract:** impl-only.
- **Files:** 1. `frontend_module/host/layout_model.py`; 2. `frontend_module/host/layout.py`; 3.
  `frontend_module/bootstrap/connections.py`; 4. `frontend_module/host/window.py` (индикатор на подключение); 5. НОВЫЙ
  `frontend_module/host/tests/test_multi_connection.py`.
- **Acceptance:**
  - [ ] Два фейковых подключения `a`, `b` (два in-process `SocketChannel(port=0)` или два фейковых рантайма):
        команда виджета дока `connection: a` приходит только в `a` (спай `b` = 0); дельта состояния `b` не вызывает
        колбэк виджета `a`.
  - [ ] Док без `connection:`, пакет с `app_id`, которому соответствуют 2 подключения → ошибка применения раскладки,
        в тексте оба имени; 0 подключений → ошибка с `app_id`.
  - [ ] Разрыв `a` → индикатор `a` «отключён» ≤ 5 с; виджеты `b` получают кадры/дельты дальше (счётчик за 10 с
        ≥ 0.8 × прежнего).
  - [ ] Исключение в фабрике виджета подключения `a` → док с текстом ошибки вместо виджета, остальные доки созданы.
- **Break-injection (лид):** разрешать док без `connection:` первым подключением реестра → предсказание: падает
  только тест «2 кандидата»; общий `FrameHub` на все подключения → падает тест изоляции кадров.
- **Dependencies:** Ф2 (2.1); вместе с gui-service 3.1 (её `ConnectionStore` кладёт N рантаймов в этот реестр).

---

### Task 3.2 — Шина интерфейса: события объявлены в пакетах

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** `ctx.ui_bus` перестаёт быть адаптером к `QtEventBus` без контрактов: события объявлены в
  `GuiAppSpec.ui_events` (имя с префиксом пакета + схема payload), необъявленное — ошибка; шина общая на процесс
  клиента. Два потребителя: `sim.*` (выбранный слой: список ↔ свойства ↔ сцена) и `fw.pult.add_knob` (Ф4) — правило
  двух потребителей выполнено.
- **Design:** `design-connection-context.md` §3.5. Доменная `QtEventBus` прототипа (`TopologyReplaced`, …) **не
  переводится** — она внутри пакета инспектора; шина интерфейса — между пакетами. **Module contract:** new-lite
  (`frontend_module/host/ui_bus.py`, Qt-free).
- **Files:** 1. НОВЫЙ `frontend_module/host/ui_bus.py`; 2. `frontend_module/bootstrap/interfaces.py` (`UiEventSpec`);
  3. `frontend_module/bootstrap/context.py` (канал); 4. `frontend_module/bootstrap/pack_loader.py` (сбор объявлений,
  конфликт имён); 5. НОВЫЙ `frontend_module/host/tests/test_ui_bus.py`.
- **Acceptance:**
  - [ ] Публикация объявленного события с верным payload → все подписчики получили `dict`, равный отправленному.
  - [ ] Необъявленное событие → `UnknownUiEvent` с именем события (dev-режим); payload без обязательного ключа →
        ошибка с именем ключа.
  - [ ] Два пакета объявляют одно имя → ошибка загрузки с именами обоих пакетов.
  - [ ] Подписка виджета снимается при уничтожении дока и при рестарте воплощения (число подписчиков после рестарта
        = после старта).
  - [ ] `grep -l PySide6 frontend_module/host/ui_bus.py` → пусто.
- **Break-injection (лид):** пропускать необъявленные события молча → предсказание: падает только тест
  `UnknownUiEvent`; не снимать подписку при рестарте → падает тест числа подписчиков.
- **Dependencies:** Ф1 (1.5). Параллельно 3.1.

---

### Task 3.3 — Пакет `sim.*` в `Services/line_sim/gui/`: скелет, сцена, пульт ленты

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** первый пакет среза сервиса: `Services/line_sim/gui/` отдаёт `APP_SPEC` с `app_id` симулятора, виджеты
  `sim.scene` (дисплей сцены через `ctx.frames`) и `sim.belt` (скорость/поток/брак/пауза командами `belt.*` —
  line-sim 2.3a, те же, что у веб-пульта 8092); раскладка по умолчанию — вкладка «Симулятор». Корень
  `Services/line_sim` остаётся без Qt.
- **Design:** `design-shell-layout.md` §4 (место пакета, правила); кнопки `sim.belt` строятся через движок форм по
  описанию команд, не руками там, где описание есть. Зона hot-reload пакета — `("Services.line_sim.gui.",)`.
  **Module contract:** new-full (`Services/line_sim/gui/`: README, тесты; публичное — только `APP_SPEC`).
- **Files:** 1. НОВЫЙ `Services/line_sim/gui/__init__.py` (`APP_SPEC`); 2. НОВЫЙ `…/gui/scene_widget.py`; 3. НОВЫЙ
  `…/gui/belt_widget.py`; 4. НОВЫЙ `…/gui/layouts/default.yaml`; 5. НОВЫЙ `…/gui/README.md`; 6. НОВЫЙ
  `Services/line_sim/tests/test_gui_pack.py`.
- **Acceptance:**
  - [ ] `python -c "import Services.line_sim, sys; assert 'PySide6' not in sys.modules"` — зелёный (корень не тянет
        `gui/`); контракт-тест Task 1.0 зелёный; `sentrux check .` зелёный.
  - [ ] Живой стенд: инспектор 8765 + `apps/line_sim` 8766, `apps/gui_client` с двумя подключениями → вкладка
        «Симулятор» видна; `sim.scene` обновляется ≥ 0.8 × fps сцены (fps — `introspect_router_stats` симулятора).
  - [ ] Скорость ленты из `sim.belt` → `backend_ctl` 8766 показывает новое значение (не по виджету); отказ бэкенда
        (значение вне диапазона) → виджет откатил поле и показал текст ошибки.
  - [ ] Остановка симулятора → вкладка «Симулятор» «отключён», вкладки инспектора работают (fps дисплея `main`
        инспектора за 10 с ≥ 0.8 × прежнего).
  - [ ] `grep -rn "line_sim" frontend_module apps/gui_client --include='*.py'` → 0: фреймворк и клиент не знают,
        что второе подключение — симулятор.
- **Break-injection (лид):** реэкспорт `gui` из `Services/line_sim/__init__.py` → предсказание: падает проверка
  `sys.modules` и контракт-тест; `sim.scene` подписывается на кадры синхронно в фабрике → падает тест 50 мс 1.5 на
  этом виджете (если тестер его перенёс) — иначе слепая зона, записать.
- **Dependencies:** 3.1, 3.2; gui-service 3.1–3.2 (`apps/gui_client` с N подключениями, штатные виджеты против сима);
  `feat/line-sim` в `main` (сверено gui-service: 1.1/1.3 закрыты).

---

### Task 3.4 — Помощник «черновик + ревизия» во фреймворке (второй потребитель после `recipe.*`)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** холсты-редакторы (рецепт, слои; позже разметка) сохраняют документ командой с ревизией одним
  клиентским помощником: черновик, undo-стек словарей, `commit{doc, base_rev}` → `{ok, rev}` / `conflict`.
- **Design:** `design-connection-context.md` §4.1. Потребитель 1 — редактор рецептов (gui-service 1b.1, уже на
  `base_rev`); потребитель 2 — редактор слоёв (`line-sim-layer-editor` Task 1.2 в новой форме). Если к моменту
  старта редактор слоёв ещё не поставлен — задача ждёт (правило двух потребителей), не строится заранее.
  **Module contract:** new-lite (`frontend_module/bootstrap/revisioned_draft.py`, Qt-free).
- **Files:** 1. НОВЫЙ `frontend_module/bootstrap/revisioned_draft.py`; 2. НОВЫЙ тест рядом; 3. один сайт редактора
  рецептов в прототипе переведён на помощник (назвать файл в отчёте); 4. README контекста — раздел шаблона.
- **Acceptance:**
  - [ ] Две копии черновика одного документа (`rev=5`): первая коммитит → `rev=6`; вторая коммитит с `base_rev=5` →
        `conflict`, черновик второй **не потерян**, её `rev` не изменился.
  - [ ] Undo после трёх правок возвращает документ, равный исходному `to_dict()`.
  - [ ] Разрыв соединения при `commit` → `Reply(ok=False, error="connection lost")`, черновик цел, повтор после
        реконнекта проходит.
- **Break-injection (лид):** отбрасывать черновик при `conflict` → предсказание: падает только тест «не потерян».
- **Dependencies:** 1.5; постановка редактора слоёв в `line-sim-layer-editor` (его Task 1.2).

---

### Task 3.5 — `examples/minimal_app`, шаги 3–4: регистр, два рецепта с переключением (по вытягиванию)

- **Статус:** [PENDING — по вытягиванию] · **Level:** Middle · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** шаг 3 — `interval_sec` как регистр плагина: форма настроек в `minimal_gui` строится из описания, без
  Qt-кода в плагине; шаг 4 — два рецепта (`slow`, `fast`) в `recipes/` и переключение из `minimal_gui` командой —
  главное в решении владельца: приложение собирается через топологию рецептов.
- **Design:** `constructor-layers.md` → шаги 3–4. **Не стартовать**, пока шаг не тянет виджет `minimal_gui` или
  потребность прототипа: условие старта — Task 4.2 (Пульт рисует ручку по описанию регистра) для шага 3; сервис
  рецептов на бэкенде (gui-service 1b.1 — есть) плюс виджет переключения рецепта в кит фреймворка — для шага 4.
  **Module contract:** impl-only.
- **Files:** 1. `examples/minimal_app/plugins/tick_source/{plugin,registers}.py`; 2. НОВЫЕ
  `examples/minimal_app/recipes/{slow,fast}.yaml`; 3. `examples/minimal_gui/layout.yaml` (форма регистра, выбор
  рецепта); 4. тесты smoke обоих эталонов.
- **Acceptance:**
  - [ ] Правка `interval_sec` из формы `minimal_gui` → `introspect_registers` показывает новое значение; значение
        вне диапазона → откат поля с текстом.
  - [ ] Активация `fast` из `minimal_gui` → за 2 с не меньше 6 новых значений счётчика; `slow` → не больше 3.
  - [ ] `grep -c PySide6` по `examples/minimal_app` → 0.
- **Dependencies:** 2.3, 2.4; условия старта выше.

---

## Приёмка фазы

Живой стенд двух бэкендов: таблица «вкладка / подключение / работает» из gui-service 3.2 + этот план (3.1–3.3),
отвал каждого бэкенда по очереди, числа fps. Инъекции — таблицей в этом файле. CTO — приёмка фазы.
