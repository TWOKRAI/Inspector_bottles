# Phase 1b — Рецепт и auth принадлежат бэкенду: GUI без диска

Часть плана [`plan.md`](plan.md). Заведена 2026-09-23 решением владельца: **«рецепт — бэкенд,
фронтенд лишь помогает его редактировать»**. Цель фазы: ни одна сборка GUI (встроенная в дерево и
Пульт) не читает и не пишет `recipes/`, `app.yaml` и каталог плагинов с локального диска. Все данные
приложения идут через командную поверхность бэкенда. Без этой фазы Пульт на другой машине (Ф2) молча
расходится с бэкендом по рецептам. Это разъём S9 из
[`docs/audits/2026-09-22_gui-seams-inventory.md`](../../docs/audits/2026-09-22_gui-seams-inventory.md):
«чтения рецепта и записи манифеста через сокет нет».

**Что по коду сейчас (grep, 2026-09-23):**
- `RecipeManager(` создаётся **только** в GUI (`frontend/app.py:503`). Бэкенд читает рецепт с диска
  при старте (`backend/launch.py:414-465`), GUI пишет файл и шлёт `apply_topology`. Контракт между
  ними — общий диск.
- GUI пишет `app.yaml` бэкенда (`app.py:846` `ManifestStore(...).set_pipeline`).
- GUI сам находит плагины (`app.py:173` `PluginRegistry.discover` по локальным путям), то есть
  импортирует код `Plugins/` в процесс GUI.
- Импорты фронта в бэкенд прототипа: `backend.*` — 6 файлов, `recipes.*` — 5 файлов (список в
  Task 1b.3).
- Порты уже оформлены как `Protocol` (`domain/protocols`, `AppServices` — 10 полей). Меняется
  реализация портов, а не виджеты.

**Порядок внутри фазы и с Ф1:** 1b.1 и 1b.2 — чисто бэкенд, от сокета не зависят и могут идти
**параллельно Ф1**. Встроенный GUI переходит на них через тот же `CommandSender`. 1b.3 доказывает
результат на обеих сборках и поэтому ждёт 1.4. Ф2 (сеть) без 1b не стартует.

**Тестовый канон** — как у всего плана (`plan.md` → «Риски»): `tester` до кода в worktree на
пред-коммите, break-injection по каждому свойству, `reviewer` синхронно после каждой задачи.

---

### Task 1b.1 — Сервис рецептов на бэкенде: командная поверхность `recipe.*` с ревизией

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** бэкенд — единственный владелец рецептов. Список, чтение, сохранение, активация и удаление
идут командами. Сохранение идёт с оптимистичной ревизией: два редактора (Пульт + встроенный GUI, два
Пульта, Пульт + `backend_ctl`) не затирают друг друга молча.

**Контекст:** рецептный код раздвоен: фреймворковая крыша `modules/recipe` (`manager.py`,
`recipe_engine.py`, `yaml_io.py`, ADR-RCP-001) и прикладной `multiprocess_prototype/recipes/manager.py`
с миграциями формата инспектора (уточнено разведкой 2026-09-24: это шим-реэкспорт, логика — в
`recipes/migrations/`, `backend/launch.py:79` `unwrap_recipe`, `recipes/save.py`). Сервис — это **обобщённая поверхность команд во фреймворке**, а
формат инспектора — хук приложения. Второго менеджера не появляется. Где живут обработчики: **на хабе** (`ProcessManagerProcessApp`, проводка через
`orchestrator_hooks`), сервис — `modules/recipe/service.py` (вердикт cto 2026-09-24). Прежний критерий
«у хаба нет receive-мидлвари» снят: мидлварь у PM есть (`builtin_commands.py:3931`), её обходит
сокетный канал (`router_manager.py:1509-1514`) для ВСЕХ команд хаба, включая `topology.apply` — судья на
хабе (G1b) нужен 1b.4 независимо от места `recipe.*`; хаб уже владеет фактом «активный рецепт»
(`_retarget_recipe_address`). Вне хаба `activate` пришлось бы делать асинхронным
(`RouterReentrantRequestError`, deferred-reply нет) и заводить второго владельца истины.

**Files:**
- НОВЫЙ `multiprocess_framework/modules/recipe/service.py` (или `service/`, по Step 1): обработчики
  `recipe.list / get / save / activate / delete / validate`, **Qt-free**, dict на границе.
- `multiprocess_framework/modules/recipe/{README,STATUS,DECISIONS}.md`: контракт команд, ADR-RCP-*
  «владелец рецепта — бэкенд, ревизия».
