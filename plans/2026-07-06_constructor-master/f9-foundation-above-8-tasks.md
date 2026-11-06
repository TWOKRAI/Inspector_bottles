# Ф9 — задачи осей 2–7

Продолжение [f9-foundation-above-8.md](f9-foundation-above-8.md) (шапка, база, ворота W1–W5, порядок, ось 1, метрики, открытое). Файл разделён по лимиту размера документа. Сквозные правила задач (стадия 0, слепой тестер, инъекции, класс ревью) — там же, раздел «Ворота владельца и потолки».

## Ось 2 — модульность и границы

### Task Ф9.6 — `sentrux check .` в venv и в CI

- **Ось:** 2 · **Level:** Middle · **Assignee:** `developer` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0, независимо (полоса М/инфра)
- **Goal:** граница слоёв доказана санкционированной проверкой, не только grep (F1).
- **Files:** `.github/workflows/ci.yml`, `.claude/modes/_stack.md` (строка Toolchain — правит лид, файл англ.), `scripts/sentrux_install.md` (новый, как поставить бинарь в `.venv/Scripts`)
- **Steps:** (1) способ установки бинаря `sentrux` в `.venv` воспроизводимо (новая зависимость — с причиной в коммите); (2) job `sentrux` в `ci.yml`: `sentrux check .`, exit ≠ 0 → красный; (3) локальный прогон в venv.
- **Acceptance criteria:** `.venv/Scripts/sentrux check .` exit 0 на `main`; job CI зелёный; инъекция — временный обратный импорт `Services` в `multiprocess_framework` → job красный.
- **Тестер:** n/a (инфра); **инъекции:** И1 обратный импорт → красный `sentrux check`. **Ревью:** sonnet.
- **Out of scope:** `importlinter` — remediation Task 4.5 (`backend-ctl-review-remediation.md:210`); пороги sentrux — Ф8 H.5.

### Task Ф9.7 — `command_specs()` + `register_from` + тест тождества дампа (пилот)

- **Ось:** 2, 6 · **Level:** Senior+ · **Assignee:** `teamlead` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0, после 6а, camera 1.3, Ф9.2 · **Module contract:** public-api-change
- **Goal:** одна форма объявления команд для `BaseManager` (CTO Q3: `command_contracts: dict[str, type[BaseModel]]` из camera 1.3 → `command_specs()`); владелец семьи регистрирует её сам (`register_from` зовёт владелец).
- **Files:** `multiprocess_framework/modules/base_manager/interfaces.py`, `multiprocess_framework/modules/base_manager/` (новый `command_specs.py`), `multiprocess_framework/modules/process_module/commands/builtin_commands.py`, пилотная семья — `stats`/`state_store` (менеджер владельца — путь в стадии 0), `process_module/tests/test_capabilities_dump_identity.py` (тестер), `base_manager/tests/test_command_specs.py` (автор)
- **Steps:** (1) `command_specs() -> list[CommandSpec]` у `BaseManager`, умолчание — пустой список; (2) `register_from(manager)` в `CommandManager`; (3) семья `stats`/`state_store` переезжает из `BuiltinCommands` в менеджер-владелец; (4) тест тождества: дамп `introspect.capabilities` до и после — побайтно равен.
- **Acceptance criteria:** дамп побайтно равен до/после; `grep -c -F "self._services" builtin_commands.py` уменьшился на число строк пилотной семьи (число — в отчёте); `len == 7` сторожа `test_lifetime_interfaces.py:176` не менять.
- **Тестер до кода:** да; запрет — `builtin_commands.py`, `base_manager/*.py`. **Инъекции:** И1 `register_from` пропускает одну команду → красный тест тождества; И2 двойная регистрация → красный `*no_duplicate*`.
- **Ревью:** sonnet задача / opus ветка.
- **Out of scope:** `@expose`, седьмая форма, `declare_module`, `unregister_command` (W3); остальные пять форм — FREEZE только по W4.

### Task Ф9.8 — Семьи `BuiltinCommands` к владельцам (по касанию)

