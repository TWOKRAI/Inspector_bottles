# O1 — Источники знаний, дубли, устаревание

Репо: main, HEAD 03952a020, 2026-10-04. Только чтение. Числа из команд (`git ls-files`, `git log`, `cmp`, `comm`, pytest `--collect-only`). Скрипты: `scratchpad/stale.py`, вывод `scratchpad/stale_out.txt`. graphify MCP не запускал: вопрос структурный, хватило git.

## 1. Инвентарь: виды артефактов знания

Читатели: **S** = грузится в каждую сессию, **A** = агент по требованию, **H** = владелец/разработчик, **M** = машина (хук/скрипт/CI).

| Вид | Кол-во (tracked md/файлов) | Кто пишет | Как создаётся | Кто читает |
|---|---|---|---|---|
| `~/.claude/CLAUDE.md` + `rules/context7.md` | 2 файла, 6,2 КБ | владелец | руками | S |
| Корневой `CLAUDE.md` | 1 файл, 194 стр., 25,3 КБ | владелец + агенты | руками | S, H |
| `.claude/CLAUDE.md` | 1 файл, 390 стр., 30,0 КБ | владелец + агенты | руками | S |
| MEMORY.md (индекс, копия A) | 1 файл, 107 стр., 29,9 КБ | агент (auto-memory) | руками агента, dual-write | S |
| Память: A `~/.claude/projects/<hash>/memory` | 418 файлов, вне репо | агент | руками агента | A (по триггеру из индекса) |
| Память: B `docs/claude/memory` | 431 файл, tracked | агент (dual-write) | руками агента, копия A | A, между машинами |
| Память: C `.claude/memory` | 36 файлов, tracked | агент (Mac) | руками | A |
| Agent-memory `.claude/agent-memory/<роль>` | 118 файлов (teamlead 39, tester 26, developer 21, cto 12, investigator 12, tech-writer 4, manager 3, debugger 1) | сами роли | авто-память роли (CC) | A: подгружается в промпт роли |
| `.claude/plugins/<id>/` источники | 225 md; 24 плагина | владелец | руками (источник) | M (compose/sync) |
| `.claude/{agents,commands,skills}` зеркала | agents 15, commands 77, skills 20 файлов | скрипт sync | материализация из plugins | S (skills-описания), A |
| `.claude/modes`, `.rules/` | modes/*.md, `.rules` 8 файлов | владелец | руками | A (path-scoped) |
| `docs/claude/*` (без memory) | 37 файлов (13 + `frozen/` 24) | владелец | руками | A, H |
| `docs/reviews` | 364 файла | reviewer | агент пишет отчёт | H, A (редко) |
| `docs/sessions` | 106 | `/wrap-up` | руками команды | A (новая сессия: «последний лог») |
| `docs/handoffs` | 77 | lead-агенты | руками | A (первым делом) |
| `docs/audits` | 42 | агенты | руками | H |
| `docs/maps` | 4 (`crop`, `layer_render`, `line_sim_tools`, `transport`) | агент по подсистеме | руками | A |
| `docs/diagrams` | 9 файлов: 2 `.mmd` (2026-05-14), 3 `.html`, 3 `.gitkeep` | руками; `make diagrams` для classes/deps | смесь | H |
| `docs/direction` (living spec), `docs/refactors` 13, `docs/decisions` (1 README), `docs/plans` 7 | 4 / 13 / 1 / 7 | spec-writer / агенты | руками | H, A |
| `multiprocess_framework/docs` | 38 (21 верхнего уровня + `archive/` 12 + `observability/` 5) | владелец + агенты | руками; `ADR_REGISTRY.md` скриптом | A, H |
| Пер-модульные `README/STATUS` (framework) | README ~69, STATUS 41 (по модулям 27) | developer | руками при задаче | A, H |
| `DECISIONS.md` (ADR) | 41 файл, 496 заголовков `ADR-*`; корень `multiprocess_framework/DECISIONS.md` 149 | developer/tech-writer | руками; разделы «Оглавление/Модульные решения/Устарело/Коды» — `scripts.sync` | A, H |
| `interfaces.py` | 45 | developer | код | M, A |
| `plans/` | 459 md: 61 активных, `_archive` 177 md | manager/агенты | `/dev:plan`; `plans_progress` читает | A, H |
| `plans/queue/*` | 5 md + baseline | lead | руками (ORDER.md 2026-10-04) | A, H |
| Граф graphify | `graphify-out/` **в `.gitignore`** (`.gitignore:122`) | хук | post-commit `graphify update .` (локальный `.git/hooks`) | A (MCP) |
| Индекс qex | вне репо, сейчас DOWN | хук | post-commit, при живой Ollama | A |
| Git-хуки | `.git/hooks/{commit-msg,pre-commit,post-commit,pre-push}` **не tracked** | `install_hook.sh` | установка вручную | M |
| Хуки сессии | `.claude/settings.json`: 6 SessionStart, 6 PreToolUse, 3 PostToolUse и др. | compose из `plugin.json` | генерация | M |

Вывод по §1: из этих видов **tracked и воспроизводимы в облачном клоне** — только то, что в `git ls-files`. Не едут в клон: память A (418 файлов), граф, индекс qex, `.git/hooks`, venv.

Загрузка в каждую сессию: 25 320 + 29 958 + 4 887 + 29 881 + 1 267 = **91 313 байт** (команда: `wc -c` по пяти файлам). Это только то, что грузится автоматически; MEMORY.md сам по себе 29,9 КБ.

## 2. Дубли: факты в 2+ местах (с цитатами)

**D1. Число модулей фреймворка. Расходятся.**
- `CLAUDE.md:18`: «Всего модулей … 27».
- `CLAUDE.md:30`: «Конструктор-blueprint фреймворка (25 модулей)» — в том же файле.
- `multiprocess_framework/docs/MODULES_OVERVIEW.md:3`: «короткая карта 25 модулей».
- `multiprocess_framework/MODULES_STATUS.md:3`: «Сводка по 27 модулям»; `MODULE_TIERS.md:19`: «Карта (27 модулей)»; `CONSTRUCTOR_BLUEPRINT.md:45`: «27 модулей, 12 слоёв».
- Факт: `git ls-files 'multiprocess_framework/modules/*/__init__.py'` → 28 пакетов, из них `tests` не модуль, значит 27. `MODULES_OVERVIEW.md` не упоминает `app_module` и `telemetry_readmodel_module` (grep).
- Контракт-тест сверяет только `MODULE_TIERS.md`. Остальные четыре места — вручную.

