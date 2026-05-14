# Inspector_bottles — формат commit-сообщений

Единый источник истины: как писать commit'ы в этом репо. Читают и люди, и
агенты (Claude в роли developer/teamlead). Обязательно для всех, кто
коммитит в `main`.

## TL;DR

```
<type>(<scope>): краткое описание в императиве

- буллетами: что сделано (файлы, классы, числа тестов)
- акцент на реализации, не мотивации

Why: одна-две строки про мотивацию
Layer: framework | services | plugins | prototype | docs | scripts | tests
Refs: docs/plans/.../*.md, ADR-XXX, PR#NN
Risk: low|medium|high — короткое почему
Reversible: yes | migration-needed | no
Tested: scope/N passed, например auth/120
Rejected: альтернатива X — отвергнута, потому что Y

Co-Authored-By: ...
```

**Обязательны:** subject + `Why:` + `Layer:`. Остальное — opt-in, добавляй
если есть что сказать.

**Hook валидирует автоматически:** `git commit` без `--no-verify` запустит
`scripts/validate_commit/validate_commit.py` и откажет, если формат сломан.
Установка: `bash scripts/validate_commit/install_hook.sh` (один раз на репо).

## Зачем

Коммит — единственное место в проекте, где знание **необратимо привязано
к коду**. Wiki и ADR могут устареть; commit message — никогда.
Структурированные trailers позволяют:

- **Агенту** (Claude в новой сессии) собрать срез истории через
  `git log --grep`, `git log --trailer=Refs`, не читая прозу.
- **Тебе** через год понять «почему мы это сделали» и «что отвергли».
- **sentrux/qex** строить связь commit ↔ ADR ↔ план.

ROI ~5–10% на средней задаче, до 30% на археологии/миграциях. Подробнее
про trade-off — в обсуждении 2026-05-11 в чате (это запомнено).

## Подробно по полям

### Subject (первая строка)

Формат Conventional Commits: `<type>(<scope>): <subject>`.

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
| `revert` | откат |

**Scope** — модуль или подсистема (`auth`, `framework`, `data_schema`,
`plugins`, `frontend_module`, …). Допускается несколько через запятую.

**Breaking change** — суффикс `!`: `feat(api)!: drop legacy endpoint`.

### Body (что сделано)

- Буллеты, имена файлов, классы, методы, числа тестов.
- Описывай **реализацию**, не мотивацию. Мотивация → `Why:`.

### `Why:` — обязательно

Одна-две строки про **мотивацию**. Отвечает на «зачем», не «что».

```
Why: dev-роль должна получать все права без перечисления каждого
```

❌ `Why: добавлен wildcard` — это что, не зачем.
✅ `Why: dev-роль должна получать все права без явного списка`.

### `Layer:` — обязательно

Слой архитектуры из CLAUDE.md (правило 9). Допустимые значения:

| Значение | Где |
|---|---|
| `framework` | `multiprocess_framework/` |
| `services` | `Services/` |
| `plugins` | `Plugins/` |
| `prototype` | `multiprocess_prototype/` |
| `docs` | `docs/`, `*.md` |
| `scripts` | `scripts/` |
| `tests` | только тесты |
| `infra` | `.sentrux/`, CI, hooks, `pyproject.toml` |
| `mixed` | затрагивает 3+ слоя одновременно |

Несколько через запятую: `Layer: framework, services`.

### `Refs:` — связь с планами/ADR

Через запятую. Любое из:

- путь к плану: `docs/plans/auth-rbac/04-pr4-audit.md`
- ADR-код: `ADR-Auth-005`, `ACT-001`
- PR/issue: `PR#12`, `issue#34`
- хеш коммита: `b073abe`

```
Refs: docs/plans/auth-rbac/03-pr3.md, ADR-Auth-005, PR#12
```

### `Risk:` — оценка риска

`low | medium | high` + короткое почему.

```
Risk: medium — меняется shared-resource lifecycle, регресс возможен в IPC
```

### `Reversible:` — обратимость

- `yes` — `git revert` без боли
- `migration-needed` — нужна обратная миграция (схема БД, формат данных)
- `no` — данные/контракт изменены необратимо

### `Tested:` — что зелёное

Скоупы и числа.

```
Tested: auth/120, framework/2587, frontend/1064
```

### `Rejected:` — отвергнутые альтернативы (опц., но ценно)

```
Rejected: hardcoded role-check — отвергнут, негибко для custom-ролей
Rejected: отдельный wildcard_grant() — отвергнут, лишний API surface
```

Самое ценное поле через год. Не ленись заполнять, когда было реальное
сравнение вариантов.

## Полный пример

```
feat(auth): декларативные permission-поля в BaseControlConfig

- BaseControlConfig: поля required_view_permission и required_edit_permission
- NumericPresenter/CheckboxPresenter читают поля из view_config
- presenter.set_access_context(AccessContext) применяет полный контекст
- AccessTrait уже умел работать с AccessContext — подключаем
- 7 новых тестов на BaseControlConfig.permissions и AccessTrait flow

Why: убрать ручной permission-проверки из tab-кода, унифицировать с trait-based gating
Layer: framework
Refs: docs/plans/auth-rbac/03-pr3-permissions.md, ADR-Auth-005
Risk: low — изменения локальны в config + presenter
Reversible: yes
Tested: auth/120, framework/2587
Rejected: setattr-runtime на widget — отвергнут, теряется типизация конфига

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Что НЕ нужно делать

- ❌ Не дублируй body и `Why:` — body про реализацию, Why про мотивацию.
- ❌ Не пиши в Why «added X to fix Y». Пиши **почему нужно было X**.
- ❌ Не используй `--no-verify` для обхода hook — это для merge/rebase.
- ❌ Не пиши Russian-trailers (`Зачем:`, `Слой:`) — парсеры ждут латиницу.
- ❌ Не пиши Tested в body — отдельным trailer, чтобы grep работал.

## Использование агентами

Промпты `.claude/agents/company/developer.md` и `teamlead.md` обновлены —
агенты автоматически генерируют все trailers. Если агент забыл — hook
отклонит коммит и попросит исправить.

Слэш-команды `/ship` и `/pipeline` показывают шаблон в выводе.

## Запросы к истории (cheat-sheet)

```bash
# Все commits, упоминающие ADR-Auth-005
git log --grep="Refs:.*ADR-Auth-005"

# Все changes в слое framework
git log --grep="^Layer: framework" --all-match

# Все high-risk коммиты последнего месяца
git log --since=1.month --grep="^Risk: high"

# Все отвергнутые альтернативы (для ретроспективы)
git log --grep="^Rejected:" --pretty=format:"%h %s%n%b" | grep -A1 "Rejected:"

# Использование git interpret-trailers напрямую
git log --pretty=format:"%H%n%(trailers:key=Refs,valueonly)"
```

## Установка hook

Один раз на репо:

```bash
bash scripts/validate_commit/install_hook.sh
```

Hook ставится в `.git/hooks/commit-msg` (не версионируется git'ом, поэтому
не общий). Если делишь репо с другим разработчиком — пусть он тоже
запустит установку.

CI-проверка (опционально, для PR): запустить тот же скрипт на каждом
коммите ветки. См. `scripts/validate_commit/README.md`.

## Bypass

Валидатор пропускает:

- `Merge ...` коммиты
- `Revert ...` коммиты
- `fixup!` / `squash!` / `amend!` (для interactive rebase)

Полный обход — `git commit --no-verify`. Используй **только** для
исправления уже закоммиченной истории, не для обычных коммитов.
