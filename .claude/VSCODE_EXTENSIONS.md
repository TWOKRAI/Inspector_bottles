# VS Code Extensions — Стек для AI-разработки

Полный список расширений с обоснованием. Установка одной командой внизу страницы.

---

## Обязательный минимум

### Claude Code
- **anthropic.claude-code** — официальное расширение Claude Code. Чат, MCP, agents.

### Python
- **ms-python.python** — официальная поддержка Python (debug, IntelliSense).
- **ms-python.vscode-pylance** — продвинутый language server (часть Python ext).
- **charliermarsh.ruff** — линт + формат через ruff (в проекте уже настроен).
- **ms-python.mypy-type-checker** — type checking inline.

---

## Diagrams-as-Code

### Mermaid
- **bierner.markdown-mermaid** — рендер `.mmd` и Mermaid в markdown.
- **mermaidchart.vscode-mermaid-chart** *(опц.)* — расширенный редактор Mermaid.

### PlantUML
- **jebbs.plantuml** — рендер `.puml` (генерируется pyreverse).
  Требует Java или серверный рендеринг (`plantuml.render: PlantUMLServer`).

### Draw.io
- **hediet.vscode-drawio** — редактирование `.drawio.svg` прямо в VS Code.
  Импортирует PlantUML, версионируется в git как обычный текст.

### Excalidraw *(опц.)*
- **pomdtr.excalidraw-editor** — быстрые наброски, поддерживает Mermaid-импорт.

---

## Git и workflow

### Базовое
- **eamodio.gitlens** — git blame inline, история файла, сравнение веток.
- **mhutchie.git-graph** *(опц.)* — визуальный граф коммитов.

### PR / GitHub
- **github.vscode-pull-request-github** *(опц.)* — работа с PR прямо в IDE.

---

## Quality of life

### Подсветка ошибок
- **usernamehw.errorlens** — ошибки/предупреждения inline (не нужно открывать Problems-tab).

### Markdown
- **yzhang.markdown-all-in-one** — горячие клавиши, TOC, autocompletion.
- **DavidAnson.vscode-markdownlint** *(опц.)* — линт markdown.

### TOML
- **tamasfe.even-better-toml** — подсветка и схема для `pyproject.toml`.

### YAML
- **redhat.vscode-yaml** — подсветка + схема для `.pre-commit-config.yaml` и др.

### Indentation
- **oderwat.indent-rainbow** *(опц.)* — цветная индентация (полезно для YAML/Python).

---

## Тестирование

- **ms-python.debugpy** — отладка Python (входит в Python ext).
- **littlefoxteam.vscode-python-test-adapter** *(опц.)* — UI для pytest.

---

## Опциональные

### AI-помощники
- **github.copilot** *(опц.)* — рядом с Claude Code, для inline-suggestions.

### Productivity
- **alefragnani.bookmarks** *(опц.)* — закладки в коде.
- **streetsidesoftware.code-spell-checker** *(опц.)* — проверка орфографии.

---

## Полный список одной командой

### Windows / Linux / macOS

```bash
# Обязательный минимум
code --install-extension anthropic.claude-code
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension charliermarsh.ruff
code --install-extension ms-python.mypy-type-checker

# Diagrams
code --install-extension bierner.markdown-mermaid
code --install-extension jebbs.plantuml
code --install-extension hediet.vscode-drawio

# Git
code --install-extension eamodio.gitlens

# Quality of life
code --install-extension usernamehw.errorlens
code --install-extension yzhang.markdown-all-in-one
code --install-extension tamasfe.even-better-toml
code --install-extension redhat.vscode-yaml

# Опциональные
code --install-extension mermaidchart.vscode-mermaid-chart
code --install-extension pomdtr.excalidraw-editor
code --install-extension mhutchie.git-graph
code --install-extension github.vscode-pull-request-github
code --install-extension DavidAnson.vscode-markdownlint
```

---

## Рекомендуемые VS Code settings

В `settings.json` (User или Workspace):

```jsonc
{
    // ── Python ──
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "[python]": {
        "editor.defaultFormatter": "charliermarsh.ruff",
        "editor.formatOnSave": true,
        "editor.codeActionsOnSave": {
            "source.fixAll.ruff": "explicit",
            "source.organizeImports.ruff": "explicit"
        }
    },

    // ── PlantUML (без локальной Java — через публичный сервер) ──
    "plantuml.server": "https://www.plantuml.com/plantuml",
    "plantuml.render": "PlantUMLServer",

    // ── Mermaid ──
    "markdown-mermaid.lightModeTheme": "default",
    "markdown-mermaid.darkModeTheme": "dark",

    // ── Draw.io ──
    "hediet.vscode-drawio.theme": "atlas",

    // ── Error Lens ──
    "errorLens.fontSize": "12px",
    "errorLens.enabledDiagnosticLevels": ["error", "warning"],

    // ── GitLens ──
    "gitlens.currentLine.enabled": true,
    "gitlens.codeLens.enabled": true,

    // ── Files ──
    "files.exclude": {
        "**/__pycache__": true,
        "**/.pytest_cache": true,
        "**/.mypy_cache": true,
        "**/.ruff_cache": true,
        "**/*.egg-info": true
    }
}
```

---

## Проверка после установки

```bash
# Список установленных extensions
code --list-extensions

# Поиск конкретных
code --list-extensions | grep -E "claude|python|ruff|drawio|plantuml|mermaid"
```

---

## Связанные документы

- [`BOOTSTRAP.md`](BOOTSTRAP.md) — установка стека с нуля
- [`STACK.md`](STACK.md) — описание всех инструментов