- **Ось:** 2 · **Level:** Middle+ · **Assignee:** `developer` · **Размер:** L, дробится (оценка CTO, подтвердить) · **Когда:** 2.0, после Ф9.7, по одной семье на задачу
- **Goal:** `BuiltinCommands` перестаёт быть бог-файлом; мерило 92 → < 30.
- **Files:** на семью: `builtin_commands.py` + менеджер-владелец семьи + тест тождества дампа (общий из Ф9.7).
- **Steps:** семья переезжает только когда её и так трогают; дамп — побайтно равен; старые имена команд — замороженный контракт.
- **Acceptance criteria:** после каждой семьи: дамп равен, B4 уменьшился; цель фазы B4 < 30.
- **Тестер:** нет (тест тождества Ф9.7 — общий); **инъекции:** И1 пропуск одной команды семьи → красный тест тождества. **Ревью:** sonnet.
- **Out of scope:** переименование команд; удаление пустых обработчиков (W4).

## Ось 3 — тестируемость

### Task Ф9.9 — Зелёный `main`: карантин по ID дефекта

- **Ось:** 3 · **Level:** Middle · **Assignee:** `developer` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0; перечень — сейчас
- **Goal:** гейт снова бинарный: красный отказывает.
- **Files:** тест-файлы красных C-6, C-71…C-75, C-81 (`plans/queue/defects.md:257,333-337,343`), `conftest.py` (корень), `scripts/tests/test_xfail_has_defect_id.py` (новый)
- **Steps:** (1) перечень красных `main` с ID → владельцу (W4: каждый карантин поимённо); (2) одобренные — `pytest.mark.xfail(strict=True, reason="C-xx: …")`; (3) сторож: каждый `xfail` в дереве несёт `C-\d+`/`L-\d+`, и ID есть в `defects.md`.
- **Acceptance criteria:** `make gate` exit 0 на `main` пять дней подряд (**число CTO, не замер** — подтвердить владельцу); сторож красный на `xfail` без ID.
- **Тестер до кода:** да (сторож); запрет — тест-файлы карантина. **Инъекции:** И1 `xfail` без ID → красный сторож; И2 `strict=False` → красный сторож. **Ревью:** sonnet.
- **Out of scope:** починка самих дефектов (их полосы); новые `xfail` без решения владельца (метрики plan.md: «новые xfail — только решением владельца»).

### Task Ф9.10 — Ожидание по условию вместо `time.sleep` + линт роста

- **Ось:** 3 · **Level:** Middle · **Assignee:** `developer` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0, независимо
- **Goal:** новые тесты ждут условие, не время; число файлов со `sleep` не растёт.
- **Files:** `multiprocess_framework/modules/conftest.py` (фикстура `wait_until`, без нового пакета), `multiprocess_framework/modules/tests/test_wait_until_fixture.py` (тестер), `scripts/lint_test_sleep.py` (новый), `scripts/tests/test_lint_test_sleep.py`, `scripts/lint_test_sleep_baseline.txt`
- **Steps:** (1) образцы уже есть: `backend_ctl/conditions.py:207` `await_condition`, `process_manager_module/tests/test_lifecycle_fifo_acceptance.py:269` `wait_until` — одна фикстура `wait_until(pred, timeout, step)` в общем `conftest.py` модулей (слой: тесты framework не импортируют `backend_ctl`); (2) линт: число тест-файлов с `time.sleep` ≤ базы (B8); (3) линт в `make gate`.
- **Acceptance criteria:** линт красный при новом файле со `sleep`; хелпер отдаёт время ожидания и `False` по таймауту (литералы в тесте).
- **Тестер до кода:** да; запрет — `modules/conftest.py`, `lint_test_sleep.py`. **Инъекции:** И1 линт не считает новый файл → красный `*grows*`; И2 хелпер игнорирует таймаут → красный `*timeout*` (вызов в daemon-потоке с дедлайном). **Ревью:** sonnet.
- **Out of scope:** массовая замена 168 файлов (по касанию); детерминированные часы (потолок оси 3).

### Task Ф9.11 — ССЫЛКА: atlas — балл мутаций, yaml ↔ interfaces, 2.5

