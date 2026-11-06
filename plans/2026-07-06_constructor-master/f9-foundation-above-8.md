# Ф9 — Фундамент «выше 8»: семь осей вердикта CTO

- **Мастер-план:** [plan.md](plan.md), фаза Ф9 (номер свободен: `Ф9`/`F9` в каталоге плана не встречались). Id в «Порядке выполнения»: `Ф9.N` → `F9-N`. Задачи осей 2–7 (Ф9.6–Ф9.24) — [f9-foundation-above-8-tasks.md](f9-foundation-above-8-tasks.md) (разделено по лимиту размера документа).
- **Дата:** 2026-11-01 · **Статус:** DRAFT (ждёт S1′: `reviewer` `MODE: plan` → владелец) · **База:** `main` @ `dcf7bc22c`
- **Основание:** [вердикт CTO, второй проход](../../docs/reports/2026-11-01_cto-roadmap-above-8.md) (§1 оси, §2 фундамент, §5 потолок) + [планы очереди](../../docs/reports/2026-11-01_cto-roadmap-above-8-plans.md); решения карточки — [вердикт №1](../../docs/reports/2026-11-01_cto-verdict-module-card.md) (Q17 советы 1–8, «не делать»).
- **Решение владельца 2026-11-01:** скоуп — все 7 осей; место — фаза мастер-плана, не новый план.
- **Место в очереди:** 2.0 (решение 23: строки 1–27 — 1.0 и идут первыми). Исключение — задачи «без писателя» (раздел «Порядок»). Перенос любой задачи в 1.0 — только обменом строки владельцем.

## Цель и база

**Цель:** каждая из семи осей выше 8 там, где принципы владельца это позволяют; где не позволяют — честный потолок и названное условие его подъёма. Цель числом — только через измеримый гейт (таблица «Метрики приёмки фазы»), не прилагательным.

**Числа CTO — наблюдения одного прохода.** Ф9.0 повторяет каждое командой. Менеджер 2026-11-01 повторил часть (столбец «Повтор»); остальное — «не повторено».

| # | Факт CTO | Число CTO | Повтор менеджера | Команда |
|---|---|---|---|---|
| B1 | `params_schema` в каталоге | 282 | 282 | `grep -c -F params_schema docs/contracts/CAPABILITIES.yaml` |
| B2 | строки `description:` в каталоге | 606 | 606 | `grep -c -F "description:" docs/contracts/CAPABILITIES.yaml` |
| B3 | `access` в каталоге | 0 | 0 | `grep -c -F access docs/contracts/CAPABILITIES.yaml` |
| B4 | `self._services` в `BuiltinCommands` | 92 | 92 | `grep -c -F "self._services" multiprocess_framework/modules/process_module/commands/builtin_commands.py` |
| B5 | `ToolSpec(` в `backend_ctl` | 53 | 53 | `grep -c -F "ToolSpec(" backend_ctl/mcp_tools.py` |
| B6 | версия контракта в IPC | 0 | 0 | `git grep -n -E "schema_version\|contract_version\|api_version" -- multiprocess_framework/modules/{message,router,command}_module \| wc -l` |
| B7 | `plans_progress --check`, информационных | 146 | 146 (блокирующих 0, планов 80) | `python scripts/plans_progress/plans_progress.py --check` |
| B8 | тест-файлы с `time.sleep` | 168 из 911 | не повторено | Ф9.0 шаг 3 |
| B9 | счётчики рестарта (3 имени) | 5/1/2 вхождения | не повторено | Ф9.0 шаг 4 |
| B10 | `"running"` в `Services/*/service.py` | «5 оболочек из 9» | 11 строк в 7 файлах (другое мерило) | `grep -n -F '"running"' Services/*/service.py` |
| B11 | корни при импорте одного модуля | 23 (rework:9) | не повторено | Ф9.0 шаг 6 |
| B12 | `sentrux check .` | не выполним (`sentrux.exe` нет) | не повторено | Ф9.0 шаг 7 |

### Task Ф9.0 — Замер базы фазы командами

