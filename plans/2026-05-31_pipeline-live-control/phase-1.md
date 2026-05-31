# Этап 1 — Ручные кнопки управления (простой, «применить целиком»)

**Цель этапа:** подключить кнопки Запустить / Остановить / Перезапустить (Pipeline) и
Сохранить / Загрузить рецепт (Recipes) к работающему бэкенду через готовые API
(`replace_blueprint`, `start/stop/restart_process`). Закрыть корневой блокер —
прокинуть `process_manager_proxy` в GUI через IPC-мост.

**Сложность этапа:** Middle / Middle+ · **Риск:** низкий-средний
**Что переиспользуется:** `replace_blueprint` (PM:635), `start/stop/restart_process`
(PM:964-1004), `launch_active_recipe` (pipeline/presenter:1491), `RouterManager` GUI-процесса,
CommandSender IPC паттерн.
**Что пишется заново:** тонкий прокси-фасад `ProcessManagerProxy` (GUI-сторона, шлёт команды
по IPC), wiring в `app.py`.

---

### Task 1.1 — IPC-мост GUI→ProcessManagerProcess + кнопка «Перезапустить» (vertical slice)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** GUI-процесс получает рабочий `process_manager_proxy`, который по IPC
(RouterManager/CommandSender) вызывает `replace_blueprint`/`restart_process` на
ProcessManagerProcess; кнопка «Перезапустить» на вкладке Pipeline применяет текущую
топологию-граф к живому бэкенду.

**Context:** Это фундамент всего плана. Сейчас `AppServices` собирается с `config={}`
(`app.py:441`), `launch_active_recipe` (`pipeline/presenter.py:1491`) зовёт
`proxy.replace_blueprint`, но `proxy=None`. Нужен тонкий фасад GUI-стороны, который
сериализует вызов в `dict`-команду (Dict at Boundary) и отправляет через уже имеющийся
у GUI **`CommandSender`** (создаётся в `app.py:108` как `command_sender = CommandSender(process)`,
файл `frontend/bridge/command_sender.py`) в ProcessManagerProcess, где готовый
`replace_blueprint` (PM:635) выполняет atomic replace с rollback. **Транспорт уже есть —
proxy лишь оборачивает CommandSender, не создавать новый IPC-канал.**

**Files:**
- `multiprocess_prototype/frontend/app.py` (~441) — собрать `process_manager_proxy` и
  передать в `config`/`AppServices` (убрать `config={}`); найти, где GUI создаёт
  `RouterManager`, и переиспользовать его для команд