- **Ось:** 3, 2, 7 · **Владелец:** [`2026-10-04_atlas`](../2026-10-04_atlas/plan.md) — Task 1.8 «производитель мутационного балла» (`:172`, DEFERRED — FREEZE по K0b); Task 2.5 «удаление мёртвого и дублей» (`:217`)
- **Добавляемое условие:** (1) балл мутаций числом в отчёте интеграции — только после разморозки 1.8 владельцем (W4); (2) находка «`modules.yaml` без `interfaces.py`» — да, как сторож; (3) 2.5 — только с поимённым одобрением (Принцип №1).
- **Не переописываем:** состав 1.8, 2.5.

## Ось 4 — готовность к агентам

### Task Ф9.12 — ССЫЛКА: remediation — клиент читает `access`

- **Ось:** 4 · **Владелец:** [`backend-ctl-review-remediation`](../backend-ctl-review-remediation.md) (4/18; строка 36 ORDER, 2.0)
- **Зависимость Ф9:** после Ф9.2 (поле в каталоге); первым шагом — W1 (снять противоречие `:18` ↔ `:261`).
- **Добавляемое условие:** клиент берёт класс доступа из каталога; кортеж `READ_SAFE_*` (`backend_ctl/mcp_tools.py:1579`) замораживается (FREEZE, не KILL); живой тест ненуля (BCTL-ADR-007): чтение без `access` в каталоге → клиент считает его не-read.
- **Не переописываем:** Фазы 0–5 remediation.

### Task Ф9.13 — CLI над `dispatch_tool`, ноль новых MCP-инструментов

- **Ось:** 4 · **Level:** Middle · **Assignee:** `developer` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0, независимо; `backend_ctl` — один писатель
- **Goal:** второй клиент (агент без MCP, скрипт release-1.0 α) зовёт те же инструменты из shell.
- **Files:** `backend_ctl/cli.py` (новый), `backend_ctl/tests/test_cli_parity.py` (тестер), `backend_ctl/README.md` (раздел CLI)
- **Steps:** (1) `python -m backend_ctl.cli <tool> --json '<args>'` → тот же `dispatch_tool`, что MCP; (2) `list` печатает имена из того же реестра `ToolSpec`; (3) замер токенов на 10 пробах (вывод CLI против ответа MCP) — числа в README.
- **Acceptance criteria:** 10 проб (список — в стадии 0, только `access=read`) — результат CLI равен результату MCP по ключам; `grep -c -F "ToolSpec(" backend_ctl/mcp_tools.py` = B5 (53) — без роста.
- **Тестер до кода:** да; запрет — `cli.py`. **Инъекции:** И1 CLI теряет аргумент → красный `*parity*`; И2 CLI регистрирует свой инструмент → красный `*no_new_tool*`. **Ревью:** sonnet.
- **Out of scope:** новые MCP-инструменты; destructive-вызовы из CLI без флага подтверждения.

### Task Ф9.14 — Инструменты по намерению (53 → ~15) + `outputSchema` для 10 чтений

- **Ось:** 4 · **Level:** Senior · **Assignee:** `teamlead` (дизайн семей) → `developer` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0, **только после W1**; после Ф9.12, Ф9.3
- **Goal:** выбор инструмента агентом не деградирует (строка 44 ORDER: деградация после ~30–50 определений).
- **Files:** `backend_ctl/mcp_tools.py`, `backend_ctl/tests/test_tools_list_live.py`, `backend_ctl/tests/test_output_schema.py`
- **Steps:** (1) таблица «старый инструмент → семья по намерению» — владельцу; (2) новый инструмент заменяет ≥ 2 старых (W1); старые — FREEZE-алиасы (W4); (3) `outputSchema` (JSON Schema 2020-12) для 10 самых частых чтений.
- **Acceptance criteria:** живой тест `tools/list` ≤ 20 видимых; 10 чтений с `outputSchema`, ответ проходит валидацию схемы; токены до/после на 10 пробах Ф9.13 — числами.
- **Тестер до кода:** да; запрет — `mcp_tools.py`. **Инъекции:** И1 вернуть старый инструмент в видимые → красный `*tools_list_le_20*`; И2 ответ без ключа схемы → красный `*output_schema*`. **Ревью:** sonnet / opus ветка.
- **Out of scope:** MCP resources/prompts/tasks; серверный токен (gui-service 2.2).

