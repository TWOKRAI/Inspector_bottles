# Карта правил 2.4a: кто какое правило несёт после omitClaudeMd

Источник: worktree atlas, ветка feat/atlas, 2026-10-04. Только чтение. Размеры в байтах, замер `wc -c` и разбор по заголовкам; расщепление внутри раздела помечено оценкой (сумма сохранена). Токены ≈ байт / 2,3 (калибровка аудита).

Режим «ядро»: `link` — в ядре только ссылка; `core-N` — сжатый текст, N КБ; `full-N` — полный текст; `—` — в ядре нет.

## 1. Таблица разметки

### 1a. CLAUDE.md (три файла), rules, project-rules

| файл | раздел | байт | кому нужен | класс дефекта | дом после изменения | ядро: ссылка/текст | причина |
|---|---|---|---|---|---|---|---|
| root CLAUDE.md | заголовок | 60 | все субагенты | — | ядро: строка 1 | core-0.2 | название проекта; одна строка |
| root CLAUDE.md | Проект | 399 | все субагенты | — | ядро: строка 1; полный текст остаётся в root | core-0.3 | что за проект; роли без него гадают |
| root CLAUDE.md | Архитектура | 2192 | отдельные роли: developer, teamlead, reviewer, investigator, integrator, manager, debugger, tester, cto, tech-writer, spec-writer | ложная модель системы; путаница process vs channel | root CLAUDE.md (остаётся); строка в карте | link | общий справочник; лид тоже читает |
| root CLAUDE.md | Ключевые пути | 1777 | отдельные роли: те же роли | правка в старом дереве вместо multiprocess_prototype/ | root CLAUDE.md; строка в карте | link | таблица путей нужна и лиду |
| root CLAUDE.md | История версий и архив | 365 | никто сейчас | — | строка в Ключевые пути; детали в git log | — | v1/v2 удалены; факт только исторический |
| root CLAUDE.md | Стек | 515 | отдельные роли: developer, tester, debugger, teamlead | — | .claude/modes/_stack.md (дубль, сверить в 2.4c) | link | _stack.md уже читают роли |
| root CLAUDE.md | Правила проекта: инварианты (п.1,2,5,6,9) | 1100 | отдельные роли: developer, teamlead, reviewer, tester, cto, integrator | обратный импорт слоя; не-dict через границу процесса | ядро: 2 строки (слои, Dict at Boundary); полный текст root | core-0.35 | нарушаются по умолчанию; ревью ловит только при знании |
| root CLAUDE.md | Правила проекта: ADR и автосинхронизация (п.3,7,8) | 500 | отдельные роли: developer, teamlead, tech-writer | дрейф DECISIONS.md; CI-красный validate.py | карта: правка DECISIONS.md → python -m scripts.sync | link | срабатывает по триггеру, не всегда |
| root CLAUDE.md | Правила проекта: команды тестов (п.4) | 450 | отдельные роли: developer, tester, debugger, teamlead | pytest не из того каталога | .claude/modes/_stack.md | link | _stack.md уже даёт test command |
| root CLAUDE.md | Правила проекта: коммиты (п.10) | 518 | все субагенты: все, кто коммитит | отказ хука commit-msg | ядро: 4 строки; COMMIT_GUIDE.md | core-0.7 | защищаемый класс: трейлеры |
| root CLAUDE.md | Принципы владельца (6 пунктов) | 1906 | отдельные роли: developer, teamlead, reviewer, manager, cto, investigator, integrator | удалён спящий путь; обход бага framework; лишний слой; GUI запускает процессы | ядро: 6 однострочников (0.5 КБ); полный текст root | core-0.5 | решения владельца; без них ревьюер не заметит нарушения |
| root CLAUDE.md | Формат commit-сообщений (для агентов) | 1477 | отдельные роли: developer, teamlead, tester, debugger, tech-writer, docs-writer, spec-writer | отказ хука; коммит без Why/Layer | COMMIT_GUIDE.md; в ядре — 4 строки (см. п.10) | link | шаблон дублирует COMMIT_GUIDE и .gitmessage |
| root CLAUDE.md | Plan-Driven: Refs-правило | 500 | отдельные роли: developer, teamlead, tester, tech-writer | коммит плана без Refs: plans/<slug>.md | ядро: 1 строка в «коммиты» | core-0.1 | обязательный трейлер при задаче из плана |
| root CLAUDE.md | Plan-Driven: slug, ветка, статус | 660 | лид: лид, manager | — | .claude/commands/dev/plan.md; manager.md | link | план создаёт лид и manager |
| root CLAUDE.md | Память (канон docs/claude/memory) | 1142 | лид | dual-write затирает правки другой стороны | root (сократить); см. «Дубли» п.14 — конфликт с dot | — | субагенты пишут память через свой harness |
| root CLAUDE.md | MCP qex: свежесть и EN-запросы | 600 | отдельные роли: developer, tester, reviewer, teamlead, investigator, manager, integrator, cto | устаревший индекс отвечает уверенно | ядро: 2 строки; .claude/plugins/mcp-qex/README.md | core-0.3 | уже есть в project-rules §1 |
| root CLAUDE.md | MCP qex: стоимость, модель, реиндекс | 3115 | лид | — | .claude/plugins/mcp-qex/README.md | link | справочник по обслуживанию; сверить, что README его содержит |
| root CLAUDE.md | MCP sentrux: выбор инструмента (таблица) | 1300 | лид: лид; integrator, reviewer частично | — | .claude/plugins/mcp-sentrux/README.md | link | навигация qex/sentrux/graph-slice |
| root CLAUDE.md | MCP sentrux: check_rules даёт ложный зелёный | 1600 | отдельные роли: reviewer, teamlead, integrator, cto, лид | вердикт о границах слоёв по 9 из 39 правил | role-файлы reviewer/teamlead/integrator/cto: «границы — CLI sentrux check .»; README sentrux | link | reviewer.md и teamlead.md сейчас велят звать check_rules |
| root CLAUDE.md | MCP sentrux: qex и sentrux ортогональны, graph-slice | 1100 | лид | — | README sentrux; scripts/graph_slice/README.md | link | навигация |
| root CLAUDE.md | MCP sentrux: цена бэкенда claude-cli | 1900 | лид | съеден дневной лимит (53 вызова) | docs/claude/memory/feedback_claude_cli_backend_costs_a_full_session.md; 2 строки в root | link | graphify label запускает только лид |
| root CLAUDE.md | MCP sentrux: обслуживание графа graphify | 700 | лид | призраки в графе после update | README sentrux или graphify-доку | link | обслуживание |
| root CLAUDE.md | MCP sentrux: имена сообществ — подсказка | 788 | отдельные роли: reviewer, investigator, integrator, cto | имя сообщества процитировано как факт | ядро: нет; роли-потребители графа: 1 строка; README | link | ложная точность вердикта |
| root CLAUDE.md | Slash-команды | 1224 | лид | — | root (сократить) или .claude/commands | — | лид вызывает; субагент — нет |
| root CLAUDE.md | Makefile | 497 | лид: лид, developer | — | _stack.md или scripts/README.md | link | команды make check/gate |
| root CLAUDE.md | Diagrams-as-Code | 489 | лид: лид, tech-writer | — | docs/diagrams (README) | link | редкая задача |
| .claude/CLAUDE.md | заголовок + Modes | 526 | лид | — | dot CLAUDE.md | — | выбор режима dev/spec |
| .claude/CLAUDE.md | Test authorship: три роли, таблица | 1100 | отдельные роли: tester, developer, teamlead, reviewer, cto, лид | ложная модель автора | ядро: 0.7 КБ сжатое; modes/dev.md уже дублирует 1646 Б | core-0.7 | защищаемый класс #1 |
| .claude/CLAUDE.md | Test authorship: break-injection обязателен | 800 | отдельные роли: лид (проводит), cto и reviewer (проверяют) | тест зелёный под своей поломкой; зависший тест | dot (1 строка STRICT); cto.md; reviewer.md; CRAFT-injection.md | link | инъекцию делает лид; роли проверяют результат |
| .claude/CLAUDE.md | Test authorship: хазард-тесты автора | 400 | отдельные роли: developer, teamlead | регрессии в тонких местах механизма | developer.md и teamlead.md: 3 строки | — | правило только для авторов |
| .claude/CLAUDE.md | Test authorship: независимый tester раз на механизм | 1500 | отдельные роли: лид (запускает), tester | слепота тестера; повторный прогон за 479k | dot (1 абзац); tester.md (worktree уже есть); modes/dev.md | — | порядок запуска — дело лида |
| .claude/CLAUDE.md | Test authorship: ревью без прогона = совет; литералы; spy на имя; fake-harness; «impossible» | 1300 | отдельные роли: reviewer, tester, developer, teamlead, cto | vacuous green; spy на имя API; неверное «невозможно» | ядро: 0.7 КБ (с п.1 выше); CRAFT-tests.md | core-0.7 | доходят до всех, кто пишет и судит тесты |
| .claude/CLAUDE.md | Test authorship: замеры Ф0 (история) | 805 | никто сейчас | — | docs/claude/memory/CRAFT-tests.md или ARCHIVE | — | обоснование, не правило |
| .claude/CLAUDE.md | Task launch convention: таблица стадий | 1500 | лид | пропуск стадии 0/1/3/5 | dot CLAUDE.md (сократить) + modes/dev.md | — | лид каждый раз запускает задачу |
| .claude/CLAUDE.md | Task launch: Stage 1 уточнён, слепота через worktree | 1400 | отдельные роли: лид, tester | второй тестер впустую; утечка прозой | tester.md (worktree есть) + modes/dev.md | — | tester уже несёт worktree-текст |
| .claude/CLAUDE.md | Task launch: solo-исключение и multi-select | 721 | лид | — | modes/dev.md | — | история решения владельца |
| .claude/CLAUDE.md | Subagents background by default: таблица | 1100 | все субагенты: лид (STRICT); все субагенты — строка | тихий commit/push/PR фоновым агентом; ревью не успело | dot (STRICT, 3 строки); ядро: «отчёт, не коммит и не push» | core-0.2 | защищаемый класс #3 |
| .claude/CLAUDE.md | Subagents background: /review vs /code-review | 360 | лид | — | dot | — | выбор команды |
| .claude/CLAUDE.md | ponytail: когда лестница | 1200 | лид | — | dot (сократить); ponytail SKILL | — | граница применения |
| .claude/CLAUDE.md | ponytail: приоритет правил проекта | 537 | все субагенты: все, кто может вызвать skill ponytail | ponytail отменяет тест/доку/трейлеры | ядро: 1 строка | core-0.15 | skill виден всем субагентам в списке |
| .claude/CLAUDE.md | Standing rules — один skill, не двенадцать копий | 1805 | лид | — | dot: 3 строки-указатель; история в ARCHIVE | — | в основном история дублирования |
| .claude/CLAUDE.md | Team mode: роли→модели, эскалация | 1600 | лид | — | dot (сократить) + AGENT_TEAMS_GUIDE.md; эскалация = дубль §7 | — | лестница уже в project-rules |
| .claude/CLAUDE.md | Team mode: хуки-гейты | 800 | лид | — | AGENT_TEAMS_GUIDE.md | link | справочник |
| .claude/CLAUDE.md | Team mode: git (worktree на писателя, явные пути) | 600 | отдельные роли: writers: developer, teamlead, tester | чужая запись в общем дереве; false-green venv | ядро: 0.3 КБ (одно дерево — один писатель); _WORKTREE_PATTERN.md | core-0.5 | защищаемый класс #8 |
| .claude/CLAUDE.md | Team mode: пределы движка | 535 | лид | — | AGENT_TEAMS_GUIDE.md | link | справочник |
| .claude/CLAUDE.md | Persistent agents: re-summon (правила) | 2396 | лид | призрак при резюме; свежий агент платит 107–228k | dot (4 строки); docs/claude/pilot-company-v2.md | link | лид решает, кого резюмировать |
| .claude/CLAUDE.md | Language policy: таблица и STRICT | 900 | все субагенты: все; built-in agents через CLAUDE.md | английский вывод владельцу | ядро: 0.35 КБ; dot (остаётся для general-purpose) | core-0.35 | защищаемый класс #4 |
| .claude/CLAUDE.md | Language policy: STE-80 абзац | 579 | отдельные роли: все, кто пишет отчёт | — | project-rules reference/ste-80.md (=§9); в dot — убрать дубль | link | дубль §9 |
| .claude/CLAUDE.md | Commands — quick reference | 977 | лид | — | dot или root (один дом) | — | дубль списка slash в root |
| .claude/CLAUDE.md | MCP routing: README первым, fallback | 300 | отдельные роли: роли с MCP | вызов недоступного сервера | ядро: 1 строка (= §3) | core-0.15 | дубль §3 |
| .claude/CLAUDE.md | MCP routing: список серверов | 1078 | лид: лид; роли — по таблице 2.4e | — | 2.4e: таблица роль→сервер | link | по ролям решает 2.4e |
| .claude/CLAUDE.md | Behavioral: think-before-coding, goal-driven | 400 | отдельные роли: developer, teamlead, debugger, manager | тихий выбор из нескольких прочтений; слабый критерий | developer.md, teamlead.md: 2 строки | — | исполнителям; лид тоже |
| .claude/CLAUDE.md | Behavioral: smart-zone | 518 | лид | — | dot | — | контекст лида |
| .claude/CLAUDE.md | Token discipline: lean output | 350 | отдельные роли: developer, tester, teamlead, debugger | — | ядро: 1 строка в «evidence» | core-0.1 | pytest -q --tb=short, ruff -q |
| .claude/CLAUDE.md | Token discipline: tool-search, baseline | 622 | лид | — | dot | — | настройки сессии |
| .claude/CLAUDE.md | Project layout: таблица где писать | 1150 | лид: лид, manager, docs-writer | — | docs/claude/CLAUDE_FOLDER_OVERVIEW.md; manager.md | link | лид знает; manager несёт Plan naming сам |
| .claude/CLAUDE.md | Project layout: Thread (plan→implement→ship) | 603 | лид: лид, manager | — | dot | — | цепочка лида |
| .claude/CLAUDE.md | Memory OVERRIDE: канон и lint | 1000 | лид | — | root «Память»; КОНФЛИКТ с root, см. п.14 «Дубли» | — | две CLAUDE.md называют разные каноны |
| .claude/CLAUDE.md | Memory OVERRIDE: capture rail (WHEN/FORBID) | 622 | отдельные роли: роли с memory: project (9) | дубль записи памяти | карта: «пишу память → dot §Memory»; harness сам даёт инструкции | link | проверить, что harness не повторяет |
| ~/.claude/CLAUDE.md | заголовок + Dev Company | 815 | лид | — | global (вне репо, 2.4 не правит) | — | список ролей |
| ~/.claude/CLAUDE.md | Threshold Rule | 938 | лид | — | global | — | порог делегирования |
| ~/.claude/CLAUDE.md | Science Company, Key Boundaries, sci-searcher | 862 | никто сейчас | — | global; вынести в проект knowledge | — | в этом проекте нет sci-агентов |
| ~/.claude/CLAUDE.md | Plans Hierarchy | 791 | лид: лид, manager | смешение планов зон | global; manager.md: Plan naming есть | — | manager несёт свою часть |
| ~/.claude/CLAUDE.md | Spec Format (Task X.Y) | 282 | отдельные роли: manager | — | manager.md «Task file format» (2058 Б) — дубль | — | manager.md полнее |
| ~/.claude/CLAUDE.md | Base Rules (8 правил) | 346 | все субагенты: все исполнители | тихий except; секреты в коде; 3-я итерация без эскалации | ядро: 3 строки (секреты в env, логи, 2 итерации) | core-0.15 | в omitClaudeMd исчезнут |
| ~/.claude/CLAUDE.md | Prohibitions | 403 | все субагенты | rm -rf, curl|sh, новая зависимость без причины | ядро: 1 строка | core-0.1 | опасные команды |
| ~/.claude/CLAUDE.md | Response Format, Ambiguity, Token Limit | 211 | лид | — | global | — | стиль ответа лида |
| ~/.claude/CLAUDE.md | graphify trigger | 226 | лид | — | global | — | команда владельца |
| ~/.claude/rules/context7.md | context7: когда звать | 1267 | отдельные роли: developer, teamlead, tester, tech-writer | доки из памяти модели | role-файлы: уже есть строка context7 в MCP routing | — | правило «когда НЕ звать» теряется; мелочь |
| project-rules SKILL.md | frontmatter (description) | 494 | все субагенты | — | project-rules: сократить до 2 предложений | — | виден в листинге навыков всем |
| project-rules SKILL.md | §1 qex свежесть | 218 | отдельные роли: роли с qex | устаревший индекс | ядро: 2 строки | core-0.3 | оставить |
| project-rules SKILL.md | §2 Честность | 724 | все субагенты | ложная уверенность | ядро: полный | full-0.75 | защищаемый класс #6 |
| project-rules SKILL.md | §3 MCP по enabled.yaml | 325 | отдельные роли: роли с MCP | вызов отсутствующего сервера | ядро: 1 строка | core-0.15 | сжать |
| project-rules SKILL.md | §4 Коммиты, push, PR | 630 | все субагенты: все писатели | тихий push/PR; git add -A; чужой коммит | ядро: полный (0.7 КБ вместе с root п.10) | full-0.7 | защищаемые классы #3, #5 |
| project-rules SKILL.md | §5 spawn, scope, brief, test radius, evidence | 1300 | отдельные роли: executors | правка вне FILES; чужая зелень; цепочка Bash | ядро: 0.9 КБ; executor-brief.md | core-0.9 | основное правило исполнителя |
| project-rules SKILL.md | §5 модели, worktree-писатель, live GUI, public path, knobs | 791 | отдельные роли: лид (модели), writers (worktree), stand-роли | модель не задана; не тот venv | worktree → ядро (0.5 КБ выше); модели → dot; stand/knobs → карта | link | делится по адресатам |
| project-rules SKILL.md | §6 Язык | 190 | все субагенты | — | ядро (слить с Language policy) | core-0.35 | один дом |
| project-rules SKILL.md | §7 Лестница эскалации | 1425 | все субагенты | гадание вместо вопроса | ядро: сжатая таблица 1.0 КБ + блок ESCALATION | core-1.0 | защищаемый класс #7 |
| project-rules SKILL.md | §8 Границы сессии | 562 | лид: лид (строка в отчёте субагента читает лид) | — | reference/session-boundaries.md | link | не для исполнителя |
| project-rules SKILL.md | §9 STE-80 полный | 1938 | отдельные роли: все, кто пишет отчёт | — | reference/ste-80.md; в ядре 3 строки | core-0.25 | полный текст по ссылке |