- `multiprocess_prototype/backend/…`: подключение сервиса в дерево инспектора, хук формата
  (миграции v1→v2, `unwrap_recipe`, `save_editor_topology_to_recipe`).
- Запись `app.yaml` (`ManifestStore.set_pipeline`) появляется под `recipe.activate` (второй писатель тем же
  `ManifestStore`, flock + `os.replace`); GUI-писатель `_persist_active_recipe` снимается в 1b.3.
- Тесты: `modules/recipe/tests/test_service.py`, характеризация старта бэкенда с рецептом.

**Steps:**
1. Разведать: чем отличаются `modules/recipe/manager.py` и `multiprocess_prototype/recipes/manager.py`;
   что из прикладного менеджера обобщается, что остаётся хуком; где хостить обработчики (процесс
   или хаб, критерий выше). Решение и причина — в DECISIONS модуля **до кода**.
2. Командная поверхность. `recipe.get` возвращает `{name, rev, body}`; `recipe.save` принимает
   `{name, base_rev, body}` → `{rev}` или ошибку `conflict` с текущим `rev`. Валидация авторитетна на
   бэкенде: ошибки возвращаются списком `{path, message}`, а не исключением.
3. `recipe.activate(name)` — обработчик PM: `hook.normalize` → `hook.validate` →
   `self._cmd_topology_apply(topology_dict=hook.to_topology(body), recipe_path=<абс. путь>)` → при success
   `ManifestStore.set_pipeline` → **синхронный** ответ `{success, name, apply: <ответ topology.apply>}`.
   Персист после success — порядок GUI сегодня (`presenter.py:481`). Второго пути применения нет.
   В DECISIONS: `rev` — непрозрачная строка (сегодня sha256 байтов файла), клиент сравнивает на
   равенство; любой писатель мимо `recipe.save` (сегодня `save_layout`, `recipe_store.py:111`)
   инвалидирует `rev` редактора — желаемое поведение, автосохранение позиций решается в 1b.3.
4. Автор пишет hazard-тесты: (а) два `save` с одним `base_rev` — ровно один успешен, второй получает
   `conflict`; (б) `save` невалидного рецепта не меняет файл на диске (побайтно); (в) падение посреди
   записи не оставляет полуфайл (атомарная замена); (г) `activate` несуществующего — ошибка с именем,
   активный рецепт не меняется.

**Acceptance criteria:**
- [ ] Через `backend_ctl send_command` (не через GUI): `recipe.list` → список имён, совпадающий с
      `ls recipes/*.yaml` (сравнение множествами); `recipe.get` → `rev` и тело.
- [ ] `recipe.save` с устаревшим `base_rev` → `conflict`, файл на диске не изменился (sha256 до и
      после совпадает).
- [ ] `recipe.activate(X)` → `get_status`/`system_overview` показывают топологию X; после рестарта
      бэкенд стартует с X (тот же контракт «последний активный», что сегодня пишет GUI).
- [ ] Ни один новый файл сервиса не импортирует `PySide6` и `multiprocess_prototype` (`grep` → 0);
      `sentrux check .` зелёный.

**Out of scope:** перевод GUI на эти команды (1b.3); права на команды (Task 1b.4); история версий рецепта глубже одной ревизии.
**Edge cases:** рецепт правят руками на диске, пока бэкенд жив: `rev` считается от содержимого (хеш),
а не счётчиком в памяти, поэтому ручная правка даёт `conflict` у редактора, а не тихую перезапись.
**Dependencies:** нет (бэкенд; может идти параллельно Ф1).
**Module contract:** new-lite (`recipe/service` — докстринг-контракт Pre/Post на каждую команду).

---

### Task 1b.2 — Каталоги от бэкенда: плагины, дисплеи, сервисы

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** GUI получает каталог плагинов (имена, схемы параметров, порты), дисплеев и сервисов от
бэкенда. Он перестаёт делать `PluginRegistry.discover` по локальным путям и перестаёт импортировать
код `Plugins/` в свой процесс.

**Контекст:** часть данных уже отдаётся наружу: `capabilities` (`driver.py:1261`) и
`introspect_plugins`. Step 1 проверяет, хватает ли их редактору (схемы полей для форм — `field_info`)
или нужна команда `catalog.plugins` с полными схемами.