**D2. Правило «Layer: обязателен». Документы расходятся, хук молчит.**
- `CLAUDE.md` («Обязательны: `Why:` и `Layer:`. Без них hook отклонит коммит»); `.claude/modes/_stack.md:27-29` («`Layer:` — оба обязательны … хук отклонит коммит»); `docs/claude/COMMIT_GUIDE.md:16` (`Layer: framework | services | plugins | prototype | …`); `.gitmessage:16` (тот же enum).
- `.claude/COMMIT_GUIDE.md:31`: «`Layer:` — если `.claude/commit-layers.txt` непустой».
- `.claude/commit-layers.txt` в репо — **только комментарии** (`git show HEAD:.claude/commit-layers.txt | grep -v '^#'` → пусто). `validate_commit.py:566-585`: пустой файл ⇒ «`Layer:` is OPTIONAL». `DEFAULT_LAYERS` (`validate_commit.py:64-74`) = `app, lib, tests, docs, scripts, infra, build, ci, mixed` — другой enum.
- Воспроизведение: сообщение `feat(x): test\n\n- a\n\nWhy: because` → `validate_commit.py <file>` → **exit=0**. Хук Layer не требует и значения не проверяет.
- Но последние 200 non-merge коммитов: Layer 200/200, Why 200/200, Refs 200/200 (скрипт по `git log`). Дисциплину держат агенты по промпту, а не хук. Три документа утверждают enforcement, которого нет.
- Два файла `COMMIT_GUIDE.md` (`.claude/` 230 стр. и `docs/claude/`, 230 стр.) разные: `.claude` версия — seed-шаблон (последний коммит 2026-05-26), `docs/claude` — проектная (2026-05-14).

**D3. Где живёт память. Три «канонических» ответа.**
- `CLAUDE.md:98-108`: dual-write в `~/.claude/projects/<hash>/memory` **и** `docs/claude/memory`; «на Windows пишем в Windows-папку».
- `.claude/CLAUDE.md:372`: «**Canonical path:** `.claude/memory/` (project-local, git-tracked)».
- `MEMORY.md` (копия A): «Три уровня»… индекс на 418 файлов в A.
- Факт: C (`.claude/memory`) содержит 36 файлов, и его `MEMORY.md` начинается «Status: empty by design» при 87 строках (`head -12 .claude/memory/MEMORY.md`). Каноническим назван тот, который почти пуст.

