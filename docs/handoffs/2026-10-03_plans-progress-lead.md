# Handoff лида: plans-progress-dashboard (2026-10-03)

План (layout v2 с 2026-10-03): `plans/2026-10-02_plans-progress-dashboard/plan.md`, формат и интерфейс — `design.md` рядом, тела задач — `tasks/<id>.md`. Ветка `feat/plans-progress-p2` (worktree `.claude/worktrees/team-plans-p2-impl`), поверх Фазы 1, которая уже в `main` (`3e79b264a`, ff). Прежний handoff: `2026-10-02_plans-progress-lead.md` (Фаза 1).

## Раскладка плана (2026-10-03)
- Файл плана (46 КБ, бюджет 32 КБ) разложен в layout v2: `plan.md` 9,7 КБ, `design.md`, `tasks/<id>.md` ×20, `tasks/<id>.result.md`, `reports/` (длинные отчёты 1.0 и 1.1).
- Оба парсера дают на нём 8 из 19; `plans_ledger.py status --check --plan` без находок; `brief` собирается для всех задач.
- Добавлена Фаза 5 «Доска сессий» (журнал агентов → `active` в `--json` → чип и секция «Кто где»); `claim` отложен (5.4).
- Первый план проекта в layout v2: образец формата. Остальные планы приводят их владельцы; сообщение соседним сессиям не отправлено, ждёт отработки образца.
- Fable на ревью формата, плана и идеи — только после вопроса владельцу (лимит был 94%).

## Решения владельца (2026-10-03), которых нет в коде
- Страница и блок `ORDER.md` показывают только очередь и актуальное по `ORDER.md`: §4.1 основной список, §4.2 свёрнуто, «Нет в ORDER.md» видно, §4.3 и архив свёрнуты вместе.
- После ревью Opus (`ab3dd4bcfffd1386a`, оценка готовности к переносу 2/10) владелец сказал «давай»: сид защищён условием, блок не блокирует, закрытый план показывает статус, Фаза 3 сужена до поля `После:`, Фаза 4 «в сид» по шагам Opus.
- Процент в строке числа остаётся рядом с чипом «закрыт» (понято как «вместо полосы»); вопрос владельцу не снят.

## Состояние
| Что | Где | Состояние |
|---|---|---|
| Tasks 2.1–2.3 | коммиты `2baee0621`, `d642c4f46`, `06d7c4a3d` | DONE, ревью APPROVED |
| Task 2.4 (область очереди) | `491d14ab9` | код и тесты есть, ревью раунд 1 прошёл |
| Task 2.5 (доверие к цифрам, защита сида) | `6ffa29d5a`, правки `e4a04dd15` | 427 тестов зелёные; инъекции лида: T01–T17 и V01–V06 убиты (T03, T13 закрыты тестами лида) |
| Ревью 2.4+2.5, раунд 2 | reviewer `a0e1aa578a8278f9f` | на момент записи идёт |
| Слияние Фазы 2 в `main` | не сделано | порядок ниже |

## Слияние в main (только лид)
1. Спросить лида transport SHA его ветки `fix/t55c-gate-green` (обещал написать до своего слияния); `main` сдвигается чужими слияниями (`68fb2e6df` и далее).
2. В корневом дереве (чистом, без чужих правок; сейчас там незакоммиченные `.claude/agent-memory/*` — не трогать): `git merge --no-ff --no-commit feat/plans-progress-p2`.
3. `python scripts/plans_progress/plans_progress.py --sync-order` на слитом дереве, `git add plans/queue/ORDER.md`, `git merge --continue` (сообщение — файлом, `git merge -F -` не читает stdin; хук `protect-branch` блокирует обычный commit на main, merge --continue проходит).
4. `--check --baseline plans/queue/progress-baseline.txt` на main: exit 0; затем убрать worktree: `team-plans-p2-red` (вложен в `plans-progress` по ошибке пути), `team-plans-p2-impl`, `plans-progress`, ветки `red/plans-progress`, `red/plans-progress-p2`, `feat/plans-progress` (после ff).

