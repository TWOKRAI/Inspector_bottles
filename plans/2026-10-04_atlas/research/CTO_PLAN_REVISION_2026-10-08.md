# Ревизия плана Атласа от CTO (Fable) — помощник брифа и справочник для всех агентов (2026-10-08)

Запрос владельца: «пусть Fable посмотрит план Атласа и внесёт все улучшения; придумает, как сделать Атлас
эффективным помощником брифа — можно менять форматы и механизмы; нужно, чтобы получилась полезная библиотека и
справочник для агентов всего проекта». CTO работал только на чтение, на `main` `2d7e9d8f6`; текст ниже — его ответ
(сокращены только повторы). Применение в `plan.md` — после слова владельца.

## 0. Что воспроизведено

- `pack k0-framework-quality#1.2` → «итог без разделов формы 0.7: …/1.1.result.md», хвостов 0. Итоги K0 пишут
  `**Не проверено:**`, парсер `_section` (`views.py:233–251`) принимает только `## Не проверено` или
  `**Не проверено.**`. Писатель и читатель разошлись в одном знаке; гейта нет.
- `python scripts/plans_ledger.py brief 1.6c --plan …/plan.md` → «missing field(s): TASK, ROLE, DESIGN, FILES, REDS,
  TESTS, OUT OF SCOPE». Генератор спавн-брифа из `tasks/<id>.md` уже есть (`plans_ledger.py:3098 build_brief`);
  брифы Атласа его форму не соблюдают.
- Хук `lint-brief.sh`: PreToolUse `Agent|Task`, только роли-писатели; файла брифа не видит.
- `tasks/1.6c.injections.json` — машинный формат инъекций уже есть: `{id, prop, file, old, new, forecast[]}`.
- `scripts/atlas/__init__.py` пуст: публичного API библиотеки нет, только CLI.
- Тёплый `card config_module` 11,1 и 9,1 с; `ref` 9,6 с; `pack` 0,5 с; `index` 0,35 с. В CI слово `atlas` — 1 раз, в
  комментарии: 197 тестов Атласа в CI не идут.
- `scripts/channel_map/channel_map.py` (AST: объявления/отправки/подписки, `--format json`) — готовый источник каналов.
- `hypothesis` в `.venv` нет. Находки: P1 29, P2 344, P3 2, P4 18, INTERFACE_WITHOUT_TEST 465, REF_MOVED 5 380,
  DONE_WITHOUT_COMMIT 1 570.

## 1. «Атлас как помощник брифа»

Принцип: факты генерируются, решения пишет человек; у каждого числа в брифе — команда, которая его дала; у каждого
читателя формата — тест против шаблона писателя.

```
строка плана → atlas brief <slug>#<id> → tasks/<id>.md (FACTS сгенерирован, DESIGN пуст)
→ лид пишет DESIGN / REDS / OUT OF SCOPE / TRAPS + tasks/<id>.injections.json
→ atlas lint-brief tasks/<id>.md  (форма, повтор команд, проверка инъекций, зонды)
→ стадия 0: reviewer MODE: plan — только дизайн и гонки, класс на каждое замечание
→ plans_ledger.py brief <id> → спавн tester/developer (уже с FACTS)
→ atlas inject run tasks/<id>.injections.json → observed в JSON
→ tasks/<id>.result.md (форма 0.7, гейт) → pack следующего брифа читает хвосты
```

**FACTS** (между `<!-- atlas:facts <sha7> -->` и `<!-- /atlas:facts -->`, строка `- <факт> — `<команда>` → `<литерал>``):
1. задача: строка плана, статус, модули, объект задачи — символ из текста, найденный в «Код модуля»;
2. FILES-кандидаты: файлы модуля по имени/символу из текста задачи, затем файлы прошлых задач по тем же модулям, тесты
   отдельно (сегодня `pack` даёт файлы последней задачи плана — неверно);
