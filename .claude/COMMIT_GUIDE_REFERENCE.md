# Commit message format — full reference

Расширенный референс. Краткий TL;DR + обязательные поля — в **[`.claude/COMMIT_GUIDE.md`](COMMIT_GUIDE.md)**. Этот файл — для случаев, когда нужны детали: точные определения trailers, edge cases, history queries.

## Why bother (обоснование формата)

A commit is the only place in the project where knowledge is **irrevocably bound to code**. Wikis and ADRs drift; commit messages do not. Structured trailers let:

- **Agents** (Claude in a new session) slice history via `git log --grep`, `git log --trailer=Refs`, without reading prose.
- **You** a year from now understand "why we did this" and "what we rejected".
- **Tools** (sentrux/qex/etc.) link commit ↔ ADR ↔ plan.

ROI: ~5–10% на типовой задаче, до 30% на археологии / миграциях.

---

## Field-by-field

### Subject (first line)

Conventional Commits: `<type>(<scope>): <subject>`.

| `type` | Когда |
|---|---|
| `feat` | новая функциональность |
| `fix` | исправление бага |
| `refactor` | переработка без изменения поведения |
| `docs` | только документация |
| `test` | только тесты |
| `chore` | техдолг, рутина, follow-ups |
| `perf` | оптимизация |
| `build` / `ci` | build / CI |
| `revert` | revert |

**Scope** — модуль или подсистема (`auth`, `api`, `cli`, …). Множественные через запятую.

**Breaking change** — `!` suffix: `feat(api)!: drop legacy endpoint`.

### Body

- Bullets, имена файлов, классов, методов, числа тестов.
- Описывает **implementation**, не мотивацию. Мотивация → `Why:`.

### `Why:` — обязательный

Одна-две строки про **мотивацию**. Отвечает "почему", не "что".

```
Why: dev role should get all permissions without listing each one
```

- ❌ `Why: added wildcard` — это что, не почему.
- ✅ `Why: dev role needs all permissions without an explicit list`.

### `Layer:` — три режима поведения

Архитектурный слой. Allowed values — из `.claude/commit-layers.txt`.

| Состояние `.claude/commit-layers.txt` | Поведение `Layer:` trailer |
|---|---|
| Файл отсутствует | **required**, fallback к generic defaults: `app, lib, tests, docs, scripts, infra, build, ci, mixed` |
| Файл есть с значениями | **required**, whitelist = содержимое файла |
| Файл есть, но пустой / только комментарии | **OPTIONAL** — validator не требует |

Множественные через запятую: `Layer: app, tests`.

Чтобы кастомизировать под проект — редактируй `.claude/commit-layers.txt` (одно значение на строку, `#` для комментариев). Чтобы выключить enforcement — удали все non-comment строки.

### `Refs:` — связь с планом / ADR / PR

Через запятую. Любое из:

- путь плана: `plans/auth-rbac.md` или `plans/auth-rbac/phase-2.md`
- ADR код: `ADR-005`
- PR / issue: `PR#12`, `issue#34`
- commit hash: `b073abe`

```
Refs: plans/auth-rbac/phase-3.md, ADR-005, PR#12
```

**Hook enforcement:** если текущая ветка матчится `<conv-type>/<slug>` (например `feat/auth-rbac`) И существует `plans/<slug>.md` (или `plans/<slug>/plan.md`), коммит ОБЯЗАН содержать `Refs:` trailer на этот план. Hook отклоняет коммиты без него.

**Skip cases:**
- Hotfix / experiment branches (`tmp/spike`, `wip-debug`) — не триггерят проверку, только Conventional Commits типы веток.
- Detached HEAD — skipped (нет ветки → нет привязки к плану).

### `Risk:` — оценка риска

`low | medium | high` + короткое почему.

```
Risk: medium — changes shared lifecycle, regression possible in IPC
```

### `Reversible:` — обратимость

- `yes` — `git revert` работает чисто
- `migration-needed` — требуется обратная миграция (DB schema, формат данных)
- `no` — данные / контракт изменены необратимо

### `Tested:` — что зелёное

Scopes и числа.

```
Tested: auth/120, core/2587, ui/1064
```

### `Rejected:` — отвергнутые альтернативы (opt-in, но ценно)

```
Rejected: hardcoded role-check — rejected, inflexible for custom roles
Rejected: separate wildcard_grant() — rejected, extra API surface
```

Самое ценное поле через год. Не пропускай, когда было реальное сравнение вариантов.

---

## Полный пример

```
feat(auth): declarative permission fields in BaseControlConfig

- BaseControlConfig: required_view_permission and required_edit_permission fields
- NumericPresenter/CheckboxPresenter read fields from view_config
- presenter.set_access_context(AccessContext) applies full context
- 7 new tests on BaseControlConfig.permissions and AccessTrait flow

Why: remove manual permission checks from tab code, unify with trait-based gating
Layer: app
Refs: plans/auth-rbac/phase-3.md, ADR-005
Risk: low — changes are local to config + presenter
Reversible: yes
Tested: auth/120, core/2587
Rejected: setattr-runtime on widget — rejected, loses config typing

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Use by agents

Промпты в `.claude/agents/*.md` знают про эти trailers. Slash-команды `/ship` и `/pipeline` показывают шаблон в выводе. Если агент забыл — hook отклоняет коммит и просит исправить.

---

## History queries cheat-sheet

```bash
# Все коммиты с упоминанием ADR-005
git log --grep="Refs:.*ADR-005"

# Все изменения в слое `app`
git log --grep="^Layer: app" --all-match

# Все high-risk коммиты за месяц
git log --since=1.month --grep="^Risk: high"

# Все отвергнутые альтернативы (для ретроспектив)
git log --grep="^Rejected:" --pretty=format:"%h %s%n%b" | grep -A1 "Rejected:"

# Через git interpret-trailers напрямую
git log --pretty=format:"%H%n%(trailers:key=Refs,valueonly)"
```

---

## Bypass

Validator пропускает:

- `Merge ...` коммиты
- `Revert ...` коммиты
- `fixup!` / `squash!` / `amend!` (interactive rebase)

Полный bypass — `git commit --no-verify`. Использовать **только** для исправления уже закоммиченной истории, не для нормальных коммитов.