**D4. Где лежат ADR. Три дома.**
- `CLAUDE.md` (правило 3): локальные `modules/X/DECISIONS.md`, глобальные `multiprocess_framework/DECISIONS.md`.
- `.claude/plugins/dev/commands/adr.md:2,26,42`: команда `/dev:adr` пишет в `docs/claude/DECISIONS/NNNN-<slug>.md`. Каталога **нет** (`ls docs/claude/DECISIONS` → No such file).
- `docs/decisions/README.md:7`: «`docs/decisions/NNNN-kebab-case-title.md`». В каталоге один README.
- Факт: 496 ADR-заголовков в 41 `DECISIONS.md`. Дубли ID внутри файлов: `ADR-PM-038`, `ADR-PMM-020`, `ADR-PMM-021` (каждый заголовок встречается 2–3 раза).

**D5. Куда класть планы. Глобальные правила против проекта.**
- `~/.claude/CLAUDE.md` «Plans Hierarchy»: `workspace/plans/`, `apps/{app}/plans/`, `projects/{slug}/plans/`.
- `.claude/CLAUDE.md:272`: «Plans (workspace/plans/, apps/*/plans/, projects/*/plans/) — Russian».
- `CLAUDE.md:90`: «Хранение: `plans/<slug>.md` или `plans/<slug>/plan.md`».
- Факт: `workspace/plans` не существует; `apps/` содержит один `__init__.py`; реальные планы: `plans/` 459 md, `multiprocess_prototype/plans` 26, `docs/plans` 7. Три места под планы, два набора правил.

**D6. Стек-версии. Заявлено, объявлено и стоит — три разных.**
- `CLAUDE.md:48`: «PyTorch 2.11 + Ultralytics»; `pyproject.toml:91,98`: `torch>=2.11`.
- В `.venv` стоит `torch-2.6.0+cu124` (`ls .venv/Lib/site-packages | grep torch`); память `project_cuda_torch_setup.md` предписывает cu124-колесо. Заявленное `>=2.11` с этим колесом не совместимо по версии.
- `CLAUDE.md:45` «PySide6 6.10» согласуется с `.venv` (6.10.3) и `TECH_STACK_2026.md:21` (пин `<6.11`). Здесь дубль сходится, но три места (`CLAUDE.md`, `README.md:46`, `pyproject.toml`) держат его независимо.
- Ограничение: проверил `.venv` на этой машине, не CI.

**D7. Стартовая точка для новой сессии. Устарела, но размножена.**
- `MEMORY.md:7` (копии A и B): «Новая сессия начинает отсюда: `docs/sessions/2026-09-07_handoff-parallel-start.md`».
- Факт: файл есть, последний коммит 2026-09-07; новейшие хендоффы — `docs/handoffs/2026-10-03_plans-progress-lead.md`, `…transport-f5-lead*.md`. Указатель отстаёт на 26 дней и размножен двумя копиями.

**D8. Test-counts в STATUS. Дрейфуют от кода.**
- `config_module/STATUS.md`: «49 тестов» — `pytest --collect-only` → **121** тест.
- `command_module/STATUS.md`: «34 теста» → **46**.
- `message_module`, `event_module`, `state_store_module` числа не заявляют (211 / 9 / 691 собрано) — там дрейфа нет, потому что числа нет.

**D9. Один и тот же файл в трёх копиях памяти.** См. §4.