- **Ось:** все · **Level:** Junior · **Assignee:** `Explore` (haiku, effort ≥ medium) · **Размер:** S (оценка менеджера) · **Когда:** сейчас, без писателя
- **Goal:** каждое число B1–B12 записано с командой и выводом; число без повтора не идёт в цель.
- **Files:** только вывод в отчёт агента; лид переносит числа в `plans/2026-07-06_constructor-master/baseline.md` (раздел «Ф9»).
- **Steps:** (1) B1–B7 командами таблицы; (2) B2 разложить по командам: `python -I backend_ctl/dump_capabilities.py --help` → способ дампа в JSON; число команд всего / с `params_schema` / без — по ключам, не по строкам; (3) B8: `rg -l -F "time.sleep" --glob "**/tests/**/*.py" --glob "!.claude/worktrees" multiprocess_framework | wc -l` и знаменатель `rg --files --glob "**/tests/**/test_*.py" multiprocess_framework | wc -l`; то же для всего дерева; (4) B9: `git grep -n -E "incarnation|instance_restarts|restart_count" -- multiprocess_framework/modules/process_manager_module ':!*/tests/*'` — вхождения по имени и файлу; (5) B10: по каждому `service.py` — строка `start()`, что он делает (вывод `sed -n` 10–15 строк); (6) B11: `python -X importtime -c "import multiprocess_framework.modules.message_module" 2>&1 | <счёт корней верхнего уровня>`, три модуля: `message_module`, `command_module`, `process_module`; (7) B12: `ls .venv/Scripts/sentrux*`; `grep -n sentrux .github/workflows/ci.yml`; (8) `pytest.mark.xfail|skip` в тестах корня — `rg -c`; (9) классы находок B7 — счёт по первому слову строки.
- **Acceptance criteria:** 12 строк B1–B12 с командой и дословным выводом; расхождение с числом CTO > 5 % — отдельной строкой «расходится».
- **Тестер до кода / инъекции:** n/a — замер, не код. **Ревью:** лид сверяет 3 случайных числа повтором.
- **Out of scope:** правки кода, выводы о причинах.

## Ворота владельца и потолки

**Сквозные правила задач Ф9** (каждая задача с кодом, `.claude/CLAUDE.md` «Task launch convention»): стадия 0 — `reviewer` (sonnet) на тексте Task; тестер — слепой, один раз на механизм, в worktree на коммите до кода, только по Acceptance, запретные пути — `src`-файлы задачи; предсказания инъекций — до прогона, прогон — haiku по предсказаниям лида; ревью задачи — `reviewer` (sonnet), ревью ветки перед merge — `opus`. Задачи-ссылки (помечены «ССЫЛКА») не переописывают чужой план: зависимость + условие приёмки, которое добавляет Ф9.

| # | Ворота | Что решает владелец | Рекомендация CTO / менеджера | Держит задачи |
|---|---|---|---|---|
| W1 | Противоречие remediation | `backend-ctl-review-remediation.md:18` «Новые MCP-инструменты НЕ создаются» против `:261` Task 5.1 «инструмент `targets`» | CTO: ворота вместо запрета — `access` у инструмента + живой тест ненуля (BCTL-ADR-007) + новый инструмент только взамен ≥ 2 старых | Ф9.12, Ф9.14 |
| W2 | Разморозка внутрипроцессной половины стопа | `2026-10-03_lifecycle-owner-scope/plan.md:48` — Ф2, Ф5 FREEZE (владелец 2026-10-13) | CTO: без разморозки ось 5 упирается в 8; переставлять не предлагает | Ф9.17 |
| W3 | Четыре «не трогать» CTO | остаются нетронутыми: ADR-SVC-002 (`BaseService` — опция); `unregister_command` не вводить; перегруппировка `framework-architecture-rework` + codemod и `stdlib/`; имена 85 команд PM и 11 литералов `introspect.*` | подтвердить одной строкой | все |
| W4 | Принцип №1 | каждое удаление, заморозка или карантин — поимённое одобрение | список кандидатов задача приносит владельцу до правки | Ф9.8, Ф9.9, Ф9.18, Ф9.20 |
| W5 | Обмен строки 1.0 | взять ли что-то из Ф9 выше строки 27 | менеджер: нет; кандидаты при желании — Ф9.16 (версия конверта, S) и Ф9.2 (поля команды, S) — оба дешевле сейчас, чем при 50–100 модулях | весь порядок |

