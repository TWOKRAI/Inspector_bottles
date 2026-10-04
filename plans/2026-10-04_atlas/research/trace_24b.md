# Trace 2.4b: каждое правило → новый дом

Дерево: worktree atlas, ветка feat/atlas, 2026-10-04. Исполнитель: teamlead.
Обозначения: **PR** = `.claude/skills/project-rules/SKILL.md` (источник `.claude/plugins/dev/skills/project-rules/SKILL.md`), разделы нового ядра:
преамбула (проект, слои, Dict at Boundary) · §1 qex · §2 честность · §3 MCP · §4 коммиты · §5 рамки · §6 язык · §7 эскалация · §8 дерево, поиск, shell · §9 тесты и вердикты · §10 принципы владельца · §11 стиль и конец отчёта · Map.
**SB** = `project-rules/session-boundaries.md`, **STE** = `project-rules/ste-80.md`.
«только лид» — правило срабатывает в момент, когда действует лид (запуск, выбор, обслуживание); у лида CLAUDE.md остаётся.
«root/dot остаются» — файл CLAUDE.md не тронут в 2.4b (2.4c), лид его видит.

Итог: 69 строк §1a (без project-rules) + 11 строк project-rules + 45 строк индекса памяти. Потерянных: 0.

## 1. rules_map §1a — root CLAUDE.md (26)

| № | раздел | новый дом |
|---|---|---|
| 1 | заголовок | PR преамбула (название проекта) |
| 2 | Проект | PR преамбула (одна строка) |
| 3 | Архитектура | PR Map «architecture, key paths» → root `CLAUDE.md`: Архитектура |
| 4 | Ключевые пути | PR Map «architecture, key paths»; «правки только в `multiprocess_prototype/`» — PR преамбула |
| 5 | История версий и архив | только лид — исторический факт, правил нет (git log) |
| 6 | Стек | PR Map «stack…» → `.claude/modes/_stack.md` |
| 7 | Правила проекта: инварианты п.1,2,5,6,9 | PR преамбула (слои, Dict at Boundary); остальное (`interfaces.py`, логи через ObservableMixin) — Map «editing an area» → `.rules/{framework,logging,…}.md` |
| 8 | ADR и автосинхронизация п.3,7,8 | `teamlead.md` Code rules и `tech-writer.md` Before starting п.2: `python -m scripts.sync`, индекс `multiprocess_framework/DECISIONS.md` |
| 9 | команды тестов п.4 | PR Map «stack, tests…» → `_stack.md` Toolchain |
| 10 | коммиты п.10 | PR §4 (Why:/Layer:, хук, COMMIT_GUIDE) |
| 11 | Принципы владельца (6) | PR §10 (6 однострочников); полный текст — root (лид) |
| 12 | Формат commit-сообщений | PR §4 → `.claude/COMMIT_GUIDE.md`; трейлеры одной строкой — PR §4 |
| 13 | Plan-Driven: Refs | PR §4 (`Refs: plans/<slug>.md` из плана) |
| 14 | Plan-Driven: slug, ветка, статус | `manager.md` Before starting п.1: `.claude/commands/dev/plan.md`, `plans/queue/ORDER.md`, executor-brief |
| 15 | Память (канон) | только лид — субагент пишет память через harness роли; как писать урок — PR Map «lessons index» (MEMORY.md §4) |
| 16 | qex: свежесть и EN-запросы | PR §1 (свежесть); EN-запросы — Map «MCP» → `.claude/plugins/mcp-qex/README.md` |
| 17 | qex: стоимость, модель, реиндекс | только лид — обслуживание индекса |
| 18 | sentrux: таблица выбора | PR Map «MCP» → `.claude/plugins/mcp-sentrux/README.md`; кого заденет — `scripts/graph_slice/README.md` |
| 19 | sentrux: check_rules ложный зелёный | PR §3 (CLI `sentrux check .`; MCP — quick signal, not a verdict); `reviewer.md` (2 строки), `teamlead.md` Express review, `verify-done/SKILL.md` §5 |
| 20 | sentrux: ортогональность, graph-slice | PR Map «MCP» (graph_slice README) |
| 21 | sentrux: цена claude-cli | только лид — graphify label запускает лид |
| 22 | обслуживание графа graphify | только лид — обслуживание |
| 23 | имена сообществ — подсказка | PR §3 («graphify community names are hints, not facts») |
| 24 | Slash-команды | только лид — субагент команды не вызывает |
| 25 | Makefile | PR Map «stack…» (`make gate`) |
| 26 | Diagrams-as-Code | только лид — редкая задача, tech-writer получает в брифе |

## 2. rules_map §1a — .claude/CLAUDE.md (33)