**D10. Правило qex-freshness.** В `CLAUDE.md` («Сверка свежести — ПЕРВЫЙ шаг»), в `.claude/CLAUDE.md` (standing rules #1), в `project-rules/SKILL.md`, в памяти (`feedback_check_qex_freshness_before_use.md`). Четыре места. Здесь расхождения не искал; риск расхождения есть, но тексты я не сравнивал построчно.

## 3. Устаревание: документ против кода (измерено)

Метод (`stale.py`): для модуля — дата последнего non-merge коммита по `README.md|STATUS.md` и по `.py` без `tests/`; лаг = дата кода − дата дока. Выборка: **44 модуля** (27 framework + 17 Services). Plugins не вошли: их `README` лежат на глубине `Plugins/<группа>/<плагин>/` (скрипт ищет глубину 2). Все 27 — `ls-files`, не выборка.

| Группа | n | медиана, дн. | среднее | 0–7 дн. | 8–30 | 31–90 | >90 |
|---|---|---|---|---|---|---|---|
| framework | 27 | 7 | 31,3 | 14 | 3 | 7 | 3 |
| Services | 17 | 1 | 20,2 | 10 | 2 | 5 | 0 |
| всего | 44 | 5,5 | 27,0 | 24 | 5 | 12 | 3 |

Худшие: `config_module` 154 дн. (док 2026-04-30, код 2026-10-01), `command_module` 128, `dispatch_module` 128, `worker_module` 87, `hikvision_camera` 85, `console_module` 76, `modbus` 62, `auth`/`sql` 52.
Лаг — это не косметика кода: после 2026-04-30 в `config_module` было 22 кодовых коммита (2254 изменённых строки), в `dispatch_module` 19 (3257), в `worker_module` 9 (1903) (`git log --numstat --since=<дата дока>`).
Ограничение: часть кодовых коммитов — масс-правки (кодмод логгера «98 файлов», ruff). Поэтому лаг по дате завышает дрейф там, где код менял только формат. Для `config_module` есть и содержательные: `feat(shm)`, `feat(router)`.

Устаревание по другим видам (дата последнего коммита):
- `docs/diagrams/architecture.mmd`, `modules-overview.mmd`: 2026-05-14 (**143 дня**). `multiprocess_framework/docs/DIAGRAMS.md` 2026-05-07; `GLOSSARY.md`, `MODULE_README_TEMPLATE.md` 2026-04-30 (157 дней).
- `MODULES_OVERVIEW.md` 2026-08-12 (53 дня) — уже без двух модулей (D1). `MODULES_RESPONSIBILITY_MAP.md` 2026-08-24.
- `docs/maps/*` (4): 2026-10-02/03. Свежие, потому что их пишут вслед за подсистемой руками. Покрывают 4 подсистемы из 27+17 модулей.
- `plans/queue`: ORDER.md 2026-10-04, остальные 2026-09-29…10-01.
- Сгенерированное держится: `python -m scripts.sync --check` → **exit=0** (без дрейфа) для трёх секций ADR. Это единственный вид, где автоматика доказана живой.
- `scripts/docs_verify` (19 проверок) покрывает только документацию наблюдаемости; остальные 2/3 документов проверки не имеют.

## 4. Память: три копии

Пути: A `C:/Users/INNOTECH/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory` (418), B `docs/claude/memory` (431), C `.claude/memory` (36). Команда: `ls | sort` + `comm`.

| Пара | в обеих | только в первой | только во второй |
|---|---|---|---|
| A и B | 416 | 2 (`reference_gpu_monitoring_windows.md`, `user_career_goal.md` — по правилу «личное») | 15 (напр. `project_qex_model.md`, `feedback_agent_hard_budget_is_off_by_default.md`, `feedback_background_reviewer_loses_the_verdict.md`, `feedback_spawn_child_inherits_parent_sys_path.md`, `project_work_order_2026_09_22_line_sim_then_pult.md`) |
| A и C | 3 | 415 | 33 |
| B и C | 14 | 417 | 22 |
| во всех трёх | 3: `MEMORY.md`, `feedback_always_latest_models.md`, `feedback_explicit_model_per_agent_role.md` | | |

Правило dual-write нарушено уже в обе стороны: 15 файлов есть в B и нет в A (написаны на другой машине или только в git). 22 файла из C нет ни в A, ни в B (ещё 11 есть в B, но нет в A): `feedback_cto_spawn_explicit_fable.md`, `feedback_merge_commit_needs_feat_type.md`, `feedback_injection_scripts_on_committed_code.md` и др. Эти уроки видит только Mac-копия.

Содержимое 416 общих файлов A/B (`cmp`, затем `diff` после `tr -d '\r'`):
- побайтно равны: 160;
- различаются только CRLF/LF: 100 (`core.autocrlf=true`);
- реально различаются: **156** (`CRAFT.md`, `ARCHIVE.md`, `MEMORY.md` и др.). Образцы: `feedback_fewer_layers.md` — в A лишние `metadata: node_type: memory`, `originSessionId`; `feedback_framework_first.md` — другой `name:` и кавычки в `description:`. То есть, в основном frontmatter, который дописывает харнесс, а не смысл. Содержательную разницу в теле посчитать за 156 файлов построчно не успел.
- `MEMORY.md`: A 107 стр., B 122 стр., C 87 стр.; 27 строк различий A/B после снятия CR. Для трёх общих файлов: `feedback_always_latest_models.md` и `feedback_explicit_model_per_agent_role.md` B=C, но A≠B и A≠C (18 и 14 строк у всех).
Вердикт: «синхронизация» — копирование руками; у копий нет ни одного места, где различие объявлено.

## 5. Классификация видов

GENERATE — выводится из кода/git, руками не писать. HAND+STAMP — суждение человека, обязателен штамп `verified_at: <SHA>` + `covers: <пути>`; расхождение `covers` с HEAD ⇒ «устарело» машинно. ARCHIVE — история, read-only, достижима по ссылке, из индекса сессии убрана. DELETE/MERGE — дубль.

| Вид | Класс | Основание (число из §1–§4) |
|---|---|---|
| Число модулей, таблицы модулей, ярусы (`MODULES_STATUS`, `MODULES_OVERVIEW`, `MODULE_TIERS`, карта в `CONSTRUCTOR_BLUEPRINT`) | **GENERATE** из `ls modules` + `__init__.py` + реестра ярусов | 25 против 27 в 5 файлах (D1) |
| Test-count, этап, оценки в `STATUS.md` | **GENERATE** (pytest collect + git) | 49→121, 34→46 (D8); лаг >30 дн. у 15 из 44 |
| `interfaces.py` → API-раздел README | **GENERATE** | код уже есть, README пересказывает |
| Оглавление/реестр ADR, «Коды модулей» | **GENERATE** (уже есть, `scripts.sync`, exit=0) | единственный доказанно живой генератор |
| Classes/deps диаграммы, `architecture.mmd`, `modules-overview.mmd` | **GENERATE** (pyreverse/pydeps/graphify), `.mmd` вручную — снять | 143 дня без правок |
| Граф, god-nodes, слайсы | **GENERATE**, хук post-commit; в клон не едет — пересобирать | `.gitignore:122` |
| Прогресс планов, статусы задач (`plans_progress`, `plans_ledger`) | **GENERATE** | чек-боксы в планах врут, шапки врут |
| Стек-версии в `CLAUDE.md`/`README.md` | **GENERATE** из `pyproject.toml` + lock | D6 |
| `README.md` модуля: роль, границы, «почему так» | **HAND+STAMP** | суждение; штамп даёт «лаг» без чтения дат |
| `DECISIONS.md` (тела ADR), `docs/maps/*`, `docs/direction` | **HAND+STAMP** | решения/карты подсистем; maps свежие, потому что маленькие и штампуемые |
| Корневой и `.claude/CLAUDE.md`, `.rules/`, `project-rules` | **HAND+STAMP** + сжатие | 91 КБ в каждую сессию; D2/D3/D5 расходятся |
| `plans/queue/ORDER.md`, `decisions.md` | **HAND+STAMP** | решения владельца |
| Индекс памяти и уроки (`feedback_*`, `project_*`) | **HAND+STAMP**, одно хранилище | 3 копии, 156 реальных расхождений |
| Agent-memory (118) | **HAND+STAMP**, малый срок жизни; пересматривать при смене роли | пишут роли сами |
| `docs/reviews` 364, `docs/audits` 42, `docs/sessions` 106, `docs/handoffs` 77, `plans/_archive`, `multiprocess_framework/docs/archive`, `docs/claude/frozen` | **ARCHIVE** | отчёты на момент; из SessionStart-указателей убрать |
| `docs/handoffs` последний + `docs/sessions` последний | указатель **GENERATE** («самый новый по дате»), не пути в MEMORY.md | D7 |
| `.claude/COMMIT_GUIDE.md` или `docs/claude/COMMIT_GUIDE.md` | **MERGE** в один, Layer-enum из `commit-layers.txt` | D2 |
| ADR-дома `docs/decisions/`, `docs/claude/DECISIONS/` | **MERGE** в один + починить `/dev:adr` | D4 |
| Планы вне `plans/` (`docs/plans`, `multiprocess_prototype/plans`) и `workspace/plans` в глобальных правилах | **MERGE**/**DELETE** правило | D5 |
| `.claude/agents|commands|skills` зеркала | **GENERATE** (сейчас дрейфа 0: 14 agents, 73 commands, 20 skills равны источникам), но коммитить зеркало — дубль | `cmp` пройден; риск прежний |
| Копии памяти A/B/C | **MERGE** в одну tracked (B) + локальный кэш, без ручного `cp` | §4 |

## 6. Прочее, что нашёл по пути

- Зеркала `.claude/` сегодня идентичны источникам: agents 14/14, skills 20/20, commands 73/73 (`cmp`). Для commands 12 «пропавших» — это отключённый плагин `knowledge` (и `hello-world`) и `graph-slice` по другому пути; не дрейф. Риск остаётся структурным: правка в зеркале без источника не ловится ничем, кроме памяти агента.
- Git-хуки (`commit-msg`, `pre-commit`, `post-commit`) лежат в `.git/hooks` и не в репо. В облачном клоне их нет, пока не запустить `scripts/validate_commit/install_hook.sh`. `post-commit` содержит два блока: graphify и qex. `pre-commit` — это `pre-commit`-фреймворк с ruff/pyright/bandit, документов не проверяет.
- `.claude/hooks/git/pre-commit-session-log.sh` ещё tracked, хотя `.claude/CLAUDE.md` пишет «the pre-commit hook was removed on 2026-10-03». Осиротел.
- `scripts/aggregate_context` ждёт `CONTEXT.md` в каждом модуле; их нет; SessionStart-хук `session-project-map.sh` читает `docs/PROJECT_CONTEXT.md`, которого тоже нет. Хук молчит (по комментарию: «neither → silent»).

## Что я не доделал и чему не верить в этой работе

- Plugins (13 групп) не вошли в замер лага: скрипт не нашёл README на нужной глубине. Цифры §3 — framework и Services.
- Даты коммитов завышают лаг при масс-правках кода и занижают его, если док тронули косметикой (масс-реформат 2026-10-03/04). Я исключал масс-коммиты только в колонке «nomass» (>30 файлов) и не использовал её в итоговом распределении: у 5 модулей она пуста.
- 156 реальных расхождений A/B памяти разобрал на двух образцах и на `MEMORY.md`; остальные — неизвестного характера (скорее frontmatter, не проверено).
- D6 (torch) проверен по `.venv` одной машины, не по lock-файлу и не по CI.
- D10 (qex-правило в 4 местах) не сравнивал построчно.
- Не проверял, какие из 24 плагинов реально включены в `enabled.yaml`; «24» — число каталогов `.claude/plugins/*`.
- Не измерял токены, только байты; «91 КБ» не равно токенам (кириллица токенизируется иначе).
- graphify MCP не пробовал, потому что вопросы инвентаря и дрейфа решались git.

## Вопросы владельцу (с рекомендациями)

1. **Одна память или три?** Рекомендую: единственный источник — `docs/claude/memory` (tracked), A как кэш Claude Code, копировать скриптом с diff до записи; личное (`user_*`, `reference_gpu_*`) — в `.gitignore`-подкаталог. Ручной dual-write убрать.
2. **Layer: обязателен или нет?** Рекомендую: решить в `commit-layers.txt` (положить 9 слоёв из `_stack.md`), хук тогда начнёт реально отклонять; три документа с обещанием перестанут врать. Или убрать «обязательно» из документов.
3. **Какие виды переводим в GENERATE первыми?** Рекомендую три: таблицы модулей/ярусов (D1), test-count и «этап» в STATUS (D8), указатель «последний хендофф». Это закрывает 3 из 10 дублей без суждения человека.
4. **Что делать с 1024 md в `docs/` (reviews 364, sessions 106, handoffs 77, audits 42)?** Рекомендую: пометить ARCHIVE, не индексировать в SessionStart и qex-«горячем» слое, оставить достижимыми по ссылке из плана/коммита.
5. **Один дом для ADR и планов?** Рекомендую: ADR — `modules/X/DECISIONS.md` + глобальный `multiprocess_framework/DECISIONS.md` (как сейчас), починить `/dev:adr` и удалить `docs/decisions/`; планы — только `plans/`, глобальные правила `workspace/plans`/`apps/*` убрать из `~/.claude/CLAUDE.md`.