## Ось 5 — многопроцессность и IPC

### Task Ф9.15 — Один счётчик рестарта вместо трёх

- **Ось:** 5, 1 · **Level:** Senior · **Assignee:** `teamlead` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0, после 6а (ответ Ф9.5 п. 2) и `system-run-state` Ф1 · **Module contract:** public-api-change
- **Goal:** GUI, `backend_ctl` и стенды видят одну правду о рестартах.
- **Files:** `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py`, `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`, `multiprocess_framework/modules/process_manager_module/DECISIONS.md` (ADR), `process_manager_module/tests/test_restart_counter_single.py` (тестер)
- **Steps:** (1) одно каноническое имя (решает 6а); (2) два других — производные, только чтение, FREEZE (W4); (3) ADR.
- **Acceptance criteria:** `git grep -l` писателей двух старых имён вне тестов = 0; `kill -9` ребёнка → каноническое +1, оба старых показывают то же; соседи живы.
- **Тестер до кода:** да; запрет — оба `src`-файла. **Инъекции:** И1 инкремент только старого имени → красный `*canonical*`; И2 производное расходится → красный `*aliases_agree*`. **Ревью:** sonnet / opus ветка.
- **Out of scope:** изменение политики рестарта.

### Task Ф9.16 — Поле версии контракта в конверте IPC (умолчание 1)

- **Ось:** 5, 6 · **Level:** Senior · **Assignee:** `teamlead` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0 (кандидат W5), независимо · **Module contract:** public-api-change
- **Goal:** удалённые процессы и второе приложение живут с разными версиями сообщений.
- **Files:** `multiprocess_framework/modules/message_module/core/message.py`, `multiprocess_framework/modules/message_module/tests/test_contract_version.py` (тестер), `multiprocess_framework/modules/message_module/DECISIONS.md`
- **Steps:** (1) поле `contract_version: int = 1` в конверте; в `to_dict` — всегда; (2) читатель принимает dict без поля (= 1) и с незнакомой версией (лог + счётчик, не падение); (3) ADR.
- **Acceptance criteria:** тест «старый читатель принимает новый конверт» и обратно; B6 = 1+ строк; Dict at Boundary — только `dict` через границу (сторож существующий).
- **Тестер до кода:** да; запрет — `message.py`. **Инъекции:** И1 читатель падает на версии 2 → красный `*unknown_version*`; И2 поле не сериализуется → красный `*roundtrip*`. **Ревью:** sonnet / opus ветка (IPC).
- **Out of scope:** миграция читателей по версиям; hot-path кадра (носитель — плоский dict, инвариант Ф7).

### Task Ф9.17 — ССЫЛКА: внутрипроцессная половина стопа (owner-scope Ф2–Ф6)

- **Ось:** 5 · **Владелец:** [`2026-10-03_lifecycle-owner-scope`](../2026-10-03_lifecycle-owner-scope/plan.md) — Ф2, Ф5 FREEZE (`:48`); владение короткоживущих команд — `DESIGN.md:194` (`owner.own(...)`, Ф3)
- **Зависимость Ф9:** потолок оси 5 = 8, пока W2 не решён.
- **Добавляемое условие:** при разморозке — одна строка `DESIGN.md:194` вместо `unregister_command` (W3); противоречие `owner-scope/plan.md:48` ↔ `transport-single-policy/plan.md:71` (5.5d SUPERSEDED ссылкой на замороженную Ф5) — во вход Ф9.24.
- **Не переописываем:** фазы owner-scope.

## Ось 6 — расширяемость («конструктор»)

### Task Ф9.18 — ССЫЛКА: camera-device-service 1.3/1.4 — форма объявления

- **Ось:** 6, 4 · **Владелец:** [`2026-10-18_camera-device-service`](../2026-10-18_camera-device-service/plan.md) — Task 1.3 `command_contracts` (`tasks/1.3.md`, W7, public-api-change), Task 1.4 `introspect.registers` с `meta` (`tasks/1.4.md`)
- **Зависимость Ф9:** вход Ф9.2, Ф9.7, Ф9.19 (тот же `plugins/base.py` — один писатель, после 1.3); по ORDER — до адаптера плагина.
- **Добавляемое условие:** форма `command_contracts: dict[str, type[BaseModel]]` 1.3 — единственная живая форма, вход `command_specs()` Ф9.7; пять остальных форм — FREEZE только по W4.
- **Не переописываем:** DESIGN, REDS 1.3/1.4.