### Честный потолок (CTO §5) и что его поднимет

| Ось | Сейчас (CTO) | Потолок при принципах | Что поднимет потолок |
|---|---|---|---|
| 1 Наблюдаемость и управляемость | 7 | 9 | Ф9.2–Ф9.5 закрыты гейтами таблицы метрик |
| 2 Модульность и границы | 7 | 9 | Ф9.6 + Ф9.8 (92 → < 30) + корни импорта ≤ 5 (B11) |
| 3 Тестируемость | 6 | 8 | 9 требует детерминированных часов для multiprocessing + Qt на Windows (L, плана нет) |
| 4 Готовность к агентам | 6 | 8 | 9 требует серверной политики доступа и аудита — владелец откладывает («безопасность после фундамента»); охранник bind не-loopback (S) |
| 5 Многопроцессность и IPC | 6 | 8 | 9 — только с W2 (разморозка owner-scope Ф2–Ф6) |
| 6 Расширяемость | 6 | 8 | 9 требует снять пять из шести форм регистрации; FREEZE это запрещает (Принцип 3) |
| 7 Зрелость процесса | 6 | 9 | WIP-лимит механизмом (Ф9.22); выше 8 — поведение владельца и лида, кодом не поднимается |

## Порядок, полосы, граф

Правила ORDER: не больше 3 писателей; полоса Ф закрыта до приёмки 6а; `process_module` — один писатель; camera 1.3/1.4 — до адаптера плагина; работа карточки — 2.0.

**Сейчас, без писателя кода** (документы и замеры): Ф9.0, Ф9.1, Ф9.4 (S1′ `system-run-state` — их работа), Ф9.23 шаг 1 (классификация находок), решения W1–W5.

```
Ф9.0 ─► Ф9.1 ─────────────────────────────► (каталог для всех)
6а (Ф9.5: C-82, счётчики) ─► Ф9.15 один счётчик
                         └─► system-run-state (Ф9.4) ─► gui-graceful-close 0.1–1.4 (Ф9.21)
camera 1.3/1.4 (Ф9.18) ─► Ф9.2 поля ─► Ф9.7 command_specs ─► Ф9.8 семьи (по касанию)
                                   ├─► Ф9.19 имя + страж (тот же base.py — после 1.3)
                                   ├─► Ф9.12 клиент читает access (remediation) ─► W1 ─► Ф9.14
                                   └─► Ф9.3 params_schema ─► Ф9.14 шаг outputSchema
Ф9.13 CLI (backend_ctl, независимо) · Ф9.16 версия конверта (message_module, независимо)
Ф9.6 sentrux (CI, независимо) · Ф9.9, Ф9.10 тесты (независимо) · Ф9.20 оболочки (после строки 31)
Ф9.22–Ф9.24 полоса М (после W-решения о полосе М, см. Ф9.22)
```

**Писатели по модулям (конфликт файлов):** `process_module` (`builtin_commands.py`, `plugins/base.py`) — Ф9.2 → Ф9.7 → Ф9.19 → Ф9.8 строго по очереди, после camera 1.3/1.4 и после 6а; `process_manager_module` — Ф9.15 после 6а и после `system-run-state` Ф1 (одна полоса); `backend_ctl` — Ф9.13, затем remediation, затем Ф9.14; `message_module` — Ф9.16; `scripts/plans_progress` — Ф9.22 → Ф9.23 → Ф9.24. Волна — не больше трёх из этих колонок одновременно.

## Задачи: ось 1 — наблюдаемость и управляемость

### Task Ф9.1 — Гигиена каталога

