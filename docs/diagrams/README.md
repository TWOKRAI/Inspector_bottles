# Diagrams — визуализация архитектуры

Diagrams-as-code: все схемы хранятся как текст, версионируются в git, генерируются автоматически.

## Структура

```
docs/diagrams/
├── architecture.mmd    # C4 Container — ручная Mermaid-диаграмма
├── flows/              # Sequence-диаграммы взаимодействий
├── classes/            # UML классов (авто: pyreverse)
├── deps/               # Граф зависимостей (авто: pydeps)
└── README.md
```

## Генерация

```bash
make diagrams           # всё сразу
make diagrams-classes   # только UML классов (pyreverse → PlantUML)
make diagrams-deps      # только граф зависимостей (pydeps → SVG)
```

## Редактирование

- `.mmd` — Mermaid, рендерится в VS Code (Mermaid Preview extension)
- `.puml` — PlantUML, импортируется в Draw.io для визуального редактирования
- `.drawio.svg` — редактируемые схемы прямо в VS Code (Draw.io extension)

## VS Code extensions

- **Mermaid Preview** (`bierner.markdown-mermaid`)
- **Draw.io Integration** (`hediet.vscode-drawio`)
- **PlantUML** (`jebbs.plantuml`)

## Workflow

1. `make diagrams` — генерируешь актуальные схемы из кода
2. Открываешь в VS Code, правишь визуально
3. Коммитишь изменения
4. Claude Code читает схемы как контекст для рефакторинга
