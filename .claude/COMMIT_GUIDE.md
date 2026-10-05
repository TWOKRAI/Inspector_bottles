# Inspector_bottles — формат commit-сообщений (v2)

Единственная копия гайда. Старый путь `docs/claude/COMMIT_GUIDE.md` — заглушка со ссылкой сюда.
Читают люди и агенты (developer, teamlead, lead). Hook `commit-msg` проверяет формат сам:
`scripts/validate_commit/validate_commit.py`; установка — `bash scripts/validate_commit/install_hook.sh`
(один раз на репо, `.git/hooks` не версионируется). CI-проверка для PR — тот же скрипт на каждом коммите ветки,
см. `scripts/validate_commit/README.md`.

## Шаблон

```
<type>(<scope>): краткое описание в императиве

- буллетами: что сделано (файлы, классы, числа тестов)
- акцент на реализации, не на мотивации

Why: одна-две строки про мотивацию
Layer: framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
Refs: plans/<slug>/plan.md, ADR-XXX, PR#NN
Task: <slug>#<id>
Risk: low | medium | high — короткое почему
Reversible: yes | migration-needed | no
Tested: scope/N passed
Rejected: альтернатива X — отвергнута, потому что Y
Co-Authored-By: Claude <модель> <noreply@anthropic.com>
```

**Правило блока.** Все трейлеры — один абзац в самом конце сообщения:

- между телом и блоком — одна пустая строка;
- внутри блока пустых строк нет, `Co-Authored-By` стоит в том же блоке (не отдельным абзацем);
- перенос длинного значения — со строки с отступом (пробел в начале).

Зачем: если блок разорван, `git interpret-trailers` и `git log --format=%(trailers)` не видят `Why`/`Layer`/`Refs`.
До 2026-10-04 так не видел ни один из 200 коммитов. Валидатор предупреждает (`W-TRAILERS-SPLIT`), если git не видит
трейлер.

## Пример

<!-- commit-example -->
```
docs(claude): формат коммита v2 в одной копии гайда

- .claude/COMMIT_GUIDE.md: шаблон, правило блока, привычки коммита
- docs/claude/COMMIT_GUIDE.md: заглушка со ссылкой на единственную копию
- 7 сторожей на документы (test_commit_docs.py)

Why: две копии гайда расходились, а шаблон учил разрывать блок трейлеров
Layer: docs
Refs: plans/2026-10-03_commit-mechanism/plan.md
Task: commit-mechanism#2.2
Tested: validate_commit/45 passed
Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
```

## Тема

`<type>(<scope>): <описание>`. Ориентир — 72 символа; после 72 и после 100 валидатор только предупреждает, отказа нет.
Описание — в императиве, по-русски или по-английски, не транслитом.

| `type` | Когда |
|---|---|
| `feat` | новая фича |
| `fix` | багфикс |
| `refactor` | переработка без изменения поведения |
| `docs` | только документация |
| `test` | только тесты |
| `chore` | техдолг, рутина, follow-ups |
| `perf` | оптимизация |
| `build` / `ci` | сборка / CI |
| `style` | форматирование без смысла |
| `revert` | откат |
| `merge` | слияние (без scope), см. «Слияния» |

**Scope** — модуль или подсистема (`auth`, `framework`, `data_schema`, `plugins`, `claude`, `task-5.5`). Допустимые
символы: `[a-z0-9_./,-]`; несколько — через запятую. **Breaking change** — суффикс `!`: `feat(api)!: drop legacy endpoint`.

**Body** — буллеты: имена файлов, классы, числа тестов. Описывает реализацию; мотивация — в `Why:`.

## Трейлеры

### `Why:` — обязателен

Одна-две строки про **мотивацию**: «зачем», не «что».
`Why: dev-роль должна получать все права без явного списка` — да; `Why: добавлен wildcard` — нет, это «что».

### `Layer:` — обязателен

Значения — из `.claude/commit-layers.txt` (9 слоёв); несколько — через запятую: `Layer: framework, services`.

| Значение | Где |
|---|---|
| `framework` | `multiprocess_framework/` |
| `services` | `Services/` |
| `plugins` | `Plugins/` |
| `prototype` | `multiprocess_prototype/` |
| `docs` | `docs/`, `*.md`, планы |
| `scripts` | `scripts/` |
| `tests` | только тесты |
| `infra` | `.sentrux/`, CI, hooks, `pyproject.toml`, `.claude/` |
| `mixed` | затрагивает 3+ слоя сразу |

Коммиты `backend_ctl` — `Layer: mixed` (договорённость проекта).

### `Refs:` — связь с планом

Через запятую: путь плана, `ADR-XXX`, `PR#12`, `issue#34`, хеш коммита.