- **Ось:** 1, 4 · **Level:** Junior · **Assignee:** `docs-writer` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** сейчас · **Зависит от:** Ф9.0
- **Goal:** каталог и его описание не врут: дамп свежий, `access` записан как плановое поле.
- **Files:** `docs/contracts/CAPABILITIES.yaml`, `docs/contracts/CAPABILITIES.md`, `Services/STATUS.md`
- **Steps:** (1) перегенерировать дамп штатной командой из шапки `CAPABILITIES.md`; (2) в `CAPABILITIES.md` раздел «Плановые поля»: `access` (`read`/`write`/`destructive`), `idempotent`, `owner` — «не заполнены, вводит Ф9.2»; (3) `Services/STATUS.md`: число сервисов = число каталогов `Services/*/` с `service.yaml` (сейчас «14 из 18» по вердикту №1).
- **Acceptance criteria:** дамп побайтно равен свежему прогону; `grep -c -F "Плановые поля" docs/contracts/CAPABILITIES.md` = 1; число в STATUS = выводу `ls Services/*/service.yaml | wc -l`.
- **Тестер / инъекции:** n/a — документы. **Ревью:** `reviewer` express.
- **Out of scope:** `backend_ctl/STATUS.md` «47» — владеет remediation Task 4.5 (`backend-ctl-review-remediation.md:209-216`); код.

### Task Ф9.2 — Поля `access`, `idempotent`, `owner` в объявлении команды и в каталоге

- **Ось:** 1, 4 · **Level:** Senior · **Assignee:** `teamlead` · **Размер:** S (оценка CTO, подтвердить) · **Когда:** 2.0, после 6а и camera 1.3 · **Module contract:** public-api-change
- **Goal:** сервер, не клиент, знает класс доступа каждой команды; каталог отдаёт его.
- **Files:** `multiprocess_framework/modules/command_module/core/command_manager.py` (`register_command`, `:205`), `multiprocess_framework/modules/process_module/commands/builtin_commands.py` (`introspect.capabilities`, `:840-920`), `backend_ctl/dump_capabilities.py`, `docs/contracts/CAPABILITIES.yaml`, тест-файлы `command_module/tests/test_command_access_meta.py` (тестер), `process_module/tests/test_capabilities_access.py` (автор)
- **Steps:** (1) `metadata` `register_command` принимает `access`, `idempotent`, `owner`; отсутствие = `None`, путь без поля — ноль стоимости; (2) политика — одна функция `access_of(name) -> str | None`; (3) `introspect.capabilities` кладёт поля в запись команды; (4) встроенные команды PM размечены; плагинные — по умолчанию `owner` = имя плагина; (5) дамп CI краснеет, если у **новой** команды нет `access` (список старых без поля — замороженный, растёт только вниз).
- **Acceptance criteria:** `grep -c -F "access:" CAPABILITIES.yaml` = числу команд в дампе (Ф9.0 шаг 2); команда без `access` в тестовом процессе → дамп-тест красный; ответ `introspect.capabilities` без новых полей у команд старого списка побайтно прежний вне трёх ключей.
- **Тестер до кода:** да; запрет — `command_manager.py`, `builtin_commands.py`. **Инъекции (до прогона):** И1 убрать `access` из записи каталога → красные: `test_capabilities_access::*catalog*`, дамп-тест; И2 `access_of` всегда `None` → красные: `*policy*`; И3 снять храповик старого списка → красный: `*new_command_requires_access*`.
- **Ревью:** sonnet задача / opus ветка.
- **Out of scope:** серверная проверка прав (откладывает владелец); чтение поля клиентом — Ф9.12; `READ_SAFE_*` (`backend_ctl/mcp_tools.py:1579`) не трогать.

### Task Ф9.3 — `params_schema` у каждой команды (храповик)

- **Ось:** 1, 4 · **Level:** Middle · **Assignee:** `developer` · **Размер:** M, постепенно (оценка CTO, подтвердить) · **Когда:** 2.0, после Ф9.2
- **Goal:** агент не гадает аргументы: доля команд со схемой растёт, падать не может.
- **Files:** `multiprocess_framework/modules/process_module/commands/command_contracts.py`, `multiprocess_framework/modules/process_module/tests/test_params_schema_ratchet.py`, `docs/contracts/params_schema_baseline.txt`
- **Steps:** (1) тест-храповик: число команд без `params_schema` в дампе ≤ числа в `params_schema_baseline.txt`; (2) первая порция — 10 команд PM, которые чаще всего зовёт `backend_ctl` (список — из `backend_ctl/mcp_tools.py`, лид утверждает в стадии 0); (3) baseline уменьшить на 10.
- **Acceptance criteria:** храповик красный при добавлении команды без схемы; после порции число без схемы = базе Ф9.0 − 10.
- **Тестер до кода:** нет (храповик — сам тест); **инъекции:** И1 удалить схему у одной команды → красный храповик. **Ревью:** sonnet.
- **Out of scope:** `outputSchema` (Ф9.14); схемы замороженных команд.

