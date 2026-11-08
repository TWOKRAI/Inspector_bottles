# Handoff: Атлас — волна 1 влита в локальный main (9 из 27)

Дата: 2026-11-08. План: `plans/2026-11-06_atlas-passport/plan.md` (ветка `docs/atlas-reports`, worktree `.claude/worktrees/atlas-passport`).
Предыдущий handoff: `docs/handoffs/2026-11-08_atlas-passport-stage0-r2-fixes.md`.
Для кого: следующая сессия лида (новый чат). Пуш в `origin` — только владелец; ничего не запушено.

## Состояние

Локальный `main` = `17281dfa4`. Влито (merge-коммиты, порядок слияния):

| Task | merge | что |
|---|---|---|
| 0.1 | `9456632b8` | `Services/camera_device` в `modules.yaml` |
| 1.1 | `7fec56a80` | `nav_bench` в `main` |
| 4.4 | `35e68f3d5` | `purpose` в докстрингах 57 юнитов |
| 7.1b-validate | `1b508049c` | сервис без `DECISIONS.md` красный в `validate.py` (база 7 имён) |
| 7.1a | `3d269915d` | трейлер `Decision:` в валидаторе коммитов |
| 7.1b | `a23c73279` | `## Итог` при `close`, словарь статусов, FROZEN |
| 7.1c | `13403b45c` | гайд трейлеров, шаблон ADR, `/dev:adr` |
| 6.2 | `2d663a497` | шапки FREEZE `views/brief/metrics`, строка про FACTS |
| 7.2 | `17281dfa4` | `nav_bench`: клон с историей, `bash_allow`, аудит Bash (`bash-meta` и др.) |

`plan.md`: 9/27 DONE (коммит `84d037e86`, 16281 из 16384 байт). Статусы выставлены вручную (`[DONE]`).

## Правила владельца этой сессии (память `.claude/memory/feedback_cto_spawn_explicit_fable.md`)

- Express-ревью задачи — `reviewer` + `model: "opus"`. Merge gate — `reviewer` + `model: "sonnet"` (пробное слияние в своём scratch-worktree). `cto` (Fable) — только в тяжёлых случаях. План и прежний handoff пишут «CTO merge gate» — читать как «reviewer sonnet gate».
- Запущенных агентов не останавливать без прямого слова владельца.
- Живой `claude -p` и любые траты — только по слову владельца.
- Параллельным агентам — свой каталог `scratchpad/own_<task>/` (память `feedback_parallel_agents_need_own_scratch_dir.md`).
- Каждому агенту-писателю бриф по форме `.claude/plugins/dev/templates/executor-brief.md` (DESIGN / FILES / REDS / REPORT), иначе `lint-brief` отклонит spawn.

## Ждёт слова владельца

1. **В4** — потолок $7 для Task 1.2 (замер C0 и Kill-1). 1.2 теперь свободна по зависимостям (1.1 и 7.2 влиты), стоит из-за денег.
2. **Kill-1 при 6 из 8** — умолчание лида «слово владельца».
3. **В2** — судьба старого плана `plans/2026-10-04_atlas` (срок 2026-11-10; Task 6.1 не раньше этой даты).
4. **В9** — `sessions/`.
5. **Живая проверка 7.2** (центы, `--max-budget-usd 0.2`, haiku): не проверено без неё, каким shell CLI исполняет Bash, пропускает ли CLI формы `$'…'` по шаблону `Bash(git grep *)`, действует ли `--setting-sources user` на CLAUDE.md.
6. **`uv sync --inexact`** — владелец вручную, основное дерево, окно `quiet`, до Task 2.1. Без `grimp` красные `test_fixed_brief_exits_zero` и `test_card_on_origin_main_pin` (красные и на main).
7. **CI**: тест `scripts/tests/test_validate_services_decisions.py` не попадает в GitHub CI (корневые `testpaths` там не гоняются; `ci.yml` вызывает `run_framework_tests.py` и явные пути), красит только локальный `make gate`. Шаг `validate.py` в CI красный из-за двух ошибок памяти (теги, BY-MODULE). Нужна ли запись в `docs/claude/OPEN_QUESTIONS.md` и шаг CI — решает владелец; нужна ли запись про `index --check` в локальном гейте — тоже.
8. Заготовка «Итога» для плана `2026-10-26_recipe-save-noise` (24/24, locked): после 7.1b он не закрывается ни `close`, ни `doctor --fix`, пока нет `## Итог`.