### 1b. Тела агентов и шаблон брифа

| файл | раздел | байт | кому нужен | класс дефекта | дом после изменения | ядро: ссылка/текст | причина |
|---|---|---|---|---|---|---|---|
| agents/dev: все 13 (кроме ai-judge) | «Read CLAUDE.md» в Before starting / «auto-loaded» в Orient first | 1100 | роль(и): все 13 ролей | после omitClaudeMd роль читает весь lead-CLAUDE.md (≥10 КБ) или не находит его | заменить ссылкой на карту; не читать CLAUDE.md целиком | stay/правка | правка в 13 файлах |
| agents/dev: reviewer, teamlead, integrator, investigator, manager | Orient first (карта сверху вниз) | 1949 | роль(и): эти 5 | — | одна строка в карте правил; убрать из 5 файлов | stay/правка | дубль ×5 |
| agents/dev: developer, tester, debugger, investigator, integrator, reviewer, teamlead, tech-writer, spec-writer, manager | MCP routing (self-contained) | 10394 | роль(и): эти 10 | — | остаётся в role-файле; урезает 2.4e по таблице роль→сервер | stay/правка | роль-специфичная |
| agents/dev: developer, teamlead (+упоминания в tester, debugger, cto) | хвост про isolation: worktree и VIRTUAL_ENV | 2200 | роль(и): writers | false-green: uv run исполняет код основного дерева | _WORKTREE_PATTERN.md + 1 строка в ядре; хвосты убрать | stay/правка | дубль ×2 (~1.1 КБ каждый) |
| agents/dev: developer | остальное тело (Role, Workflow, Code rules, Commit, Blockers, What NOT) | 3680 | роль(и): developer | — | остаётся | stay/правка | роль-специфичное; добавить goal-driven и хазард-тесты |
| agents/dev: tester | остальное тело (два режима, RED, regression, property, test rules) | 9829 | роль(и): tester | ложная модель автора; vacuous | остаётся; уже несёт литералы, effect, hang, worktree | stay/правка | самый полный носитель test-authorship |
| agents/dev: reviewer | остальное тело (Mode plan, чек-лист, специализации, итерации) | 15021 | роль(и): reviewer | ревью без прогона; ложный зелёный sentrux | остаётся; править строки 58, 197: границы — CLI | stay/правка | носит «прогнать и процитировать» (стр.83) |
| agents/dev: teamlead | остальное тело (режимы, Code rules, Commit format, escalation) | 4650 | роль(и): teamlead | — | остаётся; править sentrux:check_rules (стр.49) | stay/правка | несёт Risk/Reversible/Rejected |
| agents/dev: debugger | остальное тело | 4494 | роль(и): debugger | лечение симптома | остаётся | stay/правка | — |
| agents/dev: investigator | остальное тело | 4007 | роль(и): investigator | — | остаётся | stay/правка | — |
| agents/dev: cto | тело (4 режима, формат ответа) | 5107 | роль(и): cto | ревью по чтению; ложный «guaranteed» | остаётся; team-protocol из skills: в ссылку §4,§5 | stay/правка | несёт инъекцию и «reproduce by running» |
| agents/dev: manager | остальное тело (Task file format, Plan format, vertical slice) | 7448 | роль(и): manager | — | остаётся | stay/правка | несёт Spec Format полнее global |
| agents/dev: integrator | остальное тело (gates, output) | 5873 | роль(и): integrator | ложный зелёный sentrux | остаётся; добавить CLI-проверку | stay/правка | — |
| agents/dev: ai-judge | всё тело (anti-bias, S2/S3/S7) | 6426 | роль(и): ai-judge | — | остаётся; project-rules снять с skills: (4 строки в файл) | stay/правка | один сигнал; 8 КБ ядра избыточны |
| agents/dev: junior | всё тело | 3949 | роль(и): junior | — | остаётся | stay/правка | — |
| agents/dev: docs-writer | всё тело | 3136 | роль(и): docs-writer | — | остаётся; язык: ссылка на ядро, не CLAUDE.md | stay/правка | — |
| agents/dev: tech-writer | остальное тело (ADR, ARCHITECTURE, Migration) | 4420 | роль(и): tech-writer | — | остаётся | stay/правка | — |
| agents/dev: spec-writer | остальное тело | 3808 | роль(и): spec-writer | — | остаётся | stay/правка | — |
| templates/executor-brief.md | форма DESIGN/FILES/REDS | 4667 | лид | бриф без DESIGN | остаётся; 2.4f добавляет дисциплину чтения | stay | — |
| templates/executor-brief.md | While the agent runs; Per-model; прочее | 3689 | лид | — | остаётся | stay | — |