3. API: шапки `ref` + публичный код модуля; для объекта задачи — сигнатуры с `файл:строка`;
4. потребители объекта: код и тесты отдельно, `файл:строка`; обязательная строка «не видно статикой: getattr, реестры,
   patch по строке, каналы роутера»;
5. хвосты: «Осталось», «Не проверено», `NEEDS LEAD`, «Для следующего брифа» прошлых задач плана и тех же модулей;
6. находки модуля → готовые числа приёмки («INTERFACE_WITHOUT_TEST config 3→0»);
7. соседи: открытые задачи других планов на модуль + ветки, трогающие модуль;
8. радиус тестов: `pytest --collect-only -q <tests модуля>` → `N tests`.

**Пишет лид:** DESIGN, REDS, OUT OF SCOPE, TRAPS, ACCEPTANCE (числа с командой), `injections.json` (`old` дословно,
`forecast` — nodeid), для гонок — `probe: reports/<id>.probe.md` со скриптом.

**Механически до стадии 0 (`atlas lint-brief <file>`, хук зовёт ту же функцию):** форма; свежесть FACTS (sha маркера =
sha файлов модулей); повтор каждой команды FACTS/ACCEPTANCE по allow-list (`atlas`, `pytest --collect-only`,
`git grep -c`, `git log`, `wc -l`, `grep -c`) — литерал не совпал → красный; REDS: существующие nodeid собираются, новые —
в файлах FILES; `injections.json`: `old` найден в `file` на HEAD, `forecast` ⊆ REDS ∪ собранные; `probe:` существует.
Прогнать инъекцию до тестов нельзя; линт ловит классы «неверный факт», «инъекция не прикладывается», «гонка без зонда» —
по 1.2 р.1 это ~13 из 25.

**Стадии 0 остаётся:** дизайн, конкурентность, потребители вне статики, границы задачи. Отчёт ревью — строка
`- [<blocker|major|minor|nit>/<fact|dryrun|form|context|design|process|nit>] текст`, в шапке `Классы: fact N, …`;
`atlas lint-review` сверяет сумму.

**Форматы (ADR-ATL-004, задача 1.9d):** бриф — метки executor-brief + `FACTS` + `ACCEPTANCE` с командами; инъекции —
`tasks/<id>.injections.json` (`id, prop, file, old, new, forecast, observed, test`), в `result.md` — одна строка
summary; `result.md` — форма 0.7 только `## `-заголовками + `## Для следующего брифа`; отчёт ревью — классы; строка
плана — без изменений. Каждый читатель получает тест «шаблон → парсер → те же поля».

**Метрики вместо экзамена и суммы Q1 (`atlas metrics <slug>`):** M1 доля строк FACTS с командой `atlas`; M2
blocker+major раунда 1 по классам (цель: fact+form+dryrun → 0); M3 раундов до APPROVED; M4 коммитов с `Task:` после
DONE-хеша (бывший Q3); U1/U2 вызовов `atlas` и чтений `.py` на задачу по ролям — из журнала хука.

## 2. Справочник для всех ролей

- **Доступ:** писатели получают FACTS через спавн-бриф (`plans_ledger.py brief`); роли без брифа (reviewer,
  investigator, debugger, docs-writer, manager) — строка в их `.claude/agents/*.md` «перед чтением исходника модуля:
  `atlas ref M` и `card M`, цитируй `файл:строка`»; строка в `project-rules` `## Map`; SessionStart печатает ревизию
  реестра и `index --check`; CI — `index --check`, `check`, `lint-brief` на изменённых `tasks/*.md`. Библиотека:
  `scripts/atlas/__init__.py` экспортирует `card/ref/pack/brief/facts` (датаклассы), CLI — рендер, `--json` у каждого
  вида.
- **Доверие:** первая строка вывода — ревизия и сборка реестра; FACTS несёт sha; INDEX.md сверяется в CI; у каждой
  сущности `файл:строка`; честная строка «не видно статикой» закреплена тестом; «нет описания» вместо молчания.