| № | раздел | новый дом |
|---|---|---|
| 27 | заголовок + Modes | только лид — выбор режима |
| 28 | Test authorship: три роли | PR §9 п.1 (автор — хазард-тесты, тестер — слепо до кода) |
| 29 | break-injection обязателен | PR §9 («Green without a red under break-injection proves nothing»); проводит лид |
| 30 | хазард-тесты автора | PR §9 п.1 |
| 31 | независимый tester раз на механизм | PR §9 п.1; порядок запуска — только лид; tester.md (worktree) без изменений |
| 32 | ревью без прогона, литералы, spy, fake-harness, «impossible» | PR §9 (литералы, эффект, daemon-поток, fake-harness, by running); «impossible» — PR §2 |
| 33 | замеры Ф0 (история) | только лид — обоснование, не правило |
| 34 | Task launch: таблица стадий | только лид — лид запускает стадии |
| 35 | Stage 1: слепота через worktree | только лид (запуск); tester.md уже несёт |
| 36 | solo-исключение | только лид |
| 37 | Subagents background: таблица | PR §5 («Default output: a report, no commit, no push»; spawn: `run_in_background: false`, промпт без коммита и пуша) |
| 38 | /review vs /code-review | только лид — выбор команды |
| 39 | ponytail: когда лестница | только лид |
| 40 | ponytail: приоритет правил | PR §5 («ponytail never cancels tests, docs or trailers») |
| 41 | Standing rules — один skill | только лид — история дублирования |
| 42 | Team mode: роли→модели, эскалация | PR §5 (модели при spawn), PR §7 (лестница) |
| 43 | Team mode: хуки-гейты | только лид — справочник |
| 44 | Team mode: git | PR §8 (одно дерево — один писатель; писатель в worktree: ruff, сообщение в файл; коммитит лид) |
| 45 | Team mode: пределы движка | только лид |
| 46 | Persistent agents: re-summon | только лид — решает лид |
| 47 | Language policy | PR §6 (Russian владельцу, комментарии, docs; .claude/ — English) |
| 48 | STE-80 абзац | PR §11 → STE |
| 49 | Commands quick reference | только лид |
| 50 | MCP routing: README первым | PR §3 |
| 51 | MCP routing: список серверов | PR §3 (enabled.yaml); по ролям — 2.4e |
| 52 | Behavioral: think-before, goal-driven | PR §5 («Several readings → list them; … verifiable goal») |
| 53 | Behavioral: smart-zone | только лид — контекст лида |
| 54 | Token discipline: lean output | PR §5 (`pytest -q --tb=short`, `ruff check -q`) |
| 55 | Token discipline: tool-search | только лид — настройки сессии |
| 56 | Project layout: где писать | только лид; manager — Before starting п.1 |
| 57 | Project layout: Thread | только лид |
| 58 | Memory OVERRIDE: канон | только лид (см. №15) |
| 59 | Memory: capture rail | PR Map «lessons index» (MEMORY.md §4 «Как писать»); harness роли |

## 3. rules_map §1a — ~/.claude/CLAUDE.md и context7 (10)

| № | раздел | новый дом |
|---|---|---|
| 60 | Dev Company | только лид |
| 61 | Threshold Rule | только лид — делегирует лид |
| 62 | Science Company | только лид — sci-агентов в проекте нет |
| 63 | Plans Hierarchy | только лид; manager — Before starting п.1 |
| 64 | Spec Format | `manager.md` «Task file format» (полнее) |
| 65 | Base Rules (8) | PR §5 (секреты в env, логи не глотать), PR §7 (2 итерации на петлю), PR §9 («Logic changed → tests changed»); readability/DRY/KISS — только лид (стиль, не защищаемый класс) |
| 66 | Prohibitions | PR §5 (`rm -rf`, `curl \| sh`, зависимость без причины, секреты) |
| 67 | Response Format, Ambiguity, Token Limit | только лид — стиль ответа лида |
| 68 | graphify trigger | только лид — команда владельца |
| 69 | context7: когда звать | role-файлы (MCP routing: context7 уже есть) — не тронуто |

## 4. Старое ядро project-rules (11, сверка)

| раздел | новый дом |
|---|---|
| frontmatter | PR frontmatter (сокращён) |
| §1 qex | PR §1 без изменений |
| §2 честность | PR §2; «Open questions» → `docs/claude/OPEN_QUESTIONS.md` (как в dot CLAUDE.md), вместо `docs/sessions/<today>.md` |
| §3 MCP | PR §3 + CLI sentrux + graphify |
| §4 коммиты | PR §4 (+ `--no-verify`; транслит — одной строкой; «git log --oneline -1 before any push» снято: push агентам запрещён) |
| §5 spawn, scope, brief, radius, evidence, Bash-цепочки, env finding | PR §5 полностью (сжато) |
| §5 модели, worktree-писатель, live GUI, public path, knobs | модели — PR §5; worktree-писатель — PR §8; live tests — PR §9; GUI-стенд — PR Map «live backend»; public path — PR §10 п.3; knobs — PR §10 |
| §6 язык | PR §6 (+ Russian явно) |
| §7 лестница | PR §7: таблица свёрнута в прозу (все роли и адресаты сохранены), блок ESCALATION дословно; колонка «Typical reason» снята — причины в первом предложении §7 |
| §8 границы сессии | SB дословно; в ядре — PR §11 |
| §9 STE-80 | STE дословно; в ядре — PR §11 |

