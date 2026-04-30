# Настройка CLAUDE.md

## Быстрый старт

### 1. Основной файл (обязательно)
```bash
# Скопируй CLAUDE.md в корень проекта
cp CLAUDE.md /path/to/your/project/
```

### 2. Настройки Claude Code
```bash
# Скопируй настройки
mkdir -p /path/to/your/project/.claude
cp -r .claude/* /path/to/your/project/.claude/

# Сделай хук исполняемым
chmod +x /path/to/your/project/.claude/hooks/validate-safe-command.sh
```

### 3. Локальные настройки (не для git)
```bash
cp CLAUDE.local.md /path/to/your/project/
echo "CLAUDE.local.md" >> /path/to/your/project/.gitignore
```

### 4. Глобальные настройки (опционально)
```bash
# Для всех проектов
mkdir -p ~/.claude
cp CLAUDE.md ~/.claude/CLAUDE.md
# Отредактируй под свои предпочтения
```

## Иерархия загрузки

Claude Code читает файлы в порядке:
1. `~/.claude/CLAUDE.md` — глобальные настройки
2. `./CLAUDE.md` — настройки проекта
3. `./.claude/CLAUDE.md` — альтернативное расположение
4. `./CLAUDE.local.md` — локальные (gitignored)

## Проверка работы

Запусти Claude Code в проекте и проверь:
```
> /mcp
# Должен показать qex сервер (если настроен)

> Напиши простую функцию на Python
# Claude должен следовать конвенциям из CLAUDE.md
```

## Обновление

По мере работы:
1. Если Claude делает ошибку — скажи: "Обнови CLAUDE.md, чтобы это не повторилось"
2. Регулярно просматривай и сокращай файл (идеал: 40-80 строк)
3. Убирай то, что Claude уже делает правильно без подсказок

## Полезные команды

```bash
# Проверить статус MCP
claude /mcp

# Переиндексация кодовой базы (qex)
# Внутри Claude Code: index_codebase(force=True)

# Очистить сессию
/clear
```

## Структура проекта

```
project/
├── CLAUDE.md                 # Основной файл (в git)
├── CLAUDE.local.md           # Локальные настройки (в .gitignore)
├── .claude/
│   ├── settings.json         # Разрешения и хуки
│   ├── hooks/
│   │   └── validate-safe-command.sh
│   ├── skills/
│   │   ├── refactor-code/
│   │   │   └── SKILL.md
│   │   └── debug-issue/
│   │       └── SKILL.md
│   └── agents/
│       └── security-reviewer.md
└── ...
```

## Ресурсы

- [Официальная документация](https://code.claude.com/docs/en/best-practices)
- [HumanLayer — Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)
