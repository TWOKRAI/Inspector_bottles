# plans_progress — прогресс планов по единому эталону

Читает планы из `plans/` и `plans/_archive/`, считает `N из M` по задачам и строит страницу.
Только stdlib. План: [`plans/2026-10-02_plans-progress-dashboard.md`](../../plans/2026-10-02_plans-progress-dashboard.md).

## Команды

```
python scripts/plans_progress/plans_progress.py --json
python scripts/plans_progress/plans_progress.py --html data/plans_progress.html
python scripts/plans_progress/plans_progress.py --check --baseline plans/queue/progress-baseline.txt
```

| Флаг | Что делает |
|---|---|
| `--root DIR` | каталог с `plans/` (по умолчанию корень репозитория) |
| `--order PATH` | `ORDER.md` (по умолчанию `<root>/plans/queue/ORDER.md`); нет файла — полосы `null` |
| `--json` | список планов: `plan`, `path`, `archived`, `lane`, `tier`, `done`, `total`, `dropped`, `unknown`, `tasks` |
| `--html [PATH]` | страница без внешних ресурсов; по умолчанию `data/plans_progress.html` |
| `--check` | печатает находки линта; exit 1 при новой блокирующей находке |
| `--baseline PATH` | известные блокирующие находки (`<план>:<КОД>[:<id>]`); из базы не блокируют |
| `--sync-order` | переписать блок прогресса между `<!-- progress:begin -->` и `<!-- progress:end -->` в `ORDER.md`; вне блока байты и EOL не меняются; нет файла или маркеров — exit 2, файл не трогается |

Без флагов печатает сводную таблицу.

## Эталон строки задачи

Задачи живут в разделе `## Порядок выполнения` (или `Execution order`, `Порядок`) файла `plan.md`.

| Элемент | Правило |
|---|---|
| Пункт | `- Task <id>: название [СТАТУС]`; допустим `**` перед `Task`; строки-продолжения принадлежат пункту |
| Статус | первая группа `[...]` со словом набора, код-спаны не считаются; слово не примыкает к букве, `_`, `-` |
| Набор слов | `PENDING`, `IN PROGRESS`, `DONE`, `BLOCKED`, `DEFERRED`, `SUPERSEDED` (`SKIPPED`/`CANCELLED` → `SUPERSEDED`) |
| Статус в заголовке задачи | `[...]` в строке заголовка; иначе хвост вне скобок: `✅`, `— DONE 50df705f`, `(ЗАКРЫТА 2026-08-03)` (слово — только перед датой, хешем или пояснением в скобках) |
| Хвост | допустим у любого статуса: `[DONE 2026-10-02 — \`hash\`; числа]`; незакрытая группа идёт до конца пункта |
| Без статуса | `~~Task X.Y~~` и `СНЯТА` → `superseded`; иначе `unknown` (`?`) |
| Родитель | пункт без статуса, за которым идёт более глубокий пункт, — не задача |
| Набор плана | если в разделе есть пункты — только они; иначе заголовки `#{2,6} Task`, затем таблица `✓`, затем `tasks/<id>.md` |
| Процент | `done / (всего − deferred − superseded − unknown)`; рядом всегда `N из M` |

Находки: `NO_TASKS` и `UNKNOWN_STATUS` блокируют только для планов §4.1 `ORDER.md`; `DUP_ID` блокирует всегда;
`UNCLOSED_FENCE` (нечётное число ограждений кода) блокирует так же, как `NO_TASKS`, — только для §4.1;
`DUP_HEADING`, `STATUS_CONFLICT`, `NO_DATE_IN_NAME`, `ALL_DONE_NOT_ARCHIVED`, `NO_STATUS_MARK`, `TASK_ID_UNPARSED`, `NOT_UTF8` — информационные.
`ORDER_BLOCK_STALE` (блок устарел) и `ORDER_BLOCK_MISSING` (нет пары маркеров) блокируют, но только на ветке `main`
в корне git-репозитория (`--root` равен `git rev-parse --show-toplevel`); в ветках, при detached HEAD, вне git и в корне,
вложенном в чужой репозиторий, блок не проверяется. Писатель блока — лид в `main`, в точке слияния.
`--check` без `plans/`, без живых планов или с отсутствующим `--baseline` завершается кодом 2.
Архивные планы линт не смотрит.

## Что показывает страница и блок

Страница `--html`: основной список — планы §4.1 `ORDER.md` (порядок таблицы); `<details id="waiting">` — §4.2
(ждут триггера); `<section id="unlisted">` — планы, которых нет в таблицах `ORDER.md` (новый план не пропадает,
пока лид не внесёт его в очередь); `<details id="archive">` — `_archive/` и закрытые §4.3. Карточки полос считают
только очередь, ждущих и «нет в ORDER».
Блок `--sync-order`: строки для §4.1, §4.2 и планов без яруса; «в архиве» включает закрытые §4.3.
`--json` и `--check` не сужаются: в них все планы, ярус — в поле `tier`.

## Слияние ветки в main (порядок лида)

Блок прогресса в `ORDER.md` пишет один человек — лид на `main`. Блок читает **рабочее** дерево, поэтому
`--sync-order` идёт после слияния и до коммита. Хук `protect-branch` блокирует прямой коммит на `main`,
поэтому коммит делает `git merge --continue`:

```
git merge --no-ff --no-commit <ветка>
python scripts/plans_progress/plans_progress.py --sync-order
git add plans/queue/ORDER.md
git merge --continue
```

На ветках `--sync-order` не запускают: два писателя блока дают конфликт в одном hunk.

## Тесты

```
python -m pytest scripts/plans_progress/tests/test_acceptance_progress.py scripts/plans_progress/tests/test_author_hazards.py -q
```