**Files:**
- Обработчик каталога рядом с существующим `introspect_plugins` (не второй реестр).
- `multiprocess_prototype/adapters/catalogs/*` — удалённые реализации `PluginCatalog` /
  `DisplayCatalog` / `ServiceManager` поверх команд (сам `Protocol` не меняется).
- Тесты: паритет «локальный каталог == удалённый» на одном дереве.

**Steps:**
1. Сравнить, что GUI берёт из `PluginRegistry` сегодня (grep по `plugins.` в презентерах вкладок
   `pipeline`/`plugins`), с тем, что отдаёт `introspect_plugins`. Разница — это содержимое команды.
2. Схемы параметров отдаются dict'ом (`to_dict`), в GUI из них строятся формы тем же `forms/`.
3. Автор пишет hazard-тест: плагин есть на бэкенде, но его кода нет в процессе GUI — форма
   параметров всё равно строится (именно это и доказывает отвязку).

**Acceptance criteria:**
- [ ] Паритет: для каждого плагина из локального `PluginRegistry.discover` удалённый каталог
      отдаёт то же множество имён параметров с теми же типами (тест сравнивает множества).
- [ ] Процесс GUI, собранный на удалённых каталогах, не имеет в `sys.modules` ни одного модуля
      `Plugins.*` после открытия вкладок `pipeline` и `plugins` (проверка в тесте).

**Out of scope:** «песочница» плагинов (`sandbox_presenter`) — если ей нужен код плагина локально,
это находка и отдельное решение, а не молчаливое исключение.
**Dependencies:** нет (бэкенд; может идти параллельно Ф1).
**Module contract:** impl-only.

---

### Task 1b.3 — Пакет вкладок инспектора на удалённых портах; GUI без диска

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** `GuiAppSpec` инспектора (см. Task 1.4, «пакет вкладок») собирает `AppServices` на
реализациях поверх команд 1b.1/1b.2 в **обеих** сборках: встроенной и Пульте. Черновик рецепта,
undo и `ProjectHolder` остаются в GUI, потому что редактирование — работа интерфейса. Сохранение
идёт `recipe.save(base_rev)`.

**Импорты фронта в бэкенд прототипа, которые уходят (grep 2026-09-23):**
- `backend.*`: `app.py` (`state.adapters.*`, `state.recipes.RecipeEngine`, `launch.merge_topologies/unwrap_recipe`,
  `config.schemas.load_system_config`, `config.manifest.load_manifest`), `widgets/tabs/settings/system/presenter.py`,
  `widgets/tabs/settings/yaml_io.py` (`SystemConfig`), `widgets/tabs/pipeline/recipe_io.py` (`unwrap_recipe`).
- `recipes.*`: `app.py` (`RecipeManager`, `save_editor_topology_to_recipe`, миграции),
  `pipeline/layout_controller.py`, `recipes/presenter.py`, `topology/presenter.py`
  (`validate_recipe_blueprint`).
- `registers.theme.schemas` и `registers.connection_map` — схемы данных без процессов. Они остаются
  как контракт приложения, запретом не покрываются.

**Files:**
- `multiprocess_prototype/frontend/app_services_factory.py` — сборка на удалённых адаптерах.
- Перечисленные выше файлы — перевод на порты или на Qt-free контракт (`domain`).
- `.sentrux/rules.toml` — новые `[[boundaries]]`: `multiprocess_prototype/frontend/*` ↛
  `multiprocess_prototype/backend/*` и ↛ `multiprocess_prototype/recipes/*`.

**Steps:**
1. Каждый импорт из списка — в одну из двух корзин: «данные, которые теперь приходят командой»
   (→ порт) или «чистая функция формата» (→ Qt-free контракт приложения, который импортируют и
   бэкенд, и GUI). Третьей корзины («оставить как есть») нет.
2. Конфликт сохранения (`conflict` из 1b.1) показывается пользователю диалогом «рецепт изменён
   другим редактором: перезагрузить / сохранить как копию». Молча не перезаписывается.
3. Автор пишет hazard-тест: GUI открыт на рецепте X, `backend_ctl` сохраняет X с новым телом →
   сохранение из GUI получает `conflict`, файл на диске равен версии `backend_ctl`.

**Acceptance criteria:**
- [ ] **GUI без диска:** Пульт запущен с рабочим каталогом во временной директории, где нет
      `recipes/` и `app.yaml` бэкенда. Он открывает рецепт, правит параметр плагина и сохраняет.
      Файл на диске бэкенда изменился (sha256), `recipe.get` отдаёт новый `rev`.