### 1c. Итоги по байтам (1a)

| файл | лид | все субагенты | отдельные роли | никто сейчас | сумма |
|---|---|---|---|---|---|
| root CLAUDE.md | 12127 (10) | 977 (3) | 13405 (12) | 365 (1) | 26874 (26 строк) |
| .claude/CLAUDE.md | 17391 (17) | 2537 (3) | 9351 (12) | 805 (1) | 30084 (33 строк) |
| ~/.claude/CLAUDE.md | 2981 (5) | 749 (2) | 282 (1) | 862 (1) | 4874 (9 строк) |
| ~/.claude/rules/context7.md | 0 (0) | 0 (0) | 1267 (1) | 0 (0) | 1267 (1 строк) |
| project-rules SKILL.md | 562 (1) | 3463 (5) | 4572 (5) | 0 (0) | 8597 (11 строк) |
| **итого** | **33061** | **7726** | **28877** | **2032** | **71696** (80 строк) |

Без строк project-rules (они уже в ядре и считаются дважды): лид 32499, все субагенты 4263, отдельные роли 24305, никто сейчас 2032, сумма 63099 Б по 69 строкам.

Число после `core-` в таблице — запрос раздела к ядру; бюджет ядра — только таблица §2 (значения там ниже и приоритетны).

В скобках — число строк таблицы. «Сумма» root = 26874 из 27089 Б (215 Б — переводы строк); dot = 30084 из 30099. В «все субагенты» входят только то, что идёт в ядро; «отдельные роли» — справочники и правила, которым нужна ссылка либо role-файл. Правила проекта и qex/sentrux расщеплены по абзацам.