- `multiprocess_prototype/frontend/bridge/process_manager_proxy.py` (создать) —
  тонкий фасад `ProcessManagerProxy(command_sender)` с методами `replace_blueprint(dict)`,
  `restart_process(name)`, `start_process(name)`, `stop_process(name)`; внутри —
  сериализация в dict-команду + отправка через переданный `CommandSender` (см. `command_sender.py`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (~1491
  `launch_active_recipe`, ~_on_toolbar_action) — подключить proxy
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — кнопка «Перезапустить»
  в тулбаре (если ещё нет — добавить; если есть — подключить обработчик)
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
  (~635 `replace_blueprint`, ~964-1004) — НЕ менять логику, только убедиться, что команда
  принимается через существующий command-handler (если нет handler для команды — добавить
  тонкий приёмник, делегирующий в готовый метод)
- `multiprocess_framework/modules/process_manager_module/interfaces.py` — если нужен новый
  command-контракт, объявить здесь

**Steps:**
1. Изучить `frontend/bridge/command_sender.py` (`CommandSender`, создаётся в `app.py:108`):
   как он формирует и шлёт dict-команду в backend. Понять, какой command-handler на стороне
   ProcessManagerProcess её принимает.
2. Изучить образец живого пути `SetPluginConfig → PluginConfigChanged → rm.set_value → IPC`
   (`app.py:476-490`) — как другие команды доходят до живого процесса. Скопировать паттерн.
3. Создать `ProcessManagerProxy(command_sender)` (GUI-сторона): методы оборачивают аргументы
   в `dict` и шлют команду нужного типа через `CommandSender`. Без бизнес-логики —
   только сериализация + отправка.
4. На стороне ProcessManagerProcess убедиться, что приходящая команда `replace_blueprint`
   (и `restart_process`) роутится в готовые методы PM:635 / PM:964-1004. Если приёмника
   нет — добавить тонкий command-handler, делегирующий в существующий метод (не дублировать логику).
5. В `app.py` (~441) собрать `ProcessManagerProxy(command_sender)` и положить в
   `AppServicesDeps` (вместо `config={}` либо как отдельное поле deps) → довести до
   pipeline/recipes presenter через AppServices.
6. В `pipeline/presenter.py` подключить `proxy` к `launch_active_recipe` (~1491) и к
   обработчику кнопки «Перезапустить»: текущая топология-граф → blueprint-dict → `proxy.replace_blueprint`.
7. В `pipeline/tab.py` завести/подключить кнопку «Перезапустить» в тулбаре.

**Acceptance criteria:**
- [x] `process_manager_proxy` создаётся в `app.py` и доступен в pipeline-presenter (не `None`)
- [x] Между GUI и ProcessManagerProcess передаётся только `dict` (test_process_manager_proxy)
- [x] qt-mcp smoke: proto запущен, кнопки Pipeline собраны, IPC-мост доказан end-to-end
      (лог: `command gui -> ['ProcessManager'] cmd=process.command` → `replace_blueprint: начало замены`).
      Найден + исправлен корневой баг: GUI грузил рецепт без `unwrap_recipe` → редактор видел
      только `gui`. После фикса топология полная (8 процессов, детерминир. проверка).
      ⚠️ Полный «delete→restart→дисплей меняется» блокируется тем, что recipe-launch теряет
      `protected:true` для `gui` (running PM: `protected=[]`) → «Перезапустить» весь граф рестартит
      и GUI. Framework-фикс protected — follow-up (Этап 2 / отдельная задача).
- [x] `python scripts/run_framework_tests.py` зелёный (3010 passed, 8 skipped)
- [x] Никаких прямых обращений GUI к SHM; команда идёт через RouterManager/CommandSender

**Out of scope:** реактивный hot-apply (Этап 2), per-worker/адресное управление (Этап 3),
изменение логики `replace_blueprint`/`restart_process` (только вызов готовых методов).
**Edge cases:** proxy недоступен (backend ещё не поднят) — кнопка должна давать понятный
статус, не падать; пустая топология; replace_blueprint rollback (ошибка в blueprint) —
GUI показывает ошибку, состояние не рассинхронизируется.
**Dependencies:** —
**Module contract:** public-api-change (новый proxy-фасад + возможный новый command-контракт
в interfaces.py) + impl-only (app.py wiring)

---

### Task 1.2 — Кнопки Запустить / Остановить / Перезапустить на вкладке Pipeline

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** тулбар Pipeline имеет три рабочие кнопки, вызывающие через proxy
`start_process` / `stop_process` / `restart_process` (готовые API PM:964-1004) для
процесса(ов) активного рецепта.

**Context:** После Task 1.1 proxy готов. Остаётся развести три действия и связать их
с обработчиками тулбара (`_on_toolbar_action`). Запуск/остановка — по **имени процесса**
(не по адресу — это Этап 3).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — кнопки в тулбаре
  (Запустить / Остановить / Перезапустить), сигналы
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py`
  (`_on_toolbar_action`, ~552 `remove_selected` для контекста) — обработчики, вызовы proxy

**Steps:**
1. Добавить/подключить 3 кнопки в тулбаре `pipeline/tab.py` с сигналами в presenter.
2. В `_on_toolbar_action` развести действия на `proxy.start_process(name)`,
   `proxy.stop_process(name)`, `proxy.restart_process(name)`.
3. Определить, какой process_name берётся (из активного рецепта / выбранного контейнера-ноды).
4. Отразить статус процесса в UI после действия (использовать существующую телеметрию/StateStore,
   не изобретать).

**Acceptance criteria:**
- [x] Три кнопки видимы и активны на вкладке Pipeline (qt-mcp: «Старт/Стоп/Рестарт процесса»)
- [x] Команды идут через proxy/IPC dict (control_process → proxy.start/stop/restart_process)
- [x] Нет регрессий: `python scripts/run_framework_tests.py` зелёный
- [~] qt-mcp smoke per-process stop: канал доказан (Task 1.1 лог); прямой клик «Стоп процесса»
      требует выбора ноды на canvas (scene-coords) — отложено, IPC-путь идентичен Task 1.1

**Out of scope:** per-worker stop, адресное управление (Этап 3); авто-apply (Этап 2).
**Edge cases:** процесс уже остановлен/запущен (idempotent поведение); нет активного рецепта
(кнопки disabled или понятный статус); защищённый main worker не должен останавливаться целиком.
**Dependencies:** Task 1.1
**Module contract:** impl-only

---

### Task 1.3 — Сохранить / Загрузить рецепт на вкладке Recipes

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** кнопки Сохранить и Загрузить (активировать) рецепт на вкладке Recipes
работают через `replace_blueprint_fn` / `on_set_active` (recipes/presenter:287),
применяя выбранный рецепт к живому бэкенду через proxy.

**Context:** `recipes/presenter.py:287` (`on_set_active`) уже предполагает
`replace_blueprint_fn` — нужно проверить проброс и связать с proxy из Task 1.1.
Сохранение рецепта — на стороне RecipesManager (yaml-секции, ADR-131/132), переиспользовать.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py` (~287 `on_set_active`,
  `replace_blueprint_fn`) — подключить proxy / fn
- `multiprocess_prototype/frontend/widgets/tabs/recipes/` (tab/view) — кнопки Сохранить / Загрузить
- `multiprocess_prototype/frontend/app.py` — проброс `replace_blueprint_fn` (через proxy) в recipes-presenter

**Steps:**
1. Проверить, проброшен ли `replace_blueprint_fn` в recipes-presenter; если `None` —
   связать с `proxy.replace_blueprint` из Task 1.1.
2. «Загрузить/Активировать рецепт»: `on_set_active` → рецепт→blueprint-dict→`replace_blueprint_fn`.
3. «Сохранить рецепт»: вызвать существующий RecipesManager API (replace_blueprint с rollback,
   yaml-секции — ADR-131/132); не дублировать сериализацию.
4. Статус активного рецепта отразить в UI (cross-tab Services-highlight уже есть — Phase G).

**Acceptance criteria:**
- [x] «Сделать активным» (= Загрузить/Активировать) → `replace_blueprint_fn=proxy.replace_blueprint`
      применяет рецепт к живому backend (on_set_active, recipes/presenter.py:328)
- [x] «Сохранить» → персист через RecipesManager (Pipeline `save_to_active_recipe` + on_create, ADR-131/132)
- [x] Между процессами — dict; нет регрессий тестов recipes/process_manager (479 + 3010 passed)
- [~] qt-mcp smoke переключения рецепта — IPC-путь идентичен Task 1.1 (proxy.replace_blueprint доказан)

**Out of scope:** редактор содержимого рецепта, новые форматы; авто-apply (Этап 2).
**Edge cases:** битый/несовместимый рецепт (rollback, ошибка в UI); рецепт без процессов;
конкуренция с ручными кнопками Pipeline (последнее действие выигрывает — задокументировать).
**Dependencies:** Task 1.1
**Module contract:** impl-only