- **Охват:** строки `modules.yaml` с `purpose` для `multiprocess_prototype/*` (только `card`/`ref`, правила ADR-175 вне
  охвата) и `scripts/{atlas,plans_progress,validate_commit,channel_map,memory}`; в `card` — «ADR модуля: N записей,
  последняя …» и «Уроки (N)» по frontmatter `module:`/`mechanism:` (1.4-lite без долга свежести).
- **Измерение:** PostToolUse на `Bash`/`Read` пишет `data/atlas/usage.log` (`ts, session, agent_type, вид`);
  `atlas metrics` считает U1/U2; kill-условие №2 плана — по журналу.

## 3. Строки плана (порядок = порядок исполнения; каждая — одна локальная сессия)

### 3.1 Скорость и CI

- Task 1.6e: кэш `ref`/`card` по ключу ревизии (выгрузка, griffe, grimp, rules в SQLite по sha дерева корней `modules.yaml`) и LF в выводе CLI на Windows; приёмка: тёплый `card config_module` ≤ 1,5 с на Windows (3 замера — литералы в итоге), `pytest scripts/atlas/tests -q` на Windows без красных по `\r\n` [IN PROGRESS] (облако, последняя облачная задача)
- Task 1.7a: job `atlas` в `.github/workflows/ci.yml` (ubuntu, `fetch-depth: 0`): `pytest scripts/atlas/tests -q`, `python -m scripts.atlas check --base origin/main`, `index --check`; тесты > 60 с — маркер `slow`, локально `-m "not slow"`; приёмка: job `success` на PR задачи, время локального `pytest scripts/atlas/tests -m "not slow"` на Windows — литерал в итоге (цель ≤ 8 мин), PR с правкой `.github/**` — разбор лидом до слияния [PENDING] (после 1.6e)

### 3.2 Помощник брифа

- Task 1.9a: хвосты без потерь — `_section` принимает `## T`, `**T.**`, `**T:**`; раздел `## Для следующего брифа`; `atlas lint-result <file>` + хук PostToolUse `Edit|Write` на `plans/**/tasks/*.result.md`; находка `RESULT_FORM` (warning) в `check`; тест «шаблон task-result.md → парсер → 7 разделов»; приёмка: `pack k0-framework-quality#1.2` печатает «Не проверено:» итога 1.1 (непусто) и 0 строк «итог без разделов формы 0.7»; `lint-result` на `1.1.result.md` до правки → exit 1 с именами отсутствующих разделов [PENDING] (после 1.7a; заменяет 2.3)
- Task 1.9d: ADR-ATL-004 — форматы без потерь: бриф (метки executor-brief + `FACTS`/`ACCEPTANCE` с командой у каждого числа), `tasks/<id>.injections.json` (`id, prop, file, old, new, forecast, observed, test`; таблица в `result.md` → строка summary), `result.md` только `## `-заголовками, отчёт ревью `- [sev/class]` + `Классы:`; шаблоны в `.claude/plugins/dev/templates/`; приёмка: reviewer `MODE: plan` APPROVED, у каждого формата назван читатель и тест-контракт, `validate.py` зелёный [PENDING] (после 1.9a)
- Task 1.9b: `atlas brief <slug>#<id> [--module M] [--symbol S] [--write|--check]` — блок FACTS (п. 1–8) между маркерами в `tasks/<id>.md`, `--check` код 1 при отставании от sha; `pack` для задачи без коммитов берёт файлы по имени/символу из текста задачи; блок «Соседи»; приёмка: для `k0-framework-quality#1.2` на пине `2d7e9d8f6` FACTS содержит `tools/watcher.py`, `tests/test_watcher.py`, потребителей `observability_reload.py` и `orchestrator.py` с `:строка`, ≥ 1 хвост 1.1 (литералы в тесте); у 100 % строк FACTS есть команда; `brief --check` после правки файла модуля → exit 1 [PENDING] (после 1.9d)
- Task 1.9c: `atlas lint-brief <file>` — форма, повтор команд FACTS/ACCEPTANCE по allow-list и сверка литералов, REDS, `injections.json`, `probe:`; `lint-brief.sh` получает режим файла и зовёт ту же функцию; приёмка: на брифе K0 1.2 ревизии `24a229e66` (после переноса чисел в FACTS формы 1.9d) линт называет ≥ 4 из 6 неверных чисел/строк (nit 1–4, 8, 9 отчёта `1.2.review-r1.md`) — литералы в тесте; на исправленном брифе exit 0 [PENDING] (после 1.9b)
- Task 1.9e: `atlas inject apply|run|revert|summary tasks/<id>.injections.json` — `old→new` в worktree, радиус из брифа, `observed`, откат `git checkout --`, пустой `git diff --exit-code` после; приёмка: на `1.6c.injections.json` (пин `857a0248f`) прогноз/факт совпадает с `reports/1.6c.injections_result.md` для ≥ 3 инъекций; `summary` печатает «N инъекций, совпало M, расхождений K» [PENDING] (после 1.9c)