## 5. docs/claude/memory/MEMORY.md (45)

### Указатели (7)
| строка | новый дом |
|---|---|
| CRAFT-injection | PR Map «lessons» (brace) |
| CRAFT-tests | PR Map «lessons» |
| CRAFT-verdict | PR Map «lessons» |
| CRAFT-config-qt | PR Map «lessons» |
| CRAFT-by-module | PR Map «lessons» |
| CRAFT (заглушка) | только лид — указатель на файлы выше, сам правил не несёт |
| ARCHIVE | только лид — закрытые треки |

### §1 Правила на каждую сессию (22)
| строка | новый дом |
|---|---|
| qex: get_indexing_status, возраст в промпт | PR §1; «возраст в промпт субагента» — только лид (пишет промпт) |
| Тесты: тестер до кода, инъекция, ревью запуском | PR §9 |
| Ноль наблюдений | PR Map «lessons index» (MEMORY.md §1) |
| Ноль красных | PR Map «lessons index»; CRAFT-injection |
| Правдоподобное ≠ проверенное | PR §9 («A verdict without input → observed output is advice») |
| Об ОТСУТСТВИИ | PR Map «lessons index» |
| Сторож «хоть раз» слеп | PR Map «lessons index» |
| Дублёр верен форме | PR §9 (fake-harness) + Map «lessons index» |
| Чужая сессия в том же дереве | PR §8 («A peer may share your tree: stage explicit paths only») |
| commit берёт весь индекс | PR §4 (`git add -A`), PR §8 |
| pre-commit и 2 агента | PR Map «lessons index» — recovery-рецепт, нужен редко |
| Merge в main | только лид — мержит только лид |
| Субагенты в worktree | PR §5 (spawn: `model` явно, `run_in_background: false`) |
| RU-вывод и wc врут | PR §8 (`PYTHONUTF8=1`) |
| uv sync сносит необъявленное | PR §8 (`--inexact`) |
| Глобальный taskkill | PR §8 (`TaskStop` или PID) |
| Апостроф ломает Bash | PR §8 (проза — в файл) |
| Хук жив, если проверен входом | PR Map «lessons index» — урок для правящих хуки |
| ruff сносит свежий импорт | PR §8 (импорт и использование одним Edit) |
| Посылка плана — гипотеза | PR §9 |
| Причина из плана — гипотеза | PR §9 («symptom holds to the number») |
| Число без разброса | PR Map «lessons index» |


### §2 Решения владельца (8)
| строка | новый дом |
|---|---|
| Приоритет — маятник | только лид — порядок задач выбирает лид |
| Жизненный цикл | PR Map «lessons index» → «## 2. Решения владельца (живые)» |
| Framework-first | PR §10 п.1–4 |
| Флаг закрыт, когда удалён | PR Map → «## 2. Решения владельца (живые)» |
| Ручки наблюдаемости | PR §10 (последняя строка) |
| Один пишущий логгер | PR Map → «## 2. Решения владельца (живые)» |
| Память одним модулем | PR Map → «## 2. Решения владельца (живые)» |
| Стек 2026 | PR Map → «## 2. …»; `_stack.md` |

### §3 Окружение Windows (8)
| строка | новый дом |
|---|---|
| venv держит MCP | только лид — переустановку пакетов делает лид |
| CUDA torch cu124 | PR §8 (в worktree без `uv sync`, `uv run` только `--no-sync`) |
| monotonic 15.6 мс | PR Map «lessons index» |
| qex runbook | только лид — реиндекс |
| graphify MCP | только лид — установка |
| Запуск qt-mcp | PR Map «MCP»/«live backend» + MEMORY.md |
| GUI-стенд боевым входом | PR Map «live backend» (`INSPECTOR_GUI_UNATTENDED=1`) |
| Бэкенд через backend_ctl | PR Map «live backend» (backend_ctl, qt-mcp только GUI, без psutil) |

## 6. Передача в 2.4c (ссылки в .claude/CLAUDE.md)

| строка | ссылка | состояние после 2.4b |
|---|---|---|
| `.claude/CLAUDE.md:211` | `project-rules` §7 | верна (§7 эскалация) |
| `.claude/CLAUDE.md:280` | `project-rules` §6 | верна (§6 язык) |
| `.claude/CLAUDE.md:287` | `project-rules` §9 (STE-80) | **неверна**: §9 теперь тесты; заменить на `project-rules/ste-80.md` |
| `.claude/CLAUDE.md:333` | `project-rules` §8 (границы сессии) | **неверна**: §8 теперь дерево и поиск; заменить на `project-rules/session-boundaries.md` |
