# Установка `.claude/` в новый проект

Эта папка — самодостаточная конфигурация Claude Code (агенты, команды, режимы, хуки, MCP-серверы). При копировании в новый проект всё разворачивается одной командой.

---

## Быстрый путь (рекомендуется)

```bash
# 1. Скопировать .claude и корневой CLAUDE.md в новый проект
cp -r /path/to/Inspector_bottles/.claude /path/to/new-project/
cp /path/to/Inspector_bottles/CLAUDE.md /path/to/new-project/

# 2. Запустить bootstrap MCP-инфраструктуры (кросс-платформа)
cd /path/to/new-project
python3 .claude/mcp/bootstrap.py    # macOS / Linux
# python .claude/mcp/bootstrap.py   # Windows

# 3. Если Context7 ещё не настроен на этой машине
npx -y ctx7 setup --claude

# 4. Перезапустить Claude Code
```

`bootstrap.sh` сам:
- проверит `brew` и поставит **sentrux** если нет
- проверит **ollama** и подскажет `ollama pull` если модель не загружена
- проверит **node/npx** (нужен для Context7)
- скопирует `.claude/mcp/mcp.template.json` → `./.mcp.json`

Подробности — в [`mcp/README.md`](mcp/README.md).

---

## Иерархия загрузки CLAUDE.md

Claude Code читает в порядке:

1. `~/.claude/CLAUDE.md` — глобальные настройки (на машине)
2. `./CLAUDE.md` — настройки проекта **(основная точка)**
3. `./.claude/CLAUDE.md` — расширения (modes, language policy)
4. `./CLAUDE.local.md` — локальные (gitignored)

Корневой `CLAUDE.md` — single source of truth для проектного контекста (стек, пути, правила). `.claude/CLAUDE.md` — описывает сам KnowledgeOS workflow и должен оставаться универсальным между проектами.

---

## Проверка работы

После рестарта Claude Code:

```
> /mcp
```

Должны быть зелёные:
- `qex` — семантический поиск
- `sentrux` — архитектурный анализ
- `context7` — документация библиотек

Если красное — см. troubleshooting в [`mcp/README.md`](mcp/README.md).

---

## Структура `.claude/`

```
.claude/
├── CLAUDE.md              # Workflow обеих команд + language policy
├── CLAUDE-SETUP.md        # Этот файл
├── README.md              # Навигация по папке
├── settings.json          # Tools allowlist + хуки + statusLine
├── settings.local.json    # Локальный override (gitignored)
│
├── agents/                # Sub-агенты
│   ├── _template.md       # Шаблон для /hire
│   └── company/           # IT-Команда (developer, reviewer, manager, ...)
│
├── commands/              # Slash-команды (/plan, /implement, /test, ...)
├── modes/                 # Режимы (dev.md, spec.md)
├── hooks/                 # Pre/Post-tool хуки
├── skills/                # Skills для агентов
├── platforms/             # Legacy platform-specific конфиги
│
└── mcp/                   # MCP-инфраструктура (кросс-платформа)
    ├── README.md          # Документация по MCP
    ├── mcp.template.json  # Эталон проектного .mcp.json
    ├── qex-launcher.py    # Кросс-платформенный launcher для qex (macOS/Linux/Windows)
    └── bootstrap.py       # Автоустановка для нового проекта (Python = везде работает)
```

---

## Ручная установка (если bootstrap не подходит)

### 1. CLAUDE.md в корне
```bash
cp /path/to/source/CLAUDE.md /path/to/new-project/CLAUDE.md
```

Адаптируй под новый проект — пути, стек, специфические правила.

### 2. .claude/ целиком
```bash
cp -r /path/to/source/.claude /path/to/new-project/
chmod +x /path/to/new-project/.claude/hooks/*.sh
chmod +x /path/to/new-project/.claude/mcp/bootstrap.py
```

(На Windows `chmod` не нужен — Python запускается явно через `python`.)

### 3. .mcp.json в корне
```bash
cp /path/to/new-project/.claude/mcp/mcp.template.json /path/to/new-project/.mcp.json
```

### 4. Зависимости MCP-серверов

**sentrux** (архитектурный анализ):
```bash
brew install sentrux/tap/sentrux                                    # macOS
curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh | sh   # Linux
# Windows: https://github.com/sentrux/sentrux/releases
```

**ollama** (для qex):
```bash
brew install ollama                                # macOS
curl -fsSL https://ollama.com/install.sh | sh      # Linux
# Windows: https://ollama.com/download
ollama pull qwen3-embedding:8b                     # macOS / Linux
# ollama pull qwen3-embedding:4b                   # Windows
```

**Context7** (актуальные доки, user-level один раз на машину):
```bash
npx -y ctx7 setup --claude   # OAuth, free tier
```

### 5. Локальные настройки (опционально)
```bash
echo "CLAUDE.local.md" >> /path/to/new-project/.gitignore
echo ".claude/settings.local.json" >> /path/to/new-project/.gitignore
echo ".claude/CLAUDE.local.md" >> /path/to/new-project/.gitignore
```

---

## Обновление

По мере работы:

1. Если Claude делает ошибку → «Обнови CLAUDE.md, чтобы это не повторилось»
2. Регулярно сокращай `CLAUDE.md` — идеал 60–100 строк
3. Убирай то, что Claude уже делает правильно без подсказок
4. Новый агент → `/hire <роль>` (создаст по `agents/_template.md`)
5. Новая slash-команда → файл в `commands/`
6. Новый MCP-сервер → блок в `mcp.template.json` + строка проверки в `bootstrap.sh`

---

## Ресурсы

- [Официальная документация Claude Code](https://code.claude.com/docs/en/best-practices)
- [HumanLayer — Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)