## 2. Ядро project-rules для всех субагентов

| № | пункт | цель, КБ |
|---|---|---|
| 1 | Кто ты, где что лежит: проект (1 строка), слои framework→Services→Plugins→prototype, Dict at Boundary, активный прототип multiprocess_prototype/ | 0.40 |
| 2 | Честность (§2 полностью): раздел «Что осталось открытым / ненадёжно», OPEN_QUESTIONS, grep -F для счётчиков | 0.70 |
| 3 | Лестница эскалации (§7): сжатая таблица + блок ESCALATION; 3-я итерация, spec-vs-code | 0.90 |
| 4 | Принципы владельца: 6 однострочников (framework-first, fix forward, FREEZE, меньше слоёв, подключаемость, GUI не запускает) | 0.45 |
| 5 | Язык: ответ владельцу — русский; комментарии и docs — русский; файлы .claude/ — английский; не смешивать в одном файле | 0.30 |
| 6 | Коммиты: коммитит только роль с правом и бриф; никогда push/PR/--no-verify/git add -A; Why:/Layer:/Refs:; git show --stat после; Co-Authored-By | 0.60 |
| 7 | Дерево и поиск: одно дерево — один писатель; писатель в worktree — явные пути, env -u VIRTUAL_ENV, preflight; НЕ grep -r от корня — git grep или rg с исключением .claude/worktrees; цепочки Bash не клеить; uv sync только с --inexact; не taskkill глобально; PYTHONIOENCODING=utf-8 | 0.95 |
| 8 | Рамки: отчёт, не коммит и не push (фон по умолчанию); правки только в FILES; бриф = форма, первая правка за ≤5 вызовов; evidence-or-nothing; тест-радиус, не весь suite; ponytail не отменяет тесты/доку/трейлеры; опасные команды и секреты | 0.80 |
| 9 | Тесты — для developer/tester/reviewer/teamlead/debugger/cto: литерал вместо пересчёта; эффект, не имя API; зависший тест хуже отсутствующего; зелёный без красного не доказательство; ревью = прогон + цитата; «невозможно» только с воспроизведением | 0.60 |
| 10 | qex: сначала get_indexing_status; MCP — только если включён в enabled.yaml; границы слоёв — CLI sentrux check .; STE-80 в 3 строки | 0.35 |
| | **ядро (тело)** | **6.05** |
| | frontmatter (description в 2 предложения) | 0.40 |
| | «Карта правил: что читать когда» (таблица §4 ниже, ≤ 28 строк по ≤ 50 Б) | 1.40 |
| | **файл целиком** | **7.85** |