На ветке, которая разрешается в план (заголовок плана `Ветка:`, каталог `plans/YYYY-MM-DD_<slug>`), `Refs:` на план
обязателен. Подходит любой существующий план; не подходят `plans/queue/…` и `*.result.md`.

### `Task: <slug>#<id>` — по желанию

`slug` — поле Slug плана без даты, `id` — номер задачи. Примеры: `commit-mechanism#2.1`, `atlas#1.3a`, `atlas#K1.1`.
Только ASCII. Нужен, чтобы по `git log --grep` собрать все коммиты одной задачи.

### Остальные (необязательные)

- `Risk:` — `low | medium | high` и короткое почему.
- `Reversible:` — `yes` (`git revert` чисто) / `migration-needed` / `no`.
- `Tested:` — скоупы и числа: `Tested: auth/120, framework/2587`. Отдельным трейлером, не в body.
- `Rejected:` — отвергнутая альтернатива и причина. Самое ценное поле через год; пиши, когда был реальный выбор.

Ключи — латиницей (`Why`, не `Зачем`): парсеры ждут её.

## Слияния

Слияние валидируется так же, как коммит: `merge: <что вошло>` + `Why:`/`Layer:`/`Refs:`.
Синхронизация ветки с main: `merge: main (<sha>) в <ветка> — <зачем>`. Текст git по умолчанию (`Merge branch …`) —
предупреждение. Слияние в `main` без формата — частая ошибка; команда — в разделе «Привычки».

## Привычки

Эти срывы повторялись; привычка закрывает каждый.

- **Сообщение — файлом.** Напиши файл инструментом Write, затем:
  `git commit -F <файл> -- <пути>`. Явные пути вместо `git add -A`. Новые (неотслеживаемые) файлы сначала
  `git add <пути>`, иначе `pathspec … did not match`. Heredoc с прозой не используй: апостроф ломает кавычки.
- **Слияние — `git merge --no-ff <ветка> -F <файл>`.** `-F -` не читает stdin. Файл пиши инструментом Write либо
  в том же вызове Bash, что и слияние: файл во временной папке может пропасть между вызовами Bash.
- **Конфликт при слиянии:** разреши, `git add <пути>`, затем `git commit -F <тот же файл>` без `-- <пути>`. С путями
  git отказывает: `fatal: cannot do a partial commit during a merge`.
- **`.py`, записанный мимо хука правки** (через Bash, `cp`, `sed`, слияние): до `git add` запусти
  `ruff format <пути> && ruff check --fix <пути>`. F401 (неиспользуемый импорт) чинится руками.
- **После `git commit` не ставь `| grep` и `| tail`.** Конвейер прячет отказ хука и подменяет код выхода. Смотри
  `git show --stat HEAD` отдельным вызовом — в коммит вошли только твои пути.

## Фаза

Новые правила v2 сейчас — предупреждения (`STRICT = False`, stderr, rc 0, пометка «error from phase 3»):
нет `Layer`; `Layer` не из списка; `Refs` на `plans/queue/`, `*.result.md` или несуществующий файл; трейлер `Task`
неверной формы; разорванный блок трейлеров; слияние без трейлеров или с текстом git по умолчанию.
Тема длиннее 72 и 100 — тоже предупреждение, но без пометки: отказа нет ни в каком режиме (решение владельца).
Отказ (rc 1) в обоих режимах — только: нет `Why`; нет `Refs` вовсе (или без пути `plans/…md`) на ветке с планом;
сломана грамматика темы или типа (например, `merge(scope)`); нет пустой строки между темой и телом. Строгий режим
включает Task 3.1 плана
`plans/2026-10-03_commit-mechanism/plan.md`.

## Зачем всё это

Коммит — единственное место, где знание необратимо привязано к коду. Структурированные трейлеры дают агенту срез
истории через `git log --grep` и `--format=%(trailers)` без чтения прозы; тебе — ответ «почему» и «что отвергли» через
год; `sentrux`/`qex` — связь коммит ↔ ADR ↔ план.

## Запросы к истории

```bash
# Все коммиты, упоминающие ADR-005
git log --grep="Refs:.*ADR-005"

# Все коммиты одной задачи
git log --grep="^Task: commit-mechanism#2"

# Все изменения в слое framework
git log --grep="^Layer: framework" --all-match

# Все high-risk коммиты за месяц
git log --since=1.month --grep="^Risk: high"

# Все отвергнутые альтернативы (для ретроспективы)
git log --grep="^Rejected:" --pretty=format:"%h %s%n%b" | grep -A1 "Rejected:"

# Трейлеры через git (работает, только если блок не разорван)
git log --pretty=format:"%H%n%(trailers:key=Refs,valueonly)"
```

## Обход

Валидатор пропускает `Revert …` и `fixup!` / `squash!` / `amend!` (interactive rebase). Полный обход —
`git commit --no-verify` — только для исправления уже закоммиченной истории, не для обычных коммитов.