### Task Ф9.19 — Правило имени `<модуль>.<действие>` + страж коллизий `ExactMatch`

- **Ось:** 6 · **Level:** Middle+ · **Assignee:** `developer` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0, после 6а и camera 1.3 (тот же файл)
- **Goal:** второй плагин с тем же именем команды (`set_config`) не проигрывает молча первому.
- **Files:** `multiprocess_framework/modules/process_module/plugins/base.py` (`:1733-1742`), `multiprocess_framework/modules/process_module/tests/test_plugin_command_collision.py` (тестер), `multiprocess_framework/docs/ROUTING_GLOSSARY.md` (правило имени)
- **Steps:** (1) регистрация `ExactMatch` с уже занятым именем → громкая ошибка с именами обоих владельцев (лог + счётчик в `introspect`), не тихая перезапись; (2) правило: новые команды — `<модуль>.<действие>`; старые имена без префикса — замороженный контракт (W3); (3) сторож-тест: новая команда без точки → красный.
- **Acceptance criteria:** два тестовых плагина с `set_config` в одном процессе → ошибка с двумя именами; поведение первого плагина не изменилось; сторож краснеет на новом имени без точки, старые — в списке исключений.
- **Тестер до кода:** да; запрет — `base.py`. **Инъекции:** И1 вернуть тихую перезапись → красный `*collision_is_loud*`; И2 снять список исключений → красные старые имена (`*legacy_names_frozen*`). **Ревью:** sonnet / opus ветка.
- **Out of scope:** переименование старых команд.

### Task Ф9.20 — Честные оболочки сервисов: `state: "shell"`

- **Ось:** 6, 1 · **Level:** Middle · **Assignee:** `developer` · **Размер:** S на сервис (оценка CTO, подтвердить) · **Когда:** 2.0, полоса Services, после строки 31 ORDER
- **Goal:** внешний встройщик не видит `running` у пустышки.
- **Files:** `service.py` оболочек — перечень из Ф9.0 шаг 5 (кандидаты из 7 файлов с `"running"`: `Services/{auth,dataset_gen,hikvision_camera,ml_inference,ml_train,modbus,sql}/service.py`), `Services/STATUS.md`, `Services/tests/test_service_state_honest.py` (тестер)
- **Steps:** (1) оболочка (нет ресурса после `start()`) отдаёт `state: "shell"`; (2) приёмка настоящего сервиса — «после `start()` ресурс виден» (соединение, файл, порт); (3) пометка FREEZE в STATUS — только поимённо по W4.
- **Acceptance criteria:** у оболочек `"running"` = 0 (`grep -n -F '"running"'` по их `service.py`); у настоящих — тест «ресурс виден после `start()`».
- **Тестер до кода:** да; запрет — `service.py` перечня. **Инъекции:** И1 оболочка возвращает `running` → красный `*shell_is_honest*`. **Ревью:** sonnet.
- **Out of scope:** `BaseService` для всех 18 (W3, ADR-SVC-002); `ServiceContext` — `observability-closure` Task 4.5 (`plan.md:172`) — те же `robot_comm`/`vfd_comm`/`modbus`: один писатель на файл.

### Task Ф9.21 — ССЫЛКА: принцип 6 — gui-graceful-close и gui-service

- **Ось:** 4, 5 · **Владельцы:** [`2026-10-20_gui-graceful-close`](../2026-10-20_gui-graceful-close/plan.md) (DRAFT; строка 14 ORDER); [`2026-09-22_gui-service`](../2026-09-22_gui-service/plan.md) (строка 33, 2.0)
- **Добавляемое условие:** (1) graceful-close `:25` «принудительный режим `backend_ctl` — короткий срок» — срок числом в плане, иначе это обход; `:34` GUI только шлёт `system.shutdown`; (2) gui-service `:53` (бэкенды headless) против `:262` Task 3.3 («`frontend/run.py` = бэкенд + Пульт») — во вход Ф9.24; (3) охранник bind не-loopback (S, вердикт №1 совет 8) — условие внешней двери вместе с gui-service 2.2.
- **Не переописываем:** их задачи.