### Task Ф9.4 — ССЫЛКА: состояния системы `system.run.*`

- **Ось:** 1, 5 · **Владелец:** [`2026-10-27_system-run-state`](../2026-10-27_system-run-state/plan.md) (DRAFT, 12 PENDING; Task 1.1 vertical slice, `:65`) · **Assignee:** их · **Размер:** их
- **Зависимость Ф9:** главный рычаг оси 1 (CTO); код — после 6а (файлы PM у Ф).
- **Добавляемое условие приёмки:** `backend_ctl capabilities` показывает `system.run.start/stop/status` с `access` (`write`/`write`/`read`) и `idempotent` (Ф9.2); на стенде `backend_ctl` видит `ready` до нажатия ЗАПУСТИТЬ (число CTO).
- **Не переописываем:** машину состояний, `run_event`, `readiness()`.

### Task Ф9.5 — ССЫЛКА: приёмка 6а, C-82 и вопрос счётчиков

- **Ось:** 1, 5 · **Владелец:** полоса Ф, [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md), строка 6а ORDER; C-82 — `plans/queue/defects.md:344` + поправка причины `plans/queue/inbox/2026-11-01_inspector-bottles-ca_2.md`
- **Зависимость Ф9:** ворота для всего в `process_module` и `process_manager_module`.
- **Добавляемое условие приёмки:** (1) C-82: стенд early — PM-exit ≤ 1,5 с в 6 из 6 (число CTO; ждёт решения владельца «стоп во время `initialize()` прерывает подъём», `docs/handoffs/2026-11-01_Ф-C60-merged.md:20`); (2) в протоколе 6а — ответ «один счётчик рестарта» → вход Ф9.15.
- **Не переописываем:** C-36, C-57/58, C-53/54, флейки, C-60.

## Метрики приёмки фазы

База — из Ф9.0 (до неё действует столбец «Повтор» раздела «Цель и база»). Цель выше 8 засчитывается только гейтом этой таблицы.

| Ось | Метрика | База | Цель | Команда |
|---|---|---|---|---|
| 1 | команды с `access` / всего в дампе | 0 / Ф9.0 | равны | `grep -c -F "access:" docs/contracts/CAPABILITIES.yaml` против числа команд дампа |
| 1 | команды без `params_schema` | Ф9.0 шаг 2 | храповик вниз, −10 за порцию; 0 у незамороженных к концу фазы | `test_params_schema_ratchet.py` |
| 1, 5 | PM-exit при раннем `system.shutdown` | 4,97–8,05 с (C-82, investigator) | ≤ 1,5 с в 6 из 6 (число CTO) | стенд C-82 early, `stand_l9.py` |
| 1 | `ready` виден до ЗАПУСТИТЬ | нет | да | `backend_ctl` `system.run.status` на стенде |
| 2 | `sentrux check .` | не выполним | exit 0 локально и в CI | `.venv/Scripts/sentrux check .`; job CI |
| 2 | `self._services` в `BuiltinCommands` | 92 | < 30 | B4 |
| 2 | корни при импорте модуля | 23 (не повторено) | ≤ 5 | Ф9.0 шаг 6 |
| 3 | `make gate` на `main` | красный (C-6, C-71…75, C-81) | exit 0 пять дней подряд (число CTO) | `machine_gate.sh heavy … make gate` |
| 3 | тест-файлы с `time.sleep` | 168 (не повторено) | не растёт | `scripts/lint_test_sleep.py` |
| 4 | видимые MCP-инструменты | 53 | ≤ 20 | `test_tools_list_live.py` |
| 4 | CLI = MCP на пробах | — | 10 из 10 | `test_cli_parity.py` |
| 4 | чтения с `outputSchema` | 0 | 10 | `test_output_schema.py` |
| 5 | имена счётчика рестарта с писателем | 3 | 1 | `git grep -l` по трём именам вне тестов |
| 5 | версия контракта в конверте | 0 | поле есть, умолчание 1 | B6 + `test_contract_version.py` |
| 5 | `kill -9` любого процесса — соседи живы | — | 10 из 10 (`current-path/architecture-10-of-10.md:17`) | стенд |
| 6 | дамп до/после переноса семьи | — | побайтно равен | `test_capabilities_dump_identity.py` |
| 6 | коллизия `ExactMatch` | тихая | громкая ошибка | `test_plugin_command_collision.py` |
| 6 | `"running"` у оболочек | Ф9.0 шаг 5 | 0 | `grep -n -F '"running"'` по перечню |
| 7 | информационных `--check` | 146 | < 50 (число CTO) | `plans_progress.py --check` |
| 7 | писателей сверх лимита | не проверяется | `--check` exit ≠ 0 при > 3 | `test_wip_limit.py` |
| 7 | шапки старше последнего DONE | не проверяется | 0 | `HEADER_STALE` |