Жёсткий предел 8,0 КБ на весь SKILL.md (тело + frontmatter + карта). Расчёт даёт 7.85 КБ. Если карта не считается в предел, ядро с запасом. Если считается и расчёт выше 8,0 — резать в таком порядке: п.4 (принципы) до 0,35, п.1 до 0,4, карта до 25 строк. Не резать: п.2, п.3, п.5, п.6, п.7, п.9.

Что остаётся вне ядра, но в skill-папке по ссылке: `reference/ste-80.md` (≈1,9 КБ, из §9), `reference/session-boundaries.md` (≈0,6 КБ, из §8).

Покрытие защищаемых классов: честность — п.2; лестница — п.3; язык — п.5; трейлеры — п.6; запрет `grep -r` и «одно дерево — один писатель» — п.7 (сейчас нигде не записаны, см. R1); test authorship — п.9 (+ tester/reviewer); background-коммиты — п.8.

## 3. Что нужно роли сверх ядра

| роль | skills: (preload) | файлы по ссылке | правки в role-файле |
|---|---|---|---|
| developer | project-rules, verify-done (как сейчас) | modes/_stack.md; .rules/* по пути; CRAFT-tests (когда пишет тест); _WORKTREE_PATTERN; COMMIT_GUIDE | убрать «Read CLAUDE.md»; добавить 2 строки goal-driven и 3 строки хазард-тестов автора; ponytail — по запросу на greenfield |
| tester | project-rules | CRAFT-tests, CRAFT-injection (как его набор будут ломать); _stack.md; property-testing по запросу | убрать «Read CLAUDE.md»; worktree-слепота уже в файле; verify-done не нужен |
| reviewer | project-rules | CRAFT-verdict, CRAFT-tests; README mcp-sentrux; team-protocol §1,3,5 только для MODE: plan (по ссылке) | заменить sentrux:check_rules на CLI sentrux check . (стр.58, 197); оставить «прогнать и процитировать» |
| teamlead | project-rules, verify-done | как developer + CRAFT-injection, CRAFT-verdict (режим Escalation); DECISIONS.md | заменить sentrux:check_rules (стр.49); оба трейлера Risk/Rejected остаются |
| debugger | project-rules, verify-done, systematic-debugging | CRAFT-tests (флейки, зависания); _WORKTREE_PATTERN | убрать memory: project, если MEMORY.md пуст (2.4e); убрать «Read CLAUDE.md» |
| investigator | project-rules | CRAFT-verdict (живой дефект); README backend-ctl; MODULES_RESPONSIBILITY_MAP; ROUTING_GLOSSARY | строка про имена сообществ graphify; systematic-debugging — по ссылке, не preload |
| cto | project-rules, verify-done | team-protocol §4 (эскалация), §5 (гейты) по ссылке; CRAFT-verdict, CRAFT-injection; OPEN_QUESTIONS | убрать team-protocol из skills: (−14,5 КБ ≈ 6k токенов); CLI sentrux check . для границ |
| manager | project-rules, team-protocol | plan.md (команда), plans/queue/ORDER.md, executor-brief.md, modes/spec.md | Spec Format из global — теперь только manager.md (уже есть) |
| integrator | project-rules | README mcp-sentrux, scripts/graph_slice/README.md, MODULE_TIERS.md | добавить: границы — CLI; имена сообществ — подсказка |
| ai-judge | —  (project-rules снять) | — | 4 строки в файл: честность, эскалация к cto, без git-мутаций, один сигнал; экономит ~3,5k токенов за вызов |
| junior | project-rules | modes/_stack.md | ядро включает «никогда не коммитит»; роль самая дешёвая, ядро 8 КБ для Haiku тяжело — вариант: junior без skill, 6 строк в файле |
| docs-writer | project-rules | _stack.md «Language policy»; шаблоны README/STATUS | ссылка на язык из ядра вместо CLAUDE.md; инструменты Read/Write/Edit/Glob/Grep — пункты про git/Bash не применимы |
| tech-writer | project-rules | /dev:adr; python -m scripts.sync; DECISIONS.md; reference/ste-80.md | STE-80 полный — по ссылке |
| spec-writer | project-rules | modes/spec.md; docs/direction/ | STE-80 полный — по ссылке |

## 4. Карта правил: триггер → файл

| триггер | читать |
|---|---|
| правлю Qt-виджеты, frontend_module, registers | .rules/gui.md; docs/claude/memory/CRAFT-config-qt.md |
| правлю multiprocess_framework/** | .rules/framework.md; .rules/module-state.md; .rules/logging.md |
| правлю Plugins/ или Services/ | .rules/plugins.md или .rules/services.md |
| правлю multiprocess_prototype/ | .rules/prototype.md |
| IPC, роутинг, process vs channel | multiprocess_framework/docs/ROUTING_GLOSSARY.md |
| границы модуля, кто что владеет | multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md; MODULE_TIERS.md |
| пишу или оцениваю тесты | docs/claude/memory/CRAFT-tests.md |
| инъекции, «0 красных», вакуумные ассерты | docs/claude/memory/CRAFT-injection.md |
| выношу вердикт ревью, живой дефект | docs/claude/memory/CRAFT-verdict.md |
| конфиг, схема Pydantic | docs/claude/memory/CRAFT-config-qt.md |
| урок по модулю (тег module:) | docs/claude/memory/CRAFT-by-module.md; индекс MEMORY.md |
| коммичу | .claude/COMMIT_GUIDE.md (одна копия, см. «Дубли» п.11); .claude/modes/_stack.md: значения Layer |
| первый тест в worktree | .claude/plugins/core/agents/_WORKTREE_PATTERN.md; scripts/worktree_preflight.py |
| стек, команды тестов, значения Layer | .claude/modes/_stack.md |
| новый публичный модуль | skill module-contract |
| красный тест, непонятная ошибка | skill systematic-debugging |
| собираюсь сказать «готово» | skill verify-done |
| стадии S0–S8, handoff, гейты, sandbox | skill team-protocol (§ по стадии) |
| границы слоёв, циклы | CLI: sentrux check . ; .claude/plugins/mcp-sentrux/README.md (не MCP check_rules) |
| поиск по смыслу, qex | .claude/plugins/mcp-qex/README.md |
| кого заденет правка модуля | scripts/graph_slice/README.md |
| живой бэкенд, стенд | .claude/plugins/mcp-backend-ctl/README.md; GUI-стенд — только INSPECTOR_GUI_UNATTENDED=1 |
| правлю DECISIONS.md | multiprocess_framework/DECISIONS.md; затем python -m scripts.sync |
| ориентируюсь в коде | root CLAUDE.md §Архитектура, §Ключевые пути → docs/PROJECT_CONTEXT.md → CONTEXT.md модуля |
| вопрос, переживающий задачу | docs/claude/OPEN_QUESTIONS.md |
| пишу отчёт или ADR | project-rules reference/ste-80.md |
| планирую задачу | .claude/commands/dev/plan.md; plans/queue/ORDER.md; executor-brief.md |
| решение владельца, приоритеты | docs/claude/memory/MEMORY.md (Стоящие правила) |

28 строк. Строки про `.rules/*` работают, только если роль читает файл сама (R5).

## 5. Риски

- **R1. Запрет `grep -r` от корня нигде не записан.** git grep по репо не нашёл такого правила ни в CLAUDE.md, ни в агентах, ни в skill; есть только feedback_walk_skips_worktrees.md (про os.walk). В .claude/worktrees лежат полные чекауты, `grep -r` от корня дублирует и тормозит. Оно живёт в брифах лида. Ядро должно его нести (п.7).
- **R2. 13 ролей велят «Read CLAUDE.md».** После omitClaudeMd роль либо прочтёт весь lead-файл (≥10 КБ, с правилами лида: «не спрашивать перед задачей», «Task launch»), либо потеряет контекст. Экономия исчезнет, а правила лида смешаются с ролью. Править все 13 файлов в 2.4b.
- **R3. reviewer.md (стр.58, 197) и teamlead.md (стр.49) велят `sentrux:check_rules` для границ слоёв.** Root CLAUDE.md измерил: инструмент даёт зелёный по 9 из 39 правил. Предупреждение живёт только в root. После omitClaudeMd роль зовёт ложный зелёный. Править role-файлы и положить CLI-проверку в ядро.
- **R4. Принципы владельца только в root.** Без них reviewer не заметит удалённый спящий путь (FREEZE), обход бага framework (fix forward), лишний слой. Нужны 6 однострочников в ядре.
- **R5. `.rules/*.md` не имеют загрузчика.** git grep нашёл «.rules/» только в root CLAUDE.md. Frontmatter `paths:` — формат `.claude/rules/`, которого нет. Возможно, path-scoped правила не срабатывают нигде, у лида тоже. Карта должна ссылаться на них явно; решить — переносить в .claude/rules/. Заодно .rules/commits.md («коммит только по явной команде», paths: **) спорит с ролями-коммитчиками — сверить с §4.
- **R6. MEMORY.md (авто-память) и «Стоящие правила» могут не дойти.** Эти строки сейчас доходят до субагента через instructions: uv sync --inexact, глобальный taskkill, PYTHONIOENCODING, «одно дерево — один писатель». Не проверено, что omitClaudeMd снимает и авто-память. Если снимает — потеря; п.7 ядра уже несёт эти четыре.
- **R7. general-purpose остаётся без ядра.** general-purpose получает CLAUDE.md (после 2.4c — сокращённые, для лида), но не получает skill project-rules. Честность, лестница, запрет grep -r, одно дерево должны остаться в dot CLAUDE.md блоком «для любого агента» (6 строк).
- **R8. Explore и Plan.** Измерено в аудите: Explore ≈ 22,8k, CLAUDE.md не несёт. Он ничего не теряет. Plan — тоже read-only; ему нужны только карта и запрет grep -r: дойдёт через бриф лида.
- **R9. Две CLAUDE.md называют разный канон памяти.** Root (worktree): канон docs/claude/memory/. dot: канон .claude/memory/ (OVERRIDE). 2.4c обязан выбрать один; иначе роли с memory: project пишут не туда.
- **R10. Правила только для лида не сработают, если их унести слишком глубоко.** «Subagents background», «run_in_background:false для reviewer/tester», стадии 0/1/3/5 срабатывают в момент запуска. В dot CLAUDE.md оставить STRICT-строки; историю и замеры вынести.

Built-in агенты: `general-purpose` — получает оба CLAUDE.md целиком (после 2.4c короче, для лида), без project-rules: см. R7. `Explore` — CLAUDE.md не несёт (аудит: 22,8k), ничего не теряет. `Plan` — read-only; полагается на бриф лида.

## 6. Дубли и единственный дом

| № | где повторяется | единственный дом |
|---|---|---|
| 1 | Лестница эскалации: global 395 Б, dot Team mode ~900, project-rules §7 1425, reviewer 890, teamlead 842, modes/dev.md Boundary rules | project-rules ядро п.3; остальные — одна строка-указатель. Итерационные лимиты роли остаются в role-файлах. |
| 2 | Независимый тестер / test authorship: dot 5905, modes/dev.md 1646, tester ~459, MEMORY ~834, global 369, project-rules 254 | ядро п.9 (все роли) + tester.md/reviewer.md (роль) + CRAFT-tests.md (уроки); лид — 1 абзац STRICT в dot; modes/dev.md держит таблицу и ссылается. |
| 3 | Трейлеры Why:/Layer:: root 1477 + п.10 518, _stack.md, .rules/commits.md, project-rules §4, developer/teamlead, dot | один дом: .claude/COMMIT_GUIDE.md; в ядре 4 строки. |
| 4 | Язык: dot 1479, project-rules §6, _stack.md, role-файлы tech/docs-writer | ядро п.5; dot оставляет строку для general-purpose. |
| 5 | Свежесть qex: root ~600, MEMORY ~700, dot ~200, project-rules §1 218 | ядро п.10 (2 строки) + mcp-qex README. |
| 6 | Worktree: dot Team mode git ~600, MEMORY ~2,3 КБ, developer и teamlead ~1,1 КБ каждый, _WORKTREE_PATTERN, team-protocol §6 | _WORKTREE_PATTERN.md + ядро п.7; хвосты в двух агентах убрать. |
| 7 | Background по умолчанию: dot 1460 + modes/dev.md Subagent launch discipline 815 | dot (STRICT для лида) + ядро п.8 (строка для субагента); dev.md → указатель. |
| 8 | Списки slash-команд: root 1224 + dot 977 | один дом — dot Commands; root — ссылка. |
| 9 | Orient first ×5 (1949 Б) + root Ключевые пути | строка в карте; из 5 файлов убрать. |
| 10 | Spec Format: global 282 + manager.md 2058 | manager.md. |
| 11 | COMMIT_GUIDE: .claude/COMMIT_GUIDE.md и docs/claude/COMMIT_GUIDE.md (обе в git; сходство не сверял) | одна копия: .claude/COMMIT_GUIDE.md (на неё ссылается project-rules §4); вторую — указателем. |
| 12 | Принципы владельца: root 1906 + MEMORY.md «Стоящие правила» | root (полный) + ядро (6 строк); MEMORY ссылается. |
| 13 | Стек: root 515 + _stack.md | _stack.md. |
| 14 | Канон памяти: root «Память» 1142 vs dot «Memory OVERRIDE» 1622 — противоречие | root (новее, 2026-10); dot — 2 строки + capture rail. |
| 15 | STE-80: dot Language policy 579 + project-rules §9 1938 | project-rules reference/ste-80.md; dot — убрать. |

## 7. Что ненадёжно в этой разметке

- Расщепление внутри разделов (Test authorship, MCP sentrux, Правила проекта, Task launch и др.) — оценка по абзацам; суммы подогнаны к размеру раздела. Точность ±150 Б на строку.
- Тела reviewer, manager, integrator, ai-judge, tech-writer, spec-writer, docs-writer прочитал по заголовкам и greps, не целиком. Хвост про worktree видел целиком только в developer и teamlead; для debugger, tester, cto — по упоминанию.
- Строки «Тело агента (остальное)» = размер файла минус вычтенные блоки; приблизительно.
- Не знаю, снимает ли `omitClaudeMd` ещё авто-память (MEMORY.md) и `.claude/rules/`. В CC 2.1.222 флага нет; проверка — после обновления, до 2.4b (R6).
- Не знаю, грузит ли что-либо `.rules/*.md`. Нашёл только строку в root CLAUDE.md; загрузчика в repo нет. Возможна нативная логика, которую я не вижу (R5).
- worktree CLAUDE.md отличается от версии, показанной системой лида (разделы «Принципы владельца» и новая «Память» есть здесь); размеры — по worktree feat/atlas.
- Не сверял содержимое README mcp-qex и mcp-sentrux: переносимые уроки (индекс, check_rules) могут там отсутствовать. Сверить до переноса в 2.4c.
- Не сверял две копии COMMIT_GUIDE.md; не сверял `_stack.md` с root «Стек» построчно.
- Размер ядра в токенах (8 КБ ≈ 3,5k) — по калибровке аудита, не измерен.