## Ось 7 — зрелость процесса

Полоса М по ORDER §1 п. 5 — «закрыть начатые фазы и остановиться». Ф9.22–Ф9.24 открывают в ней новую работу: **старт — только по слову владельца** (W-решение к W5).

### Task Ф9.22 — WIP-лимит механизмом

- **Ось:** 7 · **Level:** Middle · **Assignee:** `developer` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0
- **Goal:** «не больше 3 писателей» проверяет скрипт, не память лида.
- **Files:** `scripts/plans_progress/plans_progress.py`, `scripts/plans_progress/tests/test_wip_limit.py` (тестер), `scripts/plans_progress/README.md`
- **Steps:** (1) находка `WIP_OVER_LIMIT` — блокирующая, когда `--who` видит > 3 активных писателей; (2) лимит — константа с источником (ORDER строка 26).
- **Acceptance criteria:** фикстура с 4 писателями → `--check` exit ≠ 0 и находка; с 3 → без находки.
- **Тестер до кода:** да; запрет — `plans_progress.py`. **Инъекции:** И1 порог `>= 5` → красный `*four_writers_block*`. **Ревью:** sonnet.
- **Out of scope:** автоматическая остановка сессий.

### Task Ф9.23 — Шапки = git; `BRANCH_MISSING` и строка очереди без плана

- **Ось:** 7 · **Level:** Middle · **Assignee:** `developer` (находка) + `docs-writer` (шапки) · **Размер:** S (оценка CTO, подтвердить) · **Когда:** шаг 1 сейчас, без писателя
- **Goal:** информационных находок < 50 (число CTO) и ни одной шапки старше последнего DONE.
- **Files:** `scripts/plans_progress/plans_progress.py`, `scripts/plans_progress/tests/test_header_stale.py`; шапки планов из перечня шага 1
- **Steps:** (1) haiku: разложить 146 находок по кодам с примерами; (2) находка `HEADER_STALE`: «Статус» DRAFT/PENDING при задачах DONE с хешем; (3) шапки и строки «Ветка» из перечня — правка `docs-writer` после одобрения лида; строку 44 ORDER (`backend-ctl` без плана) — предложение координатору.
- **Acceptance criteria:** `--check`: информационных < 50; `HEADER_STALE` = 0; фикстура «DRAFT + DONE» → находка.
- **Тестер до кода:** да (находка); запрет — `plans_progress.py`. **Инъекции:** И1 находка не видит DRAFT → красный `*header_stale*`. **Ревью:** sonnet; шапки — express.
- **Out of scope:** правка ORDER.md (координатор); удаление планов.

### Task Ф9.24 — Линт противоречий между планами

- **Ось:** 7 · **Level:** Middle+ · **Assignee:** `developer` · **Размер:** M (оценка CTO, подтвердить) · **Когда:** 2.0, после Ф9.23
- **Goal:** ссылка живой задачи на замороженную, поглощённую или отложенную задачу другого плана видна до исполнения.
- **Files:** `scripts/plans_progress/plans_progress.py`, `scripts/plans_progress/tests/test_xref_inactive.py` (тестер)
- **Steps:** (1) в строке задачи — ссылка `[..](<план>)` + `Ф<N>`/`Task <id>`; статус цели — тем же парсером; (2) находка `XREF_INACTIVE_TARGET` (info), когда строка не закрыта, а цель FREEZE/DEFERRED/SUPERSEDED; (3) вход — пары из Ф9.17, Ф9.21, `atlas:217`, `device-tree-recipe:220-223`.
- **Acceptance criteria:** фикстура «PENDING → FREEZE» → находка; «DONE → FREEZE» → нет; на дереве — перечень находок, каждую лид разбирает.
- **Тестер до кода:** да; запрет — `plans_progress.py`. **Инъекции:** И1 цель DEFERRED не считается неактивной → красный `*deferred_target*`. **Ревью:** sonnet.
- **Out of scope:** смысловое сравнение текстов планов; автоправка.