## Что осталось открытым или ненадёжным

- **Не повторено менеджером:** B8 (168/911 `time.sleep`), B9 (3 счётчика, 5/1/2), B11 («23 корня» — CTO сам не повторял), B12 (`sentrux.exe`), 26 строк `skip|xfail`, F6 (размеры файлов). Повторены: B1–B7.
- **B10 расходится по мерилу:** CTO — «5 оболочек из 9 `service.py`»; `"running"` — в 7 файлах, 11 строк. Какие из семи — оболочки, решает Ф9.0 шаг 5.
- **Шапка `lifecycle-stop-ownership.md`:** CTO по дайджесту — «`:6` DRAFT против DONE». Сам читал `:6` — там «Статус: IN PROGRESS — Ф1 начата…». Противоречие дайджеста не подтверждено; Ф9.23 проверит находкой.
- **Противоречия, известные только по дайджестам CTO** (строки сам не открывал): `atlas:217` — открыл, совпадает; `owner-scope:48` и `transport:71` — открыл, совпадают; `remediation:18`/`:261` — открыл, совпадают; `gui-service:53`/`:262` — открыл, совпадают (`:262` — Task 3.3); `device-tree-recipe:220-223`, `AuthManager` в `app.py:560-603`, `observability-dx:16-17`/`:42`, `k0-framework-quality:52` — не открывал.
- **C-82:** условие «≤ 1,5 с в 6 из 6» — число CTO; решения владельца по C-82 (что меряет S5, прерывать ли `initialize()`) не приняты. Задачи в плане полосы Ф под C-82 нет — только строка реестра и вход inbox.
- **Размеры S/M/L** — суждение CTO, не подтверждено; у Ф9.0 — оценка менеджера.
- **Пути новых файлов** (`backend_ctl/cli.py`, `base_manager/command_specs.py`, тест-файлы, `scripts/lint_test_sleep.py`) — предложение; стадия 0 каждой задачи их утверждает. Пилотная семья Ф9.7 названа по вердикту №1 (`stats`/`state_store`), менеджер-владелец в коде не найден мной.
- **«Пять дней зелёного `main`»** — число CTO, не замер; ось 3 зависит от полос-владельцев красных.
- **Полоса М** закрыта ORDER §1 п. 5 — Ф9.22–Ф9.24 без слова владельца не стартуют.
- **Строка `camera-device-service` в прогресс-блоке ORDER** отсутствует при «устаревших строк 0» (CTO) — не разбирал.
- Файл разделён на два (лимит хука 32 KB против ~28 KB заказа); `plans_progress` файлы `f9-*` не читает (читает `phase-*.md`, `tasks*.md`, `tasks/`) — задачи считаются только по строкам в `plan.md`.

## Предложение в очередь

Текст для координатора (ORDER.md правит только он):

```
| 45 | [2026-07-06_constructor-master](../2026-07-06_constructor-master/plan.md) | F9-0 | 2.0 · Ф9 «фундамент выше 8» (решение владельца 2026-11-01: все 7 осей, фазой мастер-плана). Сейчас без писателя: F9-0 замер базы (haiku), F9-1 гигиена каталога, F9-23 шаг 1; решения W1–W5 (`f9-foundation-above-8.md`, «Ворота»). Код — после 6а и camera 1.3/1.4; `process_module` — один писатель (F9-2 → F9-7 → F9-19 → F9-8). Связи: строки 6а, 14, 14а, 22, 31, 36, 38, 44 |
```