## agentId (адрес — id, не имя)
| Роль | agentId | Состояние |
|---|---|---|
| developer (весь трек, автор `plans_progress.py`) | `aa708fe5916fb3d06` | 497k токенов суммарно; **не возобновлять для Фазы 3** — новый механизм, свежий контекст |
| reviewer (раунды 2.2/2.3, 2.4/2.5) | `a4c70512b4f5c4394` — ревью Фазы 1; `a0e1aa578a8278f9f` — 2.2–2.5 | раунд 2 по 2.4+2.5 может идти |
| reviewer Opus, стратегическое | `ab3dd4bcfffd1386a` | завершён; его отчёт — основа Фазы 4 |
| tester (слепой, Фаза 1) | `ae90ecf68e0e71791` | завершён |
| tester (слепой, Tasks 2.2+2.3) | `aaeab216994575d9e` | завершён; для Фазы 3 нужен СВЕЖИЙ слепой тестер |
| teamlead (Task 1.0, ledger) | `ae4f14740888447dc` | завершён |

## Состояние после ревью Fable и рассылки (2026-10-03, вечер)
- `main` = `354703451` (мой последний слив). Образец формата — `plans/2026-10-02_plans-progress-dashboard/` (layout v2), оба парсера: 10 из 25, ledger без находок, `plans_progress` 440 passed.
- Ревью Fable (`cto`, agentId `aa901c89dc065c3a9`, 170k токенов): отчёт `plans/2026-10-02_plans-progress-dashboard/reports/review-fable-2026-10-03.md`. Главное: Task 5.1 чинила не тот хук (живой — `.claude/plugins/observability/hooks/agent-journal.sh`, журнал `data/agent-journal.jsonl`); карта «ветка → план по шапке» работает у 3 веток из 71. Все правки внесены в план.
- Сделано после ревью: 3.5 (шаблоны, `3763a1b47`, тест `8284084dd`), 3.6 (README, сноска «Хранение», `dev.md`/`tester.md`/`executor-brief.md`, `4440e0a22`); тест-контракт `scripts/plans_progress/tests/test_templates_contract.py` — 13 тестов, 16 инъекций, все предсказания совпали. Новые задачи 5.5 (прогресс актуальных веток против `main`) и 5.6 (радар пересечений).
- Рассылка отправлена `inspector-bottles-f0` и `inspector-bottles-f4`. Ответы: f0 взял только `layer-render` (правок не нужно). f4 взял `transport-single-policy`: правка плана `31f846e92` на `feat/transport-f5`, в `main` придёт со слиянием ветки фазы. После этого слияния: `--sync-order` и сверка (ожидаемо 18 из 22 = 34 − 7 DEFERRED − 5 SUPERSEDED).
- Планы без владельца (сессий нет): `line-sim*`, `letters-retrain`, `observability-*`, `telemetry-*`, `observation-port`, `otel`, `pult-control-panel`, `draw-mode-rework`, `dataset-circle-capture`, `proto-frontend-carve`, `sim-lateral-offset` и `undo-restores-selection` (оба ALL_DONE_NOT_ARCHIVED).
- Ждут решения владельца: внести образец в ledger (`plans_ledger.py add`) и в `ORDER.md` §4.1; путь к репозиторию claude-kit (Фаза 4, задачи 4.2–4.4); судьба ветки `red/plans-progress`; второй Fable — только перед Фазой 4 и только по вопросу владельцу (лимит).
- Актуальная ветка (решение владельца): есть коммиты сверх `main` и последний не старше порога; замер 71 ветка → 31 с коммитами сверх `main`, 19 за двое суток.