- [ ] То же сохранение из встроенного GUI (`frontend/run.py`) даёт тот же результат, что из Пульта
      (обе сборки идут одним кодом портов).
- [ ] `sentrux check .` зелёный с новыми правилами; `grep -rnE "multiprocess_prototype\.(backend|recipes)"
      multiprocess_prototype/frontend --include=*.py` вне тестов → 0.
- [ ] pytest-qt наборы из Task 1.1 — passed ≥ baseline, 0 failed.

**Out of scope:** auth/пользователи (Task 1b.4); редактор слоёв line-sim.
**Dependencies:** 1b.1, 1b.2, Task 1.4.
**Module contract:** impl-only.

---

### Task 1b.4 — Auth на бэкенде: сессия оператора, проверка команд у владельца

**Level:** Senior (Opus) + `reviewer` в режиме security обязателен
**Assignee:** teamlead
**Goal:** пользователи, роли и аудит живут на бэкенде. Оператор входит командой `auth.login` и
получает токен сессии. Каждая команда из GUI несёт токен, и права проверяются **на бэкенде** (на
стороне того, кто исполняет). GUI только показывает и прячет контролы по ролям, которые сообщил
бэкенд. Решение — `architecture.md` → «Auth — на бэкенде».

**Контекст:** `Services/auth` (manager, session_tracker, audit_writer, storage, predefined_roles) —
готовый сервис, но хостится в процессе GUI: 32 импорта, все в `multiprocess_prototype/frontend`.
`users.yaml` читает GUI (`app.py:563`). Проверка прав сейчас клиентская (`frontend/permissions.py`).
Где проверять на бэкенде: receive-мидлварь процесса-исполнителя. У хаба мидлвари нет (G1b), поэтому
команды, которые исполняет хаб, требуют отдельного решения — Step 1 перечисляет их поимённо.

**Files:**
- Подключение `Services/auth` в дерево инспектора (процесс-хост — по тому же критерию, что 1b.1).
- Мидлварь проверки токена сессии и прав (рядом с fence-мидлварью, тот же механизм подключения).
- `frontend/permissions.py`, `auth_context.py`, `widgets/tabs/settings/administration/*` —
  перевод на удалённый `AuthFacade` (порт уже есть в `domain/protocols`).
- Тесты: матрица «роль × команда → разрешено/отказ» на бэкенде без GUI.

**Steps:**
1. Инвентарь: какие команды GUI сегодня защищены правами на клиенте (`permissions.py` → список
   действий) и кто их исполняет (дочерний процесс или хаб). Для команд хаба — решение в DECISIONS:
   судья на хабе (полоса B, строка G1b) или перенос исполнения в процесс.
2. `auth.login / logout / whoami / users.*` — команды сервиса; токен сессии — непрозрачная строка с
   TTL, на проводе dict.
3. Мидлварь: нет токена или истёк → отказ с кодом; роль не позволяет → отказ + запись в аудит.
   Встроенный GUI и Пульт идут одним путём (токен есть у обоих).
4. Автор пишет hazard-тесты: (а) команда с токеном другой сессии после `logout` → отказ; (б) рестарт
   бэкенда → старые токены недействительны (Пульт получает «войдите заново», а не молчаливый отказ);
   (в) `backend_ctl` как dev-клиент — либо свой сервисный токен, либо только localhost; решение
   записывается, дыра «без токена можно всё» не остаётся молча.

**Acceptance criteria:**
- [ ] Через `backend_ctl` без токена сессии команда, требующая роли, отвергается бэкендом (ответ с
      кодом отказа), запись в аудит +1. С токеном нужной роли — исполняется.
- [ ] GUI с подменённой клиентской проверкой прав (тест снимает её) всё равно не может исполнить
      запрещённую команду — отказ приходит от бэкенда. **Это и есть свойство задачи; break-injection
      снимает серверную мидлварь и ждёт, что этот тест покраснеет.**
- [ ] `grep -rn "YamlUserStorage\|INSPECTOR_AUTH_USERS_PATH" multiprocess_prototype/frontend` вне тестов → 0.
- [ ] Вкладка «Администрирование» в Пульте создаёт пользователя, и он появляется в хранилище бэкенда.

**Out of scope:** TLS (2.2), внешние провайдеры идентичности, многопользовательское одновременное
редактирование рецепта сверх ревизии 1b.1.
**Dependencies:** Task 1.2 (сокет); до Ф2 обязательно.
**Module contract:** impl-only (`Services/auth` — контракт команд в его README).
