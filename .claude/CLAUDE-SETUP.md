# Установка `.claude/` в новый проект

Эта папка — самодостаточная конфигурация Claude Code (агенты, команды, режимы, хуки, MCP-серверы, шаблоны). При копировании в новый проект всё разворачивается одной командой.

> **Хочешь сначала понять, что в системе и кто за что отвечает?** Читай [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) — 8 слоёв (memory / modes / agents / commands / skills / hooks / MCP / observability), таблица ownership, coverage matrix, tool routing, gap analysis. Это карта системы как единого организма.

---

## Быстрый путь (рекомендуется)

Используй `claude-kit` CLI (поставляется как Python-пакет; bundled template
лежит в `src/claude_kit/template/`):

```bash
claude-kit new ~/Project_code/my_app \
  --name "My App" \
  --description "Short description"
cd ~/Project_code/my_app
make gate                                # должен быть зелёным
```

Что делает `claude-kit new` — подробно в [`BOOTSTRAP.md`](BOOTSTRAP.md) → "Part 2".

Если MCP-инфраструктура (qex/sentrux/context7) нужна:
```bash
# .mcp.json уже создан claude-kit new. Для добавления компонента: claude-kit add <component>
npx -y ctx7 setup --claude              # один раз на машину, OAuth
```

Перезапусти Claude Code и проверь:
```
> /mcp
```

Подробности — в [`mcp/README.md`](mcp/README.md).

---

## Иерархия загрузки CLAUDE.md

Claude Code читает в порядке:

1. `~/.claude/CLAUDE.md` — глобальные настройки (на машине)
2. `./CLAUDE.md` — настройки проекта **(основная точка)**
3. `./.claude/CLAUDE.md` — расширения (modes, layout map, language policy)
4. `./CLAUDE.local.md` — локальные (gitignored)

Корневой `CLAUDE.md` — single source of truth для проектного контекста (стек, пути, правила). `.claude/CLAUDE.md` — описывает workflow, plan-driven чейн, memory override; должен оставаться универсальным между проектами.

---

## Проверка работы после bootstrap

```bash
make help            # доступные цели
make gate            # lint + типы + тесты
git log --oneline    # должен быть один commit "chore(seed): bootstrap …"
git config core.hooksPath || ls .git/hooks/commit-msg   # commit-msg hook установлен
```

Все зелёные → ready to develop.

---

## Структура `.claude/`

```
.claude/
├── CLAUDE.md              # Project layout map + memory override + commands index
├── CLAUDE-SETUP.md        # Этот файл
├── BOOTSTRAP.md           # Полный гайд установки (зависимости + per-project + optional)
├── README.md              # Навигация по папке
├── STACK.md               # Toolchain с обоснованиями
├── COMMIT_GUIDE.md        # Полный гайд по commit-формату (canonical)
├── settings.json          # Tools allowlist + хуки + statusLine
├── settings.local.json    # Локальный override (gitignored)
├── commit-layers.txt      # Whitelist для Layer trailer (пустой = Layer optional)
│
├── agents/                # Sub-агенты
│   ├── _template.md       # Шаблон для /hire
│   └── company/           # IT-Команда (manager, developer, reviewer, …)
│
├── commands/              # Slash-команды (/plan, /implement, /memory:*, …)
│   ├── dev/               # /plan, /implement, /test, /ship, /pipeline, …
│   ├── infra/             # /cold-start, /clean-cache, /diagrams, /run-proto
│   ├── memory/            # /memory:init, /memory:status, /memory:search
│   ├── quality/           # /qex-*, /sentrux-*, /code-stats, /test-ratio, …
│   ├── spec/              # /spec, /spec-sync
│   └── team/              # /team, /hire, /handoff, /docs, /wrap-up
│
├── memory/                # Долговременная память (MEMORY.md + per-memory .md)
├── modes/                 # Режимы (dev.md, spec.md, _stack.md)
├── hooks/                 # Pre/Post-tool хуки (core/ + python/)
├── skills/                # Skills для агентов (пустая по дизайну)
├── platforms/             # Платформо-зависимые конфиги (если нужны)
├── templates/             # То, что разворачивается `claude-kit new`:
│   ├── pyproject.template.toml, Makefile.template, …
│   ├── claude-md.template.md (root CLAUDE.md)
│   ├── PLAN.template.md (для Manager)
│   ├── commit-layers.template.txt
│   ├── scripts/{validate_commit,code_stats,test_ratio,clean_cache}/ (→ scripts/)
│   └── plans-readme.template.md, docs-sessions-readme.template.md
│
├── mcp/                   # MCP-инфраструктура (кросс-платформа)
│   ├── README.md          # Документация по MCP
│   ├── qex-launcher.py    # Кросс-платформенный launcher для qex
│   ├── qex/               # Core: семантический поиск
│   ├── sentrux/           # Core: архитектурный health-gate
│   ├── context7/          # Core: документация библиотек
│   ├── qt-mcp/            # Opt-in: PyQt/PySide runtime inspection
│   ├── graphify/          # Opt-in: knowledge graph + HTML viz
│   ├── serena/            # Opt-in: LSP-symbol операции
│   ├── codegraph/         # Opt-in: function call graph + impact
│   ├── github/            # Opt-in: official GitHub MCP (Issues/PR/Actions)
│   └── ast-grep/          # Opt-in: structural search + rewrite (codemods)
│
└── observability/         # Opt-in: OTel-telemetry, ccusage, замер MCP-маржи
    ├── README.md
    └── SETUP_GUIDE.md
```

Полное описание ответственности каждого инструмента — в [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md).

---

## Ручная установка (без `claude-kit new`)

Минимум — в [`BOOTSTRAP.md`](BOOTSTRAP.md) → "Part 3. Per-project setup (the manual path)".

Локальные настройки (опционально):
```bash
echo "CLAUDE.local.md" >> .gitignore
echo ".claude/settings.local.json" >> .gitignore
echo ".claude/CLAUDE.local.md" >> .gitignore
```

---

## Обновление seed → проект (sync-back)

По мере работы в проекте улучшаешь `.claude/` (правишь команды, агентов, шаблоны). Чтобы вернуть улучшения в канонический seed:

```bash
claude-kit sync-back .                   # из cwd проекта
claude-kit sync-back /path/to/project --dry-run --verbose
```

`claude-kit sync-back` исключает project-specific вещи (`.DS_Store`,
`__pycache__`, `memory/`, `settings.local.json`). Делает tar.gz backup
перед записью в canonical (`--apply` для реального применения).

---

## Ресурсы

- [Официальная документация Claude Code](https://code.claude.com/docs/en/best-practices)
- [HumanLayer — Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)