## Следующие задачи (без денег)

- **4.4b** — `modules.yaml` → корни + исключения (Д5 шаг 2), после 4.4. Формат зафиксирован в `scripts/atlas/DECISIONS.md` («Дополнение Task 4.4 (Д5)»): `roots: [{path, layer, id_prefix}]`, `root_exclude: [tests, _shared]`, `tiers`. Пока `purpose` лежит и в yaml, и в докстринге; истина — yaml; разовый скрипт сверки `scratchpad/purpose_to_docstring.py` в репо не попал — в 4.4b нужна проверка.
- **Новая задача (предложение, в план не внесена):** выровнять 14 ссылок на несуществующий `docs/claude/DECISIONS/` (`ADR.template.md:51`, `PROJECT_CONTEXT.template.md:14,59`, `sync-context.md:70` ×2, `_stack.md:169`, `aggregate_context/README.md:167` ×2, `render_adr.py:12` ×2, `module-contract/SKILL.md:223` ×2) и описания `Risk/Reversible/Tested` как «необязательных» в `agents/dev/teamlead.md`, `commands/dev/pipeline.md`, `docs/claude/TOOLING_NOTES.md`.
- Заблокированы: 2.1 (`uv sync`), 3.1/4.1–4.3/5.1 (цепочка от 1.2, 2.2, 4.2a), 6.1 (не раньше 2026-11-10), 6.2a/b/c (после 6.1; kill №2), 6.3 (слово В2), 7.2b (деньги, живой прогон), 7.3 (после 2.2 и 7.2b).

## Что решено по ходу и важно помнить

- `STRICT = False` в `validate_commit`. При включении правило «`Decision:` id не найден в индексе» и «не по форме» станет отказом (README: «warning (error in STRICT)»), а DESIGN п. 4 говорил «не отказ». Решать при включении `STRICT`.
- Аудит Bash 7.2: белый список `bash-meta`; ложные TAINTED на `HEAD^{tree}`, `HEAD@{1}`, `class.*Router` без кавычек, `dir/*.py` без кавычек, `src\gui.py`; прежний `bash-chain` на `|` в кавычках (36 % реальных команд). Долю на haiku покажет 7.2b. Проверка вывода Bash (N1) вне 7.2: `git log -p`, `git grep x HEAD` покажут файлы из `exclude`.
- `scripts/atlas/DECISIONS.md` 85 КБ при пороге 32 КБ; README `nav_bench` раздел «Раунд 2» 10,8 КБ при бюджете 8 КБ — предупреждения doc-size-guard, не блокируют.
- В 6.2 литералы шапок `views` и `metrics` короче, чем в `tasks/6.2.md` (E501); `tasks/6.2.md` не правился (16 байт до лимита 8192). Шапка `views`: «card, pack: помощники brief.py (CLI — 6.2a)».
- Весь `scripts/plans_progress/tests` на `main`: один красный `test_acceptance_deps.py::test_p8_real_tree_…` (`DEP_UNKNOWN 2026-10-27_system-run-state:2.2`), красный и до наших правок.
- `.claude/plugins/.seed-manifest.json` расходится с файлами (140 из 388 записей) ещё на старом `main`; читает его только внешний `claude-kit`.
- Lint заголовков коммитов: предупреждение «subject longer than 72» у нескольких коммитов — совет, не отказ.
- Невыполненное из прежнего handoff: артефакт v6.