### 3.3 Библиотека и доступ по ролям

- Task 1.10a: библиотека — `scripts/atlas/__init__.py` экспортирует `card, ref, pack, brief, facts, lint_brief` (датаклассы, без печати), `--json` у `card/ref/pack/brief` с правилом «ключи в конец»; `plans_ledger.py brief` и хуки зовут библиотеку; приёмка: контракт-тест ключей `--json`, `python -c "import scripts.atlas as a; print(a.card('config_module').api)"` печатает 3 имени, `wc -l scripts/atlas/__init__.py` ≤ 60 [PENDING] (после 1.9c)
- Task 1.10b: доступ по ролям и журнал использования — строка «сначала `atlas ref/card`» в `.claude/agents/{reviewer,investigator,debugger,docs-writer,manager,teamlead}.md`, строка в `project-rules` `## Map`, SessionStart печатает ревизию реестра и `index --check`, PostToolUse `Bash|Read` пишет `data/atlas/usage.log`; приёмка: `lint-agents` зелёный, после одного спавна reviewer в журнале ≥ 1 строка `atlas ref`, `usage.log` в `.gitignore` [PENDING] (после 1.10a)

### 3.4 Замер и гейт

- Task K0′: честный повтор замера — три следующих продуктовых брифа через `atlas brief` + `lint-brief` + отчёт ревью с классами; метрики M1–M4, U1/U2; база — брифы K0 1.1/1.2; приёмка: таблица «метрика — база — сейчас» по трём брифам; разморозка 1.4/1.5b/1.8 только при M2 fact+form+dryrun ≤ 2 на бриф и M3 ≤ 2 у ≥ 2 брифов [PENDING] (после 1.10b; старая строка K0 → [SUPERSEDED])
- Task 1.9f: `atlas metrics <slug>` — таблица M1–M4, U1/U2; приёмка: на `k0-framework-quality` печатает M2 для 1.2 = «major dryrun 2, form 1, context 1, design 2» после проставления классов в `1.2.review-r1.md` — литерал в тесте [PENDING] (после 1.10b)
- Task 1.7b: гейт 1.7 в минимальной форме — `check --baseline-init` одним коммитом лида, правило «число находок каждого warning-кода не растёт против базы» в job `atlas`, blocking на новом в диффе; приёмка: PR с классом фреймворка без явного наследования интерфейса → job красный с `P1_IMPL_NOT_INHERITING`; `baseline.txt` в `main`, число строк — литерал в итоге [PENDING] (после 1.7a, K0′)

### 3.5 Шире статики и охват