## Состояние на конец 2026-10-03 (после 5.1, 3.1, 3.2)
- В `main`: Фаза 2, Task 5.1 (журнал агентов пишет `session_id`, `branch`, `source`; проводка `SessionStart`), Task 3.1 (`608d609c6`: поле `После:`, `ready`, `DEP_*`), Task 3.2 (`113f9a61e`: чипы и `#ready`). Итоги — `tasks/<id>.result.md`, отчёты — `reports/<id>.md`.
- Формат слияния (решение владельца через f0): `merge: Task N — суть` + буллеты + `Why:`/`Layer:`/`Refs:`/`Co-Authored-By`. Поток: `git merge --no-ff --no-commit <ветка>` → `--sync-order` → `git add plans/queue/ORDER.md` → переписать `.git/MERGE_MSG` → `GIT_EDITOR=true git merge --continue`. Хук отказа на «Merge branch…» делает f0.
- На реальном дереве поле `После:` не пишет ни один план, поэтому `#ready` = «не определено». Ценность страницы появится с Task 3.3.
- Сессии перезапущены, имена сменились (`e4`, `68`, `7d`): SHA слияния 3.2 сессии f4 commit-mechanism не отправлен, адрес неизвестен.
- agentId задач 3.x: tester 3.2 `a3d8e49699edf62df`, developer 3.2 `ab329d6e3f89d10fb`, reviewer 3.2 (оба круга) `a92efb7ada3b12c6e`.

## Дальше (в порядке)
1. Task 5.2 (`active` в `--json`, резолвер «worktree → план»; заметки в `tasks/5.2.md`: пропускать пустые поля, использовать `source`, журнал исчезает вместе с worktree).
2. Затем 5.3, 5.5, 5.6, потом 3.3, 3.4, 5.4; Task 1.3 (отчёт расхождений `robot-protocol-v2`); 4.1 без гейта.
3. Страница глазами в браузере: секции, чипы, тёмная тема, узкий экран (Chrome не даёт `file://` — `python -m http.server` на `data/`, порт 8765; остановить по PID).
4. Фаза 4 — только после 1–2 недель практики и пути к репозиторию claude-kit (вопрос владельцу открыт).
5. Открытое — `docs/claude/OPEN_QUESTIONS.md`, раздел «plans-progress: нерешённое»; плюс вопрос «живая или архивная копия одного имени» (решает архивная; ревью 3.1 советует живую, если она открыта).

## Ловушки сессии
- Heredoc с `\n`, `\\`, `\r` в Bash → Python съедает слоями; скрипты с такими литералами — через Write и запуск файлом.
- Хук lint-brief: брифы агентам требуют блоков DESIGN (≥3 строки) / FILES / REDS / REPORT; не перечисляй их в одну строку.
- `git worktree add` с относительным путём изнутри другого worktree создаёт вложенное дерево — путь только абсолютный от корня.
- Тесты в tmp_path лежат внутри git-репозитория `C:\Users\INNOTECH` на ветке main: для теста «не main» нужен `GIT_CEILING_DIRECTORIES`.
- Просьбы соседних сессий придержать pytest на время замеров стенда (f4) выполнять; их писать в тот же канал.
- pre-commit (ruff-format, trailing-whitespace) отклоняет первый коммит — `git add` заново, проверить `git log -1`.
- Python через heredoc в Bash портит `\n` и `\r\n` в строковых литералах (три раза за день): скрипты с такими строками писать инструментом Write и запускать файлом; для одиночной правки литерала — `chr(92)`, `chr(13)`, `chr(10)`.
- `git add` с несколькими путями падает целиком, если один путь уже не существует (после `git mv`/`git rm`): коммит получается неполным. Стейджить `git add -A <каталог>` и проверять `git show --stat`.
- `git worktree remove` из каталога внутри worktree даёт «Permission denied» или «Device or resource busy»: перейти в корень `main`, затем `prune`, `branch -d`, `rmdir` (иногда со второго вызова).
- `rm -rf` в Bash отклоняется правилами: создавать свежий каталог (`mkdir -p "$TEMP/x_$$"`).
- Рекурсивный `grep -r` по всему репозиторию (в нём около 70 worktree) уходит в таймаут: искать инструментом Grep с `glob` и узким `path`, не трогать `.claude/worktrees`.