## Уборка (по слову владельца)

Worktree и ветки волны 1 (все слиты; `git worktree remove` + `git branch -d`):
`atlas-4-4` (`feat/atlas-purpose-docstrings`), `atlas-6-2` (`feat/atlas-freeze-headers`), `atlas-7-1a` (`feat/atlas-decision-trailer`), `atlas-7-1b` (`feat/atlas-ledger-itog`), `atlas-7-1b-v` (`feat/atlas-validate-decisions`), `atlas-7-1c` (`feat/atlas-decision-docs`), `atlas-7-2` (`feat/atlas-nav-bench-clone`), `atlas-nav-bench` (`feat/atlas-nav-bench-merge`).
В `atlas-7-2` лежит неотслеживаемый `docs/reviews/2026-11-08_task-7.2-developer-r2.md`; в каждом из worktree есть свои `docs/reviews/*developer*.md` — по желанию добавить в историю отдельным коммитом.
Висячие объекты временных коммитов проверяющих (`git gc` уберёт). Каталоги `scratchpad/own_*`, `hookrepo71a_*`, `gate71c_*` вне репо: проверяющие не смогли удалить (`rm -rf` запрещён).

Незакоммиченное в главном checkout (`/Users/twokrai/Project_code/Inspector_bottles`, ветка `main`), моё: `.claude/memory/MEMORY.md`, `.claude/memory/feedback_cto_spawn_explicit_fable.md`, новая `.claude/memory/feedback_parallel_agents_need_own_scratch_dir.md`. Не моё (не трогать): `docs/reports/2026-10-26_stage0-eval.md`, `plans/robot-protocol-v2/tasks/T5.4*`.

## Таблица агентов (agentId; использовать SendMessage только для живых; все закончили работу)

| Роль | agentId | заметка |
|---|---|---|
| 7.2 автор правок F1' и матрица | `a3bd495c29b65ff0a` | developer Sonnet |
| 7.2 teamlead (bash-meta) | `a840738a30d197e4a` | Opus |
| 7.2 ревью р.1–2 | `aa0d2a23da72fcef3` | Opus |
| 7.2 gate Opus / проверка F2 | `a7605e2dc384908f1` | ~150k |
| 7.2 gate Sonnet | `a19de2e23761c9e1b` | |
| 7.1a автор | `a1e745ff92293d0a9` | |
| 7.1a ревью | `ae49f7f12c3b26ac4` | |
| 7.1a gate Opus | `a4b7139162dcf7f9d` | |
| 7.1b автор | `a113dddb2fb396261` | ~210k |
| 7.1b ревью / gate Sonnet | `a45b17bf0f065e5d3` / `a8a619a8202e612af` | |
| 7.1b-validate автор | `a9810d7232f698d74` | |
| 7.1b-validate ревью / gate Opus | `a8cbc56776a734bcc` / `ac3cb15368734845f` | |
| 7.1c автор | `aa6c4818b83aeab87` | |
| 7.1c ревью Opus / gate Sonnet | `a548ca227647d7f6e` / `a54a2b55cb5f02a81` | |
| 4.4 ревью / gate Opus | `acc8e89e71375d47f` / `aaba1dcd5f247e28c` | |
| 6.2 ревью р.1 / р.2 / gate Sonnet | `a8607928d42a18b6b` / `a367a9f2426c0f2c5` / `aa4610c891467b0bb` | |

Агенты-писатели 4.4, 6.2, 7.1b-validate, 7.1b — все закончили; для новых задач брифуй свежих.

## Что оставил открытым / ненадёжным

- Все числа выше — из отчётов агентов и моих запусков в этой сессии; полные прогоны (`make gate`, весь `scripts/atlas/tests`) не делались.
- Статусы DONE в `plan.md` выставлены вручную, строки `Итог` по задачам не записаны.
- Слияния сделаны в локальный `main` без пуша; запуск CI на них не проверялся.