- Task 1.6d: каналы роутера в `card`/`ref`/`brief` — блок «Каналы: объявляет / шлёт / подписан» импортом `scripts/channel_map`, `?` для динамических; приёмка: `card process_module` на пине печатает ≥ 1 канал с `файл:строка`, честная строка «не видно статикой» теряет слова «каналы роутера» [PENDING] (после 1.9b)
- Task 1.10c: документы в карточке — «ADR модуля: N записей, последняя <заголовок>» из `DECISIONS.md`, «Уроки (N)» по frontmatter `module:`/`mechanism:` `docs/claude/memory/`; приёмка: `card config_module` печатает число ADR = `grep -c '^## ADR-' …/config_module/DECISIONS.md` и ≥ 1 урок с `module: config_module` [PENDING] (после 1.6d)
- Task 1.10d: охват `modules.yaml` — строки с `purpose` для `multiprocess_prototype/*` и `scripts/{atlas,plans_progress,validate_commit,channel_map,memory}`; приёмка: 0 путей `git ls-files '*.py'` вне `tests/` с модулем `other` среди этих каталогов, `atlas index` ≤ 220 строк, `card scripts/atlas` работает [PENDING] (после 1.10c)
- Task 1.7c: остальные гейты 1.7 — `PRE_POST_MISSING` на изменённых интерфейсах, `Refs`/`Task` на несуществующее, DONE-хеш не в `main`, `check --changed` в `pre_report_gate.py`; приёмка: как в прежней строке 1.7 [PENDING] (после 1.7b; прежняя 1.7 → [SUPERSEDED])
- Task 1.6f: карта с прогона тестов (coverage dynamic contexts) ночным job CI → артефакт → честное «тестов N» [DEFERRED] (после 1.7c)

Прочее: 2.3 → `[SUPERSEDED]` (1.9a); 1.5b остаётся `[DEFERRED]`, источник таблицы инъекций — `injections.json`;
`atlas todo` и `who` отдельными командами не строить — числа приёмки и «Соседи» живут в `brief`; HTML 3.1, сид 5.2 —
без изменений, после K1.1.

## 4. amendments.md — записи 16–18 (предложение CTO)

16. Конец облака и K0 не пройден: кредит заканчивается на 1.6e, дальше локально; `pack k0-framework-quality#1.2` →
    хвостов 0 — Q2 не подтверждён, лучше базы только Q3 задним числом; Атлас продолжается как помощник брифа и
    справочник проекта; форматы меняются (ADR-ATL-004); экзамен снимается как приёмка, вместо него M1–M4, U1/U2.
17. Новые задачи и статусы: 1.7 → 1.7a/1.7b/1.7c; 2.3 → SUPERSEDED; K0 → K0′; новые 1.9a–1.9f, 1.10a–1.10d, 1.6d;
    1.6f DEFERRED; `todo`/`who` не строятся.
18. Правила исполнения — локально: `CLOUD.md` — «исторический: до 1.6e»; в `plan.md` подраздел «Локально (с 1.6e)»:
    одна задача — одна ветка `atlas/<id>` от свежего `main`, писатель в worktree; порядок `atlas brief` → `lint-brief`
    → стадия 0 → `plans_ledger.py brief` → tester → developer → `atlas inject run` → reviewer → `result.md`
    (`lint-result`) → слияние лидом `--no-ff`; трейлеры одним блоком; FILES = граница правок; слияние только после
    проверки лида; п. 8 CLOUD.md без изменений; п. 9 снимается; бюджет — токены задачи (`subagent_tokens`) в итоге.

## 5. Открыто у CTO

Поля `modules.yaml` для охвата не сверил (grep по `path:` дал 0 — ключ другой); состояние 1.6e не видел, «≤ 1,5 с» —
цель, не замер; изменение промпта спавна хуком не проверял (дизайн на нём не держится); «линт ловит ~13 из 25» — по
одному отчёту; время набора `-m "not slow"` не мерил; `gh` не авторизован; требования `plans_ledger.py build_brief` к
полям надо сверить с формой 1.9d, чтобы не завести второй парсер брифа; экзамен и полный набор не перепрогонял.
